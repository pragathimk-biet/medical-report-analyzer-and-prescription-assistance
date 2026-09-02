import os
import json
import re

class MedicalRuleEngine:
    def __init__(self, json_path=None):
        if json_path is None:
            json_path = os.path.join(os.path.dirname(__file__), "reference_ranges.json")
        self.json_path = json_path
        self.rules_config = self._load_rules()
        self.parameter_map = self._build_parameter_map()

    def _load_rules(self):
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {self.json_path}: {e}")
            return {}

    def _build_parameter_map(self):
        param_map = {}
        for category, item in self.rules_config.items():
            if category == "metadata":
                continue
            if isinstance(item, dict):
                for key, config in item.items():
                    aliases = config.get("aliases", [])
                    for alias in aliases:
                        param_map[alias.lower().strip()] = {
                            "key": key,
                            "category": category,
                            "config": config,
                            "primary_name": aliases[0]
                        }
        return param_map

    def extract_inline_report_range(self, line_text):
        """
        Check if the report line contains its own reference range or threshold printed next to the test result.
        Examples: (Ref: 4.0 - 5.6), Ref: 70-100, Normal: < 5.7, 12.0 - 15.0, Positive >= 1:160
        """
        if not line_text:
            return None

        # Isolate parenthesized or reference range text block first to avoid matching result value
        ref_text = line_text
        paren_match = re.search(r'[\(\[]([^\)\]]+)[\)\]]', line_text)
        if paren_match:
            ref_text = paren_match.group(1)
        elif re.search(r'(?:ref|reference|normal|range)', line_text, re.IGNORECASE):
            ref_text = re.sub(r'^.*?(?:ref|reference|normal|range)[\:\=]?', '', line_text, flags=re.IGNORECASE)

        # Pattern 1: Titer threshold in report, e.g. (Positive >= 1:160) or Significant >= 1:80
        titer_ref_match = re.search(r'(?:positive|significant|ref|reference|normal)\s*(?:>=|>|equal to|more than|:)?\s*1\s*:\s*(\d+)', ref_text, re.IGNORECASE)
        if not titer_ref_match and ref_text != line_text:
            titer_ref_match = re.search(r'1\s*:\s*(\d+)', ref_text, re.IGNORECASE)

        if titer_ref_match:
            try:
                thresh_v = float(titer_ref_match.group(1))
                return {"type": "titer_threshold", "threshold": thresh_v, "raw": titer_ref_match.group(0)}
            except ValueError:
                pass

        # Pattern 2: Min-Max range, e.g., (Ref: 4.0 - 5.6) or 70.0 - 100.0 or 4.0-5.6
        min_max_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)', ref_text, re.IGNORECASE)
        if not min_max_match and ref_text != line_text:
            min_max_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)', line_text, re.IGNORECASE)

        if min_max_match:
            try:
                min_v = float(min_max_match.group(1))
                max_v = float(min_max_match.group(2))
                if min_v < max_v:
                    return {"type": "min_max", "min": min_v, "max": max_v, "raw": min_max_match.group(0)}
            except ValueError:
                pass

        # Pattern 3: Single upper bound threshold, e.g. < 5.7 or < 100
        upper_match = re.search(r'<\s*(\d+(?:\.\d+)?)', ref_text, re.IGNORECASE)
        if upper_match:
            try:
                max_v = float(upper_match.group(1))
                return {"type": "max_exclusive", "max": max_v, "raw": upper_match.group(0)}
            except ValueError:
                pass

        return None

    def evaluate_value(self, config, val, inline_range=None, patient_gender=None):
        """
        Evaluate extracted numerical value.
        Priority 1: Report inline reference range (if extracted from report)
        Priority 2: JSON reference rules fallback
        Returns (status, range_description, range_source, rule_id, provenance_source, provenance_status)
        """
        param_type = config.get("type")
        prov_source = config.get("source", "Unavailable - Standard Clinical Testing Reference Rule")
        prov_status = config.get("provenance_status", "UNAVAILABLE")

        # Priority 1: Report Inline Range
        if inline_range:
            if inline_range.get("type") == "titer_threshold" or param_type == "titer_threshold":
                thresh = inline_range.get("threshold", config.get("threshold", 160))
                pos_status = config.get("positive_status", "POSITIVE")
                neg_status = config.get("negative_status", "NEGATIVE")
                rule_id = config.get("rule_id_positive", "REPORT_INLINE_TITER_001") if val >= thresh else config.get("rule_id_negative", "REPORT_INLINE_TITER_002")
                if val >= thresh:
                    return pos_status, f"Report Threshold (>= 1:{int(thresh)})", "REPORT_INLINE", rule_id, prov_source, prov_status
                else:
                    return neg_status, f"Report Threshold (< 1:{int(thresh)})", "REPORT_INLINE", rule_id, prov_source, prov_status

            elif inline_range.get("type") == "min_max":
                min_v = inline_range["min"]
                max_v = inline_range["max"]
                if val < min_v:
                    return "LOW", f"Report Range ({min_v} - {max_v})", "REPORT_INLINE", "REPORT_INLINE_LOW_001", "Report Printed Reference Range", "VERIFIED_FROM_REPORT"
                elif val > max_v:
                    return "HIGH", f"Report Range ({min_v} - {max_v})", "REPORT_INLINE", "REPORT_INLINE_HIGH_001", "Report Printed Reference Range", "VERIFIED_FROM_REPORT"
                else:
                    return "NORMAL", f"Report Range ({min_v} - {max_v})", "REPORT_INLINE", "REPORT_INLINE_NORMAL_001", "Report Printed Reference Range", "VERIFIED_FROM_REPORT"
            elif inline_range.get("type") == "max_exclusive":
                max_v = inline_range["max"]
                if val < max_v:
                    return "NORMAL", f"Report Threshold (< {max_v})", "REPORT_INLINE", "REPORT_INLINE_NORMAL_002", "Report Printed Reference Range", "VERIFIED_FROM_REPORT"
                else:
                    return "HIGH", f"Report Threshold (< {max_v})", "REPORT_INLINE", "REPORT_INLINE_HIGH_002", "Report Printed Reference Range", "VERIFIED_FROM_REPORT"

        # Priority 2: JSON Reference Rules
        if param_type == "titer_threshold":
            thresh = config.get("threshold", 160)
            pos_status = config.get("positive_status", "POSITIVE")
            neg_status = config.get("negative_status", "NEGATIVE")
            rule_id = config.get("rule_id_positive", "TITER_POS_001") if val >= thresh else config.get("rule_id_negative", "TITER_NEG_001")
            if val >= thresh:
                return pos_status, f"JSON Threshold (>= 1:{int(thresh)})", "DEFAULT_JSON", rule_id, prov_source, prov_status
            else:
                return neg_status, f"JSON Threshold (< 1:{int(thresh)})", "DEFAULT_JSON", rule_id, prov_source, prov_status

        elif param_type in ["category", "clinical_threshold"]:
            rules = config.get("rules", [])
            for rule in rules:
                matches = True
                if "min_inclusive" in rule and val < rule["min_inclusive"]:
                    matches = False
                if "min_exclusive" in rule and val <= rule["min_exclusive"]:
                    matches = False
                if "max_inclusive" in rule and val > rule["max_inclusive"]:
                    matches = False
                if "max_exclusive" in rule and val >= rule["max_exclusive"]:
                    matches = False
                
                if matches:
                    rule_id = rule.get("rule_id", "JSON_CATEGORY_MATCH_001")
                    return rule["status"], f"JSON Rules ({config.get('unit', '')})", "DEFAULT_JSON", rule_id, prov_source, prov_status
            
            return "UNCLASSIFIED", f"JSON Rules ({config.get('unit', '')})", "DEFAULT_JSON", "JSON_UNCLASSIFIED_001", prov_source, prov_status

        elif param_type == "reference_range":
            ref = config.get("reference", {})
            
            # Gender specific fallback
            if "male" in ref and "female" in ref:
                gender_key = "female" if patient_gender and str(patient_gender).lower().startswith("f") else "male"
                ref_bounds = ref.get(gender_key, ref.get("male", {}))
            else:
                ref_bounds = ref

            min_v = ref_bounds.get("min")
            max_v = ref_bounds.get("max")

            if min_v is not None and val < min_v:
                rule_id = config.get("rule_id_low", "JSON_REF_LOW_001")
                return "LOW", f"JSON Default ({min_v} - {max_v} {config.get('unit', '')})", "DEFAULT_JSON", rule_id, prov_source, prov_status
            elif max_v is not None and val > max_v:
                rule_id = config.get("rule_id_high", "JSON_REF_HIGH_001")
                return "HIGH", f"JSON Default ({min_v} - {max_v} {config.get('unit', '')})", "DEFAULT_JSON", rule_id, prov_source, prov_status
            else:
                rule_id = config.get("rule_id_normal", "JSON_REF_NORMAL_001")
                return "NORMAL", f"JSON Default ({min_v} - {max_v} {config.get('unit', '')})", "DEFAULT_JSON", rule_id, prov_source, prov_status

        return "UNCLASSIFIED", "JSON Default", "DEFAULT_JSON", "UNCLASSIFIED_RULE_001", prov_source, prov_status

    def _parse_titer_val(self, val_str):
        """Converts string like '1:160' or '160' or '1 : 40' into float denominator 160.0 or 40.0."""
        val_str = str(val_str).strip()
        if ":" in val_str:
            parts = val_str.split(":")
            try:
                denom = float(parts[-1].strip())
                return denom, f"1:{int(denom)}"
            except ValueError:
                pass
        try:
            num = float(val_str)
            return num, f"1:{int(num)}"
        except ValueError:
            return None, val_str

    def evaluate_single_parameter(self, param_key_or_alias, value, line_text="", patient=None):
        """Directly evaluate a single parameter value by name or alias."""
        alias_key = str(param_key_or_alias).lower().strip()
        matched_info = self.parameter_map.get(alias_key)
        
        if not matched_info:
            # Try partial matching across parameter map
            for a_key, info in self.parameter_map.items():
                if a_key in alias_key or alias_key in a_key:
                    matched_info = info
                    break
        
        if not matched_info:
            return None

        config = matched_info["config"]
        patient_gender = patient.get("gender") if patient else None

        if config.get("type") == "titer_threshold":
            val, display_val = self._parse_titer_val(value)
            if val is None:
                return {
                    "finding_id": "LAB-001",
                    "parameter": matched_info["primary_name"],
                    "key": matched_info["key"],
                    "category": matched_info["category"],
                    "value": str(value),
                    "unit": config.get("unit", "titer"),
                    "status": "UNCLASSIFIED",
                    "rule_id": "INVALID_TITER_001",
                    "range_description": "Invalid Titer Format",
                    "range_source": "DEFAULT_JSON",
                    "provenance_source": config.get("source", "Unavailable"),
                    "provenance_status": config.get("provenance_status", "UNAVAILABLE")
                }
        else:
            try:
                val = float(value)
                display_val = val
            except ValueError:
                return None

        inline_range = self.extract_inline_report_range(line_text)
        status, range_desc, source, rule_id, prov_source, prov_status = self.evaluate_value(config, val, inline_range, patient_gender)
        
        return {
            "finding_id": "LAB-001",
            "parameter": matched_info["primary_name"],
            "key": matched_info["key"],
            "category": matched_info["category"],
            "value": display_val,
            "unit": config.get("unit", ""),
            "status": status,
            "rule_id": rule_id,
            "range_description": range_desc,
            "range_source": source,
            "provenance_source": prov_source,
            "provenance_status": prov_status
        }

    def parse_and_evaluate(self, report_text, patient=None, ocr_metadata=None):
        """
        Parses OCR/report text, extracts candidate values, and runs the 7-layer FindingValidator gate
        to construct validated intermediate representation objects.
        """
        from finding_validator import FindingValidator, ValidatedFinding

        raw_results = []
        seen_keys = set()

        if not report_text:
            return raw_results

        lines = report_text.splitlines()
        sorted_aliases = sorted(self.parameter_map.keys(), key=len, reverse=True)
        finding_counter = 1

        for line_idx, line in enumerate(lines, 1):
            line_clean = line.strip()
            if not line_clean:
                continue

            line_lower = line_clean.lower()
            
            conf_val = None
            if ocr_metadata and isinstance(ocr_metadata, list):
                for meta in ocr_metadata:
                    if meta.get("line_number") == line_idx or meta.get("raw_line") == line_clean:
                        conf_val = meta.get("confidence")
                        break

            for alias in sorted_aliases:
                alias_matched = False
                if len(alias) <= 3:
                    if re.search(r'\b' + re.escape(alias) + r'\b', line_lower):
                        alias_matched = True
                else:
                    if alias in line_lower:
                        alias_matched = True

                if alias_matched:
                    info = self.parameter_map[alias]
                    param_key = info["key"]
                    if param_key in seen_keys:
                        continue

                    config = info["config"]
                    is_titer = config.get("type") == "titer_threshold"
                    val = None
                    display_val = None
                    unit = config.get("unit", "")

                    if is_titer:
                        # Search for 1:N or 1 : N format on line
                        titer_match = re.search(r'1\s*:\s*(\d+)', line_clean)
                        if titer_match:
                            denom = float(titer_match.group(1))
                            val = denom
                            display_val = f"1:{int(denom)}"
                        else:
                            # Search for bare number after alias
                            num_match = re.search(r'(?:' + re.escape(alias) + r')[\:\=\s\-\>]+\s*(\d+)', line_clean, re.IGNORECASE)
                            if num_match:
                                denom = float(num_match.group(1))
                                val = denom
                                display_val = f"1:{int(denom)}"
                    else:
                        # Check for specific unit printed on line
                        unit_match = re.search(r'(\d+(?:\.\d+)?)\s*(mg/dL|mg/dl|g/dL|g/dl|%|mmol/L|mIU/L|ng/dL|cells/mcL|U/L|fL)', line_clean, re.IGNORECASE)
                        if unit_match:
                            try:
                                val = float(unit_match.group(1))
                                display_val = val
                                unit = unit_match.group(2)
                            except ValueError:
                                pass
                        
                        if val is None:
                            val_match = re.search(r'(?:' + re.escape(alias) + r')(?:[^\d\n]*?)\s*(\d+(?:\.\d+)?)', line_clean, re.IGNORECASE)
                            if val_match:
                                try:
                                    val = float(val_match.group(1))
                                    display_val = val
                                except ValueError:
                                    pass

                    if val is not None:
                        inline_range = self.extract_inline_report_range(line_clean)
                        patient_gender = patient.get("gender") if patient else None
                        
                        status, range_desc, source, rule_id, prov_source, prov_status = self.evaluate_value(config, val, inline_range, patient_gender)

                        candidate = {
                            "finding_id": f"LAB-{finding_counter:03d}",
                            "parameter": info["primary_name"],
                            "key": param_key,
                            "category": info["category"],
                            "value": display_val,
                            "unit": unit,
                            "status": status,
                            "rule_id": rule_id,
                            "range_description": range_desc,
                            "range_source": source,
                            "provenance_source": prov_source,
                            "provenance_status": prov_status,
                            "source_line_number": line_idx,
                            "raw_source_line": line_clean,
                            "confidence": conf_val
                        }

                        # Run 7-Layer Validation Gate
                        vf = FindingValidator.validate_candidate_finding(candidate, report_text=report_text)
                        raw_results.append(vf.to_dict())
                        seen_keys.add(param_key)
                        finding_counter += 1

                        # Derived Value Check: Mean Blood Glucose derived from HbA1c
                        if param_key == "hba1c" and "mean_blood_glucose" not in seen_keys:
                            mbg_match = re.search(r'(?:mean blood glucose|eag|mbg)[\:\=\s\-\>]+\s*(\d+(?:\.\d+)?)', report_text, re.IGNORECASE)
                            if mbg_match:
                                mbg_val = float(mbg_match.group(1))
                                mbg_candidate = {
                                    "finding_id": f"LAB-{finding_counter:03d}",
                                    "parameter": "Mean Blood Glucose",
                                    "key": "mean_blood_glucose",
                                    "category": "diabetes",
                                    "value": mbg_val,
                                    "unit": "mg/dL",
                                    "status": "NORMAL" if mbg_val <= 154 else "HIGH",
                                    "rule_id": "DERIVED_MBG_001",
                                    "range_description": "Derived from HbA1c (eAG)",
                                    "range_source": "DERIVED",
                                    "provenance_source": "ADA eAG Calculation Formula",
                                    "provenance_status": "VERIFIED",
                                    "source_line_number": line_idx,
                                    "raw_source_line": line_clean,
                                    "confidence": conf_val,
                                    "measurement_type": "DERIVED"
                                }
                                vf_mbg = FindingValidator.validate_candidate_finding(mbg_candidate, report_text=report_text)
                                raw_results.append(vf_mbg.to_dict())
                                seen_keys.add("mean_blood_glucose")
                                finding_counter += 1
                        break

        return raw_results

    def format_deterministic_markdown(self, evaluation_results):
        """Format the deterministic evaluation results into a Markdown block for prompt injection."""
        if not evaluation_results:
            return "No standardized laboratory parameters evaluated by the Rule Engine."

        md_lines = ["### ⚡ Deterministic Rule Engine Clinical Evaluation"]
        md_lines.append("| Finding ID | Test Parameter | Measured Value | Unit | Status | Validation Status | Rule ID | Reference Range Source | Provenance |")
        md_lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- | :--- |")

        for res in evaluation_results:
            status_badge = f"**{res['status']}**"
            if res['status'] in ['NORMAL', 'DESIRABLE', 'OPTIMAL', 'ACCEPTABLE', 'NEGATIVE']:
                status_badge = f"🟢 **{res['status']}**"
            elif res['status'] in ['PREDIABETES', 'PREDIABETES_RANGE', 'BORDERLINE_HIGH', 'NEAR_OPTIMAL', 'MILDLY_DECREASED']:
                status_badge = f"🟡 **{res['status']}**"
            elif res['status'] in ['DIABETES_RANGE', 'HIGH', 'VERY_HIGH', 'LOW', 'POSITIVE', 'KIDNEY_FAILURE_RANGE', 'SEVERELY_DECREASED']:
                status_badge = f"🔴 **{res['status']}**"

            v_status = res.get("validation_status", "VALIDATED")
            v_badge = f"`{v_status}`"
            if v_status == "VALIDATED":
                v_badge = "🟢 `VALIDATED`"
            elif v_status in ["PARTIALLY_VALIDATED", "AMBIGUOUS"]:
                v_badge = "🟡 `PARTIALLY VALIDATED`"
            elif v_status in ["REVIEW_REQUIRED", "UNVERIFIED"]:
                v_badge = "⚠️ `REVIEW REQUIRED`"

            source_str = f"{res.get('reference_text', res.get('range_description', ''))} ({res.get('reference_status', res.get('range_source', ''))})"
            prov_str = f"{res.get('provenance_source', 'Unavailable')} [{res.get('provenance_status', 'UNAVAILABLE')}]"
            fid = res.get("finding_id", "LAB-001")
            rid = res.get("rule_id", "RULE_001")
            param_str = res.get('test_name', res.get('parameter', 'Test'))
            val_str = res.get('result_value', res.get('value', ''))
            unit_str = res.get('unit', '')
            md_lines.append(f"| {fid} | {param_str} | {val_str} | {unit_str} | {status_badge} | {v_badge} | `{rid}` | {source_str} | {prov_str} |")

        return "\n".join(md_lines)
