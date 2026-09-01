"""
===============================================================================
STEP 2: REPORT EXTRACTION AGENT TEST SUITE
===============================================================================

Tests:
  1. Clear medical report image
  2. Clear medical report PDF
  3. Multi-page / multi-line medical report
  4. Multiple biomarkers extraction
  5. Missing laboratory value (value: None, warning recorded)
  6. Poor-quality image / low OCR confidence scenario
  7. OCR ambiguity / no hallucination of values
  8. Invalid / unsupported file handling
  9. Empty OCR result
  10. Full integration with pipeline_context and app routes
"""

import os
import sys
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from app import app, extract_text_from_image, extract_text_from_pdf

class TestStep2ReportExtraction(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    # TEST 1: Clear medical report image text
    def test_01_clear_medical_report_image(self):
        raw_text = """Patient Name: Sarah Connor
Serum Creatinine: 1.2 mg/dL (Reference Range: 0.7 - 1.3 mg/dL)
Fasting Glucose: 95.0 mg/dL (Reference Range: 70 - 99 mg/dL)"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text, metadata={"filename": "report.png"})
        res_ctx = ReportExtractionAgent.process(ctx)
        
        extracted = res_ctx.get("extracted_data", {})
        self.assertEqual(extracted["raw_text"], raw_text)
        self.assertIn("biomarkers", extracted)
        self.assertGreaterEqual(len(extracted["biomarkers"]), 2)
        
        bm_map = {b["normalized_name"]: b for b in extracted["biomarkers"]}
        self.assertIn("creatinine", bm_map)
        self.assertEqual(bm_map["creatinine"]["value"], 1.2)
        self.assertEqual(bm_map["creatinine"]["unit"], "mg/dL")

    # TEST 2: Clear medical report PDF text
    def test_02_clear_medical_report_pdf(self):
        raw_text = """Patient Name: John Watson
Hemoglobin: 14.5 g/dL
Blood Urea: 30.0 mg/dL"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text, metadata={"filename": "report.pdf"})
        res_ctx = ReportExtractionAgent.process(ctx)
        
        extracted = res_ctx.get("extracted_data", {})
        self.assertEqual(extracted["report_metadata"]["file_type"], "pdf")
        self.assertEqual(len(extracted["biomarkers"]), 2)

    # TEST 3: Multi-page / multi-line medical report
    def test_03_multipage_medical_report(self):
        raw_text = """Page 1:
Patient Name: Bruce Wayne
Serum Creatinine: 1.0 mg/dL
Fasting Glucose: 90.0 mg/dL

Page 2:
HbA1c: 5.6 %
ALT: 25.0 U/L
AST: 28.0 U/L"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text, metadata={"filename": "multipage_report.pdf"})
        res_ctx = ReportExtractionAgent.process(ctx)
        
        extracted = res_ctx.get("extracted_data", {})
        self.assertGreaterEqual(len(extracted["biomarkers"]), 5)

    # TEST 4: Multiple biomarkers extraction
    def test_04_multiple_biomarkers(self):
        raw_text = """Serum Creatinine: 1.1 mg/dL
Fasting Glucose: 105.0 mg/dL
HbA1c: 6.2 %
Hemoglobin: 13.8 g/dL
Blood Urea: 28.0 mg/dL
ALT: 32.0 U/L
AST: 24.0 U/L
Serum Sodium: 140.0 mmol/L
Serum Potassium: 4.2 mmol/L"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        res_ctx = ReportExtractionAgent.process(ctx)
        
        biomarkers = res_ctx["extracted_data"]["biomarkers"]
        self.assertGreaterEqual(len(biomarkers), 9)

    # TEST 5: Missing laboratory value (Must NOT invent value; value should be None)
    def test_05_missing_laboratory_value(self):
        raw_text = """Patient Name: Alice Smith
Serum Creatinine: mg/dL (Reference Range: 0.7 - 1.3 mg/dL)"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        res_ctx = ReportExtractionAgent.process(ctx)
        
        biomarkers = res_ctx["extracted_data"]["biomarkers"]
        self.assertEqual(len(biomarkers), 1)
        self.assertIsNone(biomarkers[0]["value"])
        self.assertIsNotNone(biomarkers[0]["warning"])

    # TEST 6: Poor-quality image / low OCR confidence scenario
    def test_06_low_ocr_confidence_scenario(self):
        raw_text = """Serum Creatinine: 1.2 mg/dL"""
        ocr_meta = [{"line_number": 1, "raw_line": "Serum Creatinine: 1.2 mg/dL", "confidence": 35.0}] # 35% low conf
        ctx = create_pipeline_context(
            document_type="medical_report",
            raw_input=raw_text,
            metadata={"ocr_metadata": ocr_meta}
        )
        res_ctx = ReportExtractionAgent.process(ctx)
        
        biomarkers = res_ctx["extracted_data"]["biomarkers"]
        self.assertEqual(len(biomarkers), 1)
        self.assertIsNotNone(biomarkers[0]["warning"])

    # TEST 7: OCR ambiguity (No hallucinated value)
    def test_07_ocr_ambiguity(self):
        raw_text = """Serum Creatinine: -- mg/dL"""
        ctx = create_pipeline_context(document_type="medical_report", raw_input=raw_text)
        res_ctx = ReportExtractionAgent.process(ctx)
        
        biomarkers = res_ctx["extracted_data"]["biomarkers"]
        self.assertEqual(len(biomarkers), 1)
        self.assertIsNone(biomarkers[0]["value"])

    # TEST 8: Invalid / unsupported file handling (No crash)
    def test_08_invalid_unsupported_file_handling(self):
        res_text, ocr_meta = extract_text_from_image("non_existent_file.png")
        self.assertTrue(res_text.startswith("Error:"))
        
        ctx = create_pipeline_context(document_type="unsupported", raw_input=res_text)
        res_ctx = ReportExtractionAgent.process(ctx)
        self.assertIn("warnings", res_ctx["extracted_data"])

    # TEST 9: Empty OCR result
    def test_09_empty_ocr_result(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="")
        res_ctx = ReportExtractionAgent.process(ctx)
        
        extracted = res_ctx["extracted_data"]
        self.assertEqual(len(extracted["biomarkers"]), 0)
        self.assertEqual(extracted["confidence"], 0.0)
        self.assertGreaterEqual(len(extracted["warnings"]), 1)

    # TEST 10: App REST endpoint integration
    def test_10_app_endpoint_integration(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
