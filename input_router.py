"""
===============================================================================
STEP 1: FOUNDATION — INPUT ROUTER & COMMON PIPELINE INTERFACE
===============================================================================

This module defines the Foundation Input Router and Standardized Pipeline Context
for the target modular architecture:

Target Architecture:
  Patient Upload
         │
         ▼
    Input Router
         │
         ├───────────────────────┐
         ▼                       ▼
   Report Pipeline     Prescription Pipeline
  (Future Steps)          (Future Steps)
"""

import re
import logging

logger = logging.getLogger(__name__)

SUPPORTED_DOCUMENT_TYPES = ["medical_report", "prescription", "unsupported"]

def create_pipeline_context(document_type="unsupported", raw_input="", metadata=None):
    """
    Creates the standardized pipeline payload context used across stages.
    
    Structure:
    {
        "document_type": "medical_report" | "prescription" | "unsupported",
        "raw_input": str,
        "metadata": dict,
        "extracted_data": dict,
        "handwriting": dict,
        "verification": dict,
        "safety": dict,
        "reasoning": dict,
        "warnings": list,
        "errors": list
    }
    """
    return {
        "document_type": document_type,
        "raw_input": raw_input or "",
        "metadata": metadata or {},
        "extracted_data": {},
        "handwriting": {},
        "verification": {},
        "safety": {},
        "reasoning": {},
        "warnings": [],
        "errors": []
    }

class InputRouter:
    """
    Step 1 Foundation Input Router.
    Determines whether an incoming payload/document is a medical_report or prescription.
    """
    
    # Keyword indicators for classification
    PRESCRIPTION_KEYWORDS = [
        r'\brx\b', r'\bprescription\b', r'\btab\b', r'\btablet\b', r'\bcap\b',
        r'\bcapsule\b', r'\bsyrup\b', r'\bdosage\b', r'\bmg\b', r'\bml\b',
        r'\b1-0-1\b', r'\b0-0-1\b', r'\b1-0-0\b', r'\btake after meals\b',
        r'\bdispense\b', r'\bsig\b', r'\bdr\.\s+[a-z]+'
    ]

    REPORT_KEYWORDS = [
        r'\blab ref\b', r'\bbiochemistry\b', r'\bhaematology\b', r'\bserum\b',
        r'\b blood\b', r'\breference range\b', r'\btest parameter\b', r'\bresult\(s\)\b',
        r'\bmg\/dl\b', r'\bmmol\/l\b', r'\bg\/dl\b', r'\bu\/l\b', r'\banalyte\b',
        r'\bcreatinine\b', r'\burea\b', r'\bglucose\b', r'\bhemoglobin\b', r'\bhba1c\b'
    ]

    @classmethod
    def classify_document(cls, text="", filename="", explicit_type=None):
        """
        Classifies an input document into 'medical_report', 'prescription', or 'unsupported'.
        
        Routing Logic:
        1. Explicit route signal (if provided from specialized upload route).
        2. Content-based keyword matching on text.
        3. Filename indicators (e.g., 'rx_', 'prescription').
        4. Fallback default.
        """
        if explicit_type in ["medical_report", "prescription"]:
            return {"document_type": explicit_type}

        if not text and not filename:
            return {"document_type": "unsupported", "error": "Empty input provided."}

        text_lower = (text or "").lower()
        filename_lower = (filename or "").lower()

        rx_score = 0
        report_score = 0

        # Filename heuristics
        if "rx" in filename_lower or "prescription" in filename_lower:
            rx_score += 3
        if "report" in filename_lower or "lab" in filename_lower:
            report_score += 2

        # Keyword heuristics
        for kw in cls.PRESCRIPTION_KEYWORDS:
            if re.search(kw, text_lower):
                rx_score += 1

        for kw in cls.REPORT_KEYWORDS:
            if re.search(kw, text_lower):
                report_score += 1

        logger.debug(f"InputRouter Classification Scores -> Prescription: {rx_score}, Medical Report: {report_score}")

        if rx_score > report_score and rx_score >= 2:
            return {"document_type": "prescription"}
        elif report_score > 0 or "medical" in text_lower or "hospital" in text_lower:
            return {"document_type": "medical_report"}
        elif rx_score > 0:
            return {"document_type": "prescription"}

        # Default fallback for valid text
        if text and len(text.strip()) > 0:
            return {"document_type": "medical_report"}

        return {"document_type": "unsupported"}

    @classmethod
    def route_and_create_context(cls, text="", filename="", explicit_type=None, metadata=None):
        """Routes input and returns a pre-populated Pipeline Context dictionary."""
        classification = cls.classify_document(text=text, filename=filename, explicit_type=explicit_type)
        doc_type = classification.get("document_type", "unsupported")
        ctx = create_pipeline_context(document_type=doc_type, raw_input=text, metadata=metadata)
        if "error" in classification:
            ctx["errors"].append(classification["error"])
        return ctx


