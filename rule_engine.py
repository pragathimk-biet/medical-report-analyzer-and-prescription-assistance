"""
rule_engine.py — Deterministic Medical Rule Engine
Evaluates extracted biomarker values against reference_ranges.json
Returns structured findings: HIGH / LOW / NORMAL / CRITICAL
"""

import json
import re
import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load reference ranges
# ---------------------------------------------------------------------------
_REF_PATH = os.path.join(os.path.dirname(__file__), "reference_ranges.json")
try:
    with open(_REF_PATH, "r", encoding="utf-8") as _f:
        REFERENCE_RANGES = json.load(_f)
    logger.info(f"Loaded {len(REFERENCE_RANGES)} reference ranges from {_REF_PATH}")
except Exception as _e:
    logger.error(f"Could not load reference_ranges.json: {_e}")
    REFERENCE_RANGES = {}

# ---------------------------------------------------------------------------
# Build alias → canonical key lookup
# ---------------------------------------------------------------------------
_ALIAS_MAP: dict[str, str] = {}
for _canon, _data in REFERENCE_RANGES.items():
    _ALIAS_MAP[_canon.lower()] = _canon
    for _alias in _data.get("aliases", []):
        _ALIAS_MAP[_alias.lower()] = _canon


def _resolve_key(test_name: str) -> str | None:
    """Resolve a free-form test name to a canonical key."""
    t = test_name.strip().lower()
    if t in _ALIAS_MAP:
        return _ALIAS_MAP[t]
    # Partial match
    for alias, canon in _ALIAS_MAP.items():
        if alias in t or t in alias:
            return canon
    return None


