"""
===============================================================================
STEP 3: REPORT VERIFICATION AGENT TEST SUITE
===============================================================================

Tests:
  1. Normal biomarker with valid reference range (within_range, verified)
  2. Value below reference range (below_range, verified)
  3. Value above reference range (above_range, verified)
  4. Missing value (unverified, warning logged)
  5. Invalid/non-numeric value (invalid, warning logged)
  6. Unknown biomarker (unknown, reference_source = unavailable)
  7. Missing reference range (reference_range_unavailable, reference_source = unavailable)
  8. Report-specific reference range (Priority 1: report inline range takes priority)
  9. Low OCR confidence (Extraction confidence preserved, not falsely inflated)
  10. Missing/unknown unit (unit_missing / warning logged)
  11. Multiple biomarkers batch verification
  12. Conflicting or suspicious extracted information (biological bounds violation -> suspicious)
  13. Invalid/empty extracted_data (status: invalid_input)
  14. Verification Agent integration with pipeline context
"""

import os
import sys
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from report_verification_agent import ReportVerificationAgent

class TestStep3ReportVerification(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Normal biomarker with valid reference range
    def test_01_normal_biomarker_valid_range(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": 0.9,
            "unit": "mg/dL",
            "reference_range": "0.7 - 1.3 mg/dL",
            "source_text": "Serum Creatinine 0.9 mg/dL (0.7 - 1.3 mg/dL)",
            "confidence": 0.95
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["result_status"], "within_range")
        self.assertEqual(res["verification_status"], "verified")
        self.assertEqual(res["reference_source"], "report")
        self.assertEqual(res["confidence"], 0.95)

    # TEST 2: Value below reference range
    def test_02_value_below_reference_range(self):
        bm = {
            "name": "Hemoglobin",
            "normalized_name": "hemoglobin",
            "value": 9.5,
            "unit": "g/dL",
            "reference_range": "12.0 - 16.0 g/dL",
            "source_text": "Hemoglobin 9.5 g/dL (Ref: 12.0 - 16.0 g/dL)",
            "confidence": 0.92
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["result_status"], "below_range")
        self.assertEqual(res["verification_status"], "verified")

    # TEST 3: Value above reference range
    def test_03_value_above_reference_range(self):
        bm = {
            "name": "Fasting Glucose",
            "normalized_name": "fasting_glucose",
            "value": 145.0,
            "unit": "mg/dL",
            "reference_range": "70 - 99 mg/dL",
            "source_text": "Fasting Glucose 145.0 mg/dL (70 - 99 mg/dL)",
            "confidence": 0.96
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["result_status"], "above_range")
        self.assertEqual(res["verification_status"], "verified")

    # TEST 4: Missing value (unverified)
    def test_04_missing_value(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": None,
            "unit": "mg/dL",
            "reference_range": "0.7 - 1.3 mg/dL",
            "confidence": 0.80,
            "warning": "Value could not be reliably extracted"
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["verification_status"], "unverified")
        self.assertEqual(res["result_status"], "unknown")
        self.assertIsNone(res["value"])
        self.assertGreaterEqual(len(res["warnings"]), 1)

    # TEST 5: Invalid / non-numeric value
    def test_05_invalid_non_numeric_value(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": "INVALID_TEXT",
            "unit": "mg/dL",
            "confidence": 0.85
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["verification_status"], "invalid")
        self.assertEqual(res["result_status"], "unknown")

    # TEST 6: Unknown biomarker
    def test_06_unknown_biomarker(self):
        bm = {
            "name": "Unknown Compound XYZ",
            "normalized_name": "unknown_compound_xyz",
            "value": 42.0,
            "unit": "units",
            "confidence": 0.90
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["verification_status"], "unknown")
        self.assertEqual(res["reference_source"], "unavailable")

    # TEST 7: Missing reference range
    def test_07_missing_reference_range(self):
        # Using a custom/unregistered biomarker with no report or database range
        bm = {
            "name": "Custom Unregistered Analyte",
            "normalized_name": "custom_unregistered_analyte",
            "value": 15.0,
            "unit": "mg/dL",
            "reference_range": "",
            "confidence": 0.90
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["reference_source"], "unavailable")

    # TEST 8: Report-specific reference range priority (Report inline range takes precedence)
    def test_08_report_specific_reference_range_priority(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": 1.4,
            "unit": "mg/dL",
            "reference_range": "0.5 - 1.5 mg/dL", # Special hospital range where 1.4 is normal
            "source_text": "Serum Creatinine 1.4 mg/dL (0.5 - 1.5 mg/dL)",
            "confidence": 0.95
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["reference_source"], "report")
        self.assertEqual(res["result_status"], "within_range")

    # TEST 9: Low OCR confidence preservation (Not falsely inflated)
    def test_09_low_ocr_confidence_preservation(self):
        bm = {
            "name": "Fasting Glucose",
            "normalized_name": "fasting_glucose",
            "value": 90.0,
            "unit": "mg/dL",
            "reference_range": "70 - 99 mg/dL",
            "source_text": "Fasting Glucose 90.0 mg/dL",
            "confidence": 0.42 # Low extraction confidence
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["confidence"], 0.42, "Verification must NOT falsely inflate low OCR confidence!")

    # TEST 10: Missing/unknown unit
    def test_10_missing_unknown_unit(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": 1.0,
            "unit": "", # Missing unit
            "confidence": 0.90
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["verification_status"], "unit_missing")
        self.assertGreaterEqual(len(res["warnings"]), 1)

    # TEST 11: Multiple biomarkers batch verification
    def test_11_multiple_biomarkers_batch(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample report text")
        ctx["extracted_data"]["biomarkers"] = [
            {"name": "Serum Creatinine", "normalized_name": "creatinine", "value": 0.9, "unit": "mg/dL", "confidence": 0.95},
            {"name": "Fasting Glucose", "normalized_name": "fasting_glucose", "value": 110.0, "unit": "mg/dL", "confidence": 0.94},
            {"name": "HbA1c", "normalized_name": "hba1c", "value": 5.6, "unit": "%", "confidence": 0.96}
        ]
        res_ctx = ReportVerificationAgent.process(ctx)
        verif = res_ctx.get("verification", {})
        self.assertEqual(verif["status"], "completed")
        self.assertEqual(len(verif["biomarkers"]), 3)

    # TEST 12: Conflicting or suspicious extracted information (Biological bounds violation -> suspicious)
    def test_12_suspicious_biological_bounds_violation(self):
        bm = {
            "name": "Serum Creatinine",
            "normalized_name": "creatinine",
            "value": 9999.0, # Impossible artifact value
            "unit": "mg/dL",
            "confidence": 0.95
        }
        res = ReportVerificationAgent.verify_biomarker(bm)
        self.assertEqual(res["verification_status"], "suspicious")
        self.assertGreaterEqual(len(res["warnings"]), 1)

    # TEST 13: Invalid/empty extracted_data
    def test_13_invalid_empty_extracted_data(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="")
        ctx["extracted_data"] = {}
        res_ctx = ReportVerificationAgent.process(ctx)
        self.assertEqual(res_ctx["verification"]["status"], "invalid_input")

    # TEST 14: Verification Agent integration with pipeline context
    def test_14_pipeline_context_integration(self):
        raw_text = "Patient Name: Sarah Connor\nSerum Creatinine: 1.1 mg/dL\nFasting Glucose: 92.0 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        
        self.assertIn("verification", ctx)
        self.assertEqual(ctx["verification"]["status"], "completed")
        self.assertEqual(len(ctx["verification"]["biomarkers"]), 2)

if __name__ == "__main__":
    unittest.main()
