# Independent Real-Document Benchmark Guidelines

## Overview
This directory (`data/independent_benchmark/`) contains the foundation and ground-truth schemas for independent human evaluation of the Medical Report Analyzer pipelines.

> **CRITICAL INDEPENDENCE RULE**: Ground-truth safety targets and extraction labels in this dataset MUST be established by independent human annotation. They MUST NEVER be generated from ML models, decision trees, or automated pipeline prediction rules.

---

## Directory Structure
- `reports/`: Raw real-world anonymized medical laboratory report files (PNG/JPG/PDF).
- `prescriptions/`: Raw real-world anonymized handwritten/printed prescription files (PNG/JPG/PDF).
- `ground_truth.json`: Human-annotated ground-truth annotations and safety targets.
- `README.md`: Annotation guidelines and dataset governance documentation.

---

## Annotation Guidelines for Human Annotators

Annotators must inspect the raw document image/file and record the expected values **independently** of model output.

### 1. Document Type Classification
- `medical_report`: Laboratory reports (e.g. CBC, LFT, KFT, Lipid Profile, Blood Glucose, HbA1c).
- `prescription`: Doctor's prescription notes, medication orders, dosage schedules.
- `unsupported`: Unrelated documents (receipts, general letters, invalid files).

### 2. Document Safety Governance Targets
Human annotators should assign the document-level or finding-level `expected_safety_status` based on these rules:

#### A. `safe_to_display`
- Image text is clearly legible (high contrast, unblurred).
- Lab analyte or medication names, values, units, and ranges are unambiguous.
- Zero contradictory or implausible values.

#### B. `needs_manual_review`
- OCR text is partially faint, handwritten, or low-contrast.
- Unregistered analyte or non-standard reference range source.
- Missing or ambiguous dosage schedule or duration on a prescription item.

#### C. `hard_stop`
- Critical rule conflicts or severe medical conflicts (e.g. prescribing potassium-sparing diuretics to a patient with hyperkalemia).
- Implausible numerical values (e.g. negative lab values or extreme artifacts like Creatinine = 9999 mg/dL).
- Unreadable or missing critical lines.

---

## Reporting Performance
If no real annotated document images are present in `reports/` or `prescriptions/`, evaluation scripts MUST report:
`Independent Benchmark Accuracy: NOT AVAILABLE — NO ANNOTATED REAL-DOCUMENT CASES`
Do NOT output synthetic or fake 100% / 0% accuracy numbers.
