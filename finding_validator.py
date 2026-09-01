import re
import logging

logger = logging.getLogger(__name__)

# Analyte Unit and Numerical Bounds Registry for Clinical Validation
ANALYTE_VALIDATION_REGISTRY = {
    "hba1c": {
        "primary_name": "HbA1c",
        "valid_units": ["%", "mmol/mol", "percent"],
        "min_plausible": 3.0,
        "max_plausible": 25.0,
        "derived_analytes": ["mean_blood_glucose", "eag"],
        "category": "diabetes"
    },
    "fasting_glucose": {
        "primary_name": "Fasting Glucose",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 20.0,
        "max_plausible": 1000.0,
        "category": "diabetes"
    },
    "random_glucose": {
        "primary_name": "Random Glucose",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 20.0,
        "max_plausible": 1000.0,
        "category": "diabetes"
    },
    "ogtt_2_hour": {
        "primary_name": "2 Hour Glucose",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 20.0,
        "max_plausible": 1000.0,
        "category": "diabetes"
    },
    "mean_blood_glucose": {
        "primary_name": "Mean Blood Glucose",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 30.0,
        "max_plausible": 800.0,
        "is_derived": True,
        "derived_from": "hba1c",
        "category": "diabetes"
    },
    "total_cholesterol": {
        "primary_name": "Total Cholesterol",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 50.0,
        "max_plausible": 1000.0,
        "category": "lipid_profile"
    },
    "ldl_cholesterol": {
        "primary_name": "LDL Cholesterol",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 10.0,
        "max_plausible": 800.0,
        "category": "lipid_profile"
    },
    "hdl_cholesterol": {
        "primary_name": "HDL Cholesterol",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 5.0,
        "max_plausible": 200.0,
        "category": "lipid_profile"
    },
    "triglycerides": {
        "primary_name": "Triglycerides",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 10.0,
        "max_plausible": 3000.0,
        "category": "lipid_profile"
    },
    "urea": {
        "primary_name": "Urea",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 2.0,
        "max_plausible": 400.0,
        "category": "kidney"
    },
    "creatinine": {
        "primary_name": "Serum Creatinine",
        "valid_units": ["mg/dL", "mg/dl", "umol/L", "µmol/L"],
        "min_plausible": 0.1,
        "max_plausible": 30.0,
        "category": "kidney"
    },
    "bun": {
        "primary_name": "BUN",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 1.0,
        "max_plausible": 200.0,
        "category": "kidney"
    },
    "egfr": {
        "primary_name": "eGFR",
        "valid_units": ["mL/min/1.73m2", "ml/min/1.73m2", "mL/min", "ml/min"],
        "min_plausible": 1.0,
        "max_plausible": 200.0,
        "category": "kidney"
    },
    "sodium": {
        "primary_name": "Sodium",
        "valid_units": ["mmol/L", "mEq/L", "mmol/l", "mEq/l"],
        "min_plausible": 90.0,
        "max_plausible": 180.0,
        "category": "electrolytes"
    },
    "potassium": {
        "primary_name": "Potassium",
        "valid_units": ["mmol/L", "mEq/L", "mmol/l", "mEq/l"],
        "min_plausible": 1.0,
        "max_plausible": 10.0,
        "category": "electrolytes"
    },
    "chloride": {
        "primary_name": "Chloride",
        "valid_units": ["mmol/L", "mEq/L", "mmol/l", "mEq/l"],
        "min_plausible": 60.0,
        "max_plausible": 150.0,
        "category": "electrolytes"
    },
    "calcium": {
        "primary_name": "Calcium",
        "valid_units": ["mg/dL", "mg/dl", "mmol/L", "mmol/l"],
        "min_plausible": 2.0,
        "max_plausible": 20.0,
        "category": "electrolytes"
    },
    "tsh": {
        "primary_name": "TSH",
        "valid_units": ["mIU/L", "uIU/mL", "miu/l", "uIU/ml"],
        "min_plausible": 0.001,
        "max_plausible": 300.0,
        "category": "thyroid"
    },
    "free_t4": {
        "primary_name": "Free T4",
        "valid_units": ["ng/dL", "ng/dl", "pmol/L", "pmol/l"],
        "min_plausible": 0.1,
        "max_plausible": 10.0,
        "category": "thyroid"
    },
    "hemoglobin": {
        "primary_name": "Hemoglobin",
        "valid_units": ["g/dL", "g/dl", "g/L", "g/l"],
        "min_plausible": 2.0,
        "max_plausible": 25.0,
        "category": "cbc"
    },
    "hematocrit": {
        "primary_name": "Hematocrit",
        "valid_units": ["%", "percent"],
        "min_plausible": 10.0,
        "max_plausible": 75.0,
        "category": "cbc"
    },
    "wbc": {
        "primary_name": "WBC",
        "valid_units": ["cells/mcL", "/uL", "x10^3/uL", "10^3/uL", "/mcL", "thousand/uL", "cells/uL"],
        "min_plausible": 100.0,
        "max_plausible": 200000.0,
        "category": "cbc"
    },
    "platelets": {
        "primary_name": "Platelets",
        "valid_units": ["cells/mcL", "/uL", "x10^3/uL", "10^3/uL", "/mcL", "lakh/cumm", "cells/uL"],
        "min_plausible": 1000.0,
        "max_plausible": 2000000.0,
        "category": "cbc"
    },
    "mcv": {
        "primary_name": "MCV",
        "valid_units": ["fL", "fl"],
        "min_plausible": 40.0,
        "max_plausible": 150.0,
        "category": "cbc"
    },
    "alt": {
        "primary_name": "ALT",
        "valid_units": ["U/L", "u/l", "IU/L", "iu/l"],
        "min_plausible": 1.0,
        "max_plausible": 10000.0,
        "category": "liver"
    },
    "ast": {
        "primary_name": "AST",
        "valid_units": ["U/L", "u/l", "IU/L", "iu/l"],
        "min_plausible": 1.0,
        "max_plausible": 10000.0,
        "category": "liver"
    },
    "bilirubin_total": {
        "primary_name": "Total Bilirubin",
        "valid_units": ["mg/dL", "mg/dl", "umol/L", "µmol/L"],
        "min_plausible": 0.01,
        "max_plausible": 50.0,
        "category": "liver"
    },
    "albumin": {
        "primary_name": "Albumin",
        "valid_units": ["g/dL", "g/dl", "g/L"],
        "min_plausible": 0.5,
        "max_plausible": 8.0,
        "category": "liver"
    },
    "typhi_o": {
        "primary_name": "Salmonella Typhi O",
        "valid_units": ["titer", "ratio"],
        "min_plausible": 10.0,
        "max_plausible": 1280.0,
        "category": "widal"
    },
    "typhi_h": {
        "primary_name": "Salmonella Typhi H",
        "valid_units": ["titer", "ratio"],
        "min_plausible": 10.0,
        "max_plausible": 1280.0,
        "category": "widal"
    },
    "paratyphi_ah": {
        "primary_name": "Salmonella Paratyphi AH",
        "valid_units": ["titer", "ratio"],
        "min_plausible": 10.0,
        "max_plausible": 1280.0,
        "category": "widal"
    },
    "paratyphi_bh": {
        "primary_name": "Salmonella Paratyphi BH",
        "valid_units": ["titer", "ratio"],
        "min_plausible": 10.0,
        "max_plausible": 1280.0,
        "category": "widal"
    }
}


