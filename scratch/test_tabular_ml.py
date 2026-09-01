"""
===============================================================================
TEST SUITE FOR TABULAR ML SAFETY CLASSIFIER & APPLICATION INTEGRATION
===============================================================================
Tests:
  1. Feature extraction format & default values.
  2. Classification for 'safe_to_display' class.
  3. Classification for 'needs_manual_review' class.
  4. Classification for 'hard_stop' class.
  5. Deterministic override guarantee: Rule conflict forces hard_stop.
  6. TabularMLAgent report evaluation aggregation.
  7. Verification of saved model ('tabular_ml_model.joblib') and metrics JSON ('tabular_ml_metrics.json').
  8. End-to-end integration test with app.py medical report analysis pipeline.
"""

import os
import sys
import json
import unittest
import pandas as pd

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tabular_ml_engine import (
    extract_finding_features,
    predict_finding_safety,
    TabularMLAgent,
    load_tabular_ml_model,
    FEATURE_NAMES
)
from app import analyze_medical_report, rule_engine

class TestTabularMLSafetyClassifier(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Ensure model is trained & loaded
        cls.pipeline = load_tabular_ml_model()
        cls.assertIsNotNone(cls.pipeline, "Tabular ML model pipeline must load successfully.")

    # TEST 1: Feature Extraction
    def test_01_feature_extraction(self):
        finding = {
            "test_name": "Serum Creatinine",
            "normalized_test_name": "creatinine",
            "result_value": 1.2,
            "unit": "mg/dL",
            "status": "NORMAL",
            "range_description": "0.6 - 1.3 mg/dL",
            "reference_status": "NORMAL",
            "raw_line": "Serum Creatinine 1.2 mg/dL"
        }
        df_feat = extract_finding_features(finding, ocr_confidence=0.96)
        self.assertIsInstance(df_feat, pd.DataFrame)
        self.assertEqual(list(df_feat.columns), FEATURE_NAMES)
        self.assertEqual(df_feat.iloc[0]['value'], 1.2)
        self.assertEqual(df_feat.iloc[0]['unit_validity'], 1.0)
        self.assertEqual(df_feat.iloc[0]['ref_range_validity'], 1.0)
        self.assertEqual(df_feat.iloc[0]['ocr_confidence'], 0.96)
        self.assertEqual(df_feat.iloc[0]['evidence_availability'], 1.0)
        self.assertEqual(df_feat.iloc[0]['rule_conflict'], 0.0)

    # TEST 2: Class 'safe_to_display'
    def test_02_class_safe_to_display(self):
        safe_finding = {
            "test_name": "Fasting Glucose",
            "normalized_test_name": "fasting_glucose",
            "result_value": 92.0,
            "unit": "mg/dL",
            "status": "NORMAL",
            "range_description": "70 - 99 mg/dL",
            "reference_status": "NORMAL",
            "raw_line": "Fasting Glucose 92.0 mg/dL",
            "ocr_confidence": 0.98
        }
        res = predict_finding_safety(safe_finding)
        self.assertEqual(res['ml_safety_class'], 'safe_to_display')
        self.assertGreaterEqual(res['confidence'], 0.50)

    # TEST 3: Class 'needs_manual_review'
    def test_03_class_needs_manual_review(self):
        review_finding = {
            "test_name": "Fasting Glucose",
            "normalized_test_name": "fasting_glucose",
            "result_value": 92.0,
            "unit": "mg/dL",
            "status": "NORMAL",
            "range_description": "70 - 99 mg/dL",
            "reference_status": "NORMAL",
            "raw_line": "Fasting Glucose 92.0 mg/dL",
            "ocr_confidence": 0.72 # moderate OCR confidence (0.55 - 0.82)
        }
        res = predict_finding_safety(review_finding)
        self.assertEqual(res['ml_safety_class'], 'needs_manual_review')

    # TEST 4: Class 'hard_stop'
    def test_04_class_hard_stop(self):
        stop_finding = {
            "test_name": "Serum Creatinine",
            "normalized_test_name": "creatinine",
            "result_value": -5.0, # implausible negative value
            "unit": "mg/dL",
            "status": "INVALID",
            "range_description": "0.6 - 1.3 mg/dL",
            "reference_status": "NORMAL",
            "raw_line": "Serum Creatinine -5.0 mg/dL",
            "ocr_confidence": 0.40 # low OCR confidence
        }
        res = predict_finding_safety(stop_finding)
        self.assertEqual(res['ml_safety_class'], 'hard_stop')

    # TEST 5: Deterministic Authority Guarantee (Rule Conflict Forces Hard Stop)
    def test_05_deterministic_authority_guarantee(self):
        conflict_finding = {
            "test_name": "Serum Creatinine",
            "normalized_test_name": "creatinine",
            "result_value": 9999.0, # biologically impossible artifact
            "unit": "invalid_unit_xyz", # corrupted unit
            "status": "HIGH",
            "rule_conflict": True,
            "range_description": "0.6 - 1.3 mg/dL",
            "raw_line": "Serum Creatinine 9999.0 invalid_unit_xyz",
            "ocr_confidence": 0.99
        }
        res = predict_finding_safety(conflict_finding)
        self.assertEqual(res['ml_safety_class'], 'hard_stop')
        self.assertGreaterEqual(res['confidence'], 0.95)

    # TEST 6: TabularMLAgent Report Aggregation
    def test_06_agent_report_evaluation(self):
        eval_results = [
            {
                "test_name": "Fasting Glucose",
                "normalized_test_name": "fasting_glucose",
                "result_value": 90.0,
                "unit": "mg/dL",
                "status": "NORMAL",
                "range_description": "70 - 99 mg/dL",
                "raw_line": "Fasting Glucose 90.0 mg/dL"
            },
            {
                "test_name": "Serum Creatinine",
                "normalized_test_name": "creatinine",
                "result_value": 1.1,
                "unit": "mg/dL",
                "status": "NORMAL",
                "range_description": "0.6 - 1.3 mg/dL",
                "raw_line": "Serum Creatinine 1.1 mg/dL"
            }
        ]
        agent_res = TabularMLAgent.evaluate_report(eval_results, ocr_metadata=[{"confidence": 0.96}])
        self.assertIn("overall_safety", agent_res)
        self.assertEqual(len(agent_res["findings_evaluation"]), 2)
        self.assertIn("ml_safety_class", eval_results[0])

    # TEST 7: Metrics Artifact & Model File Integrity
    def test_07_model_artifacts_exist(self):
        self.assertTrue(os.path.exists("tabular_ml_model.joblib"))
        self.assertTrue(os.path.exists("tabular_ml_metrics.json"))

        with open("tabular_ml_metrics.json", "r", encoding="utf-8") as f:
            metrics = json.load(f)

        self.assertIn("best_model", metrics)
        self.assertIn("evaluation_summary", metrics)
        self.assertIn("Decision Tree", metrics["evaluation_summary"])
        self.assertIn("Random Forest", metrics["evaluation_summary"])
        self.assertIn("Logistic Regression", metrics["evaluation_summary"])

    # TEST 8: Full Application Integration Test
    def test_08_app_integration(self):
        report_text = """Patient Name: Sarah Connor
Fasting Blood Glucose: 95.0 mg/dL
Serum Creatinine: 0.9 mg/dL
HbA1c: 5.6 %"""

        analysis_res = analyze_medical_report(report_text)
        self.assertIn("english", analysis_res)
        self.assertIsNotNone(analysis_res["english"])
        self.assertIn("Sarah Connor", analysis_res.get("patient_name", ""))

if __name__ == "__main__":
    unittest.main()
