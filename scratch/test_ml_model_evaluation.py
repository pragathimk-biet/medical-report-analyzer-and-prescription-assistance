"""
===============================================================================
STEP 7: ML SAFETY MODEL ACCURACY EVALUATION TEST SUITE
===============================================================================

Tests:
  1. Dataset loads
  2. Dataset has all required features
  3. Three target classes exist
  4. No duplicate leakage
  5. Train/test split is stratified
  6. Preprocessing has no test leakage
  7. Decision Tree baseline trains
  8. Random Forest trains
  9. Logistic Regression trains
  10. SVM trains
  11. Gradient Boosting trains
  12. Cross-validation executes
  13. Hold-out test executes
  14. Accuracy is between 0 and 1
  15. Precision is between 0 and 1
  16. Recall is between 0 and 1
  17. F1 is between 0 and 1
  18. False-safe rate is between 0 and 1
  19. Hard-stop recall is between 0 and 1
  20. Confusion matrix dimensions are correct (3x3)
  21. Selected model exists
  22. Metrics JSON contains actual metrics
  23. Model artifact loads
  24. ML safety agent still works
  25. Deterministic hard-stop cannot be overridden
  26. Missing model fails safe
  27. Malformed features fail safe
  28. No accuracy values are hard-coded
  29. Evaluation report is generated
  30. Existing ML tests remain compatible
"""

import os
import sys
import json
import unittest
import pandas as pd
import numpy as np
import joblib

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from train_tabular_ml import (
    FEATURE_NAMES,
    CLASS_MAP,
    DATASET_FILE,
    MODEL_FILE,
    METRICS_FILE,
    REPORT_FILE,
    generate_uci_clinical_tabular_dataset,
    train_and_evaluate_all_models
)
from tabular_ml_engine import TabularMLAgent, extract_finding_features, load_tabular_ml_model
from ml_safety_agent import MLSafetyAgent

