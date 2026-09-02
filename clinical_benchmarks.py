import re
import logging

logger = logging.getLogger(__name__)

# Configurable Clinical Benchmarks & Condition Rules
CLINICAL_CONDITION_RULES = [
    {
        "condition_id": "COND_DIABETES_GLUCOSE_001",
        "condition_title": "Glucose-related Abnormality Pattern",
        "primary_analytes": ["hba1c", "fasting_glucose", "random_glucose", "ogtt_2_hour"],
        "benchmark_source": "CONFIGURED_CLINICAL_BENCHMARK",
        "source_citation": "ADA 2024 Standards of Care Glycemic Benchmarks",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["hba1c", "fasting_glucose", "random_glucose", "ogtt_2_hour"]
            and f.get("status") in ["HIGH", "VERY_HIGH", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE"]
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            and f.get("measurement_type") != "DERIVED"
            for f in findings
        ),
        "explanation": "One or more glucose parameters (HbA1c or Blood Glucose) exceed the standard laboratory reference benchmark.",
        "recommended_specialist": "Diabetologist or Endocrinologist"
    },
    {
        "condition_id": "COND_ANEMIA_001",
        "condition_title": "Possible Anemia-related Pattern",
        "primary_analytes": ["hemoglobin", "hematocrit", "mcv"],
        "benchmark_source": "CONFIGURED_CLINICAL_BENCHMARK",
        "source_citation": "WHO Anemia Diagnostic Reference Guidelines",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["hemoglobin", "hematocrit"]
            and f.get("status") == "LOW"
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            for f in findings
        ),
        "explanation": "Hemoglobin or Hematocrit is below the expected reference benchmark, which can be associated with anemia or reduced red cell capacity.",
        "recommended_specialist": "General Physician initially, Hematologist if persistent"
    },
    {
        "condition_id": "COND_KIDNEY_CLEARANCE_001",
        "condition_title": "Possible Kidney-Function / Renal Clearance Pattern",
        "primary_analytes": ["creatinine", "urea", "bun", "egfr"],
        "benchmark_source": "CONFIGURED_CLINICAL_BENCHMARK",
        "source_citation": "KDIGO 2023 Clinical Practice Guideline",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["creatinine", "urea", "bun"]
            and f.get("status") in ["HIGH", "VERY_HIGH", "KIDNEY_FAILURE_RANGE"]
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            for f in findings
        ),
        "explanation": "Serum Creatinine or Urea is above the laboratory benchmark. This result alone does not establish reduced kidney function; clinical correlation with eGFR, hydration, and medical history is required.",
        "recommended_specialist": "Nephrologist"
    },
    {
        "condition_id": "COND_THYROID_AXIS_001",
        "condition_title": "Possible Thyroid-Axis Pattern",
        "primary_analytes": ["tsh", "free_t4"],
        "benchmark_source": "CONFIGURED_CLINICAL_BENCHMARK",
        "source_citation": "ATA Thyroid Function Testing Guidelines",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["tsh", "free_t4"]
            and f.get("status") in ["HIGH", "LOW"]
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            for f in findings
        ),
        "explanation": "TSH or Thyroid hormone level is outside the standard reference benchmark, indicating a potential thyroid regulatory variation.",
        "recommended_specialist": "Endocrinologist"
    },
    {
        "condition_id": "COND_LIVER_TRANSAMINASE_001",
        "condition_title": "Possible Hepatic Transaminase Pattern",
        "primary_analytes": ["alt", "ast", "bilirubin_total"],
        "benchmark_source": "CONFIGURED_CLINICAL_BENCHMARK",
        "source_citation": "ACG Clinical Guideline for Abnormal Liver Chemistry",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["alt", "ast", "bilirubin_total"]
            and f.get("status") in ["HIGH", "VERY_HIGH"]
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            for f in findings
        ),
        "explanation": "Liver enzymes (ALT/AST) or Bilirubin exceed the laboratory reference benchmark, warranting clinical correlation.",
        "recommended_specialist": "Gastroenterologist or Hepatologist"
    },
    {
        "condition_id": "COND_SEROLOGY_WIDAL_001",
        "condition_title": "Serological Reactivity Pattern (Widal)",
        "primary_analytes": ["typhi_o", "typhi_h", "paratyphi_ah", "paratyphi_bh"],
        "benchmark_source": "REPORT_REFERENCE",
        "source_citation": "Laboratory Printed Widal Serology Thresholds",
        "rule_logic": lambda findings: any(
            f.get("normalized_test_name") in ["typhi_o", "typhi_h", "paratyphi_ah", "paratyphi_bh"]
            and f.get("status") == "POSITIVE"
            and f.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
            for f in findings
        ),
        "explanation": "One or more antibody titres are above the laboratory's reported threshold. A Widal serology result alone does not confirm an active infection.",
        "recommended_specialist": "General Physician / Internal Medicine"
    }
]


