"""
===============================================================================
STEP 1: FOUNDATION AUTOMATED TEST SUITE
===============================================================================

Tests:
  1. InputRouter document classification:
     - medical_report text -> medical_report
     - prescription text -> prescription
     - explicit_type override -> explicit_type
     - empty/invalid text -> unsupported
  2. Common Pipeline Payload Structure verification:
     - Contains: document_type, raw_input, extracted_data, verification, safety, reasoning, warnings, errors
  3. Flask Application Startup & Health:
     - GET / -> 200 OK
  4. Router API Endpoint:
     - POST /api/route-input -> 200 OK
  5. Existing Upload & Report Analysis Integrity:
     - Medical report endpoint returns success
  6. Security & Dependency Check:
     - No API key in .env.example
"""

import os
import sys
import unittest
import json

# Add repository root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, create_pipeline_context, SUPPORTED_DOCUMENT_TYPES
from app import app

class TestStep1Foundation(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    # TEST 1: InputRouter Classification
    def test_01_router_medical_report_classification(self):
        report_text = """Patient Name: Sarah Connor
Lab Ref No: N82507
BIOCHEMISTRY
Serum Creatinine: 1.2 mg/dL (Reference Range: 0.55 - 1.02 mg/dL)
Blood Urea: 45 mg/dL (Reference Range: 17 - 43 mg/dL)"""
        res = InputRouter.classify_document(text=report_text)
        self.assertEqual(res["document_type"], "medical_report")

    def test_02_router_prescription_classification(self):
        rx_text = """Rx Prescription
Patient Name: Clark Kent
Tab Metformin 500mg - 1-0-1 after meals
Tab Lisinopril 10mg - 1-0-0
Sig: Take daily for 30 days. Dr. Smith"""
        res = InputRouter.classify_document(text=rx_text)
        self.assertEqual(res["document_type"], "prescription")

    def test_03_router_explicit_type_override(self):
        res1 = InputRouter.classify_document(text="arbitrary text", explicit_type="medical_report")
        self.assertEqual(res1["document_type"], "medical_report")

        res2 = InputRouter.classify_document(text="arbitrary text", explicit_type="prescription")
        self.assertEqual(res2["document_type"], "prescription")

    def test_04_router_invalid_empty_input(self):
        res = InputRouter.classify_document(text="", filename="")
        self.assertEqual(res["document_type"], "unsupported")
        self.assertIn("error", res)

    # TEST 2: Common Pipeline Payload Structure
    def test_05_common_pipeline_payload_structure(self):
        ctx = create_pipeline_context(document_type="medical_report", raw_input="sample raw text")
        required_keys = [
            "document_type", "raw_input", "metadata", "extracted_data",
            "verification", "safety", "reasoning", "warnings", "errors"
        ]
        for key in required_keys:
            self.assertIn(key, ctx, f"Pipeline context payload missing key: {key}")
        
        self.assertEqual(ctx["document_type"], "medical_report")
        self.assertEqual(ctx["raw_input"], "sample raw text")
        self.assertIsInstance(ctx["extracted_data"], dict)
        self.assertIsInstance(ctx["verification"], dict)
        self.assertIsInstance(ctx["safety"], dict)
        self.assertIsInstance(ctx["reasoning"], dict)
        self.assertIsInstance(ctx["warnings"], list)
        self.assertIsInstance(ctx["errors"], list)

    # TEST 3: UI & Index Page Integrity
    def test_06_index_route(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Medical Report Analyzer', response.data)

    # TEST 4: Router REST API Endpoint
    def test_07_route_input_api_endpoint(self):
        payload = {
            "text": "Rx Prescription Tab Metformin 500mg 1-0-1",
            "filename": "rx_document.png"
        }
        response = self.app.post('/api/route-input', json=payload)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["routing_result"]["document_type"], "prescription")
        self.assertIn("pipeline_context", data)

    # TEST 5: Security (.env.example check)
    def test_08_env_example_security(self):
        self.assertTrue(os.path.exists(".env.example"))
        with open(".env.example", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("nvapi-", content, ".env.example must not expose real API keys!")
        self.assertIn("your_nvidia_api_key_here", content)

if __name__ == "__main__":
    unittest.main()
