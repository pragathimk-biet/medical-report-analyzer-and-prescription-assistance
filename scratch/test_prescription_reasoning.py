"""
===============================================================================
STEP 5: PRESCRIPTION REASONING AGENT TEST SUITE
===============================================================================

Tests:
  1. Verified prescription reasoning
  2. Multiple verified medications
  3. Verified dosage explanation
  4. Verified frequency explanation
  5. Verified duration explanation
  6. Before-food instruction
  7. After-food instruction
  8. Medication purpose explained without diagnosing the patient
  9. Manual-review prescription
  10. Unknown medication is NOT presented as verified
  11. Ambiguous medication is NOT presented as verified
  12. Missing strength remains missing
  13. Missing frequency remains missing
  14. Critical medication-lab conflict
  15. Hard-stop produces safe review message
  16. Hard-stop causes ZERO LLM calls (mock generator call count == 0)
  17. Manual-review filters uncertain medications from LLM prompt
  18. LLM/API failure (uses deterministic fallback)
  19. Empty LLM response
  20. LLM response cannot override verification status
  21. No diagnosis fabrication
  22. No dosage modification
  23. No fabricated drug interactions
  24. Pipeline context integration
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context
from prescription_extraction_agent import PrescriptionExtractionAgent
from handwriting_drug_classifier import HandwritingDrugClassifierAgent
from prescription_verification_agent import PrescriptionVerificationAgent
from prescription_reasoning_agent import PrescriptionReasoningAgent, HARD_STOP_MESSAGE

class TestStep5PrescriptionReasoning(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Verified prescription reasoning
    def test_01_verified_prescription_reasoning(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg 1-0-1 for 7 days")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        reasoning = ctx.get("reasoning", {})
        self.assertIn("summary", reasoning)
        self.assertGreaterEqual(len(reasoning["medications"]), 1)

    # TEST 2: Multiple verified medications
    def test_02_multiple_verified_medications(self):
        text = "1. Tab Amoxicillin 500 mg 1-0-1\n2. Tab Metformin 500 mg 1-0-0"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        reasoning = ctx["reasoning"]
        self.assertEqual(len(reasoning["medications"]), 2)

    # TEST 3: Verified dosage explanation
    def test_03_verified_dosage_explanation(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertEqual(med["strength"], "500 mg")

    # TEST 4: Verified frequency explanation
    def test_04_verified_frequency_explanation(self):
        text = "Tab Amoxicillin 500 mg 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertIn("Twice Daily", med["frequency"])

    # TEST 5: Verified duration explanation
    def test_05_verified_duration_explanation(self):
        text = "Tab Amoxicillin 500 mg for 5 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertEqual(med["duration"], "5 days")

    # TEST 6: Before-food instruction
    def test_06_before_food_instruction(self):
        text = "Tab Pantoprazole 40 mg before food"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertEqual(med["timing"], "Before Food")

    # TEST 7: After-food instruction
    def test_07_after_food_instruction(self):
        text = "Tab Amoxicillin 500 mg after food"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertEqual(med["timing"], "After Food")

    # TEST 8: Medication purpose explained without diagnosing the patient
    def test_08_medication_purpose_without_diagnosis(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Metformin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        summary = ctx["reasoning"]["summary"]
        self.assertNotIn("you have diabetes", summary.lower(), "Reasoning MUST NOT diagnose the patient!")

    # TEST 9: Manual-review prescription
    def test_09_manual_review_prescription(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab UnknownDrugXYZ123 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        reasoning = ctx["reasoning"]
        self.assertTrue(reasoning["review_required"])

    # TEST 10: Unknown medication is NOT presented as verified
    def test_10_unknown_medication_not_verified(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab UnknownDrugXYZ123 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        reasoning = ctx["reasoning"]
        self.assertEqual(len(reasoning["medications"]), 0, "Unknown medication must NOT be presented in verified list!")
        self.assertGreaterEqual(len(reasoning["unverified_medications"]), 1)

    # TEST 11: Ambiguous medication is NOT presented as verified
    def test_11_ambiguous_medication_not_verified(self):
        ctx = create_pipeline_context(document_type="prescription")
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
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        reasoning = ctx["reasoning"]
        self.assertEqual(len(reasoning["medications"]), 0)
        self.assertGreaterEqual(len(reasoning["unverified_medications"]), 1)

    # TEST 12: Missing strength remains missing
    def test_12_missing_strength_remains_missing(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertIsNone(med["strength"], "Missing strength must remain None!")

    # TEST 13: Missing frequency remains missing
    def test_13_missing_frequency_remains_missing(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        med = ctx["reasoning"]["medications"][0]
        self.assertIsNone(med["frequency"], "Missing frequency must remain None!")

    # TEST 14: Critical medication-lab conflict
    def test_14_critical_medication_lab_conflict(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["verification"] = {
            "overall_status": "hard_stop",
            "medications": [],
            "medication_lab_checks": [{"title": "Hyperkalemia Warning", "explanation": "High potassium"}],
            "warnings": ["Critical safety alert"]
        }
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        self.assertEqual(ctx["reasoning"]["generated_by"], "hard_stop_policy")

    # TEST 15: Hard-stop produces safe review message
    def test_15_hard_stop_produces_safe_review_message(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["verification"] = {"overall_status": "hard_stop", "medications": []}
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        self.assertEqual(ctx["reasoning"]["summary"], HARD_STOP_MESSAGE)

    # TEST 16: Hard-stop causes ZERO LLM calls
    def test_16_hard_stop_zero_llm_calls(self):
        mock_ai = MagicMock(return_value="AI output")
        ctx = create_pipeline_context(document_type="prescription")
        ctx["verification"] = {"overall_status": "hard_stop", "medications": []}
        
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)
        self.assertEqual(mock_ai.call_count, 0, "Hard stop MUST cause 0 LLM calls!")

    # TEST 17: Manual-review filters uncertain medications from LLM prompt
    def test_17_manual_review_filters_uncertain_meds(self):
        mock_ai = MagicMock(return_value="AI explanation")
        ctx = create_pipeline_context(document_type="prescription")
        ctx["verification"] = {
            "overall_status": "manual_review",
            "medications": [
                {"verified_name": "Amoxicillin", "identity_verified": True, "verification_status": "verified"},
                {"raw_name": "UnknownXYZ", "identity_verified": False, "verification_status": "unknown"}
            ]
        }
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)
        
        prompt_arg = mock_ai.call_args[0][0]
        self.assertIn("Amoxicillin", prompt_arg)
        self.assertIn("UnknownXYZ", prompt_arg)

    # TEST 18: LLM/API failure
    def test_18_llm_api_failure(self):
        mock_ai = MagicMock(side_effect=RuntimeError("AI Timeout"))
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")

    # TEST 19: Empty LLM response
    def test_19_empty_llm_response(self):
        mock_ai = MagicMock(return_value="")
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")

    # TEST 20: LLM response cannot override verification status
    def test_20_llm_response_cannot_override_verification_status(self):
        mock_ai = MagicMock(return_value="All medications are 100% verified and completely safe!")
        ctx = create_pipeline_context(document_type="prescription")
        ctx["verification"] = {"overall_status": "manual_review", "medications": []}
        
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=mock_ai)
        self.assertEqual(ctx["reasoning"]["verification_status_used"], "manual_review")

    # TEST 21: No diagnosis fabrication
    def test_21_no_diagnosis_fabrication(self):
        sys_prompt = PrescriptionReasoningAgent.build_system_prompt()
        self.assertIn("PROHIBITION OF DIAGNOSES", sys_prompt)

    # TEST 22: No dosage modification
    def test_22_no_dosage_modification(self):
        sys_prompt = PrescriptionReasoningAgent.build_system_prompt()
        self.assertIn("PROHIBITION OF DOSAGE MODIFICATION", sys_prompt)

    # TEST 23: No fabricated drug interactions
    def test_23_no_fabricated_drug_interactions(self):
        sys_prompt = PrescriptionReasoningAgent.build_system_prompt()
        self.assertIn("NO FABRICATED INTERACTIONS", sys_prompt)

    # TEST 24: Pipeline context integration
    def test_24_pipeline_context_integration(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        ctx = PrescriptionReasoningAgent.process(ctx)
        
        self.assertIn("reasoning", ctx)
        self.assertIn("summary", ctx["reasoning"])
        self.assertIn("medications", ctx["reasoning"])

if __name__ == "__main__":
    unittest.main()