# ---------------------------------------------------------------------------
# Widal titer helper
# ---------------------------------------------------------------------------
def _parse_titer(raw: str) -> float | None:
    """Parse titer values like 1:160, 1/160 → 160.0"""
    m = re.search(r'1[:/](\d+)', str(raw))
    if m:
        return float(m.group(1))
    try:
        return float(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------
def classify_finding(test_name: str, value: float, unit: str = "", gender: str = "unknown") -> dict:
    """
    Returns:
        {
          "test": canonical test name,
          "value": float,
          "unit": str,
          "status": "NORMAL" | "LOW" | "HIGH" | "CRITICAL" | "PREDIABETES" | "BORDERLINE" | "DEFICIENT" | "INSUFFICIENT" | "UNKNOWN",
          "reference": str (human-readable range),
          "flag": str (emoji flag),
          "note": str (optional clinical note)
        }
    """
    canon = _resolve_key(test_name)
    if not canon:
        return {
            "test": test_name, "value": value, "unit": unit,
            "status": "UNKNOWN", "reference": "No reference available",
            "flag": "❓", "note": ""
        }

    rr = REFERENCE_RANGES[canon]
    gender_key = gender.lower() if gender.lower() in ("male", "female") else None

    # ── Special: HbA1c (tiered) ──────────────────────────────────────────
    if canon == "hba1c":
        u = rr.get("unit", "%")
        if value <= 5.6:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Normal <5.7%", "flag": "✅", "note": ""}
        elif value <= 6.4:
            return {"test": canon, "value": value, "unit": u, "status": "PREDIABETES",
                    "reference": "Prediabetes 5.7–6.4%", "flag": "⚠️",
                    "note": "Borderline elevated — lifestyle changes recommended"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "Diabetes ≥6.5%", "flag": "🔴",
                    "note": "Diabetes range — consult physician"}

    # ── Special: Fasting Glucose (tiered) ────────────────────────────────
    if canon == "fasting_glucose":
        u = rr.get("unit", "mg/dL")
        if value < 70:
            return {"test": canon, "value": value, "unit": u, "status": "LOW",
                    "reference": "Hypoglycemia <70 mg/dL", "flag": "🔴",
                    "note": "Hypoglycemia — immediate attention may be needed"}
        elif value <= 99:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Normal 70–99 mg/dL", "flag": "✅", "note": ""}
        elif value <= 125:
            return {"test": canon, "value": value, "unit": u, "status": "PREDIABETES",
                    "reference": "Prediabetes 100–125 mg/dL", "flag": "⚠️",
                    "note": "Impaired fasting glucose — lifestyle intervention recommended"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "Diabetes ≥126 mg/dL", "flag": "🔴",
                    "note": "Diabetes range — consult physician"}

    # ── Special: Widal titer ─────────────────────────────────────────────
    if canon in ("widal_o", "widal_h"):
        threshold = rr.get("significant", 160)
        u = rr.get("unit", "titer")
        titer_val = _parse_titer(str(value))
        if titer_val is None:
            return {"test": canon, "value": value, "unit": u, "status": "UNKNOWN",
                    "reference": f"Significant ≥1:{threshold}", "flag": "❓", "note": "Cannot parse titer"}
        if titer_val >= threshold:
            return {"test": canon, "value": f"1:{int(titer_val)}", "unit": u, "status": "HIGH",
                    "reference": f"Significant ≥1:{threshold}", "flag": "🔴",
                    "note": "Clinically significant titer — may indicate typhoid"}
        else:
            return {"test": canon, "value": f"1:{int(titer_val)}", "unit": u, "status": "NORMAL",
                    "reference": f"Normal <1:{threshold}", "flag": "✅", "note": ""}

    # ── Special: Vitamin D (tiered) ───────────────────────────────────────
    if canon == "vitamin_d":
        u = rr.get("unit", "ng/mL")
        if value < 20:
            return {"test": canon, "value": value, "unit": u, "status": "DEFICIENT",
                    "reference": "Deficient <20 ng/mL", "flag": "🔴",
                    "note": "Vitamin D deficiency — supplementation likely needed"}
        elif value < 30:
            return {"test": canon, "value": value, "unit": u, "status": "INSUFFICIENT",
                    "reference": "Insufficient 20–29 ng/mL", "flag": "⚠️",
                    "note": "Sub-optimal — supplementation recommended"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Sufficient 30–100 ng/mL", "flag": "✅", "note": ""}

    # ── Special: Vitamin B12 (tiered) ─────────────────────────────────────
    if canon == "vitamin_b12":
        u = rr.get("unit", "pg/mL")
        if value < 200:
            return {"test": canon, "value": value, "unit": u, "status": "LOW",
                    "reference": "Normal 200–900 pg/mL", "flag": "🔴",
                    "note": "B12 deficiency — supplementation needed"}
        elif value <= 900:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Normal 200–900 pg/mL", "flag": "✅", "note": ""}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "Normal 200–900 pg/mL", "flag": "⚠️",
                    "note": "Elevated — may need investigation"}

    # ── Special: Triglycerides (tiered) ──────────────────────────────────
    if canon == "triglycerides":
        u = rr.get("unit", "mg/dL")
        if value < 150:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Normal <150 mg/dL", "flag": "✅", "note": ""}
        elif value < 200:
            return {"test": canon, "value": value, "unit": u, "status": "BORDERLINE",
                    "reference": "Borderline 150–199 mg/dL", "flag": "⚠️",
                    "note": "Borderline high triglycerides"}
        elif value < 500:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "High 200–499 mg/dL", "flag": "🔴",
                    "note": "Elevated triglycerides — cardiovascular risk"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "Very High ≥500 mg/dL", "flag": "🔴",
                    "note": "Very high triglycerides — risk of pancreatitis"}

    # ── Special: HDL (tiered) ─────────────────────────────────────────────
    if canon == "hdl":
        u = rr.get("unit", "mg/dL")
        if value < 40:
            return {"test": canon, "value": value, "unit": u, "status": "LOW",
                    "reference": "Desirable ≥60 mg/dL (Low <40)", "flag": "🔴",
                    "note": "Low HDL — cardiovascular risk factor"}
        elif value < 60:
            return {"test": canon, "value": value, "unit": u, "status": "BORDERLINE",
                    "reference": "Acceptable 40–59 mg/dL", "flag": "⚠️",
                    "note": "Borderline HDL"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Optimal ≥60 mg/dL", "flag": "✅", "note": "Protective level"}

    # ── Special: Total Cholesterol (tiered) ──────────────────────────────
    if canon == "total_cholesterol":
        u = rr.get("unit", "mg/dL")
        if value < 200:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Desirable <200 mg/dL", "flag": "✅", "note": ""}
        elif value < 240:
            return {"test": canon, "value": value, "unit": u, "status": "BORDERLINE",
                    "reference": "Borderline 200–239 mg/dL", "flag": "⚠️",
                    "note": "Borderline high — dietary modifications recommended"}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "High ≥240 mg/dL", "flag": "🔴",
                    "note": "High cholesterol — medical review recommended"}

    # ── Special: LDL (tiered) ─────────────────────────────────────────────
    if canon == "ldl":
        u = rr.get("unit", "mg/dL")
        if value < 100:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Optimal <100 mg/dL", "flag": "✅", "note": ""}
        elif value < 130:
            return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                    "reference": "Near-optimal 100–129 mg/dL", "flag": "✅", "note": ""}
        elif value < 160:
            return {"test": canon, "value": value, "unit": u, "status": "BORDERLINE",
                    "reference": "Borderline 130–159 mg/dL", "flag": "⚠️", "note": ""}
        elif value < 190:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "High 160–189 mg/dL", "flag": "🔴", "note": ""}
        else:
            return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                    "reference": "Very High ≥190 mg/dL", "flag": "🔴",
                    "note": "Very high — immediate medical attention"}

    # ── Generic: gender-specific ranges ──────────────────────────────────
    if gender_key and gender_key in rr:
        sub = rr[gender_key]
        low = sub.get("low", 0)
        high = sub.get("high", 9999)
        u = sub.get("unit", rr.get("unit", unit))
    elif "low" in rr and "high" in rr:
        low = rr["low"]
        high = rr["high"]
        u = rr.get("unit", unit)
    elif "male" in rr:
        # Default to male ranges when gender unknown (conservative approach)
        sub = rr["male"]
        low = sub.get("low", 0)
        high = sub.get("high", 9999)
        u = sub.get("unit", rr.get("unit", unit))
    elif "female" in rr:
        sub = rr["female"]
        low = sub.get("low", 0)
        high = sub.get("high", 9999)
        u = sub.get("unit", rr.get("unit", unit))
    else:
        return {"test": canon, "value": value, "unit": unit,
                "status": "UNKNOWN", "reference": "Reference not configured",
                "flag": "❓", "note": ""}

    ref_str = f"{low}–{high} {u}"
    if value < low:
        return {"test": canon, "value": value, "unit": u, "status": "LOW",
                "reference": ref_str, "flag": "🔽", "note": "Below normal range"}
    elif value > high:
        return {"test": canon, "value": value, "unit": u, "status": "HIGH",
                "reference": ref_str, "flag": "🔺", "note": "Above normal range"}
    else:
        return {"test": canon, "value": value, "unit": u, "status": "NORMAL",
                "reference": ref_str, "flag": "✅", "note": ""}