class ValidatedFinding:
    """
    Validated Intermediate Representation Object for clinical findings.
    Prevents direct consumption of raw OCR text by explanation agents.
    """
    def __init__(self, finding_id, parameter, key, value, unit, status, rule_id,
                 range_description, range_source, provenance_source, provenance_status,
                 source_line_number=None, raw_source_line="", confidence=None,
                 reference_low=None, reference_high=None, measurement_type="DIRECT"):
        self.finding_id = finding_id
        self.test_name = parameter
        self.normalized_test_name = key
        self.result_value = value
        self.result_text = f"{value} {unit}".strip() if value is not None else ""
        self.unit = unit
        self.reference_low = reference_low
        self.reference_high = reference_high
        self.reference_text = range_description
        self.status = status
        self.evidence_text = raw_source_line
        self.source_line = source_line_number
        self.source_location = f"Line {source_line_number}" if source_line_number else "Report Document"
        self.rule_id = rule_id
        self.provenance_source = provenance_source
        self.provenance_status = provenance_status
        self.measurement_type = measurement_type  # DIRECT vs DERIVED

        # Multi-layer confidence metrics (0-100)
        self.ocr_confidence = confidence if confidence is not None else 90.0
        self.extraction_confidence = 95.0
        self.mapping_confidence = 100.0
        self.reference_confidence = 100.0 if provenance_status in ["VERIFIED", "VERIFIED_FROM_REPORT"] else 70.0
        self.evidence_confidence = 100.0
        self.overall_confidence = min(
            self.ocr_confidence,
            self.extraction_confidence,
            self.mapping_confidence,
            self.reference_confidence,
            self.evidence_confidence
        )

        # Fault-tolerant validation states
        self.validation_status = "VALIDATED"  # VALIDATED, PARTIALLY_VALIDATED, AMBIGUOUS, UNVERIFIED, REVIEW_REQUIRED, UNSUPPORTED
        self.validation_errors = []
        self.reference_status = range_source  # REPORT_INLINE, DEFAULT_JSON, NOT_AVAILABLE

    def to_dict(self):
        return {
            "finding_id": self.finding_id,
            "test_name": self.test_name,
            "parameter": self.test_name,  # Alias for backward compatibility
            "normalized_test_name": self.normalized_test_name,
            "key": self.normalized_test_name,  # Alias for backward compatibility
            "result_value": self.result_value,
            "value": self.result_value,  # Alias for backward compatibility
            "result_text": self.result_text,
            "unit": self.unit,
            "reference_low": self.reference_low,
            "reference_high": self.reference_high,
            "reference_text": self.reference_text,
            "range_description": self.reference_text,  # Alias for backward compatibility
            "status": self.status,
            "evidence_text": self.evidence_text,
            "raw_source_line": self.evidence_text,  # Alias for backward compatibility
            "source_line": self.source_line,
            "source_line_number": self.source_line,  # Alias for backward compatibility
            "source_location": self.source_location,
            "rule_id": self.rule_id,
            "provenance_source": self.provenance_source,
            "provenance_status": self.provenance_status,
            "measurement_type": self.measurement_type,
            "ocr_confidence": self.ocr_confidence,
            "confidence": self.ocr_confidence,  # Alias for backward compatibility
            "extraction_confidence": self.extraction_confidence,
            "mapping_confidence": self.mapping_confidence,
            "reference_confidence": self.reference_confidence,
            "evidence_confidence": self.evidence_confidence,
            "overall_confidence": self.overall_confidence,
            "validation_status": self.validation_status,
            "validation_errors": self.validation_errors,
            "reference_status": self.reference_status,
            "range_source": self.reference_status  # Alias for backward compatibility
        }


