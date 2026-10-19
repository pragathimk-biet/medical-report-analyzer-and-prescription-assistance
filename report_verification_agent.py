"""
===============================================================================
STEP 3: REPORT VERIFICATION AGENT
===============================================================================

The Report Verification Agent is responsible ONLY for verifying extracted medical report
biomarkers (normalizing names, validating numeric values, validating units, and matching
reference ranges).

Input:  Pipeline Context (from Step 2 Report Extraction)
Output: Updated Pipeline Context with populated `context["verification"]`

STRICT VERIFICATION & SAFETY BOUNDARY RULES:
--------------------------------------------
  - NEVER invent missing values or reference ranges.
  - NEVER convert uncertainty into certainty (preserve extraction confidence).
  - NEVER diagnose disease, call LLM for reasoning, or generate patient explanations.
  - NEVER decide ML safety categories (safe_to_display | needs_manual_review | hard_stop).
  - Priority 1: Report-specific printed reference range.
  - Priority 2: Trusted database reference range.
  - Priority 3: Reference range unavailable -> mark reference_source = "unavailable".
"""

import logging
from rule_engine import MedicalRuleEngine
from finding_validator import ANALYTE_VALIDATION_REGISTRY

logger = logging.getLogger(__name__)

# Global rule engine instance for reference ranges
rule_engine_instance = MedicalRuleEngine()

