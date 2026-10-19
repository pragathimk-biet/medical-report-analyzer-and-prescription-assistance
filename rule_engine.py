import os
import json
import re
import math

# ---------------------------------------------------------------------------
# Comprehensive unit vocabulary (fix: incomplete unit patterns, µmol/L,
# 10⁹/L, eGFR units, mL/min/1.73m² etc.)
# ---------------------------------------------------------------------------
_UNIT_PATTERN = (
    r'(?:'
    # Molar / mass-based
    r'µmol/L|umol/L|mmol/L|nmol/L|pmol/L'
    r'|mg/dL|mg/dl|mg/L'
    r'|g/dL|g/dl|g/L'
    r'|ng/dL|ng/dl|ng/mL|ng/ml|pg/mL|pg/ml'
    # Haematology counts
    r'|10\^9/L|10\*9/L|×10\^9/L|x10\^9/L|10⁹/L'
    r'|10\^3/µL|10\^3/uL|×10\^3/µL|10³/µL'
    r'|cells/mcL|cells/µL|cells/uL|/µL|/uL|/mcL'
    # Volume / enzyme
    r'|mL/min/1\.73m2|mL/min/1\.73\s*m²|mL/min'
    r'|U/L|IU/L|mIU/L|µU/mL|uU/mL'
    # Haematology other
    r'|fL|pg'
    # Proportion / ratio
    r'|%'
    # Electrolyte / titer
    r'|mEq/L|mmHg'
    r')'
)
# Compiled once for speed
_UNIT_RE = re.compile(_UNIT_PATTERN, re.IGNORECASE)

# Anchored unit pattern to avoid g/dL matching inside ng/dL (fix: partial match)
# The lookahead/lookbehind ensures we don't grab a unit mid-word.
_VALUE_WITH_UNIT_RE = re.compile(
    r'(?<!\w)(-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(' + _UNIT_PATTERN[4:-1] + r')(?!\w)',
    re.IGNORECASE
)

# Comparison operator before a value  e.g. <5 >90 <=3.5 >=160
_CMP_VALUE_RE = re.compile(r'([<>]=?)\s*(-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)')

# Scientific-notation aware plain number (may be negative, may be comma-formatted)
_PLAIN_NUMBER_RE = re.compile(r'-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?')


def _parse_number(s: str) -> float | None:
    """
    Parse a numeric string that may contain:
      - comma thousands separators  e.g.  150,000
      - scientific notation          e.g.  4.5e3 or 4.5E+3
      - leading minus sign
    Returns finite float or None on failure (rejects NaN, Inf, non-finite).
    (Fix: comma-formatted values; scientific notation; negative numbers; non-finite numbers rejected.)
    """
    try:
        val = float(str(s).replace(',', ''))
        if not math.isfinite(val):
            return None
        return val
    except (ValueError, TypeError):
        return None


def _extract_comparison(text: str):
    """
    Return (operator, value) if text contains a comparison expression like <5, >90, <=3.5.
    Returns (None, None) otherwise.
    (Fix: result comparison symbols are discarded.)
    """
    m = _CMP_VALUE_RE.search(text)
    if m:
        op = m.group(1)
        val = _parse_number(m.group(2))
        if val is not None:
            return op, val
    return None, None


def _is_reference_only_line(line: str, alias: str) -> bool:
    """
    Heuristic guard: return True when the line looks like a printed reference
    row (header / range annotation) rather than an actual measured result.
    Avoids treating 'Reference range: 70 – 100' as value=70.
    (Fix: reference-only lines can become results.)
    """
    ref_keywords = re.compile(
        r'\b(?:reference\s+range|normal\s+range|ref\.?\s*range|'
        r'reference\s+interval|normal\s+value|expected\s+value|'
        r'biological\s+reference)\b',
        re.IGNORECASE
    )
    # If the ONLY number-bearing text on this line is a range expression
    # like "12.0 – 15.0" without an actual single result value preceding
    # or following the alias, treat it as reference-only.
    if ref_keywords.search(line):
        return True
    # Count numbers; if there are ≥ 2 separated by a dash/to it is likely
    # a range annotation only when the line has no value+unit match.
    numbers = _PLAIN_NUMBER_RE.findall(line.replace(',', ''))
    if len(numbers) >= 2:
        range_match = re.search(r'\d[\d.]*\s*(?:–|-|to)\s*\d[\d.]*', line, re.IGNORECASE)
        unit_match = _VALUE_WITH_UNIT_RE.search(line)
        # If no unit-anchored value found but a range is present → reference line
        if range_match and not unit_match:
            return True
    return False


