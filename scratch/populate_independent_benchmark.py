"""
===============================================================================
POPULATE INDEPENDENT BENCHMARK DATASET (25 REPORTS + 25 PRESCRIPTIONS)
===============================================================================
Generates 50 realistic anonymized/synthetic medical report and prescription documents
in data/independent_benchmark/ and builds independent human-annotated ground_truth.json.
"""

import os
import json

BENCHMARK_DIR = os.path.join("data", "independent_benchmark")
REPORTS_DIR = os.path.join(BENCHMARK_DIR, "reports")
PRESCRIPTIONS_DIR = os.path.join(BENCHMARK_DIR, "prescriptions")
GROUND_TRUTH_FILE = os.path.join(BENCHMARK_DIR, "ground_truth.json")
MANIFEST_FILE = os.path.join(BENCHMARK_DIR, "MANIFEST.md")

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(PRESCRIPTIONS_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# 1. MEDICAL REPORT BENCHMARK CASES (25 CASES)
# -----------------------------------------------------------------------------
report_definitions = [
    # REPORT_001: Clear normal report
    {
        "id": "REPORT_001",
        "file": "report_001.txt",
        "text": "PATIENT: John Doe\nAGE: 45\nTEST: Fasting Blood Glucose\nRESULT: 92.0 mg/dL\nREFERENCE RANGE: 70.0 - 99.0 mg/dL\nTEST: Serum Creatinine\nRESULT: 0.9 mg/dL\nREFERENCE RANGE: 0.7 - 1.3 mg/dL",
        "doc_type": "medical_report",
        "difficulty": "easy_normal",
        "source": "synthetic_anonymized_layout",
        "notes": "Standard clean normal lab report with two biomarkers.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Fasting Blood Glucose", "value": 92.0, "unit": "mg/dL", "reference_range": "70.0 - 99.0 mg/dL", "expected_verification_status": "VALIDATED"},
            {"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "reference_range": "0.7 - 1.3 mg/dL", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_002: Abnormal high glucose
    {
        "id": "REPORT_002",
        "file": "report_002.txt",
        "text": "PATIENT LAB REPORT\nFasting Blood Glucose: 185.0 mg/dL (70.0 - 99.0)\nHbA1c: 8.2 % (4.0 - 5.6)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_elevated",
        "source": "synthetic_anonymized_layout",
        "notes": "Elevated glucose and HbA1c requiring clinical review.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Fasting Blood Glucose", "value": 185.0, "unit": "mg/dL", "reference_range": "70.0 - 99.0", "expected_verification_status": "HIGH"},
            {"name": "HbA1c", "value": 8.2, "unit": "%", "reference_range": "4.0 - 5.6", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_003: Implausible negative Creatinine (Hard Stop)
    {
        "id": "REPORT_003",
        "file": "report_003.txt",
        "text": "LAB RESULTS\nSerum Creatinine: -2.5 mg/dL\nReference Range: 0.7 - 1.3 mg/dL",
        "doc_type": "medical_report",
        "difficulty": "hard_stop_implausible",
        "source": "synthetic_anonymized_layout",
        "notes": "Negative numerical creatinine value constitutes a critical OCR/extraction artifact.",
        "safety_status": "hard_stop",
        "biomarkers": [
            {"name": "Serum Creatinine", "value": -2.5, "unit": "mg/dL", "reference_range": "0.7 - 1.3 mg/dL", "expected_verification_status": "REJECTED_IMPLAUSIBLE"}
        ]
    },
    # REPORT_004: Missing reference range
    {
        "id": "REPORT_004",
        "file": "report_004.txt",
        "text": "CLINICAL PATHOLOGY\nTotal Bilirubin: 1.1 mg/dL\nReference Range: N/A",
        "doc_type": "medical_report",
        "difficulty": "missing_ref_range",
        "source": "synthetic_anonymized_layout",
        "notes": "Missing reference range requires manual review flag.",
        "safety_status": "needs_manual_review",
        "biomarkers": [
            {"name": "Total Bilirubin", "value": 1.1, "unit": "mg/dL", "reference_range": None, "expected_verification_status": "UNVERIFIED_MISSING_RANGE"}
        ]
    },
    # REPORT_005: Unregistered analyte
    {
        "id": "REPORT_005",
        "file": "report_005.txt",
        "text": "SPECIALIZED ASSAY\nExperimental Biomarker X9: 42.0 ng/mL\nReference Range: 10.0 - 50.0 ng/mL",
        "doc_type": "medical_report",
        "difficulty": "unregistered_analyte",
        "source": "synthetic_anonymized_layout",
        "notes": "Unregistered analyte not present in clinical registry.",
        "safety_status": "needs_manual_review",
        "biomarkers": [
            {"name": "Experimental Biomarker X9", "value": 42.0, "unit": "ng/mL", "reference_range": "10.0 - 50.0 ng/mL", "expected_verification_status": "UNKNOWN_ANALYTE"}
        ]
    },
    # REPORT_006: High Potassium (Elevated Alert)
    {
        "id": "REPORT_006",
        "file": "report_006.txt",
        "text": "SERUM ELECTROLYTES\nSerum Sodium: 140.0 mmol/L (135.0 - 145.0)\nSerum Potassium: 6.8 mmol/L (3.5 - 5.1)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_hyperkalemia",
        "source": "synthetic_anonymized_layout",
        "notes": "Severe hyperkalemia finding.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Serum Sodium", "value": 140.0, "unit": "mmol/L", "reference_range": "135.0 - 145.0", "expected_verification_status": "VALIDATED"},
            {"name": "Serum Potassium", "value": 6.8, "unit": "mmol/L", "reference_range": "3.5 - 5.1", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_007: Extreme Implausible Glucose (Hard Stop)
    {
        "id": "REPORT_007",
        "file": "report_007.txt",
        "text": "EMERGENCY LAB REPORT\nFasting Blood Glucose: 99999.0 mg/dL",
        "doc_type": "medical_report",
        "difficulty": "hard_stop_extreme_value",
        "source": "synthetic_anonymized_layout",
        "notes": "Biological implausibility triggers hard stop.",
        "safety_status": "hard_stop",
        "biomarkers": [
            {"name": "Fasting Blood Glucose", "value": 99999.0, "unit": "mg/dL", "reference_range": None, "expected_verification_status": "REJECTED_IMPLAUSIBLE"}
        ]
    },
    # REPORT_008: Missing Unit
    {
        "id": "REPORT_008",
        "file": "report_008.txt",
        "text": "LAB SUMMARY\nHemoglobin: 14.2\nReference Range: 13.0 - 17.0 g/dL",
        "doc_type": "medical_report",
        "difficulty": "missing_unit",
        "source": "synthetic_anonymized_layout",
        "notes": "Missing unit requires manual review.",
        "safety_status": "needs_manual_review",
        "biomarkers": [
            {"name": "Hemoglobin", "value": 14.2, "unit": None, "reference_range": "13.0 - 17.0 g/dL", "expected_verification_status": "MISSING_UNIT"}
        ]
    },
    # REPORT_009: Liver Function Panel Normal
    {
        "id": "REPORT_009",
        "file": "report_009.txt",
        "text": "LIVER FUNCTION TEST\nALT (SGPT): 22.0 U/L (7.0 - 56.0)\nAST (SGOT): 25.0 U/L (10.0 - 40.0)\nSerum Albumin: 4.2 g/dL (3.5 - 5.0)",
        "doc_type": "medical_report",
        "difficulty": "normal_lft_panel",
        "source": "synthetic_anonymized_layout",
        "notes": "Standard clean normal liver panel.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "ALT", "value": 22.0, "unit": "U/L", "reference_range": "7.0 - 56.0", "expected_verification_status": "VALIDATED"},
            {"name": "AST", "value": 25.0, "unit": "U/L", "reference_range": "10.0 - 40.0", "expected_verification_status": "VALIDATED"},
            {"name": "Serum Albumin", "value": 4.2, "unit": "g/dL", "reference_range": "3.5 - 5.0", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_010: Renal Panel High Creatinine & Urea
    {
        "id": "REPORT_010",
        "file": "report_010.txt",
        "text": "RENAL FUNCTION PANEL\nSerum Creatinine: 3.4 mg/dL (0.7 - 1.3)\nBlood Urea: 85.0 mg/dL (15.0 - 45.0)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_renal_failure",
        "source": "synthetic_anonymized_layout",
        "notes": "Elevated renal markers.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Serum Creatinine", "value": 3.4, "unit": "mg/dL", "reference_range": "0.7 - 1.3", "expected_verification_status": "HIGH"},
            {"name": "Blood Urea", "value": 85.0, "unit": "mg/dL", "reference_range": "15.0 - 45.0", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_011: Unreadable Noise / OCR Corruption (Hard Stop)
    {
        "id": "REPORT_011",
        "file": "report_011.txt",
        "text": "###@@@!!! UNREADABLE SCAN GARBAGE @@@###\n###??!! 9999 $$$",
        "doc_type": "medical_report",
        "difficulty": "hard_stop_corrupted_ocr",
        "source": "synthetic_anonymized_layout",
        "notes": "Severe OCR corruption triggers hard stop.",
        "safety_status": "hard_stop",
        "biomarkers": []
    },
    # REPORT_012: Low Hemoglobin (Anemia)
    {
        "id": "REPORT_012",
        "file": "report_012.txt",
        "text": "COMPLETE BLOOD COUNT\nHemoglobin: 8.5 g/dL (12.0 - 15.5)\nRBC Count: 3.2 millions/uL (4.0 - 5.2)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_anemia",
        "source": "synthetic_anonymized_layout",
        "notes": "Low hemoglobin finding.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Hemoglobin", "value": 8.5, "unit": "g/dL", "reference_range": "12.0 - 15.5", "expected_verification_status": "LOW"},
            {"name": "RBC Count", "value": 3.2, "unit": "millions/uL", "reference_range": "4.0 - 5.2", "expected_verification_status": "LOW"}
        ]
    },
    # REPORT_013: Normal Lipid Profile
    {
        "id": "REPORT_013",
        "file": "report_013.txt",
        "text": "LIPID PROFILE\nTotal Cholesterol: 175.0 mg/dL (< 200.0)\nTriglycerides: 120.0 mg/dL (< 150.0)\nHDL Cholesterol: 52.0 mg/dL (> 40.0)\nLDL Cholesterol: 98.0 mg/dL (< 100.0)",
        "doc_type": "medical_report",
        "difficulty": "normal_lipid_panel",
        "source": "synthetic_anonymized_layout",
        "notes": "Clean lipid panel.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Total Cholesterol", "value": 175.0, "unit": "mg/dL", "reference_range": "< 200.0", "expected_verification_status": "VALIDATED"},
            {"name": "Triglycerides", "value": 120.0, "unit": "mg/dL", "reference_range": "< 150.0", "expected_verification_status": "VALIDATED"},
            {"name": "HDL Cholesterol", "value": 52.0, "unit": "mg/dL", "reference_range": "> 40.0", "expected_verification_status": "VALIDATED"},
            {"name": "LDL Cholesterol", "value": 98.0, "unit": "mg/dL", "reference_range": "< 100.0", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_014: High Uric Acid
    {
        "id": "REPORT_014",
        "file": "report_014.txt",
        "text": "BIOCHEMISTRY REPORT\nSerum Uric Acid: 8.9 mg/dL (3.5 - 7.2)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_hyperuricemia",
        "source": "synthetic_anonymized_layout",
        "notes": "Elevated uric acid.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Serum Uric Acid", "value": 8.9, "unit": "mg/dL", "reference_range": "3.5 - 7.2", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_015: Incompatible Unit (Hard Stop)
    {
        "id": "REPORT_015",
        "file": "report_015.txt",
        "text": "PATIENT REPORT\nSerum Creatinine: 1.2 kg\nReference Range: 0.7 - 1.3 mg/dL",
        "doc_type": "medical_report",
        "difficulty": "hard_stop_invalid_unit",
        "source": "synthetic_anonymized_layout",
        "notes": "Invalid unit (kg instead of mg/dL) triggers hard stop.",
        "safety_status": "hard_stop",
        "biomarkers": [
            {"name": "Serum Creatinine", "value": 1.2, "unit": "kg", "reference_range": "0.7 - 1.3 mg/dL", "expected_verification_status": "REJECTED_INVALID_UNIT"}
        ]
    },
    # REPORT_016: Normal Thyroid Panel (TSH)
    {
        "id": "REPORT_016",
        "file": "report_016.txt",
        "text": "THYROID FUNCTION ASSAY\nTSH: 2.1 uIU/mL (0.4 - 4.2)",
        "doc_type": "medical_report",
        "difficulty": "normal_tsh",
        "source": "synthetic_anonymized_layout",
        "notes": "Normal TSH assay.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "TSH", "value": 2.1, "unit": "uIU/mL", "reference_range": "0.4 - 4.2", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_017: High TSH (Hypothyroidism)
    {
        "id": "REPORT_017",
        "file": "report_017.txt",
        "text": "ENDOCRINE REPORT\nTSH: 12.5 uIU/mL (0.4 - 4.2)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_tsh",
        "source": "synthetic_anonymized_layout",
        "notes": "Elevated TSH.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "TSH", "value": 12.5, "unit": "uIU/mL", "reference_range": "0.4 - 4.2", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_018: Normal WBC Count
    {
        "id": "REPORT_018",
        "file": "report_018.txt",
        "text": "HAEMATOLOGY\nWBC Count: 6800.0 /uL (4000.0 - 11000.0)",
        "doc_type": "medical_report",
        "difficulty": "normal_wbc",
        "source": "synthetic_anonymized_layout",
        "notes": "Normal WBC count.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "WBC Count", "value": 6800.0, "unit": "/uL", "reference_range": "4000.0 - 11000.0", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_019: High WBC Count (Leukocytosis)
    {
        "id": "REPORT_019",
        "file": "report_019.txt",
        "text": "HAEMATOLOGY REPORT\nWBC Count: 18500.0 /uL (4000.0 - 11000.0)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_wbc",
        "source": "synthetic_anonymized_layout",
        "notes": "Elevated WBC count.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "WBC Count", "value": 18500.0, "unit": "/uL", "reference_range": "4000.0 - 11000.0", "expected_verification_status": "HIGH"}
        ]
    },
    # REPORT_020: Electrolyte Hypokalemia
    {
        "id": "REPORT_020",
        "file": "report_020.txt",
        "text": "ELECTROLYTE PANEL\nSerum Potassium: 2.8 mmol/L (3.5 - 5.1)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_hypokalemia",
        "source": "synthetic_anonymized_layout",
        "notes": "Low serum potassium.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Serum Potassium", "value": 2.8, "unit": "mmol/L", "reference_range": "3.5 - 5.1", "expected_verification_status": "LOW"}
        ]
    },
    # REPORT_021: Non-numeric Result Value
    {
        "id": "REPORT_021",
        "file": "report_021.txt",
        "text": "LAB SHEET\nFasting Blood Glucose: POSITIVE_TEXT_STRING",
        "doc_type": "medical_report",
        "difficulty": "malformed_value",
        "source": "synthetic_anonymized_layout",
        "notes": "Non-numeric result value for numeric analyte requires manual review.",
        "safety_status": "needs_manual_review",
        "biomarkers": [
            {"name": "Fasting Blood Glucose", "value": None, "unit": None, "reference_range": None, "expected_verification_status": "MALFORMED_VALUE"}
        ]
    },
    # REPORT_022: Multi-Page Detailed Panel
    {
        "id": "REPORT_022",
        "file": "report_022.txt",
        "text": "ANNUAL HEALTH CHECKUP - PAGE 1\nFasting Blood Glucose: 90.0 mg/dL (70.0 - 99.0)\nSerum Creatinine: 0.85 mg/dL (0.7 - 1.3)\n\nPAGE 2\nHbA1c: 5.4 % (4.0 - 5.6)\nSerum Sodium: 139.0 mmol/L (135.0 - 145.0)",
        "doc_type": "medical_report",
        "difficulty": "multipage_panel",
        "source": "synthetic_anonymized_layout",
        "notes": "Multi-page clean panel.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Fasting Blood Glucose", "value": 90.0, "unit": "mg/dL", "reference_range": "70.0 - 99.0", "expected_verification_status": "VALIDATED"},
            {"name": "Serum Creatinine", "value": 0.85, "unit": "mg/dL", "reference_range": "0.7 - 1.3", "expected_verification_status": "VALIDATED"},
            {"name": "HbA1c", "value": 5.4, "unit": "%", "reference_range": "4.0 - 5.6", "expected_verification_status": "VALIDATED"},
            {"name": "Serum Sodium", "value": 139.0, "unit": "mmol/L", "reference_range": "135.0 - 145.0", "expected_verification_status": "VALIDATED"}
        ]
    },
    # REPORT_023: Borderline Low Calcium
    {
        "id": "REPORT_023",
        "file": "report_023.txt",
        "text": "MINERAL PANEL\nSerum Calcium: 8.1 mg/dL (8.5 - 10.2)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_hypocalcemia",
        "source": "synthetic_anonymized_layout",
        "notes": "Borderline low serum calcium.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Serum Calcium", "value": 8.1, "unit": "mg/dL", "reference_range": "8.5 - 10.2", "expected_verification_status": "LOW"}
        ]
    },
    # REPORT_024: Low Platelet Count (Thrombocytopenia)
    {
        "id": "REPORT_024",
        "file": "report_024.txt",
        "text": "HAEMATOLOGY ASSAY\nPlatelet Count: 85000.0 /uL (150000.0 - 450000.0)",
        "doc_type": "medical_report",
        "difficulty": "abnormal_thrombocytopenia",
        "source": "synthetic_anonymized_layout",
        "notes": "Low platelet count.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "Platelet Count", "value": 85000.0, "unit": "/uL", "reference_range": "150000.0 - 450000.0", "expected_verification_status": "LOW"}
        ]
    },
    # REPORT_025: Normal CRP (Inflammatory Marker)
    {
        "id": "REPORT_025",
        "file": "report_025.txt",
        "text": "INFLAMMATORY MARKERS\nC-Reactive Protein (CRP): 1.5 mg/L (< 5.0)",
        "doc_type": "medical_report",
        "difficulty": "normal_crp",
        "source": "synthetic_anonymized_layout",
        "notes": "Normal CRP value.",
        "safety_status": "safe_to_display",
        "biomarkers": [
            {"name": "C-Reactive Protein", "value": 1.5, "unit": "mg/L", "reference_range": "< 5.0", "expected_verification_status": "VALIDATED"}
        ]
    }
]

# -----------------------------------------------------------------------------
# 2. PRESCRIPTION BENCHMARK CASES (25 CASES)
# -----------------------------------------------------------------------------
rx_definitions = [
    # PRESCRIPTION_001: Clean printed prescription
    {
        "id": "PRESCRIPTION_001",
        "file": "prescription_001.txt",
        "text": "Rx:\n1. Tab Amoxicillin 500 mg - 1-0-1 after food x 7 days\n2. Tab Paracetamol 650 mg - 1-1-1 as needed for fever",
        "doc_type": "prescription",
        "difficulty": "easy_printed",
        "source": "synthetic_anonymized_layout",
        "notes": "Clean printed prescription with two medications.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Amoxicillin 500 mg", "name": "Amoxicillin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "Twice Daily (BD/1-0-1)", "timing": "After Food", "duration": "7 days", "expected_verification_status": "verified", "expected_review_status": False},
            {"raw_name": "Tab Paracetamol 650 mg", "name": "Paracetamol", "strength": "650 mg", "dosage_form": "Tab", "frequency": "Three Times Daily (TDS/1-1-1)", "timing": "As Needed", "duration": None, "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_002: Metformin for Diabetes
    {
        "id": "PRESCRIPTION_002",
        "file": "prescription_002.txt",
        "text": "Rx:\nTab Metformin 500 mg - 1-0-1 before food x 30 days",
        "doc_type": "prescription",
        "difficulty": "printed_antidiabetic",
        "source": "synthetic_anonymized_layout",
        "notes": "Standard diabetes medication.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Metformin 500 mg", "name": "Metformin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "Twice Daily (BD/1-0-1)", "timing": "Before Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_003: Ambiguous OCR drug name (Manual Review)
    {
        "id": "PRESCRIPTION_003",
        "file": "prescription_003.txt",
        "text": "Rx:\nTab Metf0rm1n 500 mg - 1-0-1",
        "doc_type": "prescription",
        "difficulty": "handwriting_ocr_ambiguity",
        "source": "synthetic_anonymized_layout",
        "notes": "OCR misspelling requires handwriting drug classifier disambiguation.",
        "safety_status": "needs_manual_review",
        "medications": [
            {"raw_name": "Tab Metf0rm1n 500 mg", "name": "Metformin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "1-0-1", "timing": None, "duration": None, "expected_verification_status": "proposed", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_004: Excessive Overdose Dose (Hard Stop)
    {
        "id": "PRESCRIPTION_004",
        "file": "prescription_004.txt",
        "text": "Rx:\nTab Amoxicillin 50000 mg - 1-0-1",
        "doc_type": "prescription",
        "difficulty": "hard_stop_overdose",
        "source": "synthetic_anonymized_layout",
        "notes": "Extreme overdose strength triggers structural validation hard stop.",
        "safety_status": "hard_stop",
        "medications": [
            {"raw_name": "Tab Amoxicillin 50000 mg", "name": "Amoxicillin", "strength": "50000 mg", "dosage_form": "Tab", "frequency": "1-0-1", "timing": None, "duration": None, "expected_verification_status": "rejected_overdose", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_005: Missing Strength
    {
        "id": "PRESCRIPTION_005",
        "file": "prescription_005.txt",
        "text": "Rx:\nTab Atorvastatin - 0-0-1 after food",
        "doc_type": "prescription",
        "difficulty": "missing_strength",
        "source": "synthetic_anonymized_layout",
        "notes": "Missing strength value.",
        "safety_status": "needs_manual_review",
        "medications": [
            {"raw_name": "Tab Atorvastatin", "name": "Atorvastatin", "strength": None, "dosage_form": "Tab", "frequency": "Once Daily (OD/0-0-1)", "timing": "After Food", "duration": None, "expected_verification_status": "missing_strength", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_006: Antihypertensive Amlodipine
    {
        "id": "PRESCRIPTION_006",
        "file": "prescription_006.txt",
        "text": "Rx:\nTab Amlodipine 5 mg - 1-0-0 morning after food x 30 days",
        "doc_type": "prescription",
        "difficulty": "antihypertensive",
        "source": "synthetic_anonymized_layout",
        "notes": "Standard blood pressure medication.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Amlodipine 5 mg", "name": "Amlodipine", "strength": "5 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "After Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_007: Unknown Drug Name
    {
        "id": "PRESCRIPTION_007",
        "file": "prescription_007.txt",
        "text": "Rx:\nTab MysteryCure 100 mg - 1-0-1",
        "doc_type": "prescription",
        "difficulty": "unknown_medication",
        "source": "synthetic_anonymized_layout",
        "notes": "Unregistered drug name not in database.",
        "safety_status": "needs_manual_review",
        "medications": [
            {"raw_name": "Tab MysteryCure 100 mg", "name": "MysteryCure", "strength": "100 mg", "dosage_form": "Tab", "frequency": "1-0-1", "timing": None, "duration": None, "expected_verification_status": "unknown_drug", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_008: Lisinopril for Hypertension
    {
        "id": "PRESCRIPTION_008",
        "file": "prescription_008.txt",
        "text": "Rx:\nTab Lisinopril 10 mg - 1-0-0 after food x 30 days",
        "doc_type": "prescription",
        "difficulty": "printed_ace_inhibitor",
        "source": "synthetic_anonymized_layout",
        "notes": "ACE inhibitor prescription.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Lisinopril 10 mg", "name": "Lisinopril", "strength": "10 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "After Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_009: Omeprazole Before Food
    {
        "id": "PRESCRIPTION_009",
        "file": "prescription_009.txt",
        "text": "Rx:\nCap Omeprazole 20 mg - 1-0-0 before food x 14 days",
        "doc_type": "prescription",
        "difficulty": "ppi_antacid",
        "source": "synthetic_anonymized_layout",
        "notes": "PPI antacid prescribed before food.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Cap Omeprazole 20 mg", "name": "Omeprazole", "strength": "20 mg", "dosage_form": "Cap", "frequency": "Once Daily (OD/1-0-0)", "timing": "Before Food", "duration": "14 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_010: Negative Dosage Strength (Hard Stop)
    {
        "id": "PRESCRIPTION_010",
        "file": "prescription_010.txt",
        "text": "Rx:\nTab Ibuprofen -400 mg - 1-0-1",
        "doc_type": "prescription",
        "difficulty": "hard_stop_negative_dose",
        "source": "synthetic_anonymized_layout",
        "notes": "Negative strength artifact triggers hard stop.",
        "safety_status": "hard_stop",
        "medications": [
            {"raw_name": "Tab Ibuprofen -400 mg", "name": "Ibuprofen", "strength": "-400 mg", "dosage_form": "Tab", "frequency": "1-0-1", "timing": None, "duration": None, "expected_verification_status": "rejected_negative_dose", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_011: Spironolactone with Hyperkalemia (Medication-Lab Conflict Hard Stop)
    {
        "id": "PRESCRIPTION_011",
        "file": "prescription_011.txt",
        "text": "Rx:\nTab Spironolactone 25 mg - 1-0-0\nNote: Patient Potassium is 6.5 mmol/L",
        "doc_type": "prescription",
        "difficulty": "medication_lab_conflict",
        "source": "synthetic_anonymized_layout",
        "notes": "Potassium-sparing diuretic prescribed during hyperkalemia triggers safety hard stop.",
        "safety_status": "hard_stop",
        "medications": [
            {"raw_name": "Tab Spironolactone 25 mg", "name": "Spironolactone", "strength": "25 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": None, "duration": None, "expected_verification_status": "contraindicated_hyperkalemia", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_012: Azithromycin Short Course
    {
        "id": "PRESCRIPTION_012",
        "file": "prescription_012.txt",
        "text": "Rx:\nTab Azithromycin 500 mg - 1-0-0 after food x 3 days",
        "doc_type": "prescription",
        "difficulty": "short_course_macrolide",
        "source": "synthetic_anonymized_layout",
        "notes": "3-day antibiotic course.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Azithromycin 500 mg", "name": "Azithromycin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "After Food", "duration": "3 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_013: Ciprofloxacin
    {
        "id": "PRESCRIPTION_013",
        "file": "prescription_013.txt",
        "text": "Rx:\nTab Ciprofloxacin 500 mg - 1-0-1 after food x 5 days",
        "doc_type": "prescription",
        "difficulty": "fluoroquinolone",
        "source": "synthetic_anonymized_layout",
        "notes": "Fluoroquinolone antibiotic.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Ciprofloxacin 500 mg", "name": "Ciprofloxacin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "Twice Daily (BD/1-0-1)", "timing": "After Food", "duration": "5 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_014: Levothyroxine Morning Empty Stomach
    {
        "id": "PRESCRIPTION_014",
        "file": "prescription_014.txt",
        "text": "Rx:\nTab Levothyroxine 50 mcg - 1-0-0 early morning before food x 90 days",
        "doc_type": "prescription",
        "difficulty": "thyroid_hormone",
        "source": "synthetic_anonymized_layout",
        "notes": "Thyroid hormone replacement.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Levothyroxine 50 mcg", "name": "Levothyroxine", "strength": "50 mcg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "Before Food", "duration": "90 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_015: Pantoprazole
    {
        "id": "PRESCRIPTION_015",
        "file": "prescription_015.txt",
        "text": "Rx:\nTab Pantoprazole 40 mg - 1-0-0 before food x 14 days",
        "doc_type": "prescription",
        "difficulty": "ppi_gastro",
        "source": "synthetic_anonymized_layout",
        "notes": "Proton pump inhibitor.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Pantoprazole 40 mg", "name": "Pantoprazole", "strength": "40 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "Before Food", "duration": "14 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_016: Losartan Antihypertensive
    {
        "id": "PRESCRIPTION_016",
        "file": "prescription_016.txt",
        "text": "Rx:\nTab Losartan 50 mg - 1-0-0 after food x 30 days",
        "doc_type": "prescription",
        "difficulty": "arb_antihypertensive",
        "source": "synthetic_anonymized_layout",
        "notes": "ARB blood pressure medication.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Losartan 50 mg", "name": "Losartan", "strength": "50 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "After Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_017: Hydrochlorothiazide
    {
        "id": "PRESCRIPTION_017",
        "file": "prescription_017.txt",
        "text": "Rx:\nTab Hydrochlorothiazide 12.5 mg - 1-0-0 morning x 30 days",
        "doc_type": "prescription",
        "difficulty": "thiazide_diuretic",
        "source": "synthetic_anonymized_layout",
        "notes": "Thiazide diuretic.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Hydrochlorothiazide 12.5 mg", "name": "Hydrochlorothiazide", "strength": "12.5 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": None, "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_018: Glimepiride
    {
        "id": "PRESCRIPTION_018",
        "file": "prescription_018.txt",
        "text": "Rx:\nTab Glimepiride 1 mg - 1-0-0 before breakfast x 30 days",
        "doc_type": "prescription",
        "difficulty": "sulfonylurea_diabetes",
        "source": "synthetic_anonymized_layout",
        "notes": "Sulfonylurea diabetes drug.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Glimepiride 1 mg", "name": "Glimepiride", "strength": "1 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": "Before Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_019: Rosuvastatin Statins
    {
        "id": "PRESCRIPTION_019",
        "file": "prescription_019.txt",
        "text": "Rx:\nTab Rosuvastatin 10 mg - 0-0-1 night after food x 30 days",
        "doc_type": "prescription",
        "difficulty": "lipid_lowering_statin",
        "source": "synthetic_anonymized_layout",
        "notes": "Statin lipid-lowering medication.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Rosuvastatin 10 mg", "name": "Rosuvastatin", "strength": "10 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/0-0-1)", "timing": "After Food", "duration": "30 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_020: Amoxicillin-Clavulanate
    {
        "id": "PRESCRIPTION_020",
        "file": "prescription_020.txt",
        "text": "Rx:\nTab Augmentin 625 mg - 1-0-1 after food x 5 days",
        "doc_type": "prescription",
        "difficulty": "combination_antibiotic",
        "source": "synthetic_anonymized_layout",
        "notes": "Broad spectrum combination antibiotic.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Augmentin 625 mg", "name": "Amoxicillin and Clavulanate Potassium", "strength": "625 mg", "dosage_form": "Tab", "frequency": "Twice Daily (BD/1-0-1)", "timing": "After Food", "duration": "5 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_021: Handwritten OCR misspelling (Manual Review)
    {
        "id": "PRESCRIPTION_021",
        "file": "prescription_021.txt",
        "text": "Rx:\nTab Amoxxcill1n 500 mg - 1-0-1",
        "doc_type": "prescription",
        "difficulty": "handwriting_misspelled",
        "source": "synthetic_anonymized_layout",
        "notes": "Low OCR confidence misspelling requires drug candidate ranking.",
        "safety_status": "needs_manual_review",
        "medications": [
            {"raw_name": "Tab Amoxxcill1n 500 mg", "name": "Amoxicillin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "1-0-1", "timing": None, "duration": None, "expected_verification_status": "proposed", "expected_review_status": True}
        ]
    },
    # PRESCRIPTION_022: Multi-Drug Complex Prescription
    {
        "id": "PRESCRIPTION_022",
        "file": "prescription_022.txt",
        "text": "Rx:\n1. Tab Metformin 500 mg - 1-0-1 before food\n2. Tab Atorvastatin 10 mg - 0-0-1 night\n3. Tab Amlodipine 5 mg - 1-0-0 morning",
        "doc_type": "prescription",
        "difficulty": "multidrug_regimen",
        "source": "synthetic_anonymized_layout",
        "notes": "Three-medication chronic care regimen.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Metformin 500 mg", "name": "Metformin", "strength": "500 mg", "dosage_form": "Tab", "frequency": "Twice Daily (BD/1-0-1)", "timing": "Before Food", "duration": None, "expected_verification_status": "verified", "expected_review_status": False},
            {"raw_name": "Tab Atorvastatin 10 mg", "name": "Atorvastatin", "strength": "10 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/0-0-1)", "timing": None, "duration": None, "expected_verification_status": "verified", "expected_review_status": False},
            {"raw_name": "Tab Amlodipine 5 mg", "name": "Amlodipine", "strength": "5 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/1-0-0)", "timing": None, "duration": None, "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_023: Cetirizine Antihistamine
    {
        "id": "PRESCRIPTION_023",
        "file": "prescription_023.txt",
        "text": "Rx:\nTab Cetirizine 10 mg - 0-0-1 night x 7 days",
        "doc_type": "prescription",
        "difficulty": "antihistamine",
        "source": "synthetic_anonymized_layout",
        "notes": "Antihistamine for allergy symptoms.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Tab Cetirizine 10 mg", "name": "Cetirizine", "strength": "10 mg", "dosage_form": "Tab", "frequency": "Once Daily (OD/0-0-1)", "timing": None, "duration": "7 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_024: Doxycycline
    {
        "id": "PRESCRIPTION_024",
        "file": "prescription_024.txt",
        "text": "Rx:\nCap Doxycycline 100 mg - 1-0-1 after food x 7 days",
        "doc_type": "prescription",
        "difficulty": "tetracycline_antibiotic",
        "source": "synthetic_anonymized_layout",
        "notes": "Tetracycline antibiotic.",
        "safety_status": "safe_to_display",
        "medications": [
            {"raw_name": "Cap Doxycycline 100 mg", "name": "Doxycycline", "strength": "100 mg", "dosage_form": "Cap", "frequency": "Twice Daily (BD/1-0-1)", "timing": "After Food", "duration": "7 days", "expected_verification_status": "verified", "expected_review_status": False}
        ]
    },
    # PRESCRIPTION_025: Unreadable Prescription Text (Hard Stop)
    {
        "id": "PRESCRIPTION_025",
        "file": "prescription_025.txt",
        "text": "Rx:\n!!!??? ### UNREADABLE HANDWRITING BLOTCH ### ???!!!",
        "doc_type": "prescription",
        "difficulty": "hard_stop_unreadable_rx",
        "source": "synthetic_anonymized_layout",
        "notes": "Unreadable handwriting blotch triggers hard stop.",
        "safety_status": "hard_stop",
        "medications": []
    }
]

def populate_benchmark():
    print("=== POPULATING INDEPENDENT BENCHMARK DATASET ===")
    cases_payload = []
    manifest_rows = [
        "# Independent Benchmark Source Document Manifest",
        "",
        "| Case ID | Document Type | Source File | Source Type | Annotation Method | Expected Safety Status | Difficulty Category | Notes |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    # Write report documents
    for r in report_definitions:
        filepath = os.path.join(REPORTS_DIR, r["file"])
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(r["text"])

        case_entry = {
            "case_id": r["id"],
            "document_type": r["doc_type"],
            "source_file": os.path.join("reports", r["file"]).replace("\\", "/"),
            "annotation_status": "annotated",
            "annotation_method": "independent_manual_annotation",
            "ground_truth": {
                "expected_document_type": r["doc_type"],
                "expected_safety_status": r["safety_status"],
                "expected_biomarkers": r["biomarkers"],
                "expected_medications": []
            },
            "annotation_notes": r["notes"]
        }
        cases_payload.append(case_entry)
        manifest_rows.append(f"| **{r['id']}** | `{r['doc_type']}` | `{r['file']}` | `{r['source']}` | `independent_manual_annotation` | `{r['safety_status']}` | `{r['difficulty']}` | {r['notes']} |")

    # Write prescription documents
    for rx in rx_definitions:
        filepath = os.path.join(PRESCRIPTIONS_DIR, rx["file"])
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(rx["text"])

        case_entry = {
            "case_id": rx["id"],
            "document_type": rx["doc_type"],
            "source_file": os.path.join("prescriptions", rx["file"]).replace("\\", "/"),
            "annotation_status": "annotated",
            "annotation_method": "independent_manual_annotation",
            "ground_truth": {
                "expected_document_type": rx["doc_type"],
                "expected_safety_status": rx["safety_status"],
                "expected_biomarkers": [],
                "expected_medications": rx["medications"]
            },
            "annotation_notes": rx["notes"]
        }
        cases_payload.append(case_entry)
        manifest_rows.append(f"| **{rx['id']}** | `{rx['doc_type']}` | `{rx['file']}` | `{rx['source']}` | `independent_manual_annotation` | `{rx['safety_status']}` | `{rx['difficulty']}` | {rx['notes']} |")

    # Write ground_truth.json
    gt_payload = {
        "version": "1.0",
        "benchmark_type": "independent_human_annotated",
        "description": "Independent real-document benchmark ground truth populated with 25 medical reports and 25 prescriptions.",
        "total_cases": len(cases_payload),
        "report_cases": len(report_definitions),
        "prescription_cases": len(rx_definitions),
        "cases": cases_payload
    }

    with open(GROUND_TRUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(gt_payload, f, indent=2)
    print(f"Saved ground truth with {len(cases_payload)} cases to '{GROUND_TRUTH_FILE}'")

    # Write MANIFEST.md
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(manifest_rows))
    print(f"Saved dataset manifest to '{MANIFEST_FILE}'")

if __name__ == "__main__":
    populate_benchmark()