# ===============================================================================
# FUTURE COMPONENT BOUNDARY / INTERFACE STUBS (Prepared for Step 2+)
# ===============================================================================

class ReportExtractionAgentBoundary:
    """Interface boundary linking to Step 2 Report Extraction Agent."""
    @staticmethod
    def extract(pipeline_ctx, ocr_extractor_func=None):
        from report_extraction_agent import ReportExtractionAgent
        return ReportExtractionAgent.process(pipeline_ctx, ocr_extractor_func=ocr_extractor_func)

class ReportVerificationAgentBoundary:
    """Interface boundary linking to Step 3 Report Verification Agent."""
    @staticmethod
    def verify(pipeline_ctx):
        from report_verification_agent import ReportVerificationAgent
        return ReportVerificationAgent.process(pipeline_ctx)

class MLSafetyAgentBoundary:
    """Interface boundary linking to Step 4 ML Safety & Reliability Classifier Agent."""
    @staticmethod
    def evaluate_safety(pipeline_ctx):
        from ml_safety_agent import MLSafetyAgent
        return MLSafetyAgent.evaluate_safety(pipeline_ctx)

class ReportReasoningAgentBoundary:
    """Interface boundary linking to Step 5 Report Reasoning Agent."""
    @staticmethod
    def reason(pipeline_ctx, ai_generator_func=None):
        from report_reasoning_agent import ReportReasoningAgent
        return ReportReasoningAgent.process(pipeline_ctx, ai_generator_func=ai_generator_func)

class HandwritingDrugClassifierBoundary:
    """Interface boundary linking to Step 3 Handwriting Drug Classifier Agent."""
    @staticmethod
    def classify_handwriting(pipeline_ctx):
        """
        Executes Handwriting Drug Classifier Agent on prescription pipeline context.
        """
        from handwriting_drug_classifier import HandwritingDrugClassifierAgent
        return HandwritingDrugClassifierAgent.process(pipeline_ctx)

class PrescriptionReasoningBoundary:
    """Interface boundary linking to Step 5 Prescription Reasoning Agent."""
    @staticmethod
    def reason_prescription(pipeline_ctx, ai_generator_func=None):
        """
        Executes Prescription Reasoning Agent on prescription pipeline context.
        """
        from prescription_reasoning_agent import PrescriptionReasoningAgent
        return PrescriptionReasoningAgent.process(pipeline_ctx, ai_generator_func=ai_generator_func)

class PrescriptionPipelineBoundary:
    """Interface boundary linking to Step 2, Step 3, Step 4 & Step 5 Prescription Pipeline."""
    @staticmethod
    def process_prescription(pipeline_ctx, ocr_extractor_func=None, ai_generator_func=None):
        """
        Executes Prescription Extraction, Handwriting Drug Classifier, Prescription Verification, and Prescription Reasoning.
        """
        from prescription_extraction_agent import PrescriptionExtractionAgent
        from handwriting_drug_classifier import HandwritingDrugClassifierAgent
        from prescription_verification_agent import PrescriptionVerificationAgent
        from prescription_reasoning_agent import PrescriptionReasoningAgent

        pipeline_ctx = PrescriptionExtractionAgent.process(pipeline_ctx, ocr_extractor_func=ocr_extractor_func)
        pipeline_ctx = HandwritingDrugClassifierAgent.process(pipeline_ctx)
        pipeline_ctx = PrescriptionVerificationAgent.process(pipeline_ctx)
        pipeline_ctx = PrescriptionReasoningAgent.process(pipeline_ctx, ai_generator_func=ai_generator_func)
        return pipeline_ctx
