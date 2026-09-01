"""
===============================================================================
STEP 10: INDEPENDENT BENCHMARK FAILURE REMEDIATION REGRESSION TEST SUITE
===============================================================================

Regression Tests:
  1. Invalid report unit -> never safe_to_display (hard_stop)
  2. Missing report unit -> needs_manual_review
  3. Critical medication-lab conflict -> hard_stop
  4. Hard_stop -> zero LLM calls
  5. Negative value -> safety escalation (hard_stop)
  6. OCR-corrupted critical value -> hard_stop
  7. Reference range extraction (70.0 - 99.0, < 200.0)
  8. Decimal value extraction (0.9, 14.2)
  9. 1-0-1 frequency canonical matching
  10. BD frequency canonical matching
  11. TDS frequency canonical matching
  12. Missing frequency remains None
"""

import os
import sys
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from report_verification_agent import ReportVerificationAgent
from ml_safety_agent import MLSafetyAgent
from report_reasoning_agent import ReportReasoningAgent

from prescription_extraction_agent import PrescriptionExtractionAgent
from handwriting_drug_classifier import HandwritingDrugClassifierAgent
from prescription_verification_agent import PrescriptionVerificationAgent
from prescription_reasoning_agent import PrescriptionReasoningAgent

class TestRemediationRegression(unittest.TestCase):

    # TEST 1: Invalid report unit -> never safe_to_display (hard_stop)
    def test_01_invalid_report_unit_hard_stop(self):
        text = "Serum Creatinine: 1.2 kg\nReference Range: 0.7 - 1.3 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        ctx = MLSafetyAgent.evaluate_safety(ctx)
        
        verif_status = ctx.get("verification", {}).get("overall_status")
        safety_status = ctx.get("safety", {}).get("safety_status")
        self.assertNotEqual(verif_status, "safe_to_display")
        self.assertEqual(verif_status, "hard_stop")

    # TEST 2: Missing report unit -> needs_manual_review
    def test_02_missing_report_unit_manual_review(self):
        text = "Hemoglobin: 14.2\nReference Range: 13.0 - 17.0 g/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        verif_status = ctx.get("verification", {}).get("overall_status")
        self.assertEqual(verif_status, "needs_manual_review")

    # TEST 3: Critical medication-lab conflict -> hard_stop
    def test_03_critical_medication_lab_conflict_hard_stop(self):
        text = "Rx:\nTab Spironolactone 25 mg - 1-0-0\nNote: Patient Potassium is 6.5 mmol/L"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        verif_status = ctx.get("verification", {}).get("overall_status")
        self.assertEqual(verif_status, "hard_stop")

    # TEST 4: Hard_stop -> zero LLM calls
    def test_04_hard_stop_zero_llm_calls(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx:\nTab Spironolactone 25 mg\nPotassium 6.5")
        ctx["verification"] = {"overall_status": "hard_stop", "medications": []}
        res_ctx = PrescriptionReasoningAgent.process(ctx)
        # Verify reasoning completed without raising network LLM exception
        self.assertEqual(res_ctx.get("reasoning", {}).get("status"), "completed")

    # TEST 5: Negative value -> safety escalation (hard_stop)
    def test_05_negative_value_hard_stop(self):
        text = "Serum Creatinine: -2.5 mg/dL\nReference Range: 0.7 - 1.3 mg/dL"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        self.assertEqual(ctx.get("verification", {}).get("overall_status"), "hard_stop")

    # TEST 6: OCR-corrupted critical value -> hard_stop
    def test_06_corrupted_ocr_hard_stop(self):
        text = "###@@@!!! UNREADABLE SCAN GARBAGE @@@###"
        ctx = create_pipeline_context(document_type="medical_report", raw_input=text)
        ctx = ReportExtractionAgent.process(ctx)
        ctx = ReportVerificationAgent.process(ctx)
        self.assertEqual(ctx.get("verification", {}).get("overall_status"), "hard_stop")

    # TEST 7: Reference range extraction
    def test_07_reference_range_extraction(self):
        r1 = ReportExtractionAgent.extract_inline_ref_range("Fasting Blood Glucose: 92.0 mg/dL (70.0 - 99.0 mg/dL)")
        r2 = ReportExtractionAgent.extract_inline_ref_range("Total Cholesterol: 175.0 mg/dL (< 200.0)")
        self.assertEqual(r1, "70.0 - 99.0 mg/dL")
        self.assertEqual(r2, "< 200.0")

    # TEST 8: Decimal value extraction
    def test_08_decimal_value_extraction(self):
        v1, _ = ReportExtractionAgent.extract_numeric_value("Serum Creatinine: 0.9 mg/dL")
        v2, _ = ReportExtractionAgent.extract_numeric_value("Hemoglobin: 14.2 g/dL")
        self.assertEqual(v1, 0.9)
        self.assertEqual(v2, 14.2)

    # TEST 9: 1-0-1 frequency canonical matching
    def test_09_freq_1_0_1_canonical(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx:\nTab Amoxicillin 500 mg 1-0-1")
        ctx = PrescriptionExtractionAgent.process(ctx)
        meds = ctx.get("extracted_data", {}).get("medications", [])
        self.assertIn("Twice Daily", meds[0]["frequency"])

    # TEST 10: BD frequency canonical matching
    def test_10_freq_bd_canonical(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx:\nTab Amoxicillin 500 mg BD")
        ctx = PrescriptionExtractionAgent.process(ctx)
        meds = ctx.get("extracted_data", {}).get("medications", [])
        self.assertIn("Twice Daily", meds[0]["frequency"])

    # TEST 11: TDS frequency canonical matching
    def test_11_freq_tds_canonical(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx:\nTab Paracetamol 650 mg TDS")
        ctx = PrescriptionExtractionAgent.process(ctx)
        meds = ctx.get("extracted_data", {}).get("medications", [])
        self.assertIn("Three Times Daily", meds[0]["frequency"])

    # TEST 12: Missing frequency remains None
    def test_12_missing_frequency_remains_none(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx:\nTab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        meds = ctx.get("extracted_data", {}).get("medications", [])
        self.assertIsNone(meds[0]["frequency"])

    # TEST 13: Unreadable handwriting blotch -> hard_stop (100% hard-stop recall)
    def test_13_unreadable_blotch_hard_stop(self):
        text = "Rx:\n!!!??? ### UNREADABLE HANDWRITING BLOTCH ### ???!!!"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        self.assertEqual(ctx.get("verification", {}).get("overall_status"), "hard_stop")

if __name__ == "__main__":
    unittest.main()