# ---------------------------------------------------------------------------
# Biomarker Extractor — parses raw OCR text into structured findings
# ---------------------------------------------------------------------------
_NUMBER_PATTERN = re.compile(
    r'([\w\s\(\)/\-]+?)\s*[:\-=]\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z/%μ\.^³³]+)?',
    re.IGNORECASE
)

_TITER_PATTERN = re.compile(
    r'((?:widal|s\.?\s*typhi|typhoid)[\w\s]*?[oh](?:\s+antigen)?)\s*[:\-=]?\s*(1\s*[:/]\s*\d+)',
    re.IGNORECASE
)


def extract_biomarkers_from_text(text: str, gender: str = "unknown") -> list[dict]:
    """
    Parse OCR/extracted text and return a list of classified biomarker findings.
    Each item: {test, value, unit, status, reference, flag, note, raw_line}
    """
    findings = []
    seen_tests = set()

    lines = text.split("\n")
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Try titer patterns first (Widal)
        for m in _TITER_PATTERN.finditer(line_stripped):
            test_raw = m.group(1).strip()
            titer_raw = m.group(2).strip().replace(" ", "")
            canon = _resolve_key(test_raw)
            if canon and canon not in seen_tests:
                seen_tests.add(canon)
                titer_num = _parse_titer(titer_raw)
                if titer_num is not None:
                    result = classify_finding(test_raw, titer_num, "titer", gender)
                    result["raw_line"] = line_stripped
                    result["value"] = titer_raw  # keep original titer string
                    findings.append(result)

        # Numeric patterns
        for m in _NUMBER_PATTERN.finditer(line_stripped):
            test_raw = m.group(1).strip()
            value_str = m.group(2).strip()
            unit_str = (m.group(3) or "").strip()

            # Skip very short or numeric-only test names
            if len(test_raw) < 2 or test_raw.replace(" ", "").isdigit():
                continue

            canon = _resolve_key(test_raw)
            if not canon:
                continue
            if canon in seen_tests:
                continue

            try:
                value_float = float(value_str)
            except ValueError:
                continue

            seen_tests.add(canon)
            result = classify_finding(test_raw, value_float, unit_str, gender)
            result = validate_finding_7_layers(result, gender)
            result["raw_line"] = line_stripped
            findings.append(result)

    return findings


# ---------------------------------------------------------------------------
# STAGE 3: 7-Layer FindingValidator & Deterministic Safety Classifier
# ---------------------------------------------------------------------------
BIOLOGICAL_BOUNDS = {
    "hemoglobin": (1.0, 26.0),
    "fasting_glucose": (10.0, 1500.0),
    "random_glucose": (10.0, 1500.0),
    "hba1c": (3.0, 20.0),
    "wbc": (0.1, 200.0),
    "rbc": (0.5, 10.0),
    "platelets": (2.0, 2000.0),
    "creatinine": (0.1, 25.0),
    "urea": (2.0, 300.0),
    "total_cholesterol": (40.0, 800.0),
    "triglycerides": (20.0, 3000.0),
    "alt": (1.0, 2000.0),
    "ast": (1.0, 2000.0),
    "potassium": (1.5, 9.5),
    "sodium": (90.0, 185.0),
    "tsh": (0.01, 150.0),
    "vitamin_d": (2.0, 250.0),
    "crp": (0.0, 500.0)
}