class FindingValidator:
    """
    Core Clinical Validation Gate for Intermediate Representation.
    Enforces Analyte-Value mapping, Unit compatibility, Reference Range integrity,
    Evidence mapping, and Multi-Layer Confidence scoring.
    """

    @staticmethod
    def validate_candidate_finding(finding_dict, raw_report_text="", report_text=""):
        """
        Runs complete 7-layer validation gate on a single finding dictionary.
        Returns a ValidatedFinding object.
        """
        report_str = raw_report_text or report_text
        vf = ValidatedFinding(
            finding_id=finding_dict.get("finding_id", "LAB-001"),
            parameter=finding_dict.get("parameter", "Unknown Test"),
            key=finding_dict.get("key", "unknown"),
            value=finding_dict.get("value"),
            unit=finding_dict.get("unit", ""),
            status=finding_dict.get("status", "UNCLASSIFIED"),
            rule_id=finding_dict.get("rule_id", "RULE_001"),
            range_description=finding_dict.get("range_description", "Standard Range"),
            range_source=finding_dict.get("range_source", "DEFAULT_JSON"),
            provenance_source=finding_dict.get("provenance_source", "Unavailable"),
            provenance_status=finding_dict.get("provenance_status", "UNAVAILABLE"),
            source_line_number=finding_dict.get("source_line_number"),
            raw_source_line=finding_dict.get("raw_source_line", ""),
            confidence=finding_dict.get("confidence")
        )

        key = vf.normalized_test_name.lower().strip()
        reg_entry = ANALYTE_VALIDATION_REGISTRY.get(key)

        # 1. Test Name & Analyte Association Validation
        FindingValidator._validate_test_mapping(vf, reg_entry, raw_report_text)

        # 2. Unit Compatibility Validation
        FindingValidator._validate_units(vf, reg_entry)

        # 3. Reference Range Integrity Validation
        FindingValidator._validate_reference_range(vf, reg_entry)

        # 4. Evidence Link Integrity Validation
        FindingValidator._validate_evidence(vf, raw_report_text)

        # 5. Derived Value Detection
        FindingValidator._detect_derived_values(vf, reg_entry)

        # 6. Recompute Overall Confidence & Limiting Factor
        vf.overall_confidence = min(
            vf.ocr_confidence,
            vf.extraction_confidence,
            vf.mapping_confidence,
            vf.reference_confidence,
            vf.evidence_confidence
        )

        # 7. Final Validation Status Assignment
        if vf.validation_errors:
            if any("Unresolved" in err or "Incompatible" in err or "Ambiguous" in err for err in vf.validation_errors):
                vf.validation_status = "REVIEW_REQUIRED"
            elif any("unverified" in err.lower() or "missing" in err.lower() for err in vf.validation_errors):
                vf.validation_status = "PARTIALLY_VALIDATED"
            else:
                vf.validation_status = "PARTIALLY_VALIDATED"
        else:
            vf.validation_status = "VALIDATED"

        return vf

    @staticmethod
    def _validate_test_mapping(vf, reg_entry, raw_report_text):
        """
        Validates that extracted numeric value belongs to the matched analyte name.
        Prevents mapping Mean Blood Glucose (e.g. 121.6 mg/dL) to HbA1c (e.g. 6.2%).
        """
        line_clean = vf.evidence_text.lower() if vf.evidence_text else ""
        key = vf.normalized_test_name.lower()

        # Specific Case: HbA1c vs Mean Blood Glucose (eAG / MBG)
        if key == "hba1c":
            if "mean blood glucose" in line_clean or "average blood glucose" in line_clean or "eag" in line_clean:
                # Check if value is plausibly Mean Blood Glucose (> 25) rather than HbA1c (%)
                if isinstance(vf.result_value, (int, float)) and vf.result_value > 25.0:
                    vf.mapping_confidence = 30.0
                    vf.validation_errors.append("Ambiguous mapping: Extracted value is in Mean Blood Glucose range (> 25 mg/dL), not HbA1c (%).")
                    vf.test_name = "HbA1c / Mean Blood Glucose (Ambiguous)"

        if reg_entry:
            min_p = reg_entry.get("min_plausible")
            max_p = reg_entry.get("max_plausible")
            if isinstance(vf.result_value, (int, float)):
                if min_p is not None and vf.result_value < min_p:
                    vf.mapping_confidence = 40.0
                    vf.validation_errors.append(f"Implausible numeric value {vf.result_value} for analyte {vf.test_name} (min plausible: {min_p}).")
                elif max_p is not None and vf.result_value > max_p:
                    vf.mapping_confidence = 40.0
                    vf.validation_errors.append(f"Implausible numeric value {vf.result_value} for analyte {vf.test_name} (max plausible: {max_p}).")

    @staticmethod
    def _validate_units(vf, reg_entry):
        """
        Validates analyte-specific unit compatibility.
        """
        if not reg_entry:
            return

        valid_units = reg_entry.get("valid_units", [])
        if not valid_units or not vf.unit:
            return

        unit_clean = vf.unit.lower().strip()
        unit_matches = any(v.lower() == unit_clean for v in valid_units)

        if not unit_matches:
            vf.mapping_confidence = min(vf.mapping_confidence, 40.0)
            vf.validation_errors.append(f"Incompatible unit '{vf.unit}' for analyte {vf.test_name} (Expected: {', '.join(valid_units[:3])}).")

    @staticmethod
    def _validate_reference_range(vf, reg_entry):
        """
        Validates reference range compatibility.
        Prevents attaching a neonatal Creatinine range (e.g. 0.26 - 1.01 mg/dL) to Sodium.
        """
        key = vf.normalized_test_name.lower()
        range_text = vf.reference_text.lower() if vf.reference_text else ""

        # Specific Case: Sodium matched with inappropriate low range (e.g. 0.26 - 1.01 mg/dL)
        if key == "sodium":
            min_max_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)', range_text)
            if min_max_match:
                try:
                    r_min = float(min_max_match.group(1))
                    r_max = float(min_max_match.group(2))
                    if r_max < 90.0:  # Sodium reference max must be >= 90 mmol/L
                        vf.reference_confidence = 20.0
                        vf.reference_status = "NOT_AVAILABLE"
                        vf.reference_text = "Configured Default Reference Range (135 - 145 mmol/L)"
                        vf.provenance_source = "AACC Electrolyte Standard (Configured Default)"
                        vf.provenance_status = "VERIFIED"
                        vf.rule_id = "SODIUM_NORMAL_001"
                        if isinstance(vf.result_value, (int, float)) and 135.0 <= vf.result_value <= 145.0:
                            vf.status = "NORMAL"
                        vf.validation_errors.append("Incompatible report reference range rejected for Sodium. Switched to Configured Default Reference Range.")
                except ValueError:
                    pass

        if vf.reference_status == "DEFAULT_JSON":
            vf.reference_text = f"Configured Default Reference Range ({vf.reference_text.replace('JSON Default (', '').replace('JSON Rules (', '')}"
            if not vf.reference_text.endswith(")"):
                vf.reference_text += ")"

    @staticmethod
    def _validate_evidence(vf, raw_report_text):
        """
        Validates that raw_source_line actually contains analyte keywords.
        Prevents mapping report headers/addresses ("JANANASHANKARA, NH4, Bypass") to test evidence.
        """
        if not vf.evidence_text:
            vf.evidence_confidence = 30.0
            vf.evidence_text = "Evidence line could not be reliably linked from extracted report."
            vf.validation_errors.append("Evidence line missing or unverified.")
            return

        evidence_lower = vf.evidence_text.lower()
        name_lower = vf.test_name.lower()
        key_lower = vf.normalized_test_name.lower()

        # Check if evidence contains analyte name or key
        name_keywords = name_lower.split()
        contains_keyword = any(kw in evidence_lower for kw in name_keywords if len(kw) >= 2) or key_lower in evidence_lower

        if not contains_keyword:
            # Check for header / address noise
            if any(h in evidence_lower for h in ["bypass", "hospital", "janana", "address", "road", "dr.", "patient", "page"]):
                vf.evidence_confidence = 20.0
                vf.evidence_text = "Evidence line contains document header/address noise; unverified line link."
                vf.validation_errors.append("Unverified evidence link: Source line matches header/address noise.")

    @staticmethod
    def _detect_derived_values(vf, reg_entry):
        """
        Detects derived/calculated measurements (e.g. Mean Blood Glucose derived from HbA1c).
        """
        line_clean = vf.evidence_text.lower() if vf.evidence_text else ""
        if "derived" in line_clean or "calculated" in line_clean or "eag" in line_clean:
            vf.measurement_type = "DERIVED"
        elif reg_entry and reg_entry.get("is_derived"):
            vf.measurement_type = "DERIVED"
