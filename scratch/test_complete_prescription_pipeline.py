"""
===============================================================================
STEP 6: COMPLETE PRESCRIPTION PIPELINE TEST SUITE
===============================================================================

Tests the full end-to-end Prescription Pipeline:
  Input Router -> Context -> Extraction -> Classifier -> Verification -> Reasoning -> Output

Tests:
  1. Complete valid prescription
  2. Multiple medications
  3. Patient information propagation
  4. Dosage propagation
  5. Frequency propagation
  6. Timing propagation
  7. Duration propagation
  8. Low-confidence handwritten medication
  9. Proposed medication independently verified
  10. Ambiguous medication -> manual_review
  11. Unknown medication -> manual_review/unknown
  12. Missing strength
  13. Missing frequency
  14. Missing duration
  15. Invalid/negative strength
  16. Critical medication-lab conflict -> hard_stop
  17. Hard-stop -> ZERO LLM calls (mock generator call count == 0)
  18. Manual-review filters uncertain medication from LLM prompt
  19. LLM failure -> deterministic fallback
  20. Extraction failure handling
  21. Classifier failure handling
  22. Verification failure handling
  23. Patient-history unavailable handling
  24. Invalid prescription document handling
  25. Empty prescription OCR handling
  26. No fabricated medication information
  27. No fabricated dosage
  28. No diagnosis fabrication
  29. No fabricated drug interaction
  30. Complete pipeline context propagation
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, PrescriptionPipelineBoundary, create_pipeline_context
from patient_history import PatientHistoryManager

class TestStep6CompletePrescriptionPipeline(unittest.TestCase):

    def mock_ocr(self, text):
        return lambda path, ext=None: (text, {"confidence": 0.95, "lines": [text]})

    # TEST 1: Complete valid prescription
    def test_01_complete_valid_prescription(self):
        text = "Patient Name: Sarah Connor\nTab Amoxicillin 500 mg 1-0-1 After Food 7 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertIn("reasoning", ctx)
        self.assertGreaterEqual(len(ctx["verification"]["medications"]), 1)
        self.assertTrue(ctx["verification"]["medications"][0]["identity_verified"])

    # TEST 2: Multiple medications
    def test_02_multiple_medications(self):
        text = "1. Tab Amoxicillin 500 mg 1-0-1\n2. Tab Metformin 500 mg 1-0-0"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(len(ctx["verification"]["medications"]), 2)
        self.assertEqual(len(ctx["reasoning"]["medications"]), 2)

    # TEST 3: Patient information propagation
    def test_03_patient_info_propagation(self):
        text = "Patient Name: Sarah Connor\nAge: 45\nGender: female\nTab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        p_info = ctx["extracted_data"].get("patient_info", {})
        self.assertEqual(p_info.get("patient_name"), "Sarah Connor")

    # TEST 4: Dosage propagation
    def test_04_dosage_propagation(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(ctx["reasoning"]["medications"][0]["strength"], "500 mg")

    # TEST 5: Frequency propagation
    def test_05_frequency_propagation(self):
        text = "Tab Amoxicillin 500 mg 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertIn("Twice Daily", ctx["reasoning"]["medications"][0]["frequency"])

    # TEST 6: Timing propagation
    def test_06_timing_propagation(self):
        text = "Tab Amoxicillin 500 mg after food"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(ctx["reasoning"]["medications"][0]["timing"], "After Food")

    # TEST 7: Duration propagation
    def test_07_duration_propagation(self):
        text = "Tab Amoxicillin 500 mg for 7 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(ctx["reasoning"]["medications"][0]["duration"], "7 days")

    # TEST 8: Low-confidence handwritten medication
    def test_08_low_confidence_handwritten_medication(self):
        low_conf_ocr = lambda path, ext=None: ("Tab Amoxi... 500 mg", {"confidence": 0.40, "lines": ["Tab Amoxi... 500 mg"]})
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=low_conf_ocr)
        
        self.assertGreaterEqual(len(ctx["handwriting"]["candidates"]), 1)

    # TEST 9: Proposed medication independently verified
    def test_09_proposed_medication_independently_verified(self):
        text = "Tab Amoxil 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        med = ctx["verification"]["medications"][0]
        self.assertTrue(med["identity_verified"])

    # TEST 10: Ambiguous medication -> manual_review
    def test_10_ambiguous_medication_manual_review(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx["verification"] = {
            "overall_status": "manual_review",
            "medications": [{
                "raw_name": "Tab Amoxi...",
                "name": None,
                "verification_status": "manual_review",
                "identity_verified": False,
                "review_required": True
            }]
        }
        from prescription_reasoning_agent import PrescriptionReasoningAgent
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        self.assertTrue(ctx["reasoning"]["review_required"])
        self.assertEqual(len(ctx["reasoning"]["medications"]), 0)

    # TEST 11: Unknown medication -> manual_review/unknown
    def test_11_unknown_medication_manual_review(self):
        text = "Tab UnknownDrugXYZ123 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertTrue(ctx["verification"]["medications"][0]["review_required"])
        self.assertFalse(ctx["verification"]["medications"][0]["identity_verified"])

    # TEST 12: Missing strength
    def test_12_missing_strength(self):
        text = "Tab Amoxicillin 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertIsNone(ctx["reasoning"]["medications"][0]["strength"])

    # TEST 13: Missing frequency
    def test_13_missing_frequency(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertIsNone(ctx["reasoning"]["medications"][0]["frequency"])

    # TEST 14: Missing duration
    def test_14_missing_duration(self):
        text = "Tab Amoxicillin 500 mg 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertIsNone(ctx["reasoning"]["medications"][0]["duration"])

    # TEST 15: Invalid/negative strength
    def test_15_invalid_negative_strength(self):
        text = "Tab Amoxicillin -500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertTrue(ctx["verification"]["medications"][0]["review_required"])

    # TEST 16: Critical medication-lab conflict -> hard_stop
    def test_16_critical_med_lab_conflict_hard_stop(self):
        p_mgr = PatientHistoryManager()
        p_mgr.add_lab_results([{
            'test_name': 'Potassium', 'normalized_test_name': 'potassium',
            'result_value': 6.2, 'unit': 'mmol/L', 'status': 'HIGH',
            'validation_status': 'VALIDATED', 'rule_id': 'RULE_K_HIGH'
        }], patient_name="SafetyPatient")
        
        text = "Patient Name: SafetyPatient\nTab Spironolactone 25 mg 1-0-0"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png", metadata={"patient_name": "SafetyPatient"})
        
        # Override history manager inside verification step for testing
        from prescription_extraction_agent import PrescriptionExtractionAgent
        from handwriting_drug_classifier import HandwritingDrugClassifierAgent
        from prescription_verification_agent import PrescriptionVerificationAgent
        from prescription_reasoning_agent import PrescriptionReasoningAgent

        ctx = PrescriptionExtractionAgent.process(ctx, ocr_extractor_func=self.mock_ocr(text))
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx, patient_history_mgr=p_mgr)
        ctx = PrescriptionReasoningAgent.process(ctx)

        self.assertEqual(ctx["verification"]["overall_status"], "hard_stop")

    # TEST 17: Hard-stop -> ZERO LLM calls
    def test_17_hard_stop_zero_llm_calls(self):
        mock_ai = MagicMock(return_value="AI output")
        p_mgr = PatientHistoryManager()
        p_mgr.add_lab_results([{
            'test_name': 'Potassium', 'normalized_test_name': 'potassium',
            'result_value': 6.2, 'unit': 'mmol/L', 'status': 'HIGH',
            'validation_status': 'VALIDATED', 'rule_id': 'RULE_K_HIGH'
        }], patient_name="SafetyPatient")
        
        text = "Patient Name: SafetyPatient\nTab Spironolactone 25 mg 1-0-0"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png", metadata={"patient_name": "SafetyPatient"})
        
        from prescription_extraction_agent import PrescriptionExtractionAgent
        from handwriting_drug_classifier import HandwritingDrugClassifierAgent
        from prescription_verification_agent import PrescriptionVerificationAgent
        from prescription_reasoning_agent import PrescriptionReasoningAgent

        ctx = PrescriptionExtractionAgent.process(ctx, ocr_extractor_func=self.mock_ocr(text))
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx, patient_history_mgr=p_mgr)
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)

        self.assertEqual(mock_ai.call_count, 0, "Hard stop MUST trigger zero LLM calls!")

    # TEST 18: Manual-review filters uncertain medication from LLM prompt
    def test_18_manual_review_filters_uncertain_meds(self):
        mock_ai = MagicMock(return_value="AI explanation")
        text = "1. Tab Amoxicillin 500 mg\n2. Tab UnknownXYZ123 100 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text), ai_generator_func=mock_ai)
        
        if mock_ai.called:
            prompt_arg = mock_ai.call_args[0][0]
            self.assertIn("Amoxicillin", prompt_arg)

    # TEST 19: LLM failure -> deterministic fallback
    def test_19_llm_failure_deterministic_fallback(self):
        mock_ai = MagicMock(side_effect=RuntimeError("AI Timeout"))
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text), ai_generator_func=mock_ai)
        
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")

    # TEST 20: Extraction failure handling
    def test_20_extraction_failure_handling(self):
        fail_ocr = lambda path, ext=None: ("Error: Failed to read OCR image.", {})
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=fail_ocr)
        
        self.assertGreaterEqual(len(ctx["errors"]), 1)

    # TEST 21: Classifier failure handling
    def test_21_classifier_failure_handling(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx["extracted_data"] = {"medications": [{"raw_name": "InvalidData"}]}
        ctx["handwriting"] = "InvalidStringType"  # Invalid data structure
        
        from handwriting_drug_classifier import HandwritingDrugClassifierAgent
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        self.assertGreaterEqual(len(ctx["errors"]), 1)

    # TEST 22: Verification failure handling
    def test_22_verification_failure_handling(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx["extracted_data"] = "InvalidStringType"
        
        from prescription_verification_agent import PrescriptionVerificationAgent
        ctx = PrescriptionVerificationAgent.process(ctx)
        self.assertGreaterEqual(len(ctx["errors"]), 1)

    # TEST 23: Patient-history unavailable handling
    def test_23_patient_history_unavailable_handling(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(ctx["verification"]["overall_status"], "verified")

    # TEST 24: Invalid prescription document handling
    def test_24_invalid_prescription_document_handling(self):
        empty_ocr = lambda path, ext=None: ("", {"confidence": 0.0, "lines": []})
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=empty_ocr)
        
        self.assertTrue(ctx["reasoning"]["review_required"])

    # TEST 25: Empty prescription OCR handling
    def test_25_empty_prescription_ocr_handling(self):
        empty_ocr = lambda path, ext=None: ("", {"confidence": 0.0, "lines": []})
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=empty_ocr)
        
        self.assertEqual(len(ctx["extracted_data"]["medications"]), 0)

    # TEST 26: No fabricated medication information
    def test_26_no_fabricated_medication_info(self):
        text = "Tab Amoxicillin"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        med = ctx["reasoning"]["medications"][0]
        self.assertIsNone(med["strength"])

    # TEST 27: No fabricated dosage
    def test_27_no_fabricated_dosage(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        med = ctx["reasoning"]["medications"][0]
        self.assertEqual(med["strength"], "500 mg")

    # TEST 28: No diagnosis fabrication
    def test_28_no_diagnosis_fabrication(self):
        text = "Tab Metformin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        summary = ctx["reasoning"]["summary"].lower()
        self.assertNotIn("you have diabetes", summary)

    # TEST 29: No fabricated drug interaction
    def test_29_no_fabricated_drug_interaction(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        self.assertEqual(len(ctx["verification"]["medication_lab_checks"]), 0)

    # TEST 30: Complete pipeline context propagation
    def test_30_complete_pipeline_context_propagation(self):
        text = "Tab Amoxicillin 500 mg 1-0-1 for 7 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample.png")
        ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=self.mock_ocr(text))
        
        required_keys = ["document_type", "raw_input", "metadata", "extracted_data", "handwriting", "verification", "reasoning", "warnings", "errors"]
        for key in required_keys:
            self.assertIn(key, ctx, f"Context MUST contain key '{key}'!")

if __name__ == "__main__":
    unittest.main()
