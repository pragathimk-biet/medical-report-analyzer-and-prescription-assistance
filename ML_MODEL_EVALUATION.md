# ML Safety Model Evaluation Report

## 1. Overview & Objectives
This evaluation independently audits and compares 5 lightweight Scikit-learn machine learning classifiers for document safety governance in the Medical Report Analyzer pipeline.

## 2. Dataset Description
- **Total Samples**: 3000
- **Class Distribution**: {'safe_to_display': 1500, 'needs_manual_review': 900, 'hard_stop': 600}
- **Clinical Distributions**: UCI Chronic Kidney Disease (CKD) & UCI Hepatitis C Virus (HCV) datasets.
- **Features Used**: `value, unit_validity, ref_range_validity, ocr_confidence, extraction_confidence, evidence_availability, rule_conflict, analyte_validity`

## 3. Train / Validation / Test Split
- **Train Set**: 70% (2,100 samples)
- **Validation Set**: 15% (450 samples)
- **Test Set**: 15% (450 samples)
- **Stratified**: Yes
- **Data Leakage Guard**: Feature scaling (StandardScaler) fit strictly on train split.

## 4. Label Leakage Analysis
> The target safety labels are generated from extraction metadata rules (e.g. OCR confidence, unit validity, rule conflict). While clinical value distributions derive from UCI CKD/HCV datasets, the safety governance targets reflect document quality rules. Consequently, tree-based models achieve high accuracy by learning these rule boundaries. This performance evaluates rule-boundary separation rather than unconstrained real-world clinical generalization.

## 5. Model Comparison Summary

| Model | Accuracy | Macro Prec | Macro Rec | Macro F1 | Hard-Stop Recall | False-Safe Rate | 5-Fold CV Mean |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **DecisionTree** | 100.00% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.00% | 100.00% |
| **RandomForest** | 100.00% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.00% | 100.00% |
| **LogisticRegression** | 100.00% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.00% | 99.70% |
| **SVM** | 100.00% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.00% | 99.74% |
| **GradientBoosting** | 100.00% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.00% | 100.00% |

## 6. Selected Model Performance
**Selected Model**: `DecisionTree`

```text
MODEL ACCURACY
---------------
Selected Model: DecisionTree
Accuracy: 100.00%
Macro Precision: 1.0000
Macro Recall: 1.0000
Macro F1: 1.0000
Hard-Stop Recall: 1.0000
False-Safe Rate: 0.00%
Test Samples: 450
```

## 7. Confusion Matrix (Selected Model)
```text
                 Predicted
                 safe  review  hard_stop
Actual safe      225   0       0        
Actual review    0     135     0        
Actual hard_stop 0     0       90       
```

## 8. Limitations & Clinical Governance
- The dataset combines real clinical lab distributions with synthetic document metadata.
- Deterministic safety rules maintain ultimate authority over ML predictions.
- ML predictions never override deterministic hard-stop alerts.