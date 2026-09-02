"""
===============================================================================
STEP 1: PRESCRIPTION FOUNDATION TEST SUITE
===============================================================================

Tests:
  1. Prescription input routes to "prescription"
  2. Medical report still routes to "medical_report"
  3. Unsupported input is handled correctly
  4. Prescription context created with mandatory 10 keys:
     document_type, raw_input, metadata, extracted_data, handwriting, verification, safety, reasoning, warnings, errors
  5. Prescription context has correct initial empty structures
  6. PrescriptionPipelineBoundary exists and is callable/prepared for future stages
  7. Existing prescription-related functionality does not crash
  8. Application starts successfully (GET /)
"""

import os
import sys
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, create_pipeline_context, PrescriptionPipelineBoundary
from patient_history import PatientHistoryManager, TRUSTED_MEDICATION_DATABASE
from app import app

class TestStep1PrescriptionFoundation(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    # TEST 1: Prescription input routes to "prescription"
    def test_01_prescription_routing(self):
        sample_text = "Rx\nTab Amoxicillin 500mg\nTake 1 tablet twice daily after meals\nDr. Smith"
        res = InputRouter.classify_document(sample_text, filename="prescription.jpg")
        self.assertEqual(res["document_type"], "prescription")

    # TEST 2: Medical report still routes to "medical_report"
    def test_02_medical_report_routing(self):
        sample_text = "LABORATORY REPORT\nSerum Creatinine: 0.9 mg/dL\nFasting Glucose: 95.0 mg/dL"
        res = InputRouter.classify_document(sample_text, filename="report.pdf")
        self.assertEqual(res["document_type"], "medical_report")

    # TEST 3: Unsupported input is handled correctly
    def test_03_unsupported_routing(self):
        res = InputRouter.classify_document("", filename="unknown.txt")
        self.assertEqual(res["document_type"], "unsupported")

    # TEST 4: Prescription context is created correctly with mandatory fields
    def test_04_prescription_context_fields(self):
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx Tab Metformin 500mg")
        required_keys = [
            "document_type", "raw_input", "metadata", "extracted_data",
            "handwriting", "verification", "safety", "reasoning",
            "warnings", "errors"
        ]
        for key in required_keys:
            self.assertIn(key, ctx, f"Key '{key}' missing from prescription context!")

    # TEST 5: Prescription context has correct initial empty structures
    def test_05_prescription_context_empty_structures(self):
        ctx = create_pipeline_context(document_type="prescription")
        self.assertEqual(ctx["document_type"], "prescription")
        self.assertEqual(ctx["extracted_data"], {})
        self.assertEqual(ctx["handwriting"], {})
        self.assertEqual(ctx["verification"], {})
        self.assertEqual(ctx["safety"], {})
        self.assertEqual(ctx["reasoning"], {})
        self.assertEqual(ctx["warnings"], [])
        self.assertEqual(ctx["errors"], [])

    # TEST 6: PrescriptionPipelineBoundary exists and is callable/prepared
    def test_06_prescription_boundary_callable(self):
        self.assertTrue(hasattr(PrescriptionPipelineBoundary, "process_prescription"))
        ctx = create_pipeline_context(document_type="prescription", raw_input="Rx Amoxicillin")
        res_ctx = PrescriptionPipelineBoundary.process_prescription(ctx)
        self.assertEqual(res_ctx["document_type"], "prescription")
        self.assertIn("handwriting", res_ctx)

    # TEST 7: Existing prescription-related functionality does not crash
    def test_07_existing_prescription_functionality(self):
        self.assertIn("spironolactone", TRUSTED_MEDICATION_DATABASE)
        
        ph = PatientHistoryManager()
        self.assertTrue(hasattr(ph, "add_active_medication"))
        self.assertTrue(hasattr(ph, "check_prescription_against_past_labs"))

    # TEST 8: Application starts successfully
    def test_08_application_starts(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