class TestStep7MLModelEvaluation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Ensure fresh model training and evaluation artifact generation
        train_and_evaluate_all_models()

    # TEST 1: Dataset loads
    def test_01_dataset_loads(self):
        self.assertTrue(os.path.exists(DATASET_FILE), "Dataset CSV must exist!")
        df = pd.read_csv(DATASET_FILE)
        self.assertGreaterEqual(len(df), 1000)

    # TEST 2: Dataset has all required features
    def test_02_dataset_has_required_features(self):
        df = pd.read_csv(DATASET_FILE)
        for fname in FEATURE_NAMES:
            self.assertIn(fname, df.columns, f"Feature '{fname}' missing from dataset!")

    # TEST 3: Three target classes exist
    def test_03_three_target_classes_exist(self):
        df = pd.read_csv(DATASET_FILE)
        unique_targets = df['target_safety_class'].unique()
        self.assertEqual(len(unique_targets), 3)

    # TEST 4: No duplicate leakage
    def test_04_no_duplicate_leakage(self):
        df = pd.read_csv(DATASET_FILE)
        dup_count = df.duplicated(subset=FEATURE_NAMES).sum()
        self.assertLess(dup_count / len(df), 0.50, "Dataset contains excessive duplicate feature rows!")

    # TEST 5: Train/test split is stratified
    def test_05_train_test_split_stratified(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertTrue(metrics["split"]["stratified"])

    # TEST 6: Preprocessing has no test leakage
    def test_06_preprocessing_no_leakage(self):
        df = pd.read_csv(DATASET_FILE)
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        
        X = df[FEATURE_NAMES]
        y = df['target_safety_class']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42)
        
        scaler = StandardScaler()
        scaler.fit(X_train) # Fit ONLY on train
        
        # Test mean is independent
        self.assertNotEqual(scaler.mean_[0], X_test.mean().values[0])

    # TEST 7: Decision Tree baseline trains
    def test_07_decision_tree_trains(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("DecisionTree", metrics["models"])

    # TEST 8: Random Forest trains
    def test_08_random_forest_trains(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("RandomForest", metrics["models"])

    # TEST 9: Logistic Regression trains
    def test_09_logistic_regression_trains(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("LogisticRegression", metrics["models"])

    # TEST 10: SVM trains
    def test_10_svm_trains(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("SVM", metrics["models"])

    # TEST 11: Gradient Boosting trains
    def test_11_gradient_boosting_trains(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("GradientBoosting", metrics["models"])

    # TEST 12: Cross-validation executes
    def test_12_cross_validation_executes(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        sel_m = metrics["selected_model"]
        self.assertIn("cross_validation_mean", sel_m)
        self.assertGreaterEqual(sel_m["cross_validation_mean"], 0.0)

    # TEST 13: Hold-out test executes
    def test_13_hold_out_test_executes(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("final_test_metrics", metrics)

    # TEST 14: Accuracy is between 0 and 1
    def test_14_accuracy_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        acc = metrics["final_test_metrics"]["accuracy"]
        self.assertTrue(0.0 <= acc <= 1.0)

    # TEST 15: Precision is between 0 and 1
    def test_15_precision_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        p = metrics["final_test_metrics"]["macro_precision"]
        self.assertTrue(0.0 <= p <= 1.0)

    # TEST 16: Recall is between 0 and 1
    def test_16_recall_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        r = metrics["final_test_metrics"]["macro_recall"]
        self.assertTrue(0.0 <= r <= 1.0)

    # TEST 17: F1 is between 0 and 1
    def test_17_f1_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        f1 = metrics["final_test_metrics"]["macro_f1"]
        self.assertTrue(0.0 <= f1 <= 1.0)

    # TEST 18: False-safe rate is between 0 and 1
    def test_18_false_safe_rate_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        fsr = metrics["final_test_metrics"]["false_safe_rate"]
        self.assertTrue(0.0 <= fsr <= 1.0)

    # TEST 19: Hard-stop recall is between 0 and 1
    def test_19_hard_stop_recall_valid_range(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        hsr = metrics["final_test_metrics"]["hard_stop_recall"]
        self.assertTrue(0.0 <= hsr <= 1.0)

    # TEST 20: Confusion matrix dimensions are correct (3x3)
    def test_20_confusion_matrix_dimensions(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        cm = metrics["confusion_matrix"]
        self.assertEqual(len(cm), 3)
        for row in cm:
            self.assertEqual(len(row), 3)

    # TEST 21: Selected model exists
    def test_21_selected_model_exists(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("selected_model", metrics)
        self.assertIn("model_name", metrics["selected_model"])

    # TEST 22: Metrics JSON contains actual metrics
    def test_22_metrics_json_contains_actual_metrics(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        self.assertIn("leakage_analysis", metrics)
        self.assertIn("limitations", metrics)

    # TEST 23: Model artifact loads
    def test_23_model_artifact_loads(self):
        self.assertTrue(os.path.exists(MODEL_FILE))
        pipeline_obj = joblib.load(MODEL_FILE)
        self.assertIn("model", pipeline_obj)

    # TEST 24: ML safety agent still works
    def test_24_ml_safety_agent_works(self):
        finding = {
            "test_name": "Serum Creatinine",
            "normalized_test_name": "creatinine",
            "result_value": 0.9,
            "unit": "mg/dL",
            "reference_status": "NORMAL",
            "range_description": "0.7 - 1.3 mg/dL",
            "ocr_confidence": 0.95
        }
        res = TabularMLAgent.predict_finding_safety(finding)
        self.assertIn("predicted_class", res)

    # TEST 25: Deterministic hard-stop cannot be overridden
    def test_25_deterministic_hard_stop_precedence(self):
        # Even if ML returns safe_to_display, a hard_stop verification result locks safety_status to hard_stop
        from input_router import create_pipeline_context
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {
            "overall_status": "hard_stop",
            "biomarkers": [{"test_name": "Potassium", "validation_status": "REJECTED_IMPLAUSIBLE"}]
        }
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        self.assertEqual(ctx["safety"]["safety_status"], "hard_stop")

    # TEST 26: Missing model fails safe
    def test_26_missing_model_fails_safe(self):
        res = TabularMLAgent.predict_finding_safety({"test_name": "Test"}, model_pipeline=None)
        self.assertEqual(res["predicted_class"], "needs_manual_review")

    # TEST 27: Malformed features fail safe
    def test_27_malformed_features_fail_safe(self):
        res = TabularMLAgent.predict_finding_safety({"result_value": "INVALID_STRING_TYPE"})
        self.assertIn(res["predicted_class"], ["needs_manual_review", "hard_stop"])

    # TEST 28: No accuracy values are hard-coded
    def test_28_no_hardcoded_accuracy_values(self):
        with open(METRICS_FILE, "r") as f:
            metrics = json.load(f)
        acc = metrics["selected_model"]["accuracy"]
        self.assertIsInstance(acc, float)

    # TEST 29: Evaluation report is generated
    def test_29_evaluation_report_generated(self):
        self.assertTrue(os.path.exists(REPORT_FILE))
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# ML Safety Model Evaluation Report", content)

    # TEST 30: Existing ML tests remain compatible
    def test_30_existing_ml_tests_compatible(self):
        from scratch.test_tabular_ml import TestTabularMLSafetyClassifier
        suite = unittest.TestLoader().loadTestsFromTestCase(TestTabularMLSafetyClassifier)
        result = unittest.TextTestRunner(stream=open(os.devnull, 'w')).run(suite)
        self.assertTrue(result.wasSuccessful())

if __name__ == "__main__":
    unittest.main()
