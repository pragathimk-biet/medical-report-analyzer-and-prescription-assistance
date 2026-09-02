"""
===============================================================================
STEP 4: ML SAFETY / RELIABILITY CLASSIFIER TEST SUITE
===============================================================================

Tests:
  1. Fully verified normal report (safe_to_display)
  2. Verified abnormal report (safe_to_display / needs_manual_review)
  3. Low OCR confidence (needs_manual_review)
  4. Missing values (unverified -> needs_manual_review)
  5. Unknown analyte (unknown -> needs_manual_review)
  6. Missing reference range (reference_range_unavailable -> needs_manual_review)
  7. Invalid biomarker value (invalid -> hard_stop)
  8. Suspicious/extreme value (suspicious -> hard_stop)
  9. Multiple verification failures (needs_manual_review / hard_stop)
  10. Hard-stop condition (Deterministic Override Guarantee: hard-stop NEVER overridden to safe_to_display)
  11. Missing model file (Fails safe to needs_manual_review, no crash)
  12. Malformed feature input (Fails safe to needs_manual_review, no crash)
  13. Pipeline context integration (context["safety"] populated)
  14. Unexpected model output (Handled gracefully with fallback)
"""

import os
import sys
import unittest
from unittest.mock import patch

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from report_verification_agent import ReportVerificationAgent
from ml_safety_agent import MLSafetyAgent

class TestStep4MLSafety(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Fully verified normal report
    def test_01_fully_verified_normal_report(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 0.9 mg/dL\nFasting Glucose: 92.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "safe_to_display")
        self.assertFalse(safety["hard_stop_triggered"])
        self.assertGreaterEqual(safety["confidence"], 0.80)

    # TEST 2: Verified abnormal report
    def test_02_verified_abnormal_report(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 1.8 mg/dL\nFasting Glucose: 145.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertIn(safety["safety_status"], ["safe_to_display", "needs_manual_review"])

    # TEST 3: Low OCR confidence scenario
    def test_03_low_ocr_confidence(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL"
        ocr_meta = [{"line_number": 1, "raw_line": "Serum Creatinine: 0.9 mg/dL", "confidence": 40.0}]
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text, metadata={"ocr_metadata": ocr_meta})
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertIn(safety["safety_status"], ["needs_manual_review", "hard_stop"])

    # TEST 4: Missing values
    def test_04_missing_values(self):
        raw_text = "Serum Creatinine: mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "needs_manual_review")

    # TEST 5: Unknown analyte
    def test_05_unknown_analyte(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Unknown Analyte XYZ", "normalized_name": "unknown_xyz", "value": 10.0, "unit": "mg/dL", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "needs_manual_review")

    # TEST 6: Missing reference range
    def test_06_missing_reference_range(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Unregistered Biomarker", "normalized_name": "unregistered_bm", "value": 5.0, "unit": "mg/dL", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "needs_manual_review")

    # TEST 7: Invalid biomarker value
    def test_07_invalid_biomarker_value(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": "INVALID_VAL", "unit": "mg/dL", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "hard_stop")
        self.assertTrue(safety["hard_stop_triggered"])

    # TEST 8: Suspicious / extreme value
    def test_08_suspicious_extreme_value(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": 9999.0, "unit": "mg/dL", "confidence": 0.95}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "hard_stop")

    # TEST 9: Multiple verification failures
    def test_09_multiple_verification_failures(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": None, "unit": "mg/dL", "confidence": 0.50},
            {"name": "Unknown Compound", "normalized_name": "unknown_comp", "value": 999.0, "unit": "", "confidence": 0.40}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertIn(safety["safety_status"], ["needs_manual_review", "hard_stop"])

    # TEST 10: Hard-stop condition (Deterministic Override Guarantee)
    def test_10_hard_stop_override_guarantee(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": -5.0, "unit": "mg/dL", "confidence": 0.99}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        safety = ctx.get("safety", {})
        self.assertEqual(safety["safety_status"], "hard_stop", "Deterministic hard_stop must NEVER be overridden to safe_to_display!")

    # TEST 11: Missing model file fail-safe
    def test_11_missing_model_file_failsafe(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": 1.0, "unit": "mg/dL", "confidence": 0.95}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        
        with patch("ml_safety_agent.load_tabular_ml_model", return_value=None):
            ctx = MLSafetyAgent.evaluate_safety(ctx)
            safety = ctx.get("safety", {})
            self.assertEqual(safety["safety_status"], "needs_manual_review", "Missing model MUST fail safe to needs_manual_review!")

    # TEST 12: Malformed feature input handling
    def test_12_malformed_feature_input(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["verification"] = {"biomarkers": [{"name": None, "value": "corrupted"}]}
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        safety = ctx.get("safety", {})
        self.assertIn(safety["safety_status"], ["needs_manual_review", "hard_stop"])

    # TEST 13: Pipeline context integration
    def test_13_pipeline_context_integration(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 1.0 mg/dL\nFasting Glucose: 95.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        self.assertIn("safety", ctx)
        self.assertIn("safety_status", ctx["safety"])
        self.assertIn("reason_codes", ctx["safety"])
        self.assertIn("model_version", ctx["safety"])

    # TEST 14: Unexpected model output handling
    def test_14_unexpected_model_output(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": 1.0, "unit": "mg/dL", "confidence": 0.95}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        
        with patch("ml_safety_agent.predict_finding_safety", side_effect=Exception("Unexpected ML Model Failure")):
            ctx = MLSafetyAgent.evaluate_safety(ctx)
            safety = ctx.get("safety", {})
            self.assertEqual(safety["safety_status"], "needs_manual_review")

if __name__ == "__main__":
    unittest.main()
