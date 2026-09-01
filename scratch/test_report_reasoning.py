"""
===============================================================================
STEP 5: REPORT REASONING AGENT TEST SUITE
===============================================================================

Tests:
  1. safe_to_display report
  2. needs_manual_review report
  3. hard_stop report (returns safe review-required response)
  4. Normal verified finding
  5. Abnormal verified finding
  6. Missing value (not fabricated)
  7. Unverified finding (flagged for review)
  8. Unknown biomarker
  9. Low OCR confidence
  10. Multiple verified findings
  11. Gemini / API failure (fails safe gracefully)
  12. Empty Gemini response
  13. Verify Gemini cannot override hard_stop
  14. Verify Gemini cannot override needs_manual_review
  15. Verify missing values are not fabricated
  16. Pipeline context integration (context["reasoning"] populated)
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
from report_reasoning_agent import ReportReasoningAgent, HARD_STOP_MESSAGE

class TestStep5ReportReasoning(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: safe_to_display report
    def test_01_safe_to_display_report(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 0.9 mg/dL\nFasting Glucose: 92.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(reasoning["safety_status_used"], "safe_to_display")
        self.assertIn("Evaluated Findings", reasoning["summary"])

    # TEST 2: needs_manual_review report
    def test_02_needs_manual_review_report(self):
        raw_text = "Serum Creatinine: mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(reasoning["safety_status_used"], "needs_manual_review")

    # TEST 3: hard_stop report (returns safe review-required response)
    def test_03_hard_stop_report(self):
        raw_text = "Serum Creatinine: -5.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(reasoning["safety_status_used"], "hard_stop")
        self.assertEqual(reasoning["summary"], HARD_STOP_MESSAGE)

    # TEST 4: Normal verified finding
    def test_04_normal_verified_finding(self):
        bm = {"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "result_status": "within_range", "verification_status": "verified"}
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": [bm]}
        ctx["safety"] = {"safety_status": "safe_to_display"}
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(len(reasoning["findings"]), 1)
        self.assertIn("0.9 mg/dL", reasoning["summary"])

    # TEST 5: Abnormal verified finding
    def test_05_abnormal_verified_finding(self):
        bm = {"name": "Serum Creatinine", "value": 2.5, "unit": "mg/dL", "result_status": "above_range", "verification_status": "verified"}
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": [bm]}
        ctx["safety"] = {"safety_status": "safe_to_display"}
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertIn("ABOVE_RANGE", reasoning["summary"])

    # TEST 6: Missing value (not fabricated)
    def test_06_missing_value_not_fabricated(self):
        bm = {"name": "Serum Creatinine", "value": None, "unit": "mg/dL", "result_status": "unknown", "verification_status": "unverified"}
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": [bm]}
        ctx["safety"] = {"safety_status": "needs_manual_review"}
        ctx = ReportReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(len(reasoning["findings"]), 0, "Unverified missing values must NOT be passed as verified findings!")

    # TEST 7: Unverified finding (flagged for review)
    def test_07_unverified_finding_flagged(self):
        bm = {"name": "Serum Creatinine", "value": None, "verification_status": "unverified"}
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": [bm]}
        ctx["safety"] = {"safety_status": "needs_manual_review"}
        ctx = ReportReasoningAgent.process(ctx)
        
        self.assertGreaterEqual(len(ctx["reasoning"]["warnings"]), 1)

    # TEST 8: Unknown biomarker
    def test_08_unknown_biomarker(self):
        bm = {"name": "Unknown Analyte", "verification_status": "unknown"}
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": [bm]}
        ctx["safety"] = {"safety_status": "needs_manual_review"}
        ctx = ReportReasoningAgent.process(ctx)
        
        self.assertEqual(len(ctx["reasoning"]["findings"]), 0)

    # TEST 9: Low OCR confidence
    def test_09_low_ocr_confidence(self):
        raw_text = "Serum Creatinine: 0.9 mg/dL"
        ocr_meta = [{"line_number": 1, "raw_line": "Serum Creatinine: 0.9 mg/dL", "confidence": 40.0}]
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text, metadata={"ocr_metadata": ocr_meta})
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        self.assertIn(ctx["reasoning"]["safety_status_used"], ["needs_manual_review", "hard_stop"])

    # TEST 10: Multiple verified findings
    def test_10_multiple_verified_findings(self):
        bms = [
            {"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "result_status": "within_range", "verification_status": "verified"},
            {"name": "Fasting Glucose", "value": 95.0, "unit": "mg/dL", "result_status": "within_range", "verification_status": "verified"}
        ]
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": bms}
        ctx["safety"] = {"safety_status": "safe_to_display"}
        ctx = ReportReasoningAgent.process(ctx)
        
        self.assertEqual(len(ctx["reasoning"]["findings"]), 2)

    # TEST 11: Gemini / API failure (fails safe gracefully)
    def test_11_api_failure_failsafe(self):
        bms = [{"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "result_status": "within_range", "verification_status": "verified"}]
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": bms}
        ctx["safety"] = {"safety_status": "safe_to_display"}
        
        mock_ai_fail = lambda p, **kwargs: Exception("API Connection Timeout")
        ctx = ReportReasoningAgent.process(ctx, ai_generator_func=mock_ai_fail)
        
        reasoning = ctx.get("reasoning", {})
        self.assertIn("Evaluated Findings", reasoning["summary"])
        self.assertGreaterEqual(len(reasoning["warnings"]), 1)

    # TEST 12: Empty Gemini response
    def test_12_empty_gemini_response(self):
        bms = [{"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "result_status": "within_range", "verification_status": "verified"}]
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": bms}
        ctx["safety"] = {"safety_status": "safe_to_display"}
        
        mock_empty_ai = lambda p, **kwargs: ""
        ctx = ReportReasoningAgent.process(ctx, ai_generator_func=mock_empty_ai)
        
        reasoning = ctx.get("reasoning", {})
        self.assertIn("Evaluated Findings", reasoning["summary"])

    # TEST 13: Verify Gemini cannot override hard_stop
    def test_13_gemini_cannot_override_hard_stop(self):
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["safety"] = {"safety_status": "hard_stop", "hard_stop_triggered": True}
        
        mock_hallucinated_ai = lambda p, **kwargs: "Patient is 100% healthy!"
        ctx = ReportReasoningAgent.process(ctx, ai_generator_func=mock_hallucinated_ai)
        
        reasoning = ctx.get("reasoning", {})
        self.assertEqual(reasoning["summary"], HARD_STOP_MESSAGE, "LLM must NEVER override hard_stop!")

    # TEST 14: Verify Gemini cannot override needs_manual_review
    def test_14_gemini_cannot_override_needs_manual_review(self):
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["safety"] = {"safety_status": "needs_manual_review"}
        ctx["verification"] = {"biomarkers": [{"name": "Serum Creatinine", "value": 0.9, "unit": "mg/dL", "verification_status": "verified"}]}
        
        ctx = ReportReasoningAgent.process(ctx)
        self.assertEqual(ctx["reasoning"]["safety_status_used"], "needs_manual_review")

    # TEST 15: Verify missing values are not fabricated
    def test_15_missing_values_not_fabricated(self):
        bms = [{"name": "Serum Creatinine", "value": None, "unit": "mg/dL", "verification_status": "unverified"}]
        ctx = create_pipeline_context(document_type="medical_report")
        ctx["verification"] = {"biomarkers": bms}
        ctx["safety"] = {"safety_status": "needs_manual_review"}
        
        ctx = ReportReasoningAgent.process(ctx)
        self.assertEqual(len(ctx["reasoning"]["findings"]), 0)

    # TEST 16: Pipeline context integration
    def test_16_pipeline_context_integration(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 0.9 mg/dL\nFasting Glucose: 92.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        ctx = ReportReasoningAgent.process(ctx)
        
        self.assertIn("reasoning", ctx)
        self.assertIn("summary", ctx["reasoning"])
        self.assertIn("safety_status_used", ctx["reasoning"])
        self.assertIn("disclaimer", ctx["reasoning"])

if __name__ == "__main__":
    unittest.main()
