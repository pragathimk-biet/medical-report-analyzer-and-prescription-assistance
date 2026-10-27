"""
Regression Tests for Case B Laboratory Input Flow, Glucose Concept Mapping, and DLTI Evaluation
================================================================================================

Verifies:
1. Glucose Concept Mapping & Provenance Integrity:
   - MBG_HIGH_001 represents chronic HbA1c-derived estimated average glucose (eAG),
     NOT point-in-time acute laboratory glucose.
   - Generic "Glucose" without explicit eAG markers NEVER maps to MBG_HIGH_001.
   - Generic "Glucose" with timing_context="fasting" maps to fasting_glucose
     (FASTING_GLUCOSE_DIABETES_RANGE_001, source "ADA 2024 Standards of Care", status DIABETES_RANGE).
   - Generic "Glucose" with timing_context="random" maps to random_glucose
     (RANDOM_GLUCOSE_BELOW_THRESH_001, status BELOW_DIABETIC_THRESHOLD for 180 mg/dL).
   - Generic "Glucose" without timing context (or "unspecified") returns INSUFFICIENT_CONTEXT
     (GLUCOSE_TIMING_CONTEXT_REQUIRED); does not guess or force HIGH.
2. Full HTTP POST /upload-prescription with Prednisone PDF + Fasting Glucose 180 mg/dL:
   - Rule engine verifies 180 mg/dL as DIABETES_RANGE status under FASTING_GLUCOSE_DIABETES_RANGE_001.
   - DLTI evaluator triggers DLTI_PD_PREDNISONE_GLUCOSE_V1.
   - Input provenance table is retained in structured output and summary.
   - Direct PDF export successfully converts the analysis.
3. DLTI evaluation of unspecified and random timing:
   - Unspecified timing produces DLTI_INSUFFICIENT_CONTEXT.
   - Random timing (180 mg/dL < 200 mg/dL acute threshold) produces DLTI_RULE_EVALUATED (not triggered).
4. Premature / missing lab values (Case B root cause):
   - Confirms that missing lab values yield RESEARCH_PREVIEW_NO_PAIRS.
   - Confirms explicit disclaimer that no-pairs is NOT evidence of safety.
5. Explicit rejection reasons:
   - REJECTED_MISSING_VALUE when analyte is submitted without a value.
   - REJECTED_INVALID_NUMERIC when value is non-numeric text.
   - REJECTED_UNRECOGNIZED_ANALYTE when analyte is unknown.
   - Normal value (95 mg/dL fasting) produces NORMAL status and does not force HIGH trigger.
6. Reasoning Agent Guardrails:
   - Zero DDI pairs must reject "no interactions with other medications".
   - Zero / missing DLTI must reject "no safety alerts or warnings".
"""

import io
import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
from app import app
from rule_engine import MedicalRuleEngine
from prescription_reasoning_agent import (
    PrescriptionReasoningAgent,
    _validate_llm_output_against_ddi,
)
from pdf_export import build_analysis_pdf


class TestCaseBLaboratoryRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        cls.client = app.test_client()

        # Locate or create synthetic Prednisone PDF
        demo_pdf = os.path.join(os.path.dirname(__file__), "..", "scratch", "rx_prednisone_demo.pdf")
        if os.path.exists(demo_pdf):
            with open(demo_pdf, "rb") as f:
                cls.prednisone_pdf_bytes = f.read()
        else:
            cls.prednisone_pdf_bytes = b"%PDF-1.4 synthetic prednisone"

    def setUp(self):
        # Fast mock for AI explanation to avoid slow external API calls in test suite
        self.ai_patch = patch.object(
            app_module,
            "generate_ai_analysis",
            side_effect=lambda user_prompt, sys_prompt: (
                "Prescription verified: Prednisone. Review corticosteroid hyperglycemia risk with patient."
            ),
        )
        self.ai_patch.start()

    def tearDown(self):
        self.ai_patch.stop()

    def test_glucose_concept_mapping_direct_unit_tests(self):
        """Direct verification of glucose concept mapping in MedicalRuleEngine."""
        engine = MedicalRuleEngine()

        # 1. Generic Glucose with NO timing context must NOT map to MBG_HIGH_001
        res_no_timing = engine.evaluate_single_parameter("Glucose", 180, "mg/dL", timing_context=None)
        self.assertIsNotNone(res_no_timing)
        self.assertEqual(res_no_timing["status"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(res_no_timing["rule_id"], "GLUCOSE_TIMING_CONTEXT_REQUIRED")
        self.assertNotIn("MBG", res_no_timing["rule_id"])

        # 2. Generic Glucose with "unspecified" timing must return INSUFFICIENT_CONTEXT
        res_unspec = engine.evaluate_single_parameter("Glucose", 180, "mg/dL", timing_context="unspecified")
        self.assertEqual(res_unspec["status"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(res_unspec["rule_id"], "GLUCOSE_TIMING_CONTEXT_REQUIRED")

        # 3. Generic Glucose with timing_context="fasting" maps to fasting_glucose (ADA 2024 Standards of Care)
        res_fasting = engine.evaluate_single_parameter("Glucose", 180, "mg/dL", timing_context="fasting")
        self.assertIsNotNone(res_fasting)
        self.assertEqual(res_fasting["key"], "fasting_glucose")
        self.assertEqual(res_fasting["parameter"], "Fasting Glucose")
        self.assertEqual(res_fasting["status"], "DIABETES_RANGE")
        self.assertEqual(res_fasting["rule_id"], "FASTING_GLUCOSE_DIABETES_RANGE_001")
        self.assertEqual(res_fasting["provenance_source"], "ADA 2024 Standards of Care")
        self.assertNotIn("MBG", res_fasting["rule_id"])

        # 4. Generic Glucose with timing_context="random" maps to random_glucose (ADA 2024 Standards of Care)
        res_random = engine.evaluate_single_parameter("Glucose", 180, "mg/dL", timing_context="random")
        self.assertIsNotNone(res_random)
        self.assertEqual(res_random["key"], "random_glucose")
        self.assertEqual(res_random["parameter"], "Random Glucose")
        self.assertEqual(res_random["status"], "BELOW_DIABETIC_THRESHOLD")
        self.assertEqual(res_random["rule_id"], "RANDOM_GLUCOSE_BELOW_THRESH_001")
        self.assertEqual(res_random["provenance_source"], "ADA 2024 Standards of Care")

        # 5. Explicit "Mean Blood Glucose" or "eAG" maps to mean_blood_glucose (ADA 2024 Standards of Care (eAG Formula))
        res_mbg = engine.evaluate_single_parameter("Mean Blood Glucose", 180, "mg/dL")
        self.assertIsNotNone(res_mbg)
        self.assertEqual(res_mbg["key"], "mean_blood_glucose")
        self.assertEqual(res_mbg["rule_id"], "MBG_HIGH_001")
        self.assertEqual(res_mbg["provenance_source"], "ADA 2024 Standards of Care (eAG Formula)")

        res_eag = engine.evaluate_single_parameter("eAG", 180, "mg/dL")
        self.assertIsNotNone(res_eag)
        self.assertEqual(res_eag["key"], "mean_blood_glucose")
        self.assertEqual(res_eag["rule_id"], "MBG_HIGH_001")
        self.assertEqual(res_eag["provenance_source"], "ADA 2024 Standards of Care (eAG Formula)")

    def test_case_b_full_laboratory_flow_triggered(self):
        """Case B intended input: Prednisone + Fasting Glucose 180 mg/dL triggers DLTI via ADA 2024 fasting rule."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "180",
            "current_lab_unit": "mg/dL",
            "current_lab_timing": "fasting",
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body.get("success"))

        ctx = body.get("pipeline_context", {})

        # 1. Laboratory verification through rule engine
        labs = ctx.get("lab_values", [])
        self.assertEqual(len(labs), 1)
        self.assertEqual(labs[0].get("analyte"), "Glucose")
        self.assertEqual(labs[0].get("value"), 180.0)
        self.assertEqual(labs[0].get("status"), "DIABETES_RANGE")
        self.assertEqual(labs[0].get("rule_id"), "FASTING_GLUCOSE_DIABETES_RANGE_001")

        # 2. Input provenance retained and records submitted timing
        prov = ctx.get("lab_input_provenance", [])
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0].get("validation_status"), "VERIFIED")
        self.assertEqual(prov[0].get("derived_status"), "DIABETES_RANGE")
        self.assertEqual(prov[0].get("rule_id"), "FASTING_GLUCOSE_DIABETES_RANGE_001")
        self.assertEqual(prov[0].get("verified_analyte"), "Fasting Glucose")
        self.assertEqual(prov[0].get("submitted_timing"), "fasting")
        self.assertNotIn("MBG_HIGH", prov[0].get("rule_id", ""))

        # 3. DLTI evaluation complete and triggered
        dlti = ctx.get("dlti", {})
        self.assertEqual(dlti.get("status"), "DLTI_COMPLETE")
        coverage = dlti.get("coverage", {})
        self.assertEqual(coverage.get("pairs_evaluated"), 1)
        self.assertEqual(coverage.get("rules_triggered"), 1)

        findings = dlti.get("results", [])
        triggered = [r for r in findings if r.get("status") == "DLTI_TRIGGERED"]
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0].get("rule_id"), "DLTI_PD_PREDNISONE_GLUCOSE_V1")

        # 4. Displayed result summary contains provenance table and advisory
        summary = body.get("analysis", {}).get("english", "")
        self.assertIn("Submitted Laboratory Measurements (Input Provenance)", summary)
        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", summary)
        self.assertIn("corticosteroid", summary.lower())
        self.assertNotIn("no interactions with other medications", summary.lower())
        self.assertNotIn("no safety alerts or warnings", summary.lower())

        # 5. Direct PDF export renders cleanly
        pdf_bytes = build_analysis_pdf(summary, kind="medicine", today=date.today())
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_case_b_glucose_unspecified_timing_produces_insufficient_context(self):
        """When timing context is unspecified, system returns INSUFFICIENT_CONTEXT without guessing."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "180",
            "current_lab_unit": "mg/dL",
            "current_lab_timing": "unspecified",
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        ctx = body.get("pipeline_context", {})

        prov = ctx.get("lab_input_provenance", [])
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0].get("validation_status"), "INSUFFICIENT_CONTEXT")
        self.assertEqual(prov[0].get("derived_status"), "INSUFFICIENT_CONTEXT")
        self.assertEqual(prov[0].get("rule_id"), "GLUCOSE_TIMING_CONTEXT_REQUIRED")
        self.assertIn("timing context", prov[0].get("rejection_reason", "").lower())

        dlti = ctx.get("dlti", {})
        coverage = dlti.get("coverage", {})
        self.assertEqual(coverage.get("rules_triggered"), 0)
        self.assertEqual(coverage.get("rules_insufficient_context"), 1)

        findings = dlti.get("results", [])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].get("status"), "DLTI_INSUFFICIENT_CONTEXT")

    def test_case_b_random_glucose_below_threshold_does_not_trigger(self):
        """Random glucose of 180 mg/dL is below acute 200 mg/dL threshold and does NOT trigger DLTI."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "180",
            "current_lab_unit": "mg/dL",
            "current_lab_timing": "random",
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        ctx = body.get("pipeline_context", {})

        prov = ctx.get("lab_input_provenance", [])
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0].get("validation_status"), "VERIFIED")
        self.assertEqual(prov[0].get("derived_status"), "BELOW_DIABETIC_THRESHOLD")
        self.assertEqual(prov[0].get("rule_id"), "RANDOM_GLUCOSE_BELOW_THRESH_001")

        dlti = ctx.get("dlti", {})
        coverage = dlti.get("coverage", {})
        self.assertEqual(coverage.get("rules_triggered"), 0)
        self.assertEqual(coverage.get("rules_evaluated_not_triggered"), 1)

    def test_case_b_missing_laboratory_values_records_provenance_and_no_pairs(self):
        """When lab values are not entered (premature submit), provenance notes NONE_SUBMITTED."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            # no current_lab_* fields supplied
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        ctx = body.get("pipeline_context", {})

        prov = ctx.get("lab_input_provenance", [])
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0].get("validation_status"), "NONE_SUBMITTED")

        dlti = ctx.get("dlti", {})
        coverage = dlti.get("coverage", {})
        self.assertEqual(coverage.get("coverage_label"), "RESEARCH_PREVIEW_NO_PAIRS")
        self.assertEqual(coverage.get("pairs_evaluated"), 0)

        # Output summary includes clear notice
        summary = body.get("analysis", {}).get("english", "")
        self.assertIn("RESEARCH_PREVIEW_NO_PAIRS", summary)
        self.assertIn("No current laboratory measurements were evaluated against verified medications", summary)
        self.assertIn("This does not indicate absence of drug-laboratory interactions", summary)

    def test_explicit_rejection_reasons_preserved(self):
        """Explicit rejection reasons preserved without forcing HIGH or bypassing verification."""
        # 1. Non-numeric value
        data_invalid_num = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "abc_not_a_number",
            "current_lab_unit": "mg/dL",
        }
        res1 = self.client.post("/upload-prescription", data=data_invalid_num, content_type="multipart/form-data")
        prov1 = res1.get_json()["pipeline_context"]["lab_input_provenance"][0]
        self.assertEqual(prov1.get("validation_status"), "REJECTED_INVALID_NUMERIC")
        self.assertIn("not a valid number", prov1.get("rejection_reason", ""))

        # 2. Missing value
        data_missing_val = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "",
            "current_lab_unit": "mg/dL",
        }
        res2 = self.client.post("/upload-prescription", data=data_missing_val, content_type="multipart/form-data")
        prov2 = res2.get_json()["pipeline_context"]["lab_input_provenance"][0]
        self.assertEqual(prov2.get("validation_status"), "REJECTED_MISSING_VALUE")
        self.assertIn("without a numeric measured value", prov2.get("rejection_reason", ""))

        # 3. Unrecognized analyte
        data_unknown_analyte = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "NonExistentAnalyte999",
            "current_lab_value": "100",
            "current_lab_unit": "mg/dL",
        }
        res3 = self.client.post("/upload-prescription", data=data_unknown_analyte, content_type="multipart/form-data")
        prov3 = res3.get_json()["pipeline_context"]["lab_input_provenance"][0]
        self.assertEqual(prov3.get("validation_status"), "REJECTED_UNRECOGNIZED_ANALYTE")
        self.assertIn("could not be matched to reference ranges", prov3.get("rejection_reason", ""))

        # 4. Normal value: 95 mg/dL Fasting Glucose
        data_normal = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "95",
            "current_lab_unit": "mg/dL",
            "current_lab_timing": "fasting",
        }
        res4 = self.client.post("/upload-prescription", data=data_normal, content_type="multipart/form-data")
        ctx4 = res4.get_json()["pipeline_context"]
        prov4 = ctx4["lab_input_provenance"][0]
        self.assertEqual(prov4.get("validation_status"), "VERIFIED")
        self.assertEqual(prov4.get("derived_status"), "NORMAL")
        self.assertEqual(prov4.get("rule_id"), "FASTING_GLUCOSE_NORMAL_001")

        # Must NOT trigger DLTI rule (status is NORMAL, rule targets elevated/hyperglycemic statuses)
        dlti4 = ctx4["dlti"]
        self.assertEqual(dlti4["coverage"]["rules_triggered"], 0)
        self.assertEqual(dlti4["coverage"]["rules_evaluated_not_triggered"], 1)

    def test_reasoning_guardrail_zero_ddi_pairs_rejects_no_interactions_claim(self):
        """Zero DDI pairs (single drug) must reject 'no interactions with other medications'."""
        ddi_single_drug = {
            "overall_status": "no_pairs",
            "coverage": {
                "coverage_completeness": "NO_PAIRS",
                "total_pairs_checked": 0,
            },
            "interactions_found": [],
        }

        # Prohibited LLM output
        bad_text = "This prescription contains Prednisone with no interactions with other medications."
        valid, violations = _validate_llm_output_against_ddi(bad_text, ddi=ddi_single_drug)
        self.assertFalse(valid)
        self.assertTrue(any("claims no interactions with other medications" in v for v in violations))

    def test_reasoning_guardrail_missing_dlti_rejects_no_safety_alerts_claim(self):
        """Missing or 0-pair DLTI must reject 'no safety alerts or warnings'."""
        ddi_data = {
            "overall_status": "no_pairs",
            "coverage": {"coverage_completeness": "NO_PAIRS", "total_pairs_checked": 0},
            "interactions_found": [],
        }
        dlti_zero_pairs = {
            "status": "DLTI_COMPLETE",
            "coverage": {"pairs_evaluated": 0, "coverage_label": "RESEARCH_PREVIEW_NO_PAIRS"},
            "results": [],
        }

        bad_text = "Prednisone was reviewed. There are no safety alerts or warnings for this prescription."
        valid, violations = _validate_llm_output_against_ddi(bad_text, ddi=ddi_data, dlti=dlti_zero_pairs)
        self.assertFalse(valid)
        self.assertTrue(any("claims no safety alerts or warnings" in v for v in violations))

    def test_deterministic_summary_preserves_coverage_limitations(self):
        """Deterministic summary states no_pairs and research preview coverage accurately."""
        ddi_data = {
            "overall_status": "no_pairs",
            "coverage": {"coverage_completeness": "NO_PAIRS", "total_pairs_checked": 0},
            "interactions_found": [],
        }
        dlti_data = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "coverage_label": "RESEARCH_PREVIEW_NO_PAIRS",
                "pairs_evaluated": 0,
                "rules_triggered": 0,
            },
            "results": [],
            "lab_input_provenance": [{
                "submitted_analyte": None,
                "validation_status": "NONE_SUBMITTED",
                "rejection_reason": "No current laboratory measurements were submitted in this request."
            }]
        }
        verified_meds = [{"name": "Prednisone", "strength": "10 mg", "frequency": "Once daily"}]
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=verified_meds,
            unverified_meds=[],
            overall_status="verified",
            ddi=ddi_data,
            dlti=dlti_data,
        )

        # Must NOT claim zero interactions with other medications
        self.assertNotIn("no interactions with other medications", summary.lower())
        self.assertNotIn("no safety alerts or warnings", summary.lower())
        # Must include explicit limitation notes
        self.assertIn("No pairs to check (NO_PAIRS)", summary)
        self.assertIn("RESEARCH_PREVIEW_NO_PAIRS", summary)
        self.assertIn("Submitted Laboratory Measurements (Input Provenance)", summary)

    def test_format_provenance_value_unit_tests(self):
        """Direct unit testing of _format_provenance_value covering all missing/present combinations."""
        from prescription_reasoning_agent import _format_provenance_value

        # 1. Both absent
        self.assertEqual(_format_provenance_value(None, None), "Value and unit not provided")
        self.assertEqual(_format_provenance_value("", ""), "Value and unit not provided")
        self.assertEqual(_format_provenance_value("None", "None"), "Value and unit not provided")

        # 2. Both absent + explicit timing preserved
        self.assertEqual(_format_provenance_value(None, None, "fasting"), "Value and unit not provided (fasting)")
        self.assertEqual(_format_provenance_value("", "", "random"), "Value and unit not provided (random)")

        # 3. Both absent + unspecified timing does NOT invent timing
        self.assertEqual(_format_provenance_value(None, None, "unspecified"), "Value and unit not provided")
        self.assertEqual(_format_provenance_value(None, None, "unknown"), "Value and unit not provided")
        self.assertEqual(_format_provenance_value(None, None, ""), "Value and unit not provided")

        # 4. Value absent, unit present
        self.assertEqual(_format_provenance_value(None, "mg/dL"), "Value not provided; unit: mg/dL")
        self.assertEqual(_format_provenance_value("", "mg/dL"), "Value not provided; unit: mg/dL")
        self.assertEqual(_format_provenance_value(None, "mg/dL", "fasting"), "Value not provided; unit: mg/dL (fasting)")
        self.assertEqual(_format_provenance_value(None, "mg/dL", "unspecified"), "Value not provided; unit: mg/dL")

        # 5. Value present, unit absent
        self.assertEqual(_format_provenance_value(180, None), "180; unit not provided")
        self.assertEqual(_format_provenance_value("180", ""), "180; unit not provided")
        self.assertEqual(_format_provenance_value("180", None, "fasting"), "180; unit not provided (fasting)")
        self.assertEqual(_format_provenance_value(180, "", "unspecified"), "180; unit not provided")

        # 6. Both present
        self.assertEqual(_format_provenance_value(180, "mg/dL"), "180 mg/dL")
        self.assertEqual(_format_provenance_value(180, "mg/dL", "fasting"), "180 mg/dL (fasting)")
        self.assertEqual(_format_provenance_value("180", "mg/dL", "unspecified"), "180 mg/dL")

        # 7. Preserve zero (0, 0.0, "0") as valid numeric value
        self.assertEqual(_format_provenance_value(0, "mg/dL"), "0 mg/dL")
        self.assertEqual(_format_provenance_value(0, "mg/dL", "fasting"), "0 mg/dL (fasting)")
        self.assertEqual(_format_provenance_value(0.0, "mg/dL"), "0.0 mg/dL")
        self.assertEqual(_format_provenance_value("0", "mg/dL"), "0 mg/dL")
        self.assertEqual(_format_provenance_value(0, None), "0; unit not provided")
        self.assertEqual(_format_provenance_value(0, "", "fasting"), "0; unit not provided (fasting)")

        # 8. Pipe escaping
        self.assertEqual(_format_provenance_value("100|bad", "mg/dL"), "100\\|bad mg/dL")

    def test_case_c_provenance_formatting_and_dlti_insufficient_context(self):
        """Case C: Prednisone + Glucose with value/unit blank yields REJECTED_MISSING_VALUE and readable text."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "",
            "current_lab_unit": "",
            "current_lab_timing": "fasting",
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        ctx = body.get("pipeline_context", {})

        # 1. Provenance records rejection
        prov = ctx.get("lab_input_provenance", [])
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0].get("validation_status"), "REJECTED_MISSING_VALUE")
        self.assertEqual(prov[0].get("submitted_timing"), "fasting")

        # 2. DLTI finding is INSUFFICIENT_CONTEXT
        dlti = ctx.get("dlti", {})
        coverage = dlti.get("coverage", {})
        self.assertEqual(coverage.get("rules_triggered"), 0)
        self.assertEqual(coverage.get("rules_insufficient_context"), 1)

        findings = dlti.get("results", [])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].get("status"), "DLTI_INSUFFICIENT_CONTEXT")
        self.assertEqual(findings[0].get("rule_id"), "DLTI_PD_PREDNISONE_GLUCOSE_V1")

        # 3. Output text uses readable missing-input wording, not "None None"
        summary = body.get("analysis", {}).get("english", "")
        self.assertNotIn("None None", summary)
        self.assertIn("Value and unit not provided (fasting)", summary)
        self.assertIn("REJECTED_MISSING_VALUE", summary)

        # 4. PDF export renders cleanly without "None None"
        pdf_bytes = build_analysis_pdf(summary, kind="medicine", today=date.today())
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertNotIn(b"None None", pdf_bytes)

    def test_case_c_without_timing_does_not_invent_timing(self):
        """Case C without timing context: displays 'Value and unit not provided' without inventing timing."""
        data = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "",
            "current_lab_unit": "",
            "current_lab_timing": "unspecified",
        }
        res = self.client.post("/upload-prescription", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        summary = body.get("analysis", {}).get("english", "")

        self.assertNotIn("None None", summary)
        self.assertIn("Value and unit not provided", summary)
        self.assertNotIn("Value and unit not provided (unspecified)", summary)

    def test_provenance_partial_inputs_and_zero_value(self):
        """Verifies partial inputs (unit only, value only) and zero value in end-to-end route."""
        # 1. Value present, unit absent
        data_val_only = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "180",
            "current_lab_unit": "",
            "current_lab_timing": "fasting",
        }
        res1 = self.client.post("/upload-prescription", data=data_val_only, content_type="multipart/form-data")
        summary1 = res1.get_json().get("analysis", {}).get("english", "")
        self.assertNotIn("None None", summary1)
        self.assertIn("180; unit not provided (fasting)", summary1)

        # 2. Value absent, unit present
        data_unit_only = {
            "file": (io.BytesIO(self.prednisone_pdf_bytes), "rx_prednisone_demo.pdf"),
            "current_lab_analyte": "Glucose",
            "current_lab_value": "",
            "current_lab_unit": "mg/dL",
            "current_lab_timing": "fasting",
        }
        res2 = self.client.post("/upload-prescription", data=data_unit_only, content_type="multipart/form-data")
        summary2 = res2.get_json().get("analysis", {}).get("english", "")
        self.assertNotIn("None None", summary2)
        self.assertIn("Value not provided; unit: mg/dL (fasting)", summary2)


class TestPatientFriendlySummaryLayer(unittest.TestCase):
    """
    Focused tests for the Patient-Friendly Summary layer:
    1. Case B triggered result (prednisone + blood sugar, non-diagnostic/non-causal).
    2. Case C missing value/unit (REJECTED_MISSING_VALUE, DLTI_INSUFFICIENT_CONTEXT).
    3. Numeric result present but timing unspecified (timing context needed, value preserved).
    4. Non-triggered result (evaluated not triggered, no global safety reassurance).
    5. No submitted labs, unavailable evaluation, and blocked history (distinct, accurate limitations).
    6. Screen and PDF (same patient-summary content and complete technical details).
    7. Special characters and zero (safe rendering and no missing-value regression).
    8. Summary isolation (raw internal codes kept out of Section A, available in Section B).
    9. Conflicting or incomplete structured state (safe fallback without reassurance).
    """

    def setUp(self):
        self.med_prednisone = [{
            "name": "Prednisone",
            "verified_name": "Prednisone",
            "strength": "10 mg",
            "frequency": "OD",
            "timing": None,
            "duration": None,
            "identity_verified": True,
            "verification_status": "verified",
        }]

    def test_1_case_b_triggered_patient_summary(self):
        """Case B: Accurate patient summary, non-diagnostic/non-causal wording, counters unchanged."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 1,
                "rules_triggered": 1,
                "rules_evaluated_not_triggered": 0,
                "rules_insufficient_context": 0,
                "coverage_label": "FULL",
            },
            "results": [{
                "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                "status": "DLTI_TRIGGERED",
                "clinical_advisory": {
                    "summary_title": "Prednisone — Corticosteroid-Associated Glucose Elevation (Research Candidate)",
                    "authored_advisory_text": "Chronic therapy with systemic corticosteroids can produce hyperglycemia.",
                },
                "evidence_summary": [{
                    "source_name": "FDA Prescribing Information",
                    "document_id": "RAYOS NDA 202020",
                    "section": "Section 6.1 Adverse Reactions",
                }],
            }],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": 180,
                "submitted_unit": "mg/dL",
                "submitted_timing": "fasting",
                "validation_status": "VERIFIED",
                "derived_status": "DIABETES_RANGE",
                "rule_id": "FASTING_GLUCOSE_DIABETES_RANGE_001",
            }],
        }
        ddi = {
            "overall_status": "no_pairs",
            "coverage": {
                "total_pairs_checked": 0,
                "resolved_ingredients_count": 1,
                "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION",
            },
            "interactions_found": [],
        }

        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            ddi=ddi,
            dlti=dlti,
        )

        # 1. Section order: Section A leads, Section B follows
        idx_patient = summary.find("## 📋 Patient-Friendly Summary")
        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        self.assertNotEqual(idx_patient, -1)
        self.assertNotEqual(idx_tech, -1)
        self.assertLess(idx_patient, idx_tech, "Section A must precede Section B")

        patient_sec = summary[idx_patient:idx_tech]
        tech_sec = summary[idx_tech:]

        # 2. Section A headings
        self.assertIn("### Your prescription", patient_sec)
        self.assertIn("### What this review found", patient_sec)
        self.assertIn("### What could not be checked", patient_sec)
        self.assertIn("### What you can do next", patient_sec)
        self.assertIn("### Important limits", patient_sec)

        # 3. Prescription phrasing
        self.assertIn("The uploaded prescription lists", patient_sec)
        self.assertIn("prednisone 10 mg, once daily", patient_sec)
        self.assertIn("Prednisone", tech_sec)
        self.assertIn("10 mg", patient_sec)
        self.assertIn("once daily", patient_sec)  # OD expanded to once daily
        self.assertNotIn("OD", patient_sec)

        # No invented duration when duration is absent in source
        rx_sec = patient_sec[patient_sec.find("### Your prescription"):patient_sec.find("### What this review found")]
        self.assertNotIn("5 days", rx_sec)
        self.assertNotIn("for ", rx_sec)
        self.assertNotIn("5 days", tech_sec)
        self.assertNotIn("Duration:", tech_sec)

        # 4. Non-diagnostic and non-causal
        self.assertIn("blood sugar (glucose)", patient_sec)
        self.assertIn("matched an informational research rule", patient_sec)
        self.assertIn("Prednisone can cause blood sugar levels to rise", patient_sec)
        self.assertIn("does not establish prednisone as the cause", patient_sec)
        self.assertIn("does not diagnose diabetes", patient_sec)

        # 5. Treatment boundaries: no stopping/tapering instruction
        self.assertIn("Do not stop, taper, increase, or reduce your medication on your own", patient_sec)

        # 6. Technical outcome preserved in Section B
        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", tech_sec)
        self.assertIn("Rules Triggered | 1", tech_sec)
        self.assertIn("Section 6.1 Adverse Reactions", tech_sec)

    def test_2_case_c_missing_value_and_unit(self):
        """Case C: Clear missing-information explanation, REJECTED_MISSING_VALUE preserved in technical details."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 1,
                "rules_triggered": 0,
                "rules_insufficient_context": 1,
                "coverage_label": "RESEARCH_PREVIEW_INSUFFICIENT_CONTEXT",
            },
            "results": [{
                "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                "status": "DLTI_INSUFFICIENT_CONTEXT",
                "applicability_notes": ["Missing required numeric test value."],
            }],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": None,
                "submitted_unit": None,
                "validation_status": "REJECTED_MISSING_VALUE",
                "rejection_reason": "Analyte specified without a numeric measured value.",
            }],
        }
        ddi = {
            "overall_status": "no_pairs",
            "coverage": {
                "total_pairs_checked": 0,
                "resolved_ingredients_count": 1,
                "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION",
            },
            "interactions_found": [],
        }

        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            ddi=ddi,
            dlti=dlti,
        )

        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        patient_sec = summary[:idx_tech]
        tech_sec = summary[idx_tech:]

        # Exact requested wording in Section A
        self.assertIn("The blood sugar check could not be completed because the test result and unit were not provided", patient_sec)
        self.assertIn("- The glucose result and unit were missing, so the blood sugar check could not be completed. This neither establishes nor rules out a problem.", patient_sec)
        self.assertIn("- Only one medicine ingredient was available, so no medicine pair could be compared.", patient_sec)
        self.assertIn("- Medication history was unavailable, so interactions with other medicines could not be assessed.", patient_sec)
        self.assertIn("enter the result, unit, and timing exactly as recorded", patient_sec)

        # Prohibit false reassurance for Case C where no rule completed a negative evaluation
        self.assertNotIn("no specific medication–laboratory concerns", patient_sec.lower())
        self.assertNotIn("no specific medication-laboratory concerns", patient_sec.lower())
        self.assertNotIn("no concerns were flagged", patient_sec.lower())
        self.assertNotIn("no interaction flags were triggered", patient_sec.lower())

        # No invented duration when duration is absent in source
        rx_sec = patient_sec[patient_sec.find("### Your prescription"):patient_sec.find("### What this review found")]
        self.assertNotIn("5 days", rx_sec)
        self.assertNotIn("for ", rx_sec)
        self.assertNotIn("5 days", tech_sec)
        self.assertNotIn("Duration:", tech_sec)

        # Raw codes must not leak into Section A
        self.assertNotIn("REJECTED_MISSING_VALUE", patient_sec)
        self.assertNotIn("DLTI_INSUFFICIENT_CONTEXT", patient_sec)
        self.assertNotIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", patient_sec)

        # Raw codes preserved in Section B
        self.assertIn("REJECTED_MISSING_VALUE", tech_sec)
        self.assertIn("DLTI_INSUFFICIENT_CONTEXT", tech_sec)
        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", tech_sec)
        self.assertIn("Rules Insufficient Context | 1", tech_sec)
        self.assertIn("Rules Triggered | 0", tech_sec)

    def test_3_numeric_result_present_timing_unspecified(self):
        """Numeric result present but timing unspecified: timing explanation without claiming missing numeric value."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 1,
                "rules_triggered": 0,
                "rules_insufficient_context": 1,
            },
            "results": [{
                "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                "status": "DLTI_INSUFFICIENT_CONTEXT",
                "applicability_notes": ["Timing context required."],
            }],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": 180,
                "submitted_unit": "mg/dL",
                "submitted_timing": "unspecified",
                "validation_status": "INSUFFICIENT_CONTEXT",
                "rule_id": "GLUCOSE_TIMING_CONTEXT_REQUIRED",
                "rejection_reason": "Glucose evaluation requires timing context.",
            }],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti,
        )

        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        patient_sec = summary[:idx_tech]

        # Preserves value and unit
        self.assertIn("180 mg/dL", patient_sec)
        self.assertIn("whether the test was taken while fasting or at another time was not specified", patient_sec)
        # Does NOT state numeric value was missing
        self.assertNotIn("no numeric test result was provided", patient_sec)
        self.assertIn("check whether the blood sugar test was taken while fasting or at random", patient_sec)

    def test_4_non_triggered_result_no_global_safety_assurance(self):
        """Non-triggered result: Explains rule evaluated not triggered; no global safety claims."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 1,
                "rules_triggered": 0,
                "rules_evaluated_not_triggered": 1,
            },
            "results": [{
                "rule_id": "RANDOM_GLUCOSE_RULE",
                "status": "DLTI_RULE_EVALUATED",
            }],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": 140,
                "submitted_unit": "mg/dL",
                "submitted_timing": "random",
                "validation_status": "VERIFIED",
            }],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti,
        )

        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        patient_sec = summary[:idx_tech]

        self.assertIn("The evaluated research rule did not flag this submitted combination", patient_sec)
        self.assertNotIn("safe to take", patient_sec.lower())
        self.assertNotIn("normal", patient_sec.lower())
        self.assertNotIn("nothing to worry about", patient_sec.lower())
        self.assertNotIn("no interactions", patient_sec.lower())

    def test_5_no_submitted_labs_and_blocked_history_limitations(self):
        """Distinct, accurate limitations for no labs, single medicine DDI, and blocked history."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 0,
                "rules_triggered": 0,
                "coverage_label": "RESEARCH_PREVIEW_NO_PAIRS",
            },
            "results": [],
            "lab_input_provenance": [{
                "submitted_analyte": None,
                "validation_status": "NONE_SUBMITTED",
            }],
        }
        ddi = {
            "overall_status": "no_pairs",
            "coverage": {
                "total_pairs_checked": 0,
                "resolved_ingredients_count": 1,
                "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION",
            },
            "interactions_found": [],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            ddi=ddi,
            dlti=dlti,
        )

        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        patient_sec = summary[:idx_tech]

        # Distinct limitations
        self.assertIn("No laboratory test measurements were submitted with this prescription", patient_sec)
        self.assertIn("Only one medicine ingredient was available, so no medicine pair could be compared", patient_sec)
        self.assertIn("Medication history was unavailable, so interactions with other medicines could not be assessed", patient_sec)
        # Must not say patient takes no other medicines
        self.assertNotIn("You take no other medicines", patient_sec)

    def test_6_screen_and_pdf_render_identical_content(self):
        """Screen and PDF export use identical markdown representation and contain complete details."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {"pairs_evaluated": 1, "rules_triggered": 1},
            "results": [{
                "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                "status": "DLTI_TRIGGERED",
                "clinical_advisory": {"summary_title": "Prednisone — Corticosteroid Glucose Elevation"},
            }],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": 180,
                "submitted_unit": "mg/dL",
                "submitted_timing": "fasting",
                "validation_status": "VERIFIED",
            }],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti,
        )

        pdf_bytes = build_analysis_pdf(summary, kind="medicine", today=date.today())
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = " ".join(page.extract_text() for page in reader.pages)

        # Both Section A and Section B are present in PDF
        self.assertIn("Patient-Friendly Summary", pdf_text)
        self.assertIn("Your prescription", pdf_text)
        self.assertIn("What this review found", pdf_text)
        self.assertIn("Technical Details and Evidence", pdf_text)
        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", pdf_text)

    def test_7_special_characters_and_zero_preserved(self):
        """Zero values are preserved as valid measurements without missing-value regression."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {"pairs_evaluated": 1, "rules_triggered": 0, "rules_evaluated_not_triggered": 1},
            "results": [],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": 0,
                "submitted_unit": "mg/dL",
                "submitted_timing": "fasting",
                "validation_status": "VERIFIED",
            }],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=[{"name": "Med<Special>&Test", "strength": "5|mg", "frequency": "OD"}],
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti,
        )

        # 0 is not treated as missing
        self.assertNotIn("no numeric test result was provided", summary)
        # Special characters sanitized
        self.assertNotIn("5|mg", summary)
        self.assertIn("5mg", summary)

    def test_8_summary_isolation_raw_codes_do_not_leak(self):
        """Raw internal codes do not leak into patient summary; remain in technical section."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 1,
                "rules_triggered": 1,
                "rules_insufficient_context": 1,
            },
            "results": [
                {
                    "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                    "status": "DLTI_TRIGGERED",
                },
                {
                    "rule_id": "DLTI_UNSPECIFIED_RULE",
                    "status": "DLTI_INSUFFICIENT_CONTEXT",
                }
            ],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": None,
                "submitted_unit": None,
                "validation_status": "REJECTED_MISSING_VALUE",
            }],
        }
        ddi = {
            "overall_status": "prescription_only",
            "coverage": {
                "coverage_completeness": "PRESCRIPTION_ONLY",
                "total_pairs_checked": 0,
                "resolved_ingredients_count": 1,
                "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION",
            },
        }

        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            ddi=ddi,
            dlti=dlti,
        )

        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        patient_sec = summary[:idx_tech]
        tech_sec = summary[idx_tech:]

        raw_codes = [
            "REJECTED_MISSING_VALUE",
            "DLTI_INSUFFICIENT_CONTEXT",
            "DLTI_PD_PREDNISONE_GLUCOSE_V1",
            "BLOCKED_NO_AUTHORIZATION",
            "PRESCRIPTION_ONLY",
        ]
        for code in raw_codes:
            self.assertNotIn(code, patient_sec, f"Raw code '{code}' leaked into Section A")
            self.assertIn(code, tech_sec, f"Raw code '{code}' must be in Section B")

    def test_9_conflicting_or_incomplete_structured_state_fallback(self):
        """Incomplete or conflicting structured state triggers safe fallback without reassurance."""
        # Intentionally passing malformed / conflicting data that raises exception during extraction
        class BrokenObj:
            def get(self, *args, **kwargs):
                raise RuntimeError("Corrupted state simulation")

        broken_dlti = BrokenObj()
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=BrokenObj(),
            unverified_meds=[],
            overall_status="error",
            dlti=broken_dlti,
        )

        self.assertIn("This check could not be completed", summary)
        self.assertNotIn("safe", summary.lower())
        self.assertNotIn("no interactions", summary.lower())
        self.assertIn("Consult your prescribing doctor", summary)

    def test_10_prescription_fidelity_strength_not_hardcoded(self):
        """Prescription fidelity: 10 mg remains 10 mg in Section A & B, and is not hardcoded."""
        # 1. Test 10 mg extraction from prescription
        med_10mg = [{
            "name": "Prednisone",
            "verified_name": "Prednisone",
            "strength": "10 mg",
            "frequency": "OD",
            "timing": "Morning",
            "duration": None,
            "identity_verified": True,
            "verification_status": "verified",
        }]
        summary_10 = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_10mg,
            unverified_meds=[],
            overall_status="verified",
        )
        idx_tech_10 = summary_10.find("## 🔬 Technical Details and Evidence")
        sec_a_10 = summary_10[:idx_tech_10]
        sec_b_10 = summary_10[idx_tech_10:]

        self.assertIn("10 mg", sec_a_10)
        self.assertIn("10 mg", sec_b_10)
        self.assertNotIn("20 mg", sec_a_10)
        self.assertNotIn("20 mg", sec_b_10)
        self.assertNotIn("5 days", sec_a_10)

        # 2. Test 20 mg extraction to confirm dynamic generation without hardcoding
        med_20mg = [{
            "name": "Prednisone",
            "verified_name": "Prednisone",
            "strength": "20 mg",
            "frequency": "OD",
            "timing": "Morning",
            "duration": None,
            "identity_verified": True,
            "verification_status": "verified",
        }]
        summary_20 = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_20mg,
            unverified_meds=[],
            overall_status="verified",
        )
        idx_tech_20 = summary_20.find("## 🔬 Technical Details and Evidence")
        sec_a_20 = summary_20[:idx_tech_20]
        sec_b_20 = summary_20[idx_tech_20:]

        self.assertIn("20 mg", sec_a_20)
        self.assertIn("20 mg", sec_b_20)
        self.assertNotIn("10 mg", sec_a_20)

    def test_11_mixed_outcomes_preserve_both_findings_and_unresolved_checks(self):
        """Mixed outcomes: preserves both completed findings and unresolved checks."""
        dlti = {
            "status": "DLTI_COMPLETE",
            "coverage": {
                "pairs_evaluated": 2,
                "rules_triggered": 0,
                "rules_evaluated_not_triggered": 1,
                "rules_insufficient_context": 1,
                "coverage_label": "RESEARCH_PREVIEW_PARTIAL",
            },
            "results": [
                {
                    "rule_id": "DLTI_EVALUATED_RULE",
                    "status": "DLTI_RULE_EVALUATED",
                    "evaluation_detail": "Condition not met.",
                },
                {
                    "rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1",
                    "status": "DLTI_INSUFFICIENT_CONTEXT",
                    "applicability_notes": ["Missing required numeric test value."],
                }
            ],
            "lab_input_provenance": [{
                "submitted_analyte": "Glucose",
                "submitted_value": None,
                "submitted_unit": None,
                "validation_status": "REJECTED_MISSING_VALUE",
            }],
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti,
        )
        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        sec_a = summary[:idx_tech]

        # Both the evaluated-not-triggered finding AND the insufficient context finding are in Section A
        self.assertIn("The evaluated research rule did not flag this submitted combination", sec_a)
        self.assertIn("The blood sugar check could not be completed because the test result and unit were not provided", sec_a)

    def test_12_no_duration_in_source_no_invented_duration(self):
        """Prescription fidelity: No duration in source -> no invented duration in either output section."""
        med_no_duration = [{
            "name": "Prednisone",
            "verified_name": "Prednisone",
            "strength": "10 mg",
            "frequency": "OD",
            "timing": "Morning",
            "duration": None,
            "identity_verified": True,
            "verification_status": "verified",
        }]
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_no_duration,
            unverified_meds=[],
            overall_status="verified",
        )
        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        sec_a = summary[:idx_tech]
        sec_b = summary[idx_tech:]

        # Strength, frequency, and timing faithfully preserved
        self.assertIn("prednisone", sec_a.lower())
        self.assertIn("Prednisone", sec_b)
        self.assertIn("10 mg", sec_a)
        self.assertIn("once daily", sec_a)
        self.assertIn("morning", sec_a.lower())

        # No invented duration in Section A or Section B
        rx_sec = sec_a[sec_a.find("### Your prescription"):sec_a.find("### What this review found")]
        self.assertNotIn("5 days", rx_sec)
        self.assertNotIn("for ", rx_sec)
        self.assertNotIn("5 days", sec_b)
        self.assertNotIn("(Duration:", sec_b)

    def test_13_explicit_duration_in_source_faithfully_preserved(self):
        """Prescription fidelity: Explicit duration in source -> accurately preserved in both sections."""
        med_with_duration = [{
            "name": "Prednisone",
            "verified_name": "Prednisone",
            "strength": "10 mg",
            "frequency": "OD",
            "timing": "Morning",
            "duration": "7 days",
            "identity_verified": True,
            "verification_status": "verified",
        }]
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_with_duration,
            unverified_meds=[],
            overall_status="verified",
        )
        idx_tech = summary.find("## 🔬 Technical Details and Evidence")
        sec_a = summary[:idx_tech]
        sec_b = summary[idx_tech:]

        # Strength, frequency, timing, and duration faithfully preserved
        self.assertIn("prednisone", sec_a.lower())
        self.assertIn("Prednisone", sec_b)
        self.assertIn("10 mg", sec_a)
        self.assertIn("once daily", sec_a)
        self.assertIn("for 7 days", sec_a)

        self.assertIn("(Duration: 7 days)", sec_b)


    def test_14_frequency_normalization_without_duplication(self):
        """Frequency normalization: 'OD', 'Once Daily (OD)', and expanded forms normalize cleanly without duplication."""
        from prescription_reasoning_agent import _normalize_frequency, _format_patient_med_line

        self.assertEqual(_normalize_frequency("OD"), "once daily")
        self.assertEqual(_normalize_frequency("Once Daily (OD)"), "once daily")
        self.assertEqual(_normalize_frequency("once daily"), "once daily")
        self.assertEqual(_normalize_frequency("Once Daily (once daily)"), "once daily")
        self.assertEqual(_normalize_frequency("Twice Daily (BD/1-0-1)"), "twice daily")
        self.assertEqual(_normalize_frequency("Three Times Daily (TDS/1-1-1)"), "three times daily")
        self.assertEqual(_normalize_frequency("every 8 hours"), "every 8 hours")  # unrecognized preserved

        # Full line formatting on demo extraction produces exact requested wording
        med_demo = {"name": "Prednisone", "strength": "10mg", "frequency": "Once Daily (OD)"}
        line = _format_patient_med_line(med_demo)
        self.assertEqual(line, "prednisone 10 mg, once daily")

    def test_15_strength_formatting_readability(self):
        """Strength formatting adds spacing between numeric quantity and unit without altering value."""
        from prescription_reasoning_agent import _format_patient_strength

        self.assertEqual(_format_patient_strength("10mg"), "10 mg")
        self.assertEqual(_format_patient_strength("10 mg"), "10 mg")
        self.assertEqual(_format_patient_strength("500mcg"), "500 mcg")
        self.assertEqual(_format_patient_strength("2.5ml"), "2.5 ml")
        self.assertEqual(_format_patient_strength("500mg/5ml"), "500 mg/5ml")
        self.assertIsNone(_format_patient_strength(None))

    def test_16_pdf_technical_heading_page_break_no_blank_page(self):
        """PDF technical section begins on page 2 after patient summary, with no blank pages."""
        import fitz
        from pdf_export import build_analysis_pdf

        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
        )
        pdf_bytes = build_analysis_pdf(summary, kind="medicine")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        # Must have at least 2 pages
        self.assertGreaterEqual(len(doc), 2)
        p1_text = doc[0].get_text()
        p2_text = doc[1].get_text()

        # Patient summary is on page 1
        self.assertIn("Patient-Friendly Summary", p1_text)
        self.assertNotIn("Technical Details and Evidence", p1_text)

        # Technical section starts on page 2
        self.assertIn("Technical Details and Evidence", p2_text)

        # Neither page is blank
        self.assertGreater(len(p1_text.strip()), 100)
        self.assertGreater(len(p2_text.strip()), 100)

    def test_17_no_visible_page_break_marker_on_screen(self):
        """Screen markdown does not contain visible raw page-break markers."""
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
        )
        self.assertNotIn("<!-- pagebreak -->", summary)
        self.assertNotIn("page-break-before", summary)
        self.assertNotIn("\\newpage", summary)
        self.assertNotIn("PageBreak", summary)

    def test_18_technical_notices_clean_formatting_identifiers_preserve_underscores(self):
        """Notice formatting renders clean emphasis in PDF while rule IDs and statuses retain underscores."""
        from pdf_export import _inline, build_analysis_pdf
        import fitz

        # 1. Inline conversion converts markdown underscores without altering IDs
        converted = _inline("Rule _DLTI_PD_PREDNISONE_GLUCOSE_V1_ evaluated with status REJECTED_MISSING_VALUE.")
        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", converted)
        self.assertIn("REJECTED_MISSING_VALUE", converted)

        notice_converted = _inline("_Informational notice for testing._")
        self.assertEqual(notice_converted, "<i>Informational notice for testing.</i>")
        self.assertNotIn("_", notice_converted)

        # 2. PDF rendering preserves rule identifiers with underscores
        dlti_c = {
            "status": "DLTI_COMPLETE",
            "coverage": {"pairs_evaluated": 1, "rules_triggered": 0, "rules_insufficient_context": 1},
            "results": [{"rule_id": "DLTI_PD_PREDNISONE_GLUCOSE_V1", "status": "DLTI_INSUFFICIENT_CONTEXT"}],
            "lab_input_provenance": [{"submitted_analyte": "Glucose", "submitted_value": None, "submitted_unit": None, "validation_status": "REJECTED_MISSING_VALUE"}]
        }
        summary = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=self.med_prednisone,
            unverified_meds=[],
            overall_status="verified",
            dlti=dlti_c
        )
        pdf_bytes = build_analysis_pdf(summary, kind="medicine")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = "\n".join(p.get_text() for p in doc)

        self.assertIn("DLTI_PD_PREDNISONE_GLUCOSE_V1", full_text)
        # Verify no literal disclaimer with surrounding underscores like _This tool..._
        import re
        self.assertEqual(re.findall(r"(?<!\w)_[A-Z][^_\n]*?_(?!\w)", full_text), [])

    def test_19_generalization_different_med_multiple_meds_and_nonglucose_lab(self):
        """Generalization: Shared rendering works dynamically with different drugs, multi-drug lists, and non-glucose labs."""
        import fitz
        from pdf_export import build_analysis_pdf

        # 1. Different single medication: Atorvastatin 40mg OD
        med_atorvastatin = [{
            "name": "Atorvastatin",
            "verified_name": "Atorvastatin",
            "strength": "40mg",
            "frequency": "OD",
            "timing": None,
            "duration": None,
        }]
        sum_single = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_atorvastatin,
            unverified_meds=[],
            overall_status="verified",
            ddi={"overall_status": "no_pairs", "coverage": {"total_pairs_checked": 0, "resolved_ingredients_count": 1, "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION"}},
            dlti={"status": "DLTI_COMPLETE", "coverage": {"pairs_evaluated": 0, "rules_triggered": 0, "rules_insufficient_context": 0}, "lab_input_provenance": [{"validation_status": "NONE_SUBMITTED"}]},
        )
        self.assertIn("The uploaded prescription lists atorvastatin 40 mg, once daily.", sum_single)
        self.assertIn("- Only one medicine ingredient was available, so no medicine pair could be compared.", sum_single)

        # 2. Multiple medications: Metformin 500mg BD + Lisinopril 10mg OD
        meds_multi = [
            {"name": "Metformin", "verified_name": "Metformin", "strength": "500mg", "frequency": "Twice Daily (BD/1-0-1)", "timing": None, "duration": None},
            {"name": "Lisinopril", "verified_name": "Lisinopril", "strength": "10mg", "frequency": "OD", "timing": None, "duration": None},
        ]
        sum_multi = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=meds_multi,
            unverified_meds=[],
            overall_status="verified",
            ddi={"overall_status": "checked", "coverage": {"total_pairs_checked": 1, "resolved_ingredients_count": 2}, "interactions_found": []},
            dlti={"status": "DLTI_COMPLETE", "coverage": {"pairs_evaluated": 0, "rules_triggered": 0, "rules_insufficient_context": 0}, "lab_input_provenance": [{"validation_status": "NONE_SUBMITTED"}]},
        )
        self.assertIn("The uploaded prescription lists the following medicines:", sum_multi)
        self.assertIn("- metformin 500 mg, twice daily.", sum_multi)
        self.assertIn("- lisinopril 10 mg, once daily.", sum_multi)
        self.assertNotIn("Only one medicine ingredient was available", sum_multi)

        # 3. Non-glucose laboratory input: Potassium missing value & unit
        dlti_potassium = {
            "status": "DLTI_COMPLETE",
            "coverage": {"pairs_evaluated": 1, "rules_triggered": 0, "rules_insufficient_context": 1, "coverage_label": "RESEARCH_PREVIEW_INSUFFICIENT_CONTEXT"},
            "results": [{"rule_id": "DLTI_POTASSIUM_TEST", "status": "DLTI_INSUFFICIENT_CONTEXT"}],
            "lab_input_provenance": [{
                "submitted_analyte": "Potassium",
                "submitted_value": None,
                "submitted_unit": None,
                "validation_status": "REJECTED_MISSING_VALUE",
            }],
        }
        sum_potassium = PrescriptionReasoningAgent.generate_deterministic_summary(
            verified_meds=med_atorvastatin,
            unverified_meds=[],
            overall_status="verified",
            ddi={"overall_status": "no_pairs", "coverage": {"total_pairs_checked": 0, "resolved_ingredients_count": 1, "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION"}},
            dlti=dlti_potassium,
        )
        patient_k = sum_potassium[:sum_potassium.find("## 🔬 Technical Details and Evidence")]
        self.assertIn("The Potassium check could not be completed because the test result and unit were not provided.", patient_k)
        self.assertIn("- The Potassium result and unit were missing, so the check could not be completed. This neither establishes nor rules out a problem.", patient_k)
        self.assertNotIn("blood sugar", patient_k.lower())
        self.assertNotIn("glucose", patient_k.lower())

        # 4. Verify PDF structure on multi-drug output
        pdf_bytes = build_analysis_pdf(sum_multi, kind="medicine")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertGreaterEqual(len(doc), 2)
        self.assertNotIn("Technical Details and Evidence", doc[0].get_text())
        self.assertIn("Technical Details and Evidence", doc[1].get_text())


if __name__ == "__main__":
    unittest.main()


