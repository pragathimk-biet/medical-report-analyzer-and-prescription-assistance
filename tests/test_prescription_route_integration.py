"""
Application-Level Route Integration Tests for Prescription Workflow
===================================================================

Verifies that unauthorized historical patient record access (reads and writes)
is completely disabled across actual registered Flask routes using the framework
test client.

Tests:
1. Missing authorization -> zero history reads and zero history writes
2. Forged client fields -> zero history reads and zero history writes
3. Full 5-stage pipeline executes Step 4 and Step 4b without bypassing history block
4. Prescription-only coverage limitations survive deterministic/fallback output
5. /analyze-medicine route does not write or read historical patient stores
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Make workspace root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app, patient_history
from ddi_checker import DDInterLoader
from tests.test_ddi_checker import _make_loader_with_rows


class TestPrescriptionRouteIntegration(unittest.TestCase):
    """
    Application-level route tests exercising registered Flask endpoints:
    - POST /upload-prescription
    - POST /analyze-medicine
    """

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()

        # Build an isolated test loader with canonical records
        rows = [
            ("DDInter1", "Warfarin", "DDInter20", "Acetylsalicylic acid", "Major"),
            ("DDInter3", "Lisinopril", "DDInter4", "Spironolactone", "Moderate"),
        ]
        tmp_loader = _make_loader_with_rows(rows)
        cls.test_loader = tmp_loader

    def setUp(self):
        # Spies on patient_history methods to verify zero unauthorized calls
        self.mock_get_store = MagicMock(wraps=patient_history._get_patient_store)
        self.mock_past_labs = MagicMock(wraps=patient_history.check_prescription_against_past_labs)
        self.mock_add_rx = MagicMock(wraps=patient_history.add_prescription_record)
        self.mock_add_med = MagicMock(wraps=patient_history.add_active_medication)

    def test_missing_authorization_zero_history_reads_or_writes(self):
        """1. Missing authorization -> zero history reads and zero history writes."""
        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
             patch.object(patient_history, "add_active_medication", self.mock_add_med), \
             patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Warfarin 5mg once daily", {"confidence": 0.95})), \
             patch("ddi_checker.get_loader", return_value=self.test_loader), \
             patch("app.generate_ai_analysis", return_value="Verified prescription: Warfarin 5mg daily."):

            data = {
                "file": (io.BytesIO(b"fake_image_bytes"), "prescription_synthetic.png"),
                "patient_name": "SyntheticPatient1",
                "age": "45",
                "gender": "female",
            }
            res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()
            self.assertTrue(res_json.get("success"))

            # Assert ZERO unauthorized history reads and writes
            self.mock_get_store.assert_not_called()
            self.mock_past_labs.assert_not_called()
            self.mock_add_rx.assert_not_called()
            self.mock_add_med.assert_not_called()

            # Verify pipeline status
            ctx = res_json["pipeline_context"]
            self.assertEqual(ctx["verification"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertEqual(ctx["ddi"]["coverage"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertIn("PRESCRIPTION_ONLY", (ctx["ddi"]["coverage_completeness"], ctx["ddi"]["overall_status"]))

    def test_forged_scope_field_in_request_form_blocks_history(self):
        """2. Forged scope and client fields in form data -> rejected, zero history calls."""
        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
             patch.object(patient_history, "add_active_medication", self.mock_add_med), \
             patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Warfarin 5mg once daily", {"confidence": 0.95})), \
             patch("ddi_checker.get_loader", return_value=self.test_loader), \
             patch("app.generate_ai_analysis", return_value="Prescription analysis."):

            data = {
                "file": (io.BytesIO(b"fake_image_bytes"), "prescription_synthetic.png"),
                "patient_name": "AttackerPatient",
                "authorized_patient_scope": "VictimScope123",
                "authorized_patient_id": "VictimScope123",
            }
            res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()

            # Zero history reads and writes
            self.mock_get_store.assert_not_called()
            self.mock_past_labs.assert_not_called()
            self.mock_add_rx.assert_not_called()
            self.mock_add_med.assert_not_called()

            ctx = res_json["pipeline_context"]
            self.assertEqual(ctx["verification"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertEqual(ctx["ddi"]["coverage"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertIn("rejected", ctx["ddi"]["coverage"]["history_authorization_blocker"].lower())

    def test_full_pipeline_executes_step4_and_step4b_without_bypassing_history_block(self):
        """3. Full prescription pipeline executes Step 4 and Step 4b without bypassing history block."""
        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
             patch.object(patient_history, "add_active_medication", self.mock_add_med), \
             patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Warfarin 5mg once daily\nTab Aspirin 81mg once daily", {"confidence": 0.98})), \
             patch("ddi_checker.get_loader", return_value=self.test_loader), \
             patch("app.generate_ai_analysis", return_value="Prescription analysis text."):

            data = {
                "file": (io.BytesIO(b"fake_image_bytes"), "multi_rx_synthetic.png"),
                "patient_name": "SyntheticPatient2",
            }
            res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()
            ctx = res_json["pipeline_context"]

            # Step 2 extraction
            self.assertIn("extracted_data", ctx)
            self.assertGreaterEqual(len(ctx["extracted_data"].get("medications", [])), 1)

            # Step 4 verification executed
            self.assertIn("verification", ctx)
            self.assertEqual(ctx["verification"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertEqual(ctx["verification"]["history_scope_status"], "UNAUTHORIZED_OR_UNSCOPED")

            # Step 4b DDI executed
            self.assertIn("ddi", ctx)
            self.assertEqual(ctx["ddi"]["coverage"]["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
            self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")

            # Zero calls to history stores
            self.mock_get_store.assert_not_called()
            self.mock_past_labs.assert_not_called()

    def test_prescription_only_limitations_survive_fallback_output(self):
        """4. Prescription-only limitations survive deterministic output on LLM failure."""
        def failing_llm(*args, **kwargs):
            raise RuntimeError("Simulated external AI service offline")

        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Warfarin 5mg once daily", {"confidence": 0.95})), \
             patch("ddi_checker.get_loader", return_value=self.test_loader), \
             patch("app.generate_ai_analysis", side_effect=failing_llm):

            data = {
                "file": (io.BytesIO(b"fake_image_bytes"), "rx_fallback_synthetic.png"),
                "patient_name": "SyntheticPatient3",
            }
            res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()

            summary = res_json["analysis"]["english"]
            # Limitations must be visible in the deterministic output
            self.assertIn("PRESCRIPTION_ONLY", summary)
            self.assertIn("Prescription-only DDI coverage (PRESCRIPTION_ONLY)", summary)
            self.assertIn("Patient historical medications could not be verified or retrieved", summary)

            self.mock_get_store.assert_not_called()
            self.mock_past_labs.assert_not_called()

    def test_analyze_medicine_route_zero_history_reads_or_writes(self):
        """5. POST /analyze-medicine does not read or write historical patient records."""
        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
             patch.object(patient_history, "add_active_medication", self.mock_add_med), \
             patch("app.generate_ai_analysis", return_value="Medicine analysis for Warfarin."):

            payload = {
                "medicine": "Warfarin",
                "dosage": {"morning": 1, "evening": 0, "night": 0},
                "patient": {
                    "name": "SyntheticPatient4",
                    "age": 60,
                    "gender": "male"
                }
            }
            res = self.client.post("/analyze-medicine", json=payload)

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()
            self.assertTrue(res_json.get("success"))

            # Zero history reads and writes
            self.mock_get_store.assert_not_called()
            self.mock_past_labs.assert_not_called()
            self.mock_add_rx.assert_not_called()
            self.mock_add_med.assert_not_called()

            summary = res_json["analysis"]["english"]
            self.assertIn("Notice on Patient History", summary)

    # -----------------------------------------------------------------------
    # Requirement 5: DLTI Route-Level Acceptance Tests
    # -----------------------------------------------------------------------

    def test_dlti_5a_enabled_supported_finding_in_prescription_route(self):
        """5A. Explicitly enabled research preview with one supported finding (Prednisone + Glucose HIGH)."""
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        try:
            with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
                 patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
                 patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
                 patch.object(patient_history, "add_active_medication", self.mock_add_med), \
                 patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Prednisone 10mg once daily", {"confidence": 0.95})), \
                 patch("ddi_checker.get_loader", return_value=self.test_loader), \
                 patch("app.generate_ai_analysis", return_value="Prescription analysis explanation for Prednisone."):

                labs_payload = json.dumps([{"analyte": "glucose", "value": 180.0, "unit": "mg/dL", "status": "HIGH"}])
                data = {
                    "file": (io.BytesIO(b"fake_image_bytes"), "prednisone_rx.png"),
                    "patient_name": "SyntheticDLTI1",
                    "current_labs": labs_payload,
                }
                res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

                self.assertEqual(res.status_code, 200)
                res_json = res.get_json()
                self.assertTrue(res_json.get("success"))

                ctx = res_json["pipeline_context"]
                self.assertEqual(ctx["dlti"]["status"], "DLTI_COMPLETE")
                self.assertGreaterEqual(ctx["dlti"]["coverage"]["rules_triggered"], 1)

                summary = res_json["analysis"]["english"]
                self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", summary)
                self.assertIn("hyperglycemia", summary.lower())
                self.assertIn("Research preview — not clinically validated", summary)
        finally:
            app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = False

    def test_dlti_5b_missing_required_context_produces_insufficient_context(self):
        """5B. Missing required context (no status string) producing INSUFFICIENT_CONTEXT."""
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        try:
            with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
                 patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
                 patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
                 patch.object(patient_history, "add_active_medication", self.mock_add_med), \
                 patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Prednisone 10mg once daily", {"confidence": 0.95})), \
                 patch("ddi_checker.get_loader", return_value=self.test_loader), \
                 patch("app.generate_ai_analysis", return_value="Prescription analysis explanation for Prednisone."):

                # Lab without status field
                labs_payload = json.dumps([{"analyte": "glucose", "value": 180.0, "unit": "mg/dL"}])
                data = {
                    "file": (io.BytesIO(b"fake_image_bytes"), "prednisone_rx.png"),
                    "patient_name": "SyntheticDLTI2",
                    "current_labs": labs_payload,
                }
                res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

                self.assertEqual(res.status_code, 200)
                res_json = res.get_json()
                self.assertTrue(res_json.get("success"))

                ctx = res_json["pipeline_context"]
                self.assertGreaterEqual(ctx["dlti"]["coverage"]["rules_insufficient_context"], 1)

                summary = res_json["analysis"]["english"]
                self.assertIn("DLTI_INSUFFICIENT_CONTEXT", summary)
                self.assertIn("Insufficient Context", summary)
        finally:
            app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = False

    def test_dlti_5c_preview_disabled_by_default(self):
        """5C. Preview disabled by default (DLTI_RESEARCH_PREVIEW_ENABLED=False)."""
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = False
        with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
             patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
             patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
             patch.object(patient_history, "add_active_medication", self.mock_add_med), \
             patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Prednisone 10mg once daily", {"confidence": 0.95})), \
             patch("ddi_checker.get_loader", return_value=self.test_loader), \
             patch("app.generate_ai_analysis", return_value="Prescription analysis explanation for Prednisone."):

            labs_payload = json.dumps([{"analyte": "glucose", "value": 180.0, "unit": "mg/dL", "status": "HIGH"}])
            data = {
                "file": (io.BytesIO(b"fake_image_bytes"), "prednisone_rx.png"),
                "patient_name": "SyntheticDLTI3",
                "current_labs": labs_payload,
            }
            res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

            self.assertEqual(res.status_code, 200)
            res_json = res.get_json()
            self.assertTrue(res_json.get("success"))

            ctx = res_json["pipeline_context"]
            self.assertEqual(ctx["dlti"]["status"], "DLTI_DISABLED")

            summary = res_json["analysis"]["english"]
            self.assertIn("DLTI_DISABLED", summary)

    def test_dlti_deterministic_block_survives_llm_failure(self):
        """Confirm the deterministic DLTI block survives LLM failure and remains rendered."""
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        try:
            with patch.object(patient_history, "_get_patient_store", self.mock_get_store), \
                 patch.object(patient_history, "check_prescription_against_past_labs", self.mock_past_labs), \
                 patch.object(patient_history, "add_prescription_record", self.mock_add_rx), \
                 patch.object(patient_history, "add_active_medication", self.mock_add_med), \
                 patch("app.PerceptionExtractionAgent.extract", return_value=("Tab Prednisone 10mg once daily", {"confidence": 0.95})), \
                 patch("ddi_checker.get_loader", return_value=self.test_loader), \
                 patch("app.generate_ai_analysis", side_effect=RuntimeError("LLM generation crashed")):

                labs_payload = json.dumps([{"analyte": "glucose", "value": 180.0, "unit": "mg/dL", "status": "HIGH"}])
                data = {
                    "file": (io.BytesIO(b"fake_image_bytes"), "prednisone_rx.png"),
                    "patient_name": "SyntheticDLTI4",
                    "current_labs": labs_payload,
                }
                res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")

                self.assertEqual(res.status_code, 200)
                res_json = res.get_json()
                self.assertTrue(res_json.get("success"))

                ctx = res_json["pipeline_context"]
                self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")
                self.assertEqual(ctx["dlti"]["status"], "DLTI_COMPLETE")

                summary = res_json["analysis"]["english"]
                # Must survive LLM failure
                self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", summary)
                self.assertIn("hyperglycemia", summary.lower())
                self.assertIn("Research preview — not clinically validated", summary)
        finally:
            app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = False


if __name__ == "__main__":
    unittest.main(verbosity=2)

