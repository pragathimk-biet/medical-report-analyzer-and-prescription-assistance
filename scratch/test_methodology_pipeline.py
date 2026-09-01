"""
===============================================================================
UPDATED OVERALL PROJECT METHODOLOGY (FIG. 1) VERIFICATION TEST SUITE
===============================================================================

Comprehensive Unit Tests for all 6 Methodology Stages:
  Stage 1: Input & Routing (InputRouter)
  Stage 2: Extraction & Preprocessing (Image Enhancement + Model 2 MobileNetV2 Handwriting Cross-Check)
  Stage 3: Verification (Model 1 Report Reliability Classifier + RapidFuzz RxNorm + 37 Biomarkers)
  Stage 4: Reasoning & Safety (Reasoning Agent + Mandatory Guardrail Agent)
  Stage 5: Cross-Visit Safety & Interaction (2-Way Correlator + UUID Patient State Store)
  Stage 6: Patient Interaction (Custom RAG Chatbot Retrieval)
"""

import os
import sys
import unittest
import numpy as np

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from input_router import InputRouter, create_pipeline_context
from report_extraction_agent import ReportExtractionAgent, preprocess_image_grayscale_denoise_deskew
from handwriting_drug_classifier import HandwritingDrugClassifierAgent, MobileNetV2HandwritingClassifier
from tabular_ml_engine import TabularMLAgent, predict_finding_safety
from prescription_verification_agent import PrescriptionVerificationAgent, rxnorm_rapidfuzz_verify_drug
from patient_history import PatientHistoryManager, TRUSTED_MEDICATION_DATABASE
from rule_engine import MedicalRuleEngine
from app import PatientHistoryRAGChatbot, sanitize_llm_explanation

class TestMethodologyPipeline(unittest.TestCase):

    # -------------------------------------------------------------------------
    # STAGE 1: INPUT AND ROUTING
    # -------------------------------------------------------------------------
    def test_stage1_input_router_report(self):
        text = "Serum Creatinine: 1.1 mg/dL\nFasting Blood Glucose: 95.0 mg/dL"
        res = InputRouter.classify_document(text=text)
        self.assertEqual(res.get("document_type"), "medical_report")

    def test_stage1_input_router_prescription(self):
        text = "Rx:\nTab Amoxicillin 500 mg - 1-0-1 for 7 days"
        res = InputRouter.classify_document(text=text)
        self.assertEqual(res.get("document_type"), "prescription")

    # -------------------------------------------------------------------------
    # STAGE 2: EXTRACTION & PREPROCESSING (IMAGE ENHANCEMENT + MODEL 2 MOBILENETV2)
    # -------------------------------------------------------------------------
    def test_stage2_image_enhancement_grayscale_denoise(self):
        dummy_img = np.full((100, 100, 3), 220, dtype=np.uint8)
        enhanced = preprocess_image_grayscale_denoise_deskew(dummy_img)
        self.assertIsNotNone(enhanced)
        self.assertEqual(len(enhanced.shape), 2)

    def test_stage2_model2_mobilenetv2_handwriting_cross_check(self):
        score = MobileNetV2HandwritingClassifier.evaluate_visual_embedding_similarity("amoxicillin", "amoxicillin", "Amoxicillin (Amoxil)")
        self.assertEqual(score, 1.0)

    # -------------------------------------------------------------------------
    # STAGE 3: VERIFICATION (MODEL 1 REPORT RELIABILITY CLASSIFIER + RAPIDFUZZ RXNORM)
    # -------------------------------------------------------------------------
    def test_stage3_model1_report_reliability_classifier(self):
        finding = {
            "test_name": "Serum Creatinine",
            "result_value": 1.1,
            "unit": "mg/dL",
            "reference_text": "0.7 - 1.3 mg/dL",
            "ocr_confidence": 0.95
        }
        res = predict_finding_safety(finding)
        self.assertIsNotNone(res)

    def test_stage3_rapidfuzz_rxnorm_drug_verification(self):
        best_match, score, status = rxnorm_rapidfuzz_verify_drug("amoxicillin")
        self.assertEqual(best_match, "Amoxicillin")
        self.assertGreaterEqual(score, 0.80)
        self.assertEqual(status, "verified")

    def test_stage3_37_biomarkers_rule_engine_validation(self):
        engine = MedicalRuleEngine()
        res = engine.parse_and_evaluate("Serum Creatinine: 1.1 mg/dL\nReference Range: 0.7 - 1.3 mg/dL")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].get("status"), "NORMAL")

    # -------------------------------------------------------------------------
    # STAGE 4: REASONING AND SAFETY (GUARDRAIL AGENT MANDATORY RUN)
    # -------------------------------------------------------------------------
    def test_stage4_guardrail_agent_diagnostic_rewrite(self):
        raw_llm_text = "The patient has been diagnosed with renal failure and kidney failure."
        guarded = sanitize_llm_explanation(raw_llm_text, None)
        self.assertNotIn("diagnosed with renal failure", guarded)
        self.assertNotIn("kidney failure", guarded)
        self.assertIn("medical evaluation", guarded)

    # -------------------------------------------------------------------------
    # STAGE 5: CROSS-VISIT SAFETY AND INTERACTION (2-WAY CORRELATOR + UUID STORE)
    # -------------------------------------------------------------------------
    def test_stage5_cross_visit_safety_hyperkalemia_check(self):
        patient_mgr = PatientHistoryManager()
        lab_res = [{"key": "potassium", "normalized_test_name": "potassium", "parameter": "Serum Potassium", "result_value": 6.5, "value": 6.5, "unit": "mmol/L", "status": "HIGH"}]
        patient_mgr.add_lab_results(lab_res, patient_name="test_patient_uuid")
        alerts = patient_mgr.check_prescription_against_past_labs("Spironolactone", patient_name="test_patient_uuid")
        self.assertTrue(any(a.get("severity") in ["HIGH", "CRITICAL"] for a in alerts))

    # -------------------------------------------------------------------------
    # STAGE 6: PATIENT INTERACTION (CUSTOM RAG CHATBOT RETRIEVAL)
    # -------------------------------------------------------------------------
    def test_stage6_custom_rag_chatbot_retrieval(self):
        patient_mgr = PatientHistoryManager()
        patient_mgr.add_active_medication("Amoxicillin", "500 mg", patient_name="rag_patient_123")
        response = PatientHistoryRAGChatbot.answer_patient_query("rag_patient_123", "What medications am I taking?")
        self.assertIsNotNone(response)
        self.assertIn("Amoxicillin", response)
        self.assertIn("consult", response.lower())

if __name__ == "__main__":
    unittest.main()
