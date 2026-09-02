"""
===============================================================================
STEP 3: HANDWRITING DRUG CLASSIFIER AGENT TEST SUITE
===============================================================================

Tests:
  1. Clear high-confidence medication candidate
  2. Low-confidence medication text
  3. Truncated medication name ("Amoxi...")
  4. Single strong fuzzy candidate
  5. Multiple possible candidates
  6. Ambiguous candidates with similar scores (SAFETY TEST: no arbitrary selection)
  7. No candidate in trusted medication database
  8. OCR typo ("Amoxcillin" -> "Amoxicillin")
  9. Prefix similarity
  10. Token similarity
  11. Strength consistency when strength is available
  12. Dosage-form consistency when available
  13. Low OCR confidence forces review/unresolved behavior
  14. Verify candidate is NOT marked as medically verified (status is "proposed")
  15. Verify raw OCR text is preserved
  16. Verify no medication information is fabricated
  17. Empty candidate list
  18. Malformed handwriting input
  19. Pipeline context integration
  20. Existing high-confidence medication is preserved
"""

import os
import sys
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context
from prescription_extraction_agent import PrescriptionExtractionAgent
from handwriting_drug_classifier import HandwritingDrugClassifierAgent

class TestStep3HandwritingDrugClassifier(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Clear high-confidence medication candidate
    def test_01_clear_high_confidence_candidate(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Tab Amoxicillin 500 mg")
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["name"], "Amoxicillin")

    # TEST 2: Low-confidence medication text
    def test_02_low_confidence_medication_text(self):
        text = "Tab Amoxi... 500 mg"
        ocr_meta = [{"line_number": 1, "raw_line": "Tab Amoxi... 500 mg", "confidence": 40.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        hw = ctx.get("handwriting", {})
        self.assertGreaterEqual(len(hw["candidates"]), 1)

    # TEST 3: Truncated medication name ("Amoxi...")
    def test_03_truncated_medication_name(self):
        text = "Tab Amoxi... 500 mg"
        ocr_meta = [{"line_number": 1, "raw_line": "Tab Amoxi... 500 mg", "confidence": 40.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        cand = ctx["handwriting"]["candidates"][0]
        self.assertIn("Amoxicillin", [c["name"] for c in cand["ranked_candidates"]])

    # TEST 4: Single strong fuzzy candidate
    def test_04_single_strong_fuzzy_candidate(self):
        text = "Tab Metformin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        cand = ctx["handwriting"]["candidates"][0]
        self.assertEqual(cand["selected_candidate"], "Metformin")
        self.assertEqual(cand["classification_status"], "proposed")

    # TEST 5: Multiple possible candidates
    def test_05_multiple_possible_candidates(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Amoxi")
        self.assertGreaterEqual(len(ranked), 2)

    # TEST 6: Ambiguous candidates with similar scores (SAFETY TEST: no arbitrary selection)
    def test_06_ambiguous_candidates_safety(self):
        # "Amoxi" could be Amoxicillin, Amoxil, or Amoxiclav with close scores
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Amoxi")
        if len(ranked) > 1 and (ranked[0]["score"] - ranked[1]["score"]) < 0.10:
            self.assertIsNone(selected, "Arbitrary selection must NOT occur when scores are ambiguous!")
            self.assertEqual(status, "ambiguous")

    # TEST 7: No candidate in trusted medication database
    def test_07_no_candidate_in_database(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("UnknownDrugXYZ123")
        self.assertEqual(status, "unresolved")
        self.assertIsNone(selected)

    # TEST 8: OCR typo ("Amoxcillin" -> "Amoxicillin")
    def test_08_ocr_typo(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Amoxcillin")
        self.assertEqual(selected, "Amoxicillin")

    # TEST 9: Prefix similarity
    def test_09_prefix_similarity(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Lisinopr")
        self.assertEqual(selected, "Lisinopril")

    # TEST 10: Token similarity
    def test_10_token_similarity(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Tab Spironolact")
        self.assertEqual(selected, "Spironolactone")

    # TEST 11: Strength consistency when available
    def test_11_strength_consistency(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Pantopraz", strength="40 mg")
        self.assertEqual(selected, "Pantoprazole")

    # TEST 12: Dosage-form consistency when available
    def test_12_dosage_form_consistency(self):
        ranked, selected, status, conf = HandwritingDrugClassifierAgent.rank_candidates("Omepraz", dosage_form="Cap")
        self.assertEqual(selected, "Omeprazole")

    # TEST 13: Low OCR confidence forces review/unresolved behavior
    def test_13_low_ocr_confidence_review(self):
        text = "Tab Amoxi... 500 mg"
        ocr_meta = [{"line_number": 1, "raw_line": "Tab Amoxi... 500 mg", "confidence": 30.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        cand = ctx["handwriting"]["candidates"][0]
        self.assertIn(cand["classification_status"], ["ambiguous", "unresolved", "manual_review"])

    # TEST 14: Verify candidate is NOT marked as medically verified
    def test_14_candidate_not_marked_medically_verified(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        cand = ctx["handwriting"]["candidates"][0]
        self.assertNotEqual(cand["classification_status"], "medically_verified")
        self.assertIn(cand["classification_status"], ["proposed", "ambiguous", "unresolved"])

    # TEST 15: Verify raw OCR text is preserved
    def test_15_raw_ocr_text_preserved(self):
        text = "Tab Amoxi... 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        cand = ctx["handwriting"]["candidates"][0]
        self.assertEqual(cand["raw_text"], "Tab Amoxi... 500 mg")

    # TEST 16: Verify no medication information is fabricated
    def test_16_no_information_fabricated(self):
        text = "Tab Amoxi..."
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertIsNone(med["strength"], "Missing strength must NOT be fabricated by classifier!")

    # TEST 17: Empty candidate list
    def test_17_empty_candidate_list(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["handwriting"] = {"candidates": []}
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        self.assertEqual(ctx["handwriting"]["candidates"], [])

    # TEST 18: Malformed handwriting input
    def test_18_malformed_handwriting_input(self):
        ctx = create_pipeline_context(document_type="prescription")
        ctx["handwriting"] = {"candidates": ["invalid_string_instead_of_dict"]}
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        self.assertEqual(len(ctx["handwriting"]["candidates"]), 0)

    # TEST 19: Pipeline context integration
    def test_19_pipeline_context_integration(self):
        text = "Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        self.assertIn("handwriting", ctx)
        self.assertIn("candidates", ctx["handwriting"])
        self.assertGreaterEqual(len(ctx["handwriting"]["candidates"]), 1)

    # TEST 20: Existing high-confidence medication is preserved
    def test_20_existing_high_confidence_medication_preserved(self):
        text = "Tab Metformin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        ctx = HandwritingDrugClassifierAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["name"], "Metformin")

if __name__ == "__main__":
    unittest.main()
