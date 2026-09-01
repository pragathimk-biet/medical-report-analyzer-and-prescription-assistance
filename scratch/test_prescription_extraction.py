"""
===============================================================================
STEP 2: PRESCRIPTION EXTRACTION AGENT TEST SUITE
===============================================================================

Tests:
  1. Clear printed prescription image text
  2. Prescription PDF input
  3. Multi-page prescription PDF
  4. Multiple medications extraction
  5. Medication + strength extraction
  6. Medication + dosage form extraction
  7. Frequency schedule extraction
  8. Morning/afternoon/night schedule extraction
  9. Duration extraction
  10. Before/after food instruction extraction
  11. Patient information extraction (Name, Age, Sex, Date, Doctor)
  12. Poor-quality prescription text
  13. Low-confidence/ambiguous medication name
  14. Missing dosage information (not fabricated)
  15. Empty OCR handling
  16. Invalid/corrupted document handling
  17. Verify uncertain medication is NOT automatically resolved (name=None, candidate recorded)
  18. Pipeline context integration
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import create_pipeline_context, PrescriptionPipelineBoundary
from prescription_extraction_agent import PrescriptionExtractionAgent

class TestStep2PrescriptionExtraction(unittest.TestCase):

    def setUp(self):
        pass

    # TEST 1: Clear printed prescription image text
    def test_01_clear_printed_prescription_text(self):
        text = "Patient Name: Sarah Connor\nRx\nTab Amoxicillin 500 mg\nTake 1 tablet twice daily after meals for 7 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        ext = ctx.get("extracted_data", {})
        self.assertEqual(len(ext["medications"]), 1)
        med = ext["medications"][0]
        self.assertEqual(med["name"], "Amoxicillin")
        self.assertEqual(med["strength"], "500 mg")
        self.assertEqual(med["dosage_form"], "Tab")

    # TEST 2: Prescription PDF
    def test_02_prescription_pdf(self):
        mock_ocr = MagicMock(return_value=("Patient Name: Sarah Connor\nTab Metformin 500 mg", []))
        ctx = create_pipeline_context(document_type="prescription", raw_input="sample_rx.pdf")
        
        with unittest.mock.patch("os.path.exists", return_value=True):
            ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=mock_ocr)
        
        self.assertEqual(len(ctx["extracted_data"]["medications"]), 1)
        self.assertEqual(ctx["extracted_data"]["medications"][0]["name"], "Metformin")

    # TEST 3: Multi-page prescription PDF
    def test_03_multipage_prescription_pdf(self):
        mock_ocr = MagicMock(return_value=("Page 1:\nTab Amoxicillin 500 mg\n--- Page 2 ---\nTab Omeprazole 20 mg", []))
        ctx = create_pipeline_context(document_type="prescription", raw_input="multipage_rx.pdf")
        
        with unittest.mock.patch("os.path.exists", return_value=True):
            ctx = PrescriptionPipelineBoundary.process_prescription(ctx, ocr_extractor_func=mock_ocr)
        
        self.assertEqual(len(ctx["extracted_data"]["medications"]), 2)

    # TEST 4: Multiple medications extraction
    def test_04_multiple_medications(self):
        text = "Rx\n1. Tab Amoxicillin 500 mg 1-0-1\n2. Cap Omeprazole 20 mg 1-0-0\n3. Tab Paracetamol 650 mg as needed"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        self.assertEqual(len(ctx["extracted_data"]["medications"]), 3)

    # TEST 5: Medication + strength extraction
    def test_05_medication_strength(self):
        text = "Tab Lisinopril 10 mg once daily"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["name"], "Lisinopril")
        self.assertEqual(med["strength"], "10 mg")

    # TEST 6: Medication + dosage form extraction
    def test_06_dosage_form(self):
        text = "Cap Spironolactone 25 mg 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["dosage_form"], "Cap")

    # TEST 7: Frequency schedule extraction
    def test_07_frequency_schedule(self):
        text = "Tab Metformin 500 mg 1-0-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertIn("Twice Daily", med["frequency"])

    # TEST 8: Morning/afternoon/night schedule extraction
    def test_08_morning_afternoon_night_schedule(self):
        text = "Tab Metformin 500 mg 1-1-1"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertTrue(med["morning"])
        self.assertTrue(med["afternoon"])
        self.assertTrue(med["evening"])

    # TEST 9: Duration extraction
    def test_09_duration_extraction(self):
        text = "Tab Amoxicillin 500 mg for 5 days"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["duration"], "5 days")

    # TEST 10: Before/after food instruction extraction
    def test_10_before_after_food_instruction(self):
        text = "Tab Pantoprazole 40 mg before food"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["timing"], "Before Food")

    # TEST 11: Patient information extraction
    def test_11_patient_info_extraction(self):
        text = "Patient Name: Sarah Connor\nAge: 35 yrs\nSex: Female\nDate: 12/08/2026\nDr. John Smith\nRx Tab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        pinfo = ctx["extracted_data"]["patient_info"]
        self.assertEqual(pinfo["patient_name"], "Sarah Connor")
        self.assertEqual(pinfo["age"], 35)
        self.assertEqual(pinfo["sex"], "Female")
        self.assertEqual(pinfo["date"], "12/08/2026")
        self.assertEqual(pinfo["prescriber"], "Dr. John Smith")

    # TEST 12: Poor-quality prescription text
    def test_12_poor_quality_prescription(self):
        text = "Rx\n...blur... Tab Amox... 500 mg"
        ocr_meta = [{"line_number": 2, "raw_line": "...blur... Tab Amox... 500 mg", "confidence": 35.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        ext = ctx.get("extracted_data", {})
        self.assertEqual(len(ext["medications"]), 1)
        self.assertGreaterEqual(len(ctx["handwriting"]["candidates"]), 1)

    # TEST 13: Low-confidence/ambiguous medication name
    def test_13_low_confidence_ambiguous_drug(self):
        text = "Tab Amoxi... 500 mg"
        ocr_meta = [{"line_number": 1, "raw_line": "Tab Amoxi... 500 mg", "confidence": 40.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertIsNone(med["name"], "Ambiguous/low-confidence drug name must be None!")
        self.assertEqual(med["raw_name"], "Tab Amoxi... 500 mg")

    # TEST 14: Missing dosage information (not fabricated)
    def test_14_missing_dosage_info(self):
        text = "Tab Amoxicillin"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertEqual(med["name"], "Amoxicillin")
        self.assertIsNone(med["strength"], "Missing strength must NOT be fabricated!")
        self.assertIsNone(med["frequency"], "Missing frequency must NOT be fabricated!")

    # TEST 15: Empty OCR handling
    def test_15_empty_ocr(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="")
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        ext = ctx.get("extracted_data", {})
        self.assertEqual(ext["raw_text"], "")
        self.assertEqual(ext["medications"], [])

    # TEST 16: Invalid/corrupted document handling
    def test_16_invalid_corrupted_document(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="non_existent_rx.pdf")
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        self.assertGreaterEqual(len(ctx["warnings"]), 1)

    # TEST 17: Verify uncertain medication is NOT automatically resolved
    def test_17_uncertain_medication_not_resolved(self):
        text = "Tab Metf... 500 mg"
        ocr_meta = [{"line_number": 1, "raw_line": "Tab Metf... 500 mg", "confidence": 42.0}]
        ctx = create_pipeline_context(document_type="prescription", raw_input=text, metadata={"ocr_metadata": ocr_meta})
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        med = ctx["extracted_data"]["medications"][0]
        self.assertIsNone(med["name"])
        self.assertNotEqual(med["name"], "Metformin", "Fuzzy extraction must NOT guess 'Metformin'!")
        self.assertEqual(len(ctx["handwriting"]["candidates"]), 1)

    # TEST 18: Pipeline context integration
    def test_18_pipeline_context_integration(self):
        text = "Patient Name: Sarah Connor\nRx\nTab Amoxicillin 500 mg"
        ctx = create_pipeline_context(document_type="prescription", raw_input=text)
        ctx = PrescriptionExtractionAgent.process(ctx)
        
        self.assertIn("extracted_data", ctx)
        self.assertIn("patient_info", ctx["extracted_data"])
        self.assertIn("medications", ctx["extracted_data"])
        self.assertIn("handwriting", ctx)
        self.assertIn("candidates", ctx["handwriting"])

if __name__ == "__main__":
    unittest.main()