CRITICAL_THRESHOLDS = {
    "potassium": {"low": 2.8, "high": 6.2, "unit": "mEq/L", "reason": "Fatal cardiac arrhythmia risk"},
    "sodium": {"low": 120.0, "high": 160.0, "unit": "mEq/L", "reason": "Severe neurological impairment / seizure risk"},
    "fasting_glucose": {"low": 50.0, "high": 400.0, "unit": "mg/dL", "reason": "Severe hypoglycemia or DKA / HHS risk"},
    "hemoglobin": {"low": 6.5, "high": 21.0, "unit": "g/dL", "reason": "Severe tissue hypoxia / polycythemia risk"},
    "platelets": {"low": 20.0, "high": 1000.0, "unit": "10^3/μL", "reason": "Spontaneous bleeding risk"},
    "creatinine": {"high": 5.0, "unit": "mg/dL", "reason": "Critical acute kidney failure"},
    "wbc": {"low": 1.5, "high": 35.0, "unit": "10^3/μL", "reason": "Agranulocytosis or severe leukemoid reaction"}
}

def validate_finding_7_layers(finding: dict, gender: str = "unknown") -> dict:
    """
    Executes the 7-Layer FindingValidator:
      Layer 1: Syntax & Value Type Validation
      Layer 2: Biological Plausibility Boundary Check
      Layer 3: Unit Compatibility Validation
      Layer 4: Reference Range Classification
      Layer 5: Critical Threshold Detection (Panic Values)
      Layer 6: Demographic / Gender Specificity
      Layer 7: ML Safety Classifier Verdict
    Outputs:
      validation_verdict: 'VERIFIED' | 'MANUAL REVIEW' | 'UNKNOWN' | 'REJECTED'
      safety_flag: 'safe_to_display' | 'needs_manual_review' | 'hard_stop'
    """
    test_key = finding.get("test", "")
    raw_val = finding.get("value")

    if raw_val is None or raw_val == "":
        return {**finding, "validation_verdict": "REJECTED", "safety_flag": "hard_stop", "safety_reason": "Missing value"}

    if str(raw_val).startswith("1:"):
        return {**finding, "validation_verdict": "VERIFIED", "safety_flag": "safe_to_display"}

    try:
        val = float(raw_val)
    except (ValueError, TypeError):
        return {**finding, "validation_verdict": "REJECTED", "safety_flag": "hard_stop", "safety_reason": "Non-numeric value"}

    if test_key in BIOLOGICAL_BOUNDS:
        b_min, b_max = BIOLOGICAL_BOUNDS[test_key]
        if val < b_min or val > b_max:
            return {
                **finding,
                "validation_verdict": "MANUAL REVIEW",
                "safety_flag": "needs_manual_review",
                "safety_reason": f"Value {val} falls outside physiological limits ({b_min}–{b_max})"
            }

    status = finding.get("status", "UNKNOWN")
    is_critical = False
    critical_reason = ""
    if test_key in CRITICAL_THRESHOLDS:
        crit = CRITICAL_THRESHOLDS[test_key]
        if "low" in crit and val <= crit["low"]:
            is_critical = True
            critical_reason = f"CRITICAL LOW: {crit['reason']}"
        elif "high" in crit and val >= crit["high"]:
            is_critical = True
            critical_reason = f"CRITICAL HIGH: {crit['reason']}"

    if is_critical:
        finding["status"] = "CRITICAL"
        finding["flag"] = "🚨"
        finding["note"] = critical_reason
        return {
            **finding,
            "validation_verdict": "MANUAL REVIEW",
            "safety_flag": "hard_stop",
            "safety_reason": critical_reason
        }

    if status == "UNKNOWN":
        verdict = "UNKNOWN"
        safety_flag = "needs_manual_review"
    else:
        verdict = "VERIFIED"
        safety_flag = "safe_to_display"

    return {
        **finding,
        "validation_verdict": verdict,
        "safety_flag": safety_flag
    }


# ---------------------------------------------------------------------------
# Format findings for display
# ---------------------------------------------------------------------------
def format_findings_for_display(findings: list[dict]) -> str:
    """Format extracted findings as a readable markdown table."""
    if not findings:
        return ""

    lines = ["| Test | Value | Unit | Status | Reference |",
             "|------|-------|------|--------|-----------|"]
    for f in findings:
        test = f.get("test", "").replace("_", " ").title()
        value = f.get("value", "")
        unit = f.get("unit", "")
        status = f.get("status", "")
        flag = f.get("flag", "")
        ref = f.get("reference", "")
        lines.append(f"| {test} | **{value} {unit}** | {unit} | {flag} {status} | {ref} |")

    return "\n".join(lines)