class ClinicalBenchmarkEngine:
    """
    Evaluates validated findings against clinical benchmarks and multi-analyte condition patterns.
    Determines Disease Interpretation Levels (Level 1, Level 2, Level 3).
    """

    @staticmethod
    def evaluate_conditions(findings, raw_report_text=""):
        """
        Evaluates condition-level patterns across all validated findings.
        Returns a list of condition evaluation objects.
        """
        detected_conditions = []
        if not findings:
            return detected_conditions

        # Check for Level 3: Explicit Diagnosis Written in Source Report Text
        explicit_diagnoses = ClinicalBenchmarkEngine._detect_explicit_report_diagnoses(raw_report_text)

        for rule in CLINICAL_CONDITION_RULES:
            try:
                if rule["rule_logic"](findings):
                    # Match primary findings involved
                    matching_findings = [
                        f for f in findings 
                        if f.get("normalized_test_name") in rule["primary_analytes"]
                        and f.get("status") not in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL"]
                    ]
                    
                    interpretation_level = "Level 2: Possible / Suggestive Finding"
                    level_explanation = "The available laboratory evidence matches a configured health-condition pattern but does NOT confirm a diagnosis."
                    
                    if explicit_diagnoses:
                        interpretation_level = "Level 3: Diagnosis Explicitly Reported in Source Document"
                        level_explanation = f"The source medical report explicitly states a clinical diagnosis: '{', '.join(explicit_diagnoses)}'."

                    detected_conditions.append({
                        "condition_id": rule["condition_id"],
                        "condition_title": rule["condition_title"],
                        "interpretation_level": interpretation_level,
                        "level_explanation": level_explanation,
                        "benchmark_source": rule["benchmark_source"],
                        "source_citation": rule["source_citation"],
                        "matching_findings": [f.get("test_name", f.get("parameter")) for f in matching_findings],
                        "explanation": rule["explanation"],
                        "recommended_specialist": rule["recommended_specialist"]
                    })
            except Exception as e:
                logger.warning(f"Error evaluating condition rule {rule['condition_id']}: {e}")

        return detected_conditions

    @staticmethod
    def _detect_explicit_report_diagnoses(raw_report_text):
        """Detects if the source report explicitly writes a formal diagnosis block."""
        if not raw_report_text:
            return []
        
        diagnoses = []
        diag_patterns = [
            r'diagnosis\s*:\s*([^\n\.]+)',
            r'impression\s*:\s*([^\n\.]+)',
            r'clinical diagnosis\s*:\s*([^\n\.]+)'
        ]
        for pat in diag_patterns:
            matches = re.findall(pat, raw_report_text, re.IGNORECASE)
            for m in matches:
                m_clean = m.strip()
                if m_clean and len(m_clean) > 3 and not m_clean.lower().startswith("none"):
                    diagnoses.append(m_clean)
        return diagnoses

    @staticmethod
    def evaluate_widal_combined(findings):
        """
        Combines Widal antigens (O, H, AH, BH) according to clinical benchmark rules.
        Returns a single combined interpretation block.
        """
        widal_findings = [
            f for f in findings 
            if f.get("normalized_test_name") in ["typhi_o", "typhi_h", "paratyphi_ah", "paratyphi_bh"]
        ]
        if not widal_findings:
            return None

        positive_antigens = [
            f.get("test_name", f.get("parameter")) 
            for f in widal_findings 
            if f.get("status") in ["POSITIVE", "HIGH", "VERY_HIGH"]
        ]

        if not positive_antigens:
            return {
                "widal_status": "NON_REACTIVE",
                "summary": "All tested Widal antibody titres (S. Typhi O/H, S. Paratyphi AH/BH) are below the laboratory's reported threshold.",
                "interpretation": "No significant serological antibody elevation detected on this panel.",
                "recommended_doctor": "General Physician / Internal Medicine"
            }
        
        return {
            "widal_status": "REACTIVE_TITRE",
            "summary": f"{len(positive_antigens)} antibody titre(s) ({', '.join(positive_antigens)}) exceeded the laboratory's reported threshold.",
            "interpretation": "An elevated antibody titre indicates serological reactivity, which can be associated with past exposure, vaccination, or infection. A Widal test result alone does NOT confirm an active typhoid infection. A doctor must interpret this result together with fever duration, clinical symptoms, and confirmatory blood cultures.",
            "recommended_doctor": "General Physician / Internal Medicine"
        }
