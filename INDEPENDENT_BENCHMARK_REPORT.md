# Independent Real-Document Benchmark Report

## 1. Executive Summary & Dataset Overview
- **Total Benchmark Cases**: 50
- **Medical Report Cases**: 25
- **Prescription Cases**: 25
- **Data Source**: Synthetic anonymized realistic document layouts (`data/independent_benchmark/`).
- **Annotation Methodology**: `independent_manual_annotation` (human ground-truth annotations established without model prediction bias).

## 2. Safety Governance Metrics
```text
INDEPENDENT BENCHMARK METRICS
------------------------------
Safety Classification Accuracy: 64.00%
Macro Precision: 0.6091
Macro Recall: 0.6961
Macro F1 Score: 0.6265
Hard-Stop Recall: 100.00%
False-Safe Rate: 0.00% (0 false-safe errors)
```

## 3. Extraction Performance Metrics

### A. Medical Report Extraction Metrics
- **Analyte Name Extraction Accuracy**: 100.00%
- **Numeric Value Extraction Accuracy**: 89.19%
- **Unit Extraction Accuracy**: 78.38%
- **Reference Range Extraction Accuracy**: 78.38%

### B. Prescription Extraction Metrics
- **Medication Identification Accuracy**: 88.89%
- **Strength Extraction Accuracy**: 88.89%
- **Frequency Extraction Accuracy**: 88.89%
- **Timing Extraction Accuracy**: 81.48%
- **Duration Extraction Accuracy**: 88.89%

## 4. Confusion Matrix
```text
                 Predicted
                 safe  review  hard_stop
Actual safe      20    11      3        
Actual review    4     4       0        
Actual hard_stop 0     0       8        
```

## 5. Failure Case Analysis
Total Discrepancies: **18**

| Case ID | Document Type | Expected Status | Predicted Status | Responsible Stage | Likely Cause |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **REPORT_001** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_002** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_004** | `medical_report` | `needs_manual_review` | `safe_to_display` | `Extraction/Verification` | Discrepancy between expected 'needs_manual_review' and predicted 'safe_to_display' |
| **REPORT_012** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_014** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_018** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_019** | `medical_report` | `safe_to_display` | `hard_stop` | `Verification/Governance` | Discrepancy between expected 'safe_to_display' and predicted 'hard_stop' |
| **REPORT_022** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **REPORT_024** | `medical_report` | `safe_to_display` | `hard_stop` | `Verification/Governance` | Discrepancy between expected 'safe_to_display' and predicted 'hard_stop' |
| **REPORT_025** | `medical_report` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **PRESCRIPTION_003** | `prescription` | `needs_manual_review` | `safe_to_display` | `Extraction/Verification` | Discrepancy between expected 'needs_manual_review' and predicted 'safe_to_display' |
| **PRESCRIPTION_005** | `prescription` | `needs_manual_review` | `safe_to_display` | `Extraction/Verification` | Discrepancy between expected 'needs_manual_review' and predicted 'safe_to_display' |
| **PRESCRIPTION_017** | `prescription` | `safe_to_display` | `hard_stop` | `Verification/Governance` | Discrepancy between expected 'safe_to_display' and predicted 'hard_stop' |
| **PRESCRIPTION_018** | `prescription` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **PRESCRIPTION_020** | `prescription` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **PRESCRIPTION_021** | `prescription` | `needs_manual_review` | `safe_to_display` | `Extraction/Verification` | Discrepancy between expected 'needs_manual_review' and predicted 'safe_to_display' |
| **PRESCRIPTION_023** | `prescription` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |
| **PRESCRIPTION_024** | `prescription` | `safe_to_display` | `needs_manual_review` | `Extraction/Verification` | Discrepancy between expected 'safe_to_display' and predicted 'needs_manual_review' |

## 6. Distinguishing Derived ML Accuracy vs Independent Benchmark Accuracy
- **Derived-Label ML Accuracy (100%)**: Derived from rules on synthetic tabular feature vectors in `data/ml_safety_benchmark.csv`.
- **Independent Real-Document Accuracy (64.00%)**: Evaluated end-to-end on 50 realistic document layouts against manual human ground truth in `data/independent_benchmark/`.

## 7. Safety Rule Verification
- **Hard-Stop Precedence Verified**: Deterministic clinical safety rules (e.g. negative values, severe hyperkalemia contraindicated medication, implausible doses) reliably lock overall status to `hard_stop`, preventing ML or LLM override.