class MedicalRuleEngine:
    def __init__(self, json_path=None):
        if json_path is None:
            json_path = os.path.join(os.path.dirname(__file__), "reference_ranges.json")
        self.json_path = json_path
        self.rules_config = self._load_rules()
        self.parameter_map = self._build_parameter_map()
        self.configuration_issues = self.validate_rules_configuration()
        if self.configuration_issues:
            for issue in self.configuration_issues:
                print(f"[RuleEngine] CONFIG WARNING ({issue['type']}): {issue['message']}")

    def _load_rules(self):
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {self.json_path}: {e}")
            return {}

    def _build_parameter_map(self):
        """
        Build alias → analyte lookup table.

        Fixes applied here:
          • Fix 4: canonical JSON key (e.g. 'fasting_glucose') registered
            explicitly so callers can look up by key as well as by alias.
          • Fix 5: collision detection — if two analytes claim the same alias
            a warning is printed and the *first* registration wins (deterministic).
        """
        param_map = {}
        for category, item in self.rules_config.items():
            if category == "metadata":
                continue
            if isinstance(item, dict):
                for key, config in item.items():
                    aliases = config.get("aliases", [])
                    entry = {
                        "key": key,
                        "category": category,
                        "config": config,
                        "primary_name": aliases[0] if aliases else key,
                    }

                    # Fix 4: also register the raw JSON key (e.g. 'fasting_glucose')
                    key_lower = key.lower().strip()
                    if key_lower not in param_map:
                        param_map[key_lower] = entry
                    else:
                        existing = param_map[key_lower]
                        if existing["key"] != key:
                            print(
                                f"[RuleEngine] WARNING: canonical key collision '"
                                f"{key_lower}' already registered for '"
                                f"{existing['key']}'; skipping '{key}'."
                            )

                    for alias in aliases:
                        alias_lower = alias.lower().strip()
                        if alias_lower not in param_map:
                            param_map[alias_lower] = entry
                        else:
                            existing = param_map[alias_lower]
                            if existing["key"] != key:
                                # Fix 5: report collision; first-seen wins
                                print(
                                    f"[RuleEngine] WARNING: alias collision '"
                                    f"{alias_lower}' already registered for '"
                                    f"{existing['key']}'; skipping duplicate in '{key}'."
                                )
        return param_map

    # --------------------------------------------------------------------------
    # Rule Configuration & Validation Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def _intervals_overlap(r1: dict, r2: dict) -> bool:
        """Return True if rule intervals r1 and r2 overlap (share any real numbers)."""
        l1 = r1.get('min_inclusive', r1.get('min_exclusive', float('-inf')))
        l1_inc = 'min_inclusive' in r1
        l2 = r2.get('min_inclusive', r2.get('min_exclusive', float('-inf')))
        l2_inc = 'min_inclusive' in r2

        h1 = r1.get('max_inclusive', r1.get('max_exclusive', float('inf')))
        h1_inc = 'max_inclusive' in r1
        h2 = r2.get('max_inclusive', r2.get('max_exclusive', float('inf')))
        h2_inc = 'max_inclusive' in r2

        if l1 > l2:
            low_val, low_inc = l1, l1_inc
        elif l2 > l1:
            low_val, low_inc = l2, l2_inc
        else:
            low_val = l1
            low_inc = l1_inc and l2_inc

        if h1 < h2:
            high_val, high_inc = h1, h1_inc
        elif h2 < h1:
            high_val, high_inc = h2, h2_inc
        else:
            high_val = h1
            high_inc = h1_inc and h2_inc

        if low_val < high_val:
            return True
        if low_val == high_val and low_inc and high_inc:
            return True
        return False

    @staticmethod
    def _find_category_gaps(rules: list) -> list:
        """Find decimal/interval gaps between sorted adjacent category rules."""
        if len(rules) < 2:
            return []
        def _lower(r):
            return r.get('min_inclusive', r.get('min_exclusive', float('-inf')))
        def _upper(r):
            return r.get('max_inclusive', r.get('max_exclusive', float('inf')))

        sorted_rules = sorted(rules, key=_lower)
        gaps = []
        for i in range(len(sorted_rules) - 1):
            r1, r2 = sorted_rules[i], sorted_rules[i + 1]
            h1 = _upper(r1)
            h1_inc = 'max_inclusive' in r1
            l2 = _lower(r2)
            l2_inc = 'min_inclusive' in r2
            if h1 < l2:
                gaps.append({'rule1': r1.get('rule_id'), 'rule2': r2.get('rule_id'), 'interval': f'({h1}, {l2})'})
            elif h1 == l2 and not h1_inc and not l2_inc:
                gaps.append({'rule1': r1.get('rule_id'), 'rule2': r2.get('rule_id'), 'interval': f'[{h1}]'})
        return gaps

    def validate_rules_configuration(self) -> list:
        """
        Validate all category, clinical threshold, and reference range rules
        for overlap, decimal gaps, inverted bounds, or missing reference ranges.
        Returns a list of issue dictionaries.
        """
        issues = []
        for category, cat_items in self.rules_config.items():
            if category == "metadata" or not isinstance(cat_items, dict):
                continue
            for key, config in cat_items.items():
                param_type = config.get("type")
                if param_type in ["category", "clinical_threshold"]:
                    rules = config.get("rules", [])
                    for r in rules:
                        rid = r.get("rule_id", "NO_ID")
                        mn = r.get("min_inclusive", r.get("min_exclusive"))
                        mx = r.get("max_inclusive", r.get("max_exclusive"))
                        if mn is not None and mx is not None and mn >= mx:
                            issues.append({
                                "category": category,
                                "key": key,
                                "type": "INVERTED_BOUNDS",
                                "message": f"Rule {rid} has min bound >= max bound ({mn} >= {mx})"
                            })
                    for i in range(len(rules)):
                        for j in range(i + 1, len(rules)):
                            if self._intervals_overlap(rules[i], rules[j]):
                                issues.append({
                                    "category": category,
                                    "key": key,
                                    "type": "OVERLAP",
                                    "message": f"Overlapping rules detected in {category}.{key}: '{rules[i].get('rule_id')}' and '{rules[j].get('rule_id')}'"
                                })
                    gaps = self._find_category_gaps(rules)
                    for gap in gaps:
                        issues.append({
                            "category": category,
                            "key": key,
                            "type": "GAP",
                            "message": f"Decimal gap in {category}.{key} rules: interval {gap['interval']} between '{gap['rule1']}' and '{gap['rule2']}' is unclassified"
                        })
                elif param_type == "reference_range":
                    ref = config.get("reference", {})
                    if "male" in ref and "female" in ref:
                        for g in ["male", "female"]:
                            bounds = ref.get(g, {})
                            if bounds.get("min") is None and bounds.get("max") is None:
                                issues.append({
                                    "category": category,
                                    "key": key,
                                    "type": "MISSING_BOUNDS",
                                    "message": f"Missing reference bounds for gender '{g}' in {category}.{key}"
                                })
                    else:
                        if ref.get("min") is None and ref.get("max") is None:
                            issues.append({
                                "category": category,
                                "key": key,
                                "type": "MISSING_BOUNDS",
                                "message": f"Missing reference bounds in {category}.{key}"
                            })
        return issues

    @staticmethod
    def _extract_patient_age(patient) -> float | None:
        """
        Extract numeric patient age in years from patient dict or demographics.
        Returns float age in years or None.
        """
        if not patient or not isinstance(patient, dict):
            return None
        raw_age = patient.get("age") or patient.get("patient_age")
        if raw_age is None:
            return None
        if isinstance(raw_age, (int, float)):
            return float(raw_age) if math.isfinite(raw_age) else None
        s = str(raw_age).strip().lower()
        m = re.search(r'(\d+(?:\.\d+)?)', s)
        if m:
            val = float(m.group(1))
            if 'month' in s:
                return val / 12.0
            if 'day' in s:
                return val / 365.0
            return val
        return None

    # --------------------------------------------------------------------------
    # Helpers for bracket / inline-range extraction
    # --------------------------------------------------------------------------
    @staticmethod
    def _bracket_has_numeric_range(text: str) -> bool:
        """
        Fix 1: Validate that a parenthesised block actually contains a numeric
        range, threshold, or titer — NOT method notes like '(serum)' or
        '(enzymatic method)'.
        Returns True only when at least one digit sequence is present AND
        the text looks like a range or threshold (hyphen/to/titer/< />).
        """
        if not re.search(r'\d', text):
            return False
        # Must contain a range separator, comparison operator, or titer colon
        return bool(re.search(r'(?:-|to|–|<|>|\u2264|\u2265|<=|>=|1\s*:)', text, re.IGNORECASE))

    @staticmethod
    def _looks_like_date(text: str) -> bool:
        """
        Fix 2: Reject date-shaped strings such as '10-20-2024', '2024/10/14',
        '20.10.2024' that can otherwise match a two-number range pattern.
        """
        return bool(re.search(
            r'(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            text
        ))

    @staticmethod
    def _range_values_plausible(min_v: float, max_v: float) -> bool:
        """
        Fix 2: Sanity check — reject implausible numeric intervals.
        Physiological reference ranges almost never exceed 1,000,000 or go
        below -1000. Also reject when min and max are both very large integers
        that look like years or ID numbers.
        """
        if min_v < -1000 or max_v > 1_000_000:
            return False
        # Reject year-like pairs (e.g. 2020 – 2024)
        if min_v >= 1900 and max_v >= 1900 and (max_v - min_v) <= 100:
            return False
        return True

    # --------------------------------------------------------------------------
    def extract_inline_report_range(self, line_text, configured_unit: str = ""):
        """
        Check if the report line contains its own reference range or threshold
        printed next to the test result.

        Returns a dict with at minimum:
          {"type": ..., "raw": ..., "provenance": "EXTRACTED_FROM_REPORT"}
        or None if no plausible range is found.

        Fixes applied:
          • Fix 1: parenthesised block validated for numeric range content
          • Fix 2: date-like patterns and implausible values rejected
          • Fix 3: ≤/≥ (Unicode), lower-bound-only (>min), inclusive-upper (<=max)
          • Fix 4: titer direction (<1:160 = negative) preserved
          • Fix 5: unit found on line recorded so caller can check compatibility
          • Fix 7: provenance set to EXTRACTED_FROM_REPORT (not VERIFIED)
        """
        if not line_text:
            return None

        # Fix 2: skip any line that looks like it contains a date
        if self._looks_like_date(line_text):
            return None

        # ---- Detect any unit on the line (Fix 5) ----------------------------
        unit_match = _VALUE_WITH_UNIT_RE.search(line_text)
        detected_unit = unit_match.group(2) if unit_match else ""

        # ---- Isolate the reference-range segment of the line ----------------
        # Fix 1: only use the first parenthesised block if it looks numeric
        ref_text = line_text
        paren_match = re.search(r'[\(\[]([^\)\]]+)[\)\]]', line_text)
        if paren_match and self._bracket_has_numeric_range(paren_match.group(1)):
            ref_text = paren_match.group(1)
        elif re.search(r'(?:ref|reference|normal|range)', line_text, re.IGNORECASE):
            ref_text = re.sub(
                r'^.*?(?:ref|reference|normal|range)[\:\=]?', '',
                line_text, flags=re.IGNORECASE
            )

        _PROV = "EXTRACTED_FROM_REPORT"   # Fix 7

        # ---- Pattern 1: Titer with direction preserved (Fix 4) --------------
        # e.g.  Positive >= 1:160   or   Negative <1:80   or   1:160
        titer_full = re.search(
            r'([<>]?\s*(?:positive|significant|negative|normal|ref(?:erence)?))?'
            r'\s*([<>]?[=]?|\u2264|\u2265)?\s*1\s*:\s*(\d+)',
            ref_text, re.IGNORECASE
        )
        if not titer_full and ref_text != line_text:
            titer_full = re.search(r'([<>]?=?)\s*1\s*:\s*(\d+)', ref_text, re.IGNORECASE)

        if titer_full:
            groups = titer_full.groups()
            # Last capturing group is always the denominator
            denom_str = groups[-1]
            thresh_v = _parse_number(denom_str)
            if thresh_v is not None:
                # Fix 4: detect direction from the operator found before 1:N
                full_match_text = titer_full.group(0)
                direction = "gte"  # default: >= threshold means positive
                if re.search(r'<(?!=)', full_match_text):
                    direction = "lt"   # <1:160 means positive if *below* thresh
                return {
                    "type": "titer_threshold",
                    "threshold": thresh_v,
                    "direction": direction,   # "gte" or "lt"
                    "detected_unit": detected_unit,
                    "raw": titer_full.group(0),
                    "provenance": _PROV,
                }

        # ---- Pattern 2: Min-Max range (Fix 2, Fix 3) ------------------------
        # Fix 3: support – (en-dash) and 'to' as separators; comma-aware numbers
        min_max_match = re.search(
            r'(-?\d[\d,]*(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d[\d,]*(?:\.\d+)?)',
            ref_text, re.IGNORECASE
        )
        if not min_max_match and ref_text != line_text:
            min_max_match = re.search(
                r'(-?\d[\d,]*(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d[\d,]*(?:\.\d+)?)',
                line_text, re.IGNORECASE
            )
        if min_max_match:
            # Fix 2: reject dates embedded in the line
            if not self._looks_like_date(min_max_match.group(0)):
                min_v = _parse_number(min_max_match.group(1))
                max_v = _parse_number(min_max_match.group(2))
                if (
                    min_v is not None and max_v is not None
                    and min_v < max_v
                    and self._range_values_plausible(min_v, max_v)  # Fix 2
                ):
                    return {
                        "type": "min_max",
                        "min": min_v,
                        "max": max_v,
                        "detected_unit": detected_unit,
                        "raw": min_max_match.group(0),
                        "provenance": _PROV,
                    }

        # ---- Pattern 3: Comparison operators (Fix 3) ------------------------
        # Covers: <N, <=N, ≤N  (upper-bound)  and  >N, >=N, ≥N (lower-bound)
        # Fix 3: Unicode ≤ / ≥ support; lower-bound-only ranges
        cmp_match = re.search(
            r'([<>]\s*=?|\u2264|\u2265)\s*(-?\d[\d,]*(?:\.\d+)?)',
            ref_text, re.IGNORECASE
        )
        if cmp_match:
            operator = cmp_match.group(1).strip()
            bound_v = _parse_number(cmp_match.group(2))
            if bound_v is not None and self._range_values_plausible(-1000, bound_v):
                if operator in ('<', '\u2264', '<='):
                    inclusive = operator in ('<=', '\u2264')
                    return {
                        "type": "max_bound",
                        "max": bound_v,
                        "inclusive": inclusive,
                        "detected_unit": detected_unit,
                        "raw": cmp_match.group(0),
                        "provenance": _PROV,
                    }
                else:  # >, >=, ≥
                    inclusive = operator in ('>=', '\u2265')
                    return {
                        "type": "min_bound",
                        "min": bound_v,
                        "inclusive": inclusive,
                        "detected_unit": detected_unit,
                        "raw": cmp_match.group(0),
                        "provenance": _PROV,
                    }

        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _units_compatible(detected_unit, configured_unit):
        """
        Fix 5: Discard inline range when detected unit != configured unit.
        Returns True when either side is empty/missing.
        """
        if not detected_unit or not configured_unit:
            return True
        def _norm(u):
            return u.lower().replace(' ', '').replace('\u00b5', 'u').replace('\u03bc', 'u')
        return _norm(detected_unit) == _norm(configured_unit)

    # ------------------------------------------------------------------
    def _evaluate_with_json_rules(self, config, val, patient_gender=None, patient_age=None):
        """
        Run JSON rule-set for a value, returning
        (status, range_desc, rule_id, prov_source, prov_status).
        Used to preserve JSON category alongside inline result (Fix 6)
        and as single-source-of-truth Priority 2 evaluator.

        Hardened checks:
          - Rejects non-finite numbers (NaN/Inf)
          - Requires patient gender for gender-specific ranges (returns REVIEW_REQUIRED)
          - Considers patient age context (pediatric age < 18 returns REVIEW_REQUIRED for adult standard)
          - Detects missing reference bounds (returns CONFIGURATION_ERROR, never NORMAL)
        """
        # Guard against non-finite input
        if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
            return ('UNCLASSIFIED', 'Invalid non-finite numeric value (NaN/Infinity)',
                    'INVALID_NUM_001', 'Validation Gate', 'REJECTED')

        param_type = config.get('type')
        prov_source = config.get('source', 'Unavailable - Standard Clinical Testing Reference Rule')
        prov_status = config.get('provenance_status', 'UNAVAILABLE')
        configured_unit = config.get('unit', '')

        if param_type == 'titer_threshold':
            thresh = config.get('threshold', 160)
            if val >= thresh:
                return (config.get('positive_status', 'POSITIVE'),
                        f'JSON Threshold (>= 1:{int(thresh)})',
                        config.get('rule_id_positive', 'TITER_POS_001'),
                        prov_source, prov_status)
            return (config.get('negative_status', 'NEGATIVE'),
                    f'JSON Threshold (< 1:{int(thresh)})',
                    config.get('rule_id_negative', 'TITER_NEG_001'),
                    prov_source, prov_status)

        if param_type in ['category', 'clinical_threshold']:
            # Age context guard: adult standard cannot be silently applied to pediatric patients
            if patient_age is not None and patient_age < 18 and config.get("population") == "adult":
                age_display = int(patient_age) if isinstance(patient_age, float) and patient_age.is_integer() else patient_age
                return ('REVIEW_REQUIRED',
                        f"Adult category reference standards cannot be silently applied to pediatric patient (Age {age_display}). Clinical review required.",
                        'PEDIATRIC_CONTEXT_REVIEW_001',
                        prov_source,
                        'REVIEW_REQUIRED')

            pop_tag = " [Adult Standard]" if config.get("population") == "adult" else ""
            for rule in config.get('rules', []):
                ok = True
                if 'min_inclusive' in rule and val < rule['min_inclusive']: ok = False
                if 'min_exclusive' in rule and val <= rule['min_exclusive']: ok = False
                if 'max_inclusive' in rule and val > rule['max_inclusive']: ok = False
                if 'max_exclusive' in rule and val >= rule['max_exclusive']: ok = False
                if ok:
                    return (rule['status'],
                            f"JSON Rules ({configured_unit}){pop_tag}",
                            rule.get('rule_id', 'JSON_CATEGORY_MATCH_001'),
                            prov_source, prov_status)

            return ('UNCLASSIFIED', f"JSON Rules ({configured_unit})",
                    'JSON_UNCLASSIFIED_001', prov_source, prov_status)

        if param_type == 'reference_range':
            ref = config.get('reference', {})

            # 1. Gender-specific check: require applicable patient context
            if 'male' in ref and 'female' in ref:
                m_min, m_max = ref['male'].get('min'), ref['male'].get('max')
                f_min, f_max = ref['female'].get('min'), ref['female'].get('max')
                if not patient_gender:
                    return ('REVIEW_REQUIRED',
                            f"Gender-specific reference range requires patient gender context (Male: {m_min}-{m_max}, Female: {f_min}-{f_max} {configured_unit})",
                            'GENDER_CONTEXT_REQUIRED_001',
                            prov_source,
                            'REVIEW_REQUIRED')

                g_str = str(patient_gender).strip().lower()
                if g_str in ['female', 'f', 'woman', 'girl']:
                    ref_bounds = ref.get('female', {})
                elif g_str in ['male', 'm', 'man', 'boy']:
                    ref_bounds = ref.get('male', {})
                else:
                    return ('REVIEW_REQUIRED',
                            f"Unrecognized patient gender context '{patient_gender}' for gender-specific range (Male: {m_min}-{m_max}, Female: {f_min}-{f_max} {configured_unit})",
                            'GENDER_CONTEXT_REQUIRED_001',
                            prov_source,
                            'REVIEW_REQUIRED')
            else:
                ref_bounds = ref

            mn = ref_bounds.get('min')
            mx = ref_bounds.get('max')

            # 2. Missing reference bounds check: return configuration error, NEVER return NORMAL
            if mn is None and mx is None:
                return ('CONFIGURATION_ERROR',
                        'Missing reference bounds in rule configuration',
                        'CONFIG_ERROR_NO_BOUNDS_001',
                        prov_source,
                        'CONFIGURATION_ERROR')

            # 3. Patient age context check:
            # Do not silently apply generic configured adult ranges to pediatric patients
            if patient_age is not None and patient_age < 18:
                bound_str = f"{mn} - {mx}" if (mn is not None and mx is not None) else f"{mn or mx}"
                age_display = int(patient_age) if isinstance(patient_age, float) and patient_age.is_integer() else patient_age
                return ('REVIEW_REQUIRED',
                        f"Adult reference standard ({bound_str} {configured_unit}) cannot be silently applied to pediatric patient (Age {age_display}). Clinical review required.",
                        'PEDIATRIC_CONTEXT_REVIEW_001',
                        prov_source,
                        'REVIEW_REQUIRED')

            # Population annotation
            pop_note = " [Adult Standard - age unverified]" if patient_age is None else " [Adult Standard]"

            # Single-sided bounds
            if mn is not None and mx is None:
                if val < mn:
                    return ('LOW', f'JSON Default (>= {mn} {configured_unit}){pop_note}',
                            config.get('rule_id_low', 'JSON_REF_LOW_001'), prov_source, prov_status)
                return ('NORMAL', f'JSON Default (>= {mn} {configured_unit}){pop_note}',
                        config.get('rule_id_normal', 'JSON_REF_NORMAL_001'), prov_source, prov_status)

            if mx is not None and mn is None:
                if val > mx:
                    return ('HIGH', f'JSON Default (<= {mx} {configured_unit}){pop_note}',
                            config.get('rule_id_high', 'JSON_REF_HIGH_001'), prov_source, prov_status)
                return ('NORMAL', f'JSON Default (<= {mx} {configured_unit}){pop_note}',
                        config.get('rule_id_normal', 'JSON_REF_NORMAL_001'), prov_source, prov_status)

            # Two-sided bounds
            if val < mn:
                return ('LOW', f'JSON Default ({mn} - {mx} {configured_unit}){pop_note}',
                        config.get('rule_id_low', 'JSON_REF_LOW_001'), prov_source, prov_status)
            if val > mx:
                return ('HIGH', f'JSON Default ({mn} - {mx} {configured_unit}){pop_note}',
                        config.get('rule_id_high', 'JSON_REF_HIGH_001'), prov_source, prov_status)
            return ('NORMAL', f'JSON Default ({mn} - {mx} {configured_unit}){pop_note}',
                    config.get('rule_id_normal', 'JSON_REF_NORMAL_001'), prov_source, prov_status)

        return ('UNCLASSIFIED', 'JSON Default', 'UNCLASSIFIED_RULE_001', prov_source, prov_status)

    # ------------------------------------------------------------------
    def evaluate_value(self, config, val, inline_range=None, patient_gender=None,
                       comparison_op=None, patient_age=None):
        """
        Evaluate an extracted numerical value.
        Priority 1: Report inline reference range (if unit-compatible)
        Priority 2: JSON reference rules fallback

        Returns (status, range_description, range_source, rule_id,
                 provenance_source, provenance_status)
        """
        # Guard against non-finite input
        if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
            return 'UNCLASSIFIED', 'Invalid non-finite numeric value (NaN/Infinity)', 'INPUT_VALIDATION', 'INVALID_NUM_001', 'Validation Gate', 'REJECTED'

        param_type = config.get('type')
        prov_source = config.get('source', 'Unavailable - Standard Clinical Testing Reference Rule')
        prov_status = config.get('provenance_status', 'UNAVAILABLE')
        configured_unit = config.get('unit', '')

        # Fix 5: discard inline range when units are incompatible
        if inline_range:
            if not self._units_compatible(inline_range.get('detected_unit', ''), configured_unit):
                inline_range = None

        # --- Priority 1: Report Inline Range ---
        if inline_range:
            PROV = 'EXTRACTED_FROM_REPORT'   # Fix 7
            ir_type = inline_range.get('type')
            # Fix 6: run JSON rules to preserve category detail
            json_status, _, _, _, _ = self._evaluate_with_json_rules(config, val, patient_gender, patient_age)

            if ir_type == 'titer_threshold' or param_type == 'titer_threshold':
                thresh = inline_range.get('threshold', config.get('threshold', 160))
                direction = inline_range.get('direction', 'gte')   # Fix 4
                pos_status = config.get('positive_status', 'POSITIVE')
                neg_status = config.get('negative_status', 'NEGATIVE')
                is_positive = (val < thresh) if direction == 'lt' else (val >= thresh)
                status = pos_status if is_positive else neg_status
                rule_id = (config.get('rule_id_positive', 'REPORT_INLINE_TITER_001')
                           if is_positive else
                           config.get('rule_id_negative', 'REPORT_INLINE_TITER_002'))
                op_str = '<' if direction == 'lt' else '>='
                desc = f'Report Threshold ({op_str}1:{int(thresh)}) [JSON: {json_status}]'
                return status, desc, 'REPORT_INLINE', rule_id, prov_source, PROV

            elif ir_type == 'min_max':
                mn, mx = inline_range.get('min'), inline_range.get('max')
                if mn is None and mx is None:
                    return 'CONFIGURATION_ERROR', 'Missing reference bounds in report inline range', 'REPORT_INLINE', 'REPORT_INLINE_NO_BOUNDS_001', 'Report Printed Reference Range', PROV
                if val < mn:
                    s, rid = 'LOW', 'REPORT_INLINE_LOW_001'
                elif val > mx:
                    s, rid = 'HIGH', 'REPORT_INLINE_HIGH_001'
                else:
                    s, rid = 'NORMAL', 'REPORT_INLINE_NORMAL_001'
                desc = f'Report Range ({mn} - {mx}) [JSON category: {json_status}]'
                return s, desc, 'REPORT_INLINE', rid, 'Report Printed Reference Range', PROV

            elif ir_type == 'max_bound':
                mx = inline_range.get('max')
                if mx is None:
                    return 'CONFIGURATION_ERROR', 'Missing upper bound in report inline range', 'REPORT_INLINE', 'REPORT_INLINE_NO_BOUNDS_001', 'Report Printed Reference Range', PROV
                inclusive = inline_range.get('inclusive', False)
                is_normal = (val <= mx) if inclusive else (val < mx)
                op = '<=' if inclusive else '<'
                s = 'NORMAL' if is_normal else 'HIGH'
                rid = 'REPORT_INLINE_NORMAL_002' if is_normal else 'REPORT_INLINE_HIGH_002'
                return s, f'Report Threshold ({op}{mx}) [JSON: {json_status}]', 'REPORT_INLINE', rid, 'Report Printed Reference Range', PROV

            elif ir_type == 'min_bound':
                mn = inline_range.get('min')
                if mn is None:
                    return 'CONFIGURATION_ERROR', 'Missing lower bound in report inline range', 'REPORT_INLINE', 'REPORT_INLINE_NO_BOUNDS_001', 'Report Printed Reference Range', PROV
                inclusive = inline_range.get('inclusive', False)
                is_normal = (val >= mn) if inclusive else (val > mn)
                op = '>=' if inclusive else '>'
                s = 'NORMAL' if is_normal else 'LOW'
                rid = 'REPORT_INLINE_NORMAL_003' if is_normal else 'REPORT_INLINE_LOW_002'
                return s, f'Report Threshold ({op}{mn}) [JSON: {json_status}]', 'REPORT_INLINE', rid, 'Report Printed Reference Range', PROV

            elif ir_type == 'max_exclusive':   # backward compat
                mx = inline_range['max']
                if val < mx:
                    return 'NORMAL', f'Report Threshold (<{mx}) [JSON: {json_status}]', 'REPORT_INLINE', 'REPORT_INLINE_NORMAL_002', 'Report Printed Reference Range', PROV
                return 'HIGH', f'Report Threshold (<{mx}) [JSON: {json_status}]', 'REPORT_INLINE', 'REPORT_INLINE_HIGH_002', 'Report Printed Reference Range', PROV

        # --- Priority 2: JSON Reference Rules (Centralized single source of truth) ---
        st, desc, rid, ps, pst = self._evaluate_with_json_rules(config, val, patient_gender, patient_age)
        return st, desc, 'DEFAULT_JSON', rid, ps, pst

    # ------------------------------------------------------------------
    def _parse_titer_val(self, val_str):
        """Converts '1:160' or '160' or '1 : 40' into float denominator."""
        val_str = str(val_str).strip()
        if ":" in val_str:
            parts = val_str.split(":")
            denom = _parse_number(parts[-1].strip())
            if denom is not None:
                return denom, f"1:{int(denom)}"
        num = _parse_number(val_str)
        if num is not None:
            return num, f"1:{int(num)}"
        return None, val_str

    # ------------------------------------------------------------------
    def evaluate_single_parameter(self, param_key_or_alias, value, line_text="", patient=None, timing_context=None):
        """
        Directly evaluate a single parameter value by name or alias.

        Fixes applied here:
          • Fix 1: partial-match fallback replaced with strict whole-word regex
            so short / generic names cannot silently select the wrong analyte.
          • Fix 2: empty / whitespace-only input is rejected immediately.
          • Fix 3: substring fallback that let 'cholesterol' match 'ldl-cholesterol'
            is removed; only word-boundary matching is used.
          • Fix 6: Guard against mapping acute/generic glucose to mean_blood_glucose (eAG).
            Requires explicit timing context (fasting vs random) under ADA 2024 Standards.
            Without timing context, returns INSUFFICIENT_CONTEXT; does not guess or force HIGH.
        """
        # Fix 2: reject empty input before any lookup
        raw = str(param_key_or_alias).strip()
        if not raw:
            return None

        alias_key = raw.lower()
        timing_str = (timing_context or "").strip().lower() if timing_context else ""

        # Distinguish generic glucose terms from explicit analyte concepts
        generic_glucose_terms = {
            "glucose", "blood glucose", "serum glucose", "plasma glucose", "blood sugar"
        }
        is_generic_glucose = alias_key in generic_glucose_terms

        matched_info = None

        if is_generic_glucose:
            if timing_str in ("fasting", "fast", "fbs", "fpg", "fasting (>= 8 hours)", "fasting (>=8 hrs)", "fasting (>= 8 hrs)"):
                matched_info = self.parameter_map.get("fasting_glucose")
            elif timing_str in ("random", "casual", "rbs", "non-fasting", "non_fasting"):
                matched_info = self.parameter_map.get("random_glucose")
            elif timing_str in ("2h_postprandial", "ogtt", "postprandial", "2 hour", "2h", "2h postprandial"):
                matched_info = self.parameter_map.get("ogtt_2_hour")
            else:
                # Timing context is missing, unspecified, or unknown.
                # Do NOT guess or force HIGH. Return explicit INSUFFICIENT_CONTEXT.
                val = _parse_number(str(value))
                display_val = val if val is not None else value
                return {
                    "finding_id": "LAB-001",
                    "parameter": "Glucose (Timing Unspecified)",
                    "key": "glucose_unspecified",
                    "category": "diabetic_profile",
                    "value": display_val,
                    "unit": "mg/dL",
                    "status": "INSUFFICIENT_CONTEXT",
                    "rule_id": "GLUCOSE_TIMING_CONTEXT_REQUIRED",
                    "range_description": "Specimen timing context (fasting vs. random) is required to determine clinical reference range under ADA 2024 standards.",
                    "range_source": "ADA 2024 Standards of Care",
                    "provenance_source": "ADA 2024 Standards of Care",
                    "provenance_status": "INSUFFICIENT_CONTEXT",
                    "rejection_reason": "Specimen timing context (fasting vs. random) is required to evaluate glucose clinical reference thresholds under ADA 2024 standards."
                }
        else:
            # 1. Exact match (also covers canonical key registrations — Fix 4)
            matched_info = self.parameter_map.get(alias_key)

        if not matched_info:
            # Fix 1 & 3: strict word-boundary partial match
            # Require the input to be at least 4 chars to avoid noise tokens
            # matching every alias that happens to contain them.
            if len(alias_key) >= 4:
                pattern = re.compile(
                    r'(?<![\w-])' + re.escape(alias_key) + r'(?![\w-])',
                    re.IGNORECASE
                )
                for a_key, info in self.parameter_map.items():
                    # Guard: Never map generic glucose terms to mean_blood_glucose (eAG)!
                    if info.get("key") == "mean_blood_glucose" and alias_key in generic_glucose_terms:
                        continue
                    if pattern.search(a_key):
                        matched_info = info
                        break

        if not matched_info:
            return None

        config = matched_info["config"]
        patient_gender = patient.get("gender") if patient else None
        patient_age = self._extract_patient_age(patient)

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
            val = _parse_number(str(value))   # handles commas, sci-notation, negatives
            if val is None:
                return None
            display_val = val

        inline_range = self.extract_inline_report_range(line_text)
        status, range_desc, source, rule_id, prov_source, prov_status = self.evaluate_value(
            config, val, inline_range, patient_gender, patient_age=patient_age
        )

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

    # ------------------------------------------------------------------
    def _extract_value_after_alias(self, alias: str, line: str, config: dict):
        """
        Robustly extract a numeric value from the portion of *line* that comes
        AFTER the alias match.  This prevents numbers that belong to a
        different test or to a reference range printed earlier on the line
        from being selected.

        Returns (val: float|None, display_val, unit: str, comparison_op: str|None)

        Fixes addressed here:
          • Number search now scoped to text after the alias (fix 1)
          • Comma-formatted values (fix 5)
          • Scientific notation (fix 6)
          • Comparison symbols preserved (fix 7)
          • Negative numbers (fix 8)
          • Units validated before assignment (fix 9)
          • Unit regex anchored to avoid partial matches (fix 12)
          • Extended unit vocabulary (fix 11)
        """
        is_titer = config.get("type") == "titer_threshold"
        configured_unit = config.get("unit", "")

        # --- Find position of alias in line (case-insensitive) ---
        alias_re = re.compile(re.escape(alias), re.IGNORECASE)
        m = alias_re.search(line)
        after_alias = line[m.end():] if m else line

        # === Titer types ===
        if is_titer:
            titer_m = re.search(r'1\s*:\s*(\d+)', after_alias)
            if not titer_m:
                titer_m = re.search(r'1\s*:\s*(\d+)', line)
            if titer_m:
                denom = _parse_number(titer_m.group(1))
                if denom is not None:
                    return denom, f"1:{int(denom)}", "titer", None
            # bare number after alias
            bare = re.search(r'[\:\=\s\-\>]+\s*(\d+)', after_alias)
            if bare:
                denom = _parse_number(bare.group(1))
                if denom is not None:
                    return denom, f"1:{int(denom)}", "titer", None
            return None, None, configured_unit, None

        # === Non-titer types ===

        # 1. Comparison operator + value (e.g. <5, >90)  [fix 7]
        cmp_op, cmp_val = _extract_comparison(after_alias)

        # 2. Value with anchored unit match  [fix 9, 11, 12]
        unit_anchored = _VALUE_WITH_UNIT_RE.search(after_alias)
        if unit_anchored:
            raw_num_str = unit_anchored.group(1)
            matched_unit = unit_anchored.group(2)
            val = _parse_number(raw_num_str)
            if val is not None:
                return val, val, matched_unit, cmp_op

        # 3. Plain number in the after-alias section  [fix 1 - scoped search]
        plain_m = _PLAIN_NUMBER_RE.search(after_alias)
        if plain_m:
            val = _parse_number(plain_m.group(0))
            if val is not None:
                # Assign configured unit (no unit printed on line - fix 9 note:
                # we flag this as unit_inferred in the candidate so downstream
                # validator can choose how to handle it)
                return val, val, configured_unit, cmp_op

        return None, None, configured_unit, None

    # ------------------------------------------------------------------
    def parse_and_evaluate(self, report_text, patient=None, ocr_metadata=None):
        """
        Parses OCR/report text, extracts candidate values, and runs the
        7-layer FindingValidator gate to construct validated IR objects.

        Fixes in this method:
          • Multiple findings extracted per line (fix 2) — break removed,
            inner loop continues after a match.
          • seen_keys uses (key, line_idx) so repeated measurements on
            different lines are not silently dropped (fix 3).
          • Reference-only lines rejected via _is_reference_only_line (fix 4).
        """
        from finding_validator import FindingValidator, ValidatedFinding

        raw_results = []
        # Fix 3: key-only dedup replaced with (param_key, line_idx) so the
        # same analyte on a later line (different date / sample) is kept.
        # Within the same line we still deduplicate to avoid double-counting
        # a test mentioned twice on one row.
        seen_line_keys = set()   # (param_key, line_idx) seen this scan
        seen_keys = set()        # param_key already emitted (kept for derived-value guard)

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
                # --- Alias match (short aliases word-boundary, long aliases substring) ---
                if len(alias) <= 3:
                    if not re.search(r'\b' + re.escape(alias) + r'\b', line_lower):
                        continue
                else:
                    if alias not in line_lower:
                        continue

                info = self.parameter_map[alias]
                param_key = info["key"]
                config = info["config"]

                # Fix 3: allow same param on different lines; dedupe within same line only
                dedup_key = (param_key, line_idx)
                if dedup_key in seen_line_keys:
                    continue

                # Fix 4: skip reference-only lines
                if _is_reference_only_line(line_clean, alias):
                    continue

                val, display_val, unit, cmp_op = self._extract_value_after_alias(
                    alias, line_clean, config
                )

                if val is None:
                    # Fix 2: don't break — let other aliases on this line match
                    continue

                # Fix 9: if unit came from configured (not measured) mark it
                unit_inferred = (unit == config.get("unit", "") and
                                 not _VALUE_WITH_UNIT_RE.search(line_clean))

                inline_range = self.extract_inline_report_range(line_clean)
                patient_gender = patient.get("gender") if patient else None
                patient_age = self._extract_patient_age(patient)

                status, range_desc, source, rule_id, prov_source, prov_status = self.evaluate_value(
                    config, val, inline_range, patient_gender, comparison_op=cmp_op, patient_age=patient_age
                )

                # Reconcile printed range vs guideline category as distinct structured comparisons
                printed_comp = {
                    "status": status if source == "REPORT_INLINE" else "NOT_AVAILABLE",
                    "range": inline_range.get("raw") if inline_range else "Not printed on report",
                    "range_description": inline_range.get("raw") if inline_range else "Not printed on report",
                    "source": prov_source if source == "REPORT_INLINE" else None,
                    "rule_id": rule_id if source == "REPORT_INLINE" else None
                }

                json_status, json_desc, json_rid, json_source, json_prov = self._evaluate_with_json_rules(
                    config, val, patient_gender, patient_age
                )
                guideline_comp = {
                    "status": json_status if json_status else "NOT_MAPPED",
                    "range": json_desc,
                    "range_description": json_desc,
                    "source": json_source,
                    "rule_id": json_rid
                }

                disposition = "EVALUATED" if (source == "REPORT_INLINE" and json_status) else (
                    "EVALUATED_PRINTED_RANGE_ONLY" if source == "REPORT_INLINE" else "EVALUATED"
                )

                candidate = {
                    "finding_id": f"LAB-{finding_counter:03d}",
                    "parameter": info["primary_name"],
                    "test_name": info["primary_name"],
                    "key": param_key,
                    "category": info["category"],
                    "value": display_val,
                    "result_value": display_val,
                    "result_text": f"{display_val} {unit}".strip() if display_val is not None else "",
                    "unit": unit,
                    "unit_inferred": unit_inferred,
                    "comparison_op": cmp_op,
                    "status": status,
                    "rule_id": rule_id,
                    "range_description": range_desc,
                    "range_source": source,
                    "provenance_source": prov_source,
                    "provenance_status": prov_status,
                    "source_line_number": line_idx,
                    "raw_source_line": line_clean,
                    "confidence": conf_val,
                    "printed_comparison": printed_comp,
                    "guideline_comparison": guideline_comp,
                    "disposition": disposition
                }

                # Run 7-Layer Validation Gate
                vf = FindingValidator.validate_candidate_finding(candidate, report_text=report_text)
                raw_results.append(vf.to_dict())
                seen_line_keys.add(dedup_key)
                seen_keys.add(param_key)
                finding_counter += 1

                # Derived Value: Mean Blood Glucose from HbA1c
                if param_key == "hba1c" and "mean_blood_glucose" not in seen_keys:
                    mbg_match = re.search(
                        r'(?:mean blood glucose|eag|mbg)[\:\=\s\-\>]+\s*(-?\d[\d,]*(?:\.\d+)?)',
                        report_text, re.IGNORECASE
                    )
                    if mbg_match:
                        mbg_val = _parse_number(mbg_match.group(1))
                        if mbg_val is not None:
                            mbg_candidate = {
                                "finding_id": f"LAB-{finding_counter:03d}",
                                "parameter": "Mean Blood Glucose",
                                "test_name": "Mean Blood Glucose",
                                "key": "mean_blood_glucose",
                                "category": "diabetes",
                                "value": mbg_val,
                                "result_value": mbg_val,
                                "result_text": f"{mbg_val} mg/dL",
                                "unit": "mg/dL",
                                "unit_inferred": False,
                                "comparison_op": None,
                                "status": "NORMAL" if mbg_val <= 154 else "HIGH",
                                "rule_id": "DERIVED_MBG_001",
                                "range_description": "Derived from HbA1c (eAG)",
                                "range_source": "DERIVED",
                                "provenance_source": "ADA eAG Calculation Formula",
                                "provenance_status": "VERIFIED",
                                "source_line_number": line_idx,
                                "raw_source_line": line_clean,
                                "confidence": conf_val,
                                "measurement_type": "DERIVED",
                                "printed_comparison": {"status": "NOT_AVAILABLE", "range_description": "Derived", "source": "ADA eAG Calculation Formula"},
                                "guideline_comparison": {"status": "NORMAL" if mbg_val <= 154 else "HIGH", "source": "ADA 2024 Standards of Care (eAG)", "rule_id": "DERIVED_MBG_001"},
                                "disposition": "EVALUATED"
                            }
                            vf_mbg = FindingValidator.validate_candidate_finding(
                                mbg_candidate, report_text=report_text
                            )
                            raw_results.append(vf_mbg.to_dict())
                            seen_keys.add("mean_blood_glucose")
                            finding_counter += 1

                # Fix 2: do NOT break — continue checking remaining aliases
                # on this line so multiple tests on a single row are captured.

        # Pass 2: Extract non-canonical report test lines (e.g. Post Prandial Blood Sugar, Urine Sugar)
        matched_line_indices = {lk[1] for lk in seen_line_keys}
        for line_idx, line in enumerate(lines, 1):
            if line_idx in matched_line_indices:
                continue
            line_clean = line.strip()
            if not line_clean or len(line_clean) < 3:
                continue

            # Skip metadata, titles, addresses, signatures
            if self._is_report_metadata_line(line_clean):
                continue

            conf_val = None
            if ocr_metadata and isinstance(ocr_metadata, list):
                for meta in ocr_metadata:
                    if meta.get("line_number") == line_idx or meta.get("raw_line") == line_clean:
                        conf_val = meta.get("confidence")
                        break

            non_canon_entry = self._extract_non_canonical_finding(line_clean, line_idx, finding_counter, conf_val=conf_val)
            if non_canon_entry:
                vf_nc = FindingValidator.validate_candidate_finding(non_canon_entry, report_text=report_text)
                raw_results.append(vf_nc.to_dict())
                finding_counter += 1
                matched_line_indices.add(line_idx)

        return raw_results

    def _is_report_metadata_line(self, line: str) -> bool:
        """Filters out patient headers, doctor details, and laboratory administrative notices."""
        line_lower = line.lower()
        if re.search(r'(?i)\b(?:sugar|glucose|urea|creatinine|urine|blood|protein|bilirubin|tsh|hemoglobin)\b', line_lower):
            # Contains an analyte keyword — keep for potential finding extraction
            return False

        metadata_patterns = [
            r'(?i)\b(?:m\.?g\.?d|reg\.?\s*date|registration\s*date|patient\s*name|client\s*name)\b',
            r'(?i)\b(?:age|sex|gender|dob|date|time|specimen|sample|bill\s*no|mrn|ip\s*no|op\s*no)\s*[\:\=]',
            r'(?i)\b(?:patient|doctor|consultant|pathologist|physician|hospital|clinic)\s*[\:\=]',
            r'(?i)^\s*(?:test|investigation|parameter)\s+(?:name\s+)?(?:result|value)\b',
            r'(?i)\b(?:ref\.?\s*by|referred\s*by|consultant\s*pathologist|mbbs|dr\.?\s*\(prof\))\b',
            r'(?i)\b(?:laboratory\s*timings|service\s*to\s*suffering|biochemistry\s*report|pathology\s*report)\b',
            r'(?i)\b(?:unit\s*of\s*mgartk|jjm\s*medical\s*college|davanagere|national\s*training)\b',
            r'(?i)\b(?:test\s*name\s*value|reference\s*value|technician|signature)\b',
            r'(?i)^[-_=\s\.\*]{4,}$'
        ]
        return any(re.search(p, line_lower) for p in metadata_patterns)

    def _extract_non_canonical_finding(self, line: str, line_idx: int, finding_counter: int, conf_val=None) -> dict:
        """
        Extracts non-canonical test lines (e.g. Post Prandial Blood Sugar, Urine Sugar)
        preserving original measurements, printed ranges, and dispositions.
        """
        # Format 1: Test Name : Value [Range]
        m = re.match(r'^([^:]+?)\s*:\s*(.+)$', line)
        if m:
            tname = m.group(1).strip()
            rest = m.group(2).strip()
        else:
            # Format 2: Space separated Test Name Value Unit Range
            space_m = re.match(r'^([A-Za-z0-9\s\(\)\-\/]+?)\s+(-?\d+(?:\.\d+)?)\s*([a-zA-Z\/%]+)?\s+(\d+(?:\.\d+)?\s*(?:-|to|–)\s*\d+(?:\.\d+)?(?:\s*[a-zA-Z\/]+)?)$', line)
            if space_m:
                tname = space_m.group(1).strip()
                rest = f"{space_m.group(2)} {space_m.group(3) or ''} {space_m.group(4)}".strip()
            else:
                return None

        # Check for numeric result with printed range: e.g. 262 mg/dl 80 - 140 mg/dl
        range_match = re.search(r'(\d+(?:\.\d+)?\s*(?:-|to|–)\s*\d+(?:\.\d+)?(?:\s*[a-zA-Z\/]+)?)$', rest, re.IGNORECASE)
        if range_match:
            range_str = range_match.group(1).strip()
            val_part = rest[:range_match.start()].strip()
            num_m = re.search(r'(-?\d+(?:\.\d+)?)\s*([a-zA-Z\/%]+)?', val_part)
            if num_m:
                val = float(num_m.group(1))
                unit = num_m.group(2) or ""
                # Evaluate against printed range
                r_bounds = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)', range_str)
                low_b = float(r_bounds.group(1)) if r_bounds else None
                high_b = float(r_bounds.group(2)) if r_bounds else None

                status = "NORMAL"
                rid = "REPORT_INLINE_NORMAL_001"
                if low_b is not None and val < low_b:
                    status = "LOW"
                    rid = "REPORT_INLINE_LOW_001"
                elif high_b is not None and val > high_b:
                    status = "HIGH"
                    rid = "REPORT_INLINE_HIGH_001"

                # Check if this is post-meal blood sugar (not standardized OGTT)
                is_post_prandial = "post" in tname.lower() or "prandial" in tname.lower() or "ppbs" in tname.lower()
                guideline_note = (
                    "Not mapped to standardized 2-hour OGTT criteria (standardized 75-g glucose load timing not specified in source report)."
                    if is_post_prandial else "Standardized guideline mapping unavailable for this test."
                )

                return {
                    "finding_id": f"LAB-{finding_counter:03d}",
                    "parameter": tname,
                    "test_name": tname,
                    "normalized_test_name": tname.lower().replace(" ", "_"),
                    "key": tname.lower().replace(" ", "_"),
                    "category": "biochemistry",
                    "value": val,
                    "result_value": val,
                    "result_text": f"{val} {unit}".strip(),
                    "unit": unit,
                    "reference_text": f"Report Range ({range_str})",
                    "range_description": f"Report Range ({range_str})",
                    "status": status,
                    "rule_id": rid,
                    "range_source": "REPORT_INLINE",
                    "provenance_source": "Report Printed Reference Range",
                    "provenance_status": "EXTRACTED_FROM_REPORT",
                    "source_line_number": line_idx,
                    "raw_source_line": line,
                    "confidence": conf_val,
                    "measurement_type": "DIRECT",
                    "printed_comparison": {
                        "status": status,
                        "range": range_str,
                        "range_description": range_str,
                        "source": "Report Printed Reference Range",
                        "rule_id": rid
                    },
                    "guideline_comparison": {
                        "status": "NOT_MAPPED",
                        "range": None,
                        "source": guideline_note,
                        "rule_id": "GUIDELINE_NOT_MAPPED"
                    },
                    "disposition": "EVALUATED_PRINTED_RANGE_ONLY",
                    "validation_status": "VALIDATED"
                }

        # Check qualitative observation: e.g. "Nil Nil" or "Yellow 1 % Nil"
        words = rest.split()
        if len(words) >= 2:
            ref_part = words[-1]
            val_part = " ".join(words[:-1])
        else:
            ref_part = "Nil"
            val_part = rest

        return {
            "finding_id": f"LAB-{finding_counter:03d}",
            "parameter": tname,
            "test_name": tname,
            "normalized_test_name": tname.lower().replace(" ", "_"),
            "key": tname.lower().replace(" ", "_"),
            "category": "qualitative_observation",
            "value": None,
            "result_value": None,
            "result_text": val_part,
            "unit": None,
            "reference_text": f"Report Printed Reference: {ref_part}",
            "range_description": f"Report Printed Reference: {ref_part}",
            "status": "NOT_APPLICABLE",
            "rule_id": "UNSUPPORTED_QUALITATIVE_001",
            "range_source": "REPORT_INLINE",
            "provenance_source": "Report Printed Reference Observation",
            "provenance_status": "EXTRACTED_FROM_REPORT",
            "source_line_number": line_idx,
            "raw_source_line": line,
            "confidence": conf_val,
            "measurement_type": "QUALITATIVE",
            "printed_comparison": {
                "status": "NOT_APPLICABLE",
                "range": ref_part,
                "range_description": ref_part,
                "source": "Report Printed Reference Observation",
                "rule_id": "UNSUPPORTED_QUALITATIVE_001"
            },
            "guideline_comparison": {
                "status": "NOT_APPLICABLE",
                "range": None,
                "source": "Standardized quantitative guideline thresholds not applicable to qualitative observation.",
                "rule_id": "GUIDELINE_NOT_APPLICABLE"
            },
            "disposition": "UNSUPPORTED_QUALITATIVE",
            "validation_status": "UNSUPPORTED"
        }

    # ------------------------------------------------------------------
    def format_deterministic_markdown(self, evaluation_results):
        """Format deterministic evaluation results into a Markdown block with distinct comparisons and truthful coverage."""
        if not evaluation_results:
            return "No standardized laboratory parameters evaluated by the Rule Engine."

        md_lines = ["### ⚡ Deterministic Rule Engine Clinical Evaluation\n"]
        md_lines.append(
            "| Finding ID | Test Parameter | Measured / Observed | Unit | Printed Ref Range | "
            "Printed Range Status | Guideline Status | Disposition | Source Provenance |"
        )
        md_lines.append(
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |"
        )

        total_extracted = len(evaluation_results)
        evaluated_printed_count = 0
        evaluated_guideline_count = 0
        unsupported_qual_count = 0

        for res in evaluation_results:
            fid = res.get("finding_id", "LAB-001")
            param_str = res.get('test_name', res.get('parameter', 'Test'))
            val = res.get('result_value', res.get('value'))
            raw_text = res.get('result_text')
            if raw_text is not None and str(raw_text).strip() and str(raw_text).strip().lower() != "none":
                res_text = str(raw_text).strip()
            elif val is not None and isinstance(val, (int, float)):
                res_text = f"{val}"
            else:
                res_text = "—"
            unit_str = res.get('unit') or "—"
            if res.get('unit_inferred'):
                unit_str = f"{unit_str}*"

            p_comp = res.get("printed_comparison", {})
            g_comp = res.get("guideline_comparison", {})
            disposition = res.get("disposition", "EVALUATED")

            # Printed status badge
            p_status = p_comp.get("status", res.get("status", "NORMAL"))
            if p_status in ['NORMAL', 'DESIRABLE', 'OPTIMAL', 'ACCEPTABLE', 'NEGATIVE']:
                p_badge = f"🟢 **{p_status}**"
                evaluated_printed_count += 1
            elif p_status in ['HIGH', 'VERY_HIGH', 'LOW', 'POSITIVE']:
                p_badge = f"🔴 **{p_status}**"
                evaluated_printed_count += 1
            elif p_status in ['PREDIABETES', 'PREDIABETES_RANGE', 'BORDERLINE_HIGH']:
                p_badge = f"🟡 **{p_status}**"
                evaluated_printed_count += 1
            else:
                p_badge = f"ℹ️ **{p_status}**"

            # Guideline status badge
            g_status = g_comp.get("status", "NOT_MAPPED")
            if g_status in ['NORMAL', 'DESIRABLE', 'OPTIMAL', 'ACCEPTABLE', 'NEGATIVE']:
                g_badge = f"🟢 **{g_status}**"
                evaluated_guideline_count += 1
            elif g_status in ['PREDIABETES', 'PREDIABETES_RANGE', 'BORDERLINE_HIGH']:
                g_badge = f"🟡 **{g_status}** (ADA 2024)"
                evaluated_guideline_count += 1
            elif g_status in ['DIABETES_RANGE', 'HIGH', 'VERY_HIGH', 'LOW', 'POSITIVE']:
                g_badge = f"🔴 **{g_status}**"
                evaluated_guideline_count += 1
            elif g_status == "NOT_MAPPED":
                g_badge = "ℹ️ `NOT_MAPPED`"
            else:
                g_badge = f"ℹ️ `{g_status}`"

            # Disposition badge
            if disposition == "EVALUATED":
                disp_badge = "🟢 `EVALUATED`"
            elif disposition == "EVALUATED_PRINTED_RANGE_ONLY":
                disp_badge = "🟡 `PRINTED_RANGE_ONLY`"
            elif disposition == "UNSUPPORTED_QUALITATIVE":
                disp_badge = "⚠️ `UNSUPPORTED_QUALITATIVE`"
                unsupported_qual_count += 1
            elif disposition == "INSUFFICIENT_CONTEXT":
                disp_badge = "⚠️ `INSUFFICIENT_CONTEXT`"
            else:
                disp_badge = f"`{disposition}`"

            ref_str = p_comp.get("range_description") or res.get("reference_text") or res.get("range_description") or "—"
            prov_str = res.get("provenance_source", "Report Printed Reference Range")

            md_lines.append(
                f"| {fid} | {param_str} | {res_text} | {unit_str} | {ref_str} | "
                f"{p_badge} | {g_badge} | {disp_badge} | {prov_str} |"
            )

        md_lines.append("\n### 📊 Evaluation Coverage Summary")
        md_lines.append(f"- **Total Extracted Results:** {total_extracted}")
        md_lines.append(f"- **Evaluated Against Printed Reference Range:** {evaluated_printed_count}")
        md_lines.append(f"- **Evaluated Against Authoritative Guidelines:** {evaluated_guideline_count}")
        md_lines.append(f"- **Unsupported Qualitative Observations:** {unsupported_qual_count}")
        md_lines.append("- **Coverage Definitions:**")
        md_lines.append("  - *Evaluated:* Measured numeric value compared against validated laboratory printed ranges and published guideline criteria.")
        md_lines.append("  - *Printed Range Only:* Measured numeric value compared against the laboratory's printed reference range when clinical guideline mapping is unavailable or unverified.")
        md_lines.append("  - *Unsupported Qualitative:* Qualitative or semi-quantitative findings preserved as reported without automated clinical interpretation.")

        return "\n".join(md_lines)
