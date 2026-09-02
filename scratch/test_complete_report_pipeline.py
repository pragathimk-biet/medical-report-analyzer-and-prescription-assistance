"""
===============================================================================
STEP 6: COMPLETE REPORT PIPELINE END-TO-END TEST SUITE
===============================================================================

Target Pipeline Flow:
  Patient Upload
        ↓
   Input Router (input_router.py)
        ↓
  Report Extraction Agent (report_extraction_agent.py)
        ↓
  Report Verification Agent (report_verification_agent.py)
        ↓
  ML Safety / Reliability Agent (ml_safety_agent.py)
        ↓
  Report Reasoning Agent (report_reasoning_agent.py)
        ↓
  Patient-Facing Output Context

Tests:
  1. Safe report (safe_to_display)
  2. Abnormal but verified report
  3. Needs manual review
  4. Hard stop (deliberately unsafe/unreliable condition)
  5. Poor OCR confidence
  6. Missing value (unverified)
  7. Unknown biomarker
  8. Missing reference range
  9. Invalid unit
  10. Suspicious value (biological bound violation -> hard_stop)
  11. ML model failure fail-safe
  12. Gemini / AI failure fail-safe
  13. Invalid document
  14. Complete pipeline context propagation across all 5 stages
  15. Verify hard_stop prevents LLM reasoning (Zero LLM calls)
  16. Verify needs_manual_review filters unverified findings
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from report_verification_agent import ReportVerificationAgent
from ml_safety_agent import MLSafetyAgent
from report_reasoning_agent import ReportReasoningAgent, HARD_STOP_MESSAGE
from app import app

class TestCompleteReportPipeline(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def run_full_pipeline(self, raw_text, filename="report.png", explicit_type=None, metadata=None, ai_func=None):
        """Helper executing full 5-stage pipeline sequentially."""
        meta = metadata or {}
        meta["filename"] = filename
        ctx = InputRouter.route_and_create_context(text=raw_text, filename=filename, explicit_type=explicit_type, metadata=meta)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx, ai_generator_func=ai_func)
        return ctx

    # TEST 1: Safe report
    def test_01_safe_report(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 0.9 mg/dL\nFasting Glucose: 92.0 mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertEqual(ctx["document_type"], "medical_report")
        self.assertEqual(ctx["safety"]["safety_status"], "safe_to_display")
        self.assertEqual(ctx["reasoning"]["safety_status_used"], "safe_to_display")
        self.assertIn("Evaluated Findings", ctx["reasoning"]["summary"])

    # TEST 2: Abnormal but verified report
    def test_02_abnormal_verified_report(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 1.8 mg/dL\nFasting Glucose: 145.0 mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertIn(ctx["safety"]["safety_status"], ["safe_to_display", "needs_manual_review"])
        self.assertEqual(len(ctx["verification"]["biomarkers"]), 2)

    # TEST 3: Needs manual review
    def test_03_needs_manual_review(self):
        raw_text = "Serum Creatinine: mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertEqual(ctx["safety"]["safety_status"], "needs_manual_review")
        self.assertEqual(ctx["reasoning"]["safety_status_used"], "needs_manual_review")

    # TEST 4: Hard stop (deliberately unsafe/unreliable condition)
    def test_04_hard_stop_condition(self):
        raw_text = "Serum Creatinine: -5.0 mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertEqual(ctx["safety"]["safety_status"], "hard_stop")
        self.assertTrue(ctx["safety"]["hard_stop_triggered"])
        self.assertEqual(ctx["reasoning"]["summary"], HARD_STOP_MESSAGE)

    # TEST 5: Poor OCR confidence
    def test_05_poor_ocr_confidence(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL"
        ocr_meta = [{"line_number": 1, "raw_line": "Serum Creatinine: 0.9 mg/dL", "confidence": 30.0}]
        ctx = self.run_full_pipeline(raw_text, metadata={"ocr_metadata": ocr_meta})
        
        self.assertIn(ctx["safety"]["safety_status"], ["needs_manual_review", "hard_stop"])

    # TEST 6: Missing value (unverified, not fabricated)
    def test_06_missing_value_unverified(self):
        raw_text = "Serum Creatinine: mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        bm = ctx["verification"]["biomarkers"][0]
        self.assertEqual(bm["verification_status"], "unverified")
        self.assertIsNone(bm["value"])

    # TEST 7: Unknown biomarker
    def test_07_unknown_biomarker(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="Unknown Lab Compound XYZ: 12.0 units")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Unknown Lab Compound XYZ", "normalized_name": "unknown_xyz", "value": 12.0, "unit": "units", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        bm = ctx["verification"]["biomarkers"][0]
        self.assertEqual(bm["verification_status"], "unknown")

    # TEST 8: Missing reference range
    def test_08_missing_reference_range(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="Custom Parameter: 15.0 mg/dL")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Custom Parameter", "normalized_name": "custom_param", "value": 15.0, "unit": "mg/dL", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        bm = ctx["verification"]["biomarkers"][0]
        self.assertEqual(bm["reference_source"], "unavailable")

    # TEST 9: Invalid unit
    def test_09_invalid_unit(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="Serum Creatinine: 1.0 invalid_unit")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": 1.0, "unit": "invalid_unit", "confidence": 0.90}
        ]
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        bm = ctx["verification"]["biomarkers"][0]
        self.assertIn(bm["verification_status"], ["unverified", "invalid_unit"])

    # TEST 10: Suspicious value (biological bound violation -> hard_stop)
    def test_10_suspicious_value_hard_stop(self):
        raw_text = "Serum Creatinine: 9999.0 mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertEqual(ctx["safety"]["safety_status"], "hard_stop")

    # TEST 11: ML model failure fail-safe
    def test_11_ml_model_failure_failsafe(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL"
        with patch("ml_safety_agent.load_tabular_ml_model", return_value=None):
            ctx = self.run_full_pipeline(raw_text)
            self.assertEqual(ctx["safety"]["safety_status"], "needs_manual_review")

    # TEST 12: Gemini / AI failure fail-safe
    def test_12_gemini_failure_failsafe(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL"
        mock_fail_ai = lambda p, **kwargs: Exception("LLM Timeout")
        ctx = self.run_full_pipeline(raw_text, ai_func=mock_fail_ai)
        
        self.assertIn("Evaluated Findings", ctx["reasoning"]["summary"])

    # TEST 13: Invalid document
    def test_13_invalid_document(self):
        ctx = self.run_full_pipeline("", filename="empty.png")
        self.assertEqual(ctx["document_type"], "unsupported")

    # TEST 14: Complete pipeline context propagation across all 5 stages
    def test_14_complete_pipeline_context_propagation(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 1.0 mg/dL\nFasting Glucose: 95.0 mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        self.assertIn("document_type", ctx)
        self.assertIn("raw_input", ctx)
        self.assertIn("extracted_data", ctx)
        self.assertIn("verification", ctx)
        self.assertIn("safety", ctx)
        self.assertIn("reasoning", ctx)
        
        self.assertEqual(len(ctx["extracted_data"]["biomarkers"]), 2)
        self.assertEqual(len(ctx["verification"]["biomarkers"]), 2)
        self.assertEqual(len(ctx["safety"]["evaluated_findings"]), 2)
        self.assertIn("summary", ctx["reasoning"])

    # TEST 15: Verify hard_stop prevents LLM reasoning (Zero LLM calls)
    def test_15_hard_stop_prevents_llm_reasoning(self):
        raw_text = "Serum Creatinine: -5.0 mg/dL"
        mock_ai_spy = MagicMock(return_value="Hallucinated text")
        ctx = self.run_full_pipeline(raw_text, ai_func=mock_ai_spy)
        
        mock_ai_spy.assert_not_called()
        self.assertEqual(ctx["reasoning"]["summary"], HARD_STOP_MESSAGE)

    # TEST 16: Verify needs_manual_review filters unverified findings
    def test_16_needs_manual_review_filters_unverified(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL\nUnknown Lab Parameter: mg/dL"
        ctx = self.run_full_pipeline(raw_text)
        
        valid_bms = ctx["reasoning"]["findings"]
        for bm in valid_bms:
            self.assertIn(bm["verification_status"], ["verified", "unit_missing"])

if __name__ == "__main__":
    unittest.main()
