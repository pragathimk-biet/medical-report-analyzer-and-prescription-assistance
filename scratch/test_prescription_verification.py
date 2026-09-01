"""
===============================================================================
STEP 4: PRESCRIPTION VERIFICATION AGENT TEST SUITE
===============================================================================

Tests:
  1. Known medication in trusted registry
  2. Unknown medication (UnknownDrugXYZ -> status="unknown", review_required=True)
  3. Proposed medication from handwriting classifier
  4. Ambiguous handwriting candidate (CRITICAL SAFETY TEST: manual_review, no arbitrary selection)
  5. Unresolved medication candidate
  6. Missing medication name
  7. Missing strength (strength_unverified=True, strength remains None)
  8. Missing frequency (frequency_unverified=True, frequency remains None)
  9. Malformed dosage information (negative strength "-500 mg" -> review_required=True)
  10. Malformed frequency
  11. Patient active medication cross-check
  12. Prescription against previous lab results (2-way safety check -> hard_stop / safety alert)
  13. Existing medication against relevant new lab results
  14. Multiple medications
  15. Conflicting medication information
  16. Invalid/empty extracted_data
  17. Missing patient history
  18. Trusted registry unavailable/empty
  19. No medication information fabricated
  20. Pipeline context integration
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
from patient_history import PatientHistoryManager

class TestStep4PrescriptionVerification(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Known medication in trusted registry
    def test_01_known_medication_in_registry(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        med = ver["medications"][0]
        self.assertTrue(med["identity_verified"])
        self.assertIn(med["verification_status"], ["verified", "verified_proposed"])

    # TEST 2: Unknown medication
    def test_02_unknown_medication(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab UnknownDrugXYZ123 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertFalse(med["identity_verified"])
        self.assertEqual(med["verification_status"], "unknown")
        self.assertTrue(med["review_required"])

    # TEST 3: Proposed medication from handwriting classifier
    def test_03_proposed_medication_from_classifier(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertTrue(med["identity_verified"])

    # TEST 4: Ambiguous handwriting candidate (CRITICAL SAFETY TEST)
    def test_04_ambiguous_handwriting_candidate_safety(self):
        # Ambiguous candidate payload
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{
            "raw_name": "Tab Amoxi... 500 mg",
            "name": None,
            "proposed_name": None,
            "classification_status": "ambiguous"
        }]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertFalse(med["identity_verified"], "Ambiguous candidate must NOT be verified!")
        self.assertEqual(med["verification_status"], "manual_review")
        self.assertTrue(med["review_required"])

    # TEST 5: Unresolved medication candidate
    def test_05_unresolved_medication_candidate(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{
            "raw_name": "Tab RandomText... 500 mg",
            "name": None,
            "classification_status": "unresolved"
        }]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertFalse(med["identity_verified"])
        self.assertTrue(med["review_required"])

    # TEST 6: Missing medication name
    def test_06_missing_medication_name(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{
            "raw_name": "",
            "name": None,
            "strength": "500 mg"
        }]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertFalse(med["identity_verified"])
        self.assertEqual(med["verification_status"], "unverified")

    # TEST 7: Missing strength
    def test_07_missing_strength(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertIsNone(med["strength"], "Missing strength must remain None!")
        self.assertTrue(med["strength_unverified"])

    # TEST 8: Missing frequency
    def test_08_missing_frequency(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertIsNone(med["frequency"], "Missing frequency must remain None!")
        self.assertTrue(med["frequency_unverified"])

    # TEST 9: Malformed dosage information
    def test_09_malformed_dosage_info(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{
            "raw_name": "Tab Amoxicillin -500 mg",
            "name": "Amoxicillin",
            "strength": "-500 mg"
        }]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertTrue(med["review_required"])
        self.assertFalse(med["identity_verified"])

    # TEST 10: Malformed frequency
    def test_10_malformed_frequency(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{
            "raw_name": "Tab Amoxicillin 500 mg",
            "name": "Amoxicillin",
            "strength": "500 mg",
            "frequency": "invalid-freq-syntax"
        }]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        self.assertIn("medications", ver)

    # TEST 11: Patient active medication cross-check
    def test_11_patient_active_medication_cross_check(self):
        p_mgr = PatientHistoryManager()
        p_mgr.add_active_medication("Spironolactone", patient_name="Test Patient 11")
        
        ctx = create_pipeline_context(document_type="prescription", metadata={"patient_name": "Test Patient 11"})
        ctx["extracted_data"]["patient_info"] = {"patient_name": "Test Patient 11"}
        ctx["extracted_data"]["medications"] = [{"raw_name": "Tab Lisinopril 10 mg", "name": "Lisinopril"}]
        ctx = PrescriptionVerificationAgent.process(ctx, patient_history_mgr=p_mgr)
        
        ver = ctx.get("verification", {})
        self.assertGreaterEqual(len(ver["active_medication_checks"]), 1)

    # TEST 12: Prescription against previous lab results (2-way safety check)
    def test_12_prescription_against_previous_labs(self):
        p_mgr = PatientHistoryManager()
        # Record high potassium lab result in patient history
        p_mgr.add_lab_results([{
            "test_name": "Potassium",
            "normalized_test_name": "potassium",
            "result_value": 6.2,
            "unit": "mmol/L",
            "status": "HIGH",
            "validation_status": "VALIDATED",
            "rule_id": "RULE_POTASSIUM_HIGH"
        }], patient_name="Test Patient 12")
        
        ctx = create_pipeline_context(document_type="prescription", metadata={"patient_name": "Test Patient 12"})
        ctx["extracted_data"]["patient_info"] = {"patient_name": "Test Patient 12"}
        ctx["extracted_data"]["medications"] = [{"raw_name": "Tab Spironolactone 25 mg", "name": "Spironolactone"}]
        
        ctx = PrescriptionVerificationAgent.process(ctx, patient_history_mgr=p_mgr)
        
        ver = ctx.get("verification", {})
        self.assertGreaterEqual(len(ver["medication_lab_checks"]), 1)
        self.assertEqual(ver["overall_status"], "hard_stop")

    # TEST 13: Existing medication against relevant new lab results
    def test_13_existing_medication_against_new_labs(self):
        p_mgr = PatientHistoryManager()
        p_mgr.add_active_medication("Lisinopril", patient_name="Test Patient 13")
        alerts = p_mgr.check_new_labs_against_active_meds([
            {"parameter": "Potassium", "key": "potassium", "value": 6.5, "status": "HIGH"}
        ], patient_name="Test Patient 13")
        
        self.assertGreaterEqual(len(alerts), 1)

    # TEST 14: Multiple medications
    def test_14_multiple_medications(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [
            {"raw_name": "Tab Amoxicillin 500 mg", "name": "Amoxicillin"},
            {"raw_name": "Tab Metformin 500 mg", "name": "Metformin"}
        ]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        self.assertEqual(len(ver["medications"]), 2)

    # TEST 15: Conflicting medication information
    def test_15_conflicting_medication_information(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [
            {"raw_name": "Tab UnknownDrugABC 500 mg", "name": "UnknownDrugABC"}
        ]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        self.assertEqual(ver["overall_status"], "manual_review")

    # TEST 16: Invalid/empty extracted_data
    def test_16_invalid_empty_extracted_data(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"] = {}
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        self.assertEqual(ver["medications"], [])
        self.assertEqual(ver["overall_status"], "manual_review")

    # TEST 17: Missing patient history
    def test_17_missing_patient_history(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{"raw_name": "Tab Amoxicillin 500 mg", "name": "Amoxicillin"}]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        ver = ctx.get("verification", {})
        self.assertIn("overall_status", ver)

    # TEST 18: Trusted registry unavailable/empty
    def test_18_trusted_registry_unavailable(self):
        mock_mgr = MagicMock()
        mock_mgr.classify_medication.return_value = {"status": "UNCLASSIFIED"}
        mock_mgr.check_prescription_against_past_labs.return_value = []
        mock_mgr._get_patient_store.return_value = {}

        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{"raw_name": "Tab Amoxicillin 500 mg", "name": "Amoxicillin"}]
        ctx = PrescriptionVerificationAgent.process(ctx, patient_history_mgr=mock_mgr)
        
        ver = ctx.get("verification", {})
        med = ver["medications"][0]
        self.assertFalse(med["identity_verified"])

    # TEST 19: No medication information fabricated
    def test_19_no_medication_info_fabricated(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["extracted_data"]["medications"] = [{"raw_name": "Tab Amoxicillin", "name": "Amoxicillin"}]
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        med = ctx["verification"]["medications"][0]
        self.assertIsNone(med["strength"], "Missing strength must NOT be fabricated during verification!")
        self.assertIsNone(med["frequency"], "Missing frequency must NOT be fabricated during verification!")

    # TEST 20: Pipeline context integration
    def test_20_pipeline_context_integration(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        ctx = PrescriptionVerificationAgent.process(ctx)
        
        self.assertIn("verification", ctx)
        self.assertIn("medications", ctx["verification"])
        self.assertIn("overall_status", ctx["verification"])

if __name__ == "__main__":
    unittest.main()