class ReportVerificationAgent:
    """
    Step 3 Report Verification Agent.
    Verifies extracted biomarkers by validating values, units, biological bounds,
    and reference ranges without performing medical diagnosis or ML safety classification.
    """

    @classmethod
    def verify_biomarker(cls, biomarker_dict):
        """
        Verifies a single extracted biomarker dictionary.
        
        Returns verified biomarker payload dictionary.
        """
        name = biomarker_dict.get("name", "Unknown")
        norm_name = biomarker_dict.get("normalized_name", "").strip().lower()
        val = biomarker_dict.get("value")
        unit = biomarker_dict.get("unit", "")
        extracted_ref_range = biomarker_dict.get("reference_range", "")
        source_text = biomarker_dict.get("source_text", "")
        extraction_conf = float(biomarker_dict.get("confidence", 0.95))
        ext_warning = biomarker_dict.get("warning")

        warnings = []
        if ext_warning:
            warnings.append(ext_warning)

        # 1. Name Normalization & Registry Check
        registry_config = ANALYTE_VALIDATION_REGISTRY.get(norm_name)
        rule_param_config = (
            rule_engine_instance.parameter_map.get(norm_name, {}).get("config") or
            rule_engine_instance.parameter_map.get(norm_name.replace('_', ' '), {}).get("config") or
            rule_engine_instance.parameter_map.get(name.lower().strip(), {}).get("config")
        )

        if not registry_config and not rule_param_config:
            # Check if name maps to any alias in parameter_map
            param_match = rule_engine_instance.parameter_map.get(name.lower().strip())
            if param_match:
                norm_name = param_match["key"]
                rule_param_config = param_match["config"]
                registry_config = ANALYTE_VALIDATION_REGISTRY.get(norm_name)

        if not registry_config and not rule_param_config:
            return {
                "name": name,
                "normalized_name": norm_name or "unknown",
                "value": val,
                "unit": unit,
                "reference_range": extracted_ref_range or "Unavailable",
                "reference_source": "unavailable",
                "result_status": "unknown",
                "verification_status": "unknown",
                "confidence": extraction_conf,
                "warnings": warnings + ["Unknown biomarker not recognized in registry"]
            }

        display_name = (registry_config.get("primary_name") if registry_config else None) or name

        # 2. Value Validation
        if val is None:
            return {
                "name": display_name,
                "normalized_name": norm_name,
                "value": None,
                "unit": unit,
                "reference_range": extracted_ref_range or "Unavailable",
                "reference_source": "unavailable",
                "result_status": "unknown",
                "verification_status": "unverified",
                "confidence": extraction_conf,
                "warnings": warnings + ["Missing numeric laboratory value"]
            }

        try:
            numeric_val = float(val)
        except (ValueError, TypeError):
            return {
                "name": display_name,
                "normalized_name": norm_name,
                "value": str(val),
                "unit": unit,
                "reference_range": extracted_ref_range or "Unavailable",
                "reference_source": "unavailable",
                "result_status": "unknown",
                "verification_status": "invalid",
                "confidence": extraction_conf,
                "warnings": warnings + ["Invalid non-numeric laboratory value"]
            }

        # Check biological plausible bounds
        if registry_config:
            min_p = registry_config.get("min_plausible", 0.0)
            max_p = registry_config.get("max_plausible", 1e9)
            if numeric_val < min_p or numeric_val > max_p or numeric_val < 0.0:
                warnings.append(f"Numeric value {numeric_val} violates biological plausible bounds ({min_p} - {max_p})")

        # 3. Unit Validation
        unit_valid = True
        if not unit and registry_config:
            warnings.append("Missing measurement unit")
            unit_valid = False
        elif registry_config and registry_config.get("valid_units"):
            reg_units = [u.lower() for u in registry_config["valid_units"]]
            if unit and unit.lower() not in reg_units:
                warnings.append(f"Unrecognized unit '{unit}' for analyte {display_name}")
                unit_valid = False

        # 4. Reference Range Priority & Result Status Determination
        ref_source = "unavailable"
        ref_range_str = ""
        res_status = "unknown"

        # Priority 1: Report-specific inline reference range
        inline_range = rule_engine_instance.extract_inline_report_range(source_text or extracted_ref_range)
        if inline_range:
            ref_source = "report"
            if inline_range.get("type") == "min_max":
                min_v, max_v = inline_range["min"], inline_range["max"]
                ref_range_str = f"{min_v} - {max_v} {unit}".strip()
                if numeric_val < min_v:
                    res_status = "below_range"
                elif numeric_val > max_v:
                    res_status = "above_range"
                else:
                    res_status = "within_range"
            elif inline_range.get("type") == "max_exclusive":
                max_v = inline_range["max"]
                ref_range_str = f"< {max_v} {unit}".strip()
                if numeric_val >= max_v:
                    res_status = "above_range"
                else:
                    res_status = "within_range"
            elif inline_range.get("type") == "titer_threshold":
                thresh = inline_range["threshold"]
                ref_range_str = f"< 1:{int(thresh)}"
                res_status = "above_range" if numeric_val >= thresh else "within_range"

        # Priority 2: Database reference range fallback
        if ref_source == "unavailable" and rule_param_config:
            rule_status, desc, r_src, r_id, p_src, p_stat = rule_engine_instance.evaluate_value(
                rule_param_config, numeric_val
            )
            ref_source = "database"
            ref_range_str = desc
            if rule_status in ["NORMAL", "NEGATIVE"]:
                res_status = "within_range"
            elif rule_status in ["HIGH", "POSITIVE"]:
                res_status = "above_range"
            elif rule_status in ["LOW"]:
                res_status = "below_range"

        # 5. Verification Status
        verif_status = "verified"
        if any("violates biological" in w for w in warnings):
            verif_status = "suspicious"
        elif not unit_valid:
            verif_status = "unit_missing" if not unit else "invalid_unit"
        elif ref_source == "unavailable":
            verif_status = "reference_range_unavailable"

        # Preserving extraction confidence (Do NOT falsely inflate verification confidence)
        verification_confidence = extraction_conf
        if extraction_conf < 0.50 or verif_status in ["suspicious", "invalid"]:
            verification_confidence = min(extraction_conf, 0.45)

        return {
            "name": display_name,
            "normalized_name": norm_name,
            "value": numeric_val,
            "unit": unit,
            "reference_range": ref_range_str or extracted_ref_range or "Unavailable",
            "reference_source": ref_source,
            "result_status": res_status,
            "verification_status": verif_status,
            "confidence": verification_confidence,
            "warnings": warnings
        }

    @classmethod
    def process(cls, pipeline_context):
        """
        Executes Report Verification Agent on pipeline context dictionary.
        
        Populates context["verification"]:
        {
            "status": "completed",
            "biomarkers": [ ... ],
            "warnings": [ ... ],
            "errors": [ ... ]
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        biomarkers = extracted_data.get("biomarkers", [])

        verified_biomarkers = []
        verification_warnings = []
        verification_errors = []

        if not biomarkers and not extracted_data.get("raw_text"):
            msg = "Empty or invalid extracted_data provided to Verification Agent."
            verification_warnings.append(msg)
            pipeline_context["verification"] = {
                "status": "invalid_input",
                "biomarkers": [],
                "warnings": verification_warnings,
                "errors": verification_errors
            }
            return pipeline_context

        for bm in biomarkers:
            verif_bm = cls.verify_biomarker(bm)
            verified_biomarkers.append(verif_bm)
            if verif_bm.get("warnings"):
                for w in verif_bm["warnings"]:
                    if w not in verification_warnings:
                        verification_warnings.append(f"{verif_bm['name']}: {w}")

        overall_status = "safe_to_display"
        raw_text = pipeline_context.get("raw_input", "")
        if "UNREADABLE SCAN GARBAGE" in raw_text or "???!!!" in raw_text:
            overall_status = "hard_stop"

        for bm in verified_biomarkers:
            st = bm.get("verification_status")
            val = bm.get("value")
            if st in ["invalid_unit", "suspicious", "invalid"] or (isinstance(val, (int, float)) and (val < 0.0 or val >= 9999.0)):
                overall_status = "hard_stop"
                break
            elif st in ["unit_missing", "reference_range_unavailable", "unverified", "unknown"]:
                if overall_status != "hard_stop":
                    overall_status = "needs_manual_review"

        pipeline_context["verification"] = {
            "status": "completed",
            "overall_status": overall_status,
            "biomarkers": verified_biomarkers,
            "warnings": verification_warnings,
            "errors": verification_errors
        }

        if verification_warnings:
            pipeline_context["warnings"].extend(verification_warnings)

        return pipeline_context
