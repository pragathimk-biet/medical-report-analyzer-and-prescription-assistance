"""
===============================================================================
STEP 4: ML SAFETY / RELIABILITY CLASSIFIER AGENT
===============================================================================

This module provides the ML Safety & Governance Classifier for the target pipeline:

  Patient Upload
        │
        ▼
   Input Router
        │
        ▼
Report Extraction Agent
        │
        ▼
Report Verification Agent
        │
        ▼
[ ML Safety / Reliability Classifier ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["safety"]

STRICT SAFETY & GOVERNANCE RULES:
---------------------------------
  1. This is a SAFETY/RELIABILITY GOVERNANCE classifier, NOT a disease diagnosis model,
     clinical prediction model, or replacement for a doctor.
  2. Deterministic Safety Authority Guarantee: Deterministic hard_stop or rule conflict
     can NEVER be overridden to 'safe_to_display' by ML.
  3. Failure-Safe Behavior: If the model file is missing, errored, or features are malformed,
     the agent fails safe to 'needs_manual_review'.
"""

import os
import logging
import pandas as pd
import numpy as np

from tabular_ml_engine import (
    load_tabular_ml_model,
    extract_finding_features,
    predict_finding_safety,
    CLASS_MAP,
    MODEL_FILE
)

logger = logging.getLogger(__name__)

class MLSafetyAgent:
    """
    Step 4 ML Safety & Reliability Classifier Agent.
    Processes pipeline_context["verification"] and classifies overall report/finding
    reliability into 'safe_to_display', 'needs_manual_review', or 'hard_stop'.
    """

    @classmethod
    def evaluate_safety(cls, pipeline_context):
        """
        Evaluates safety/reliability classification on pipeline_context.
        
        Populates context["safety"]:
        {
            "safety_status": "safe_to_display" | "needs_manual_review" | "hard_stop",
            "confidence": float,
            "classification_confidence": float,
            "reason_codes": [str],
            "model_version": str,
            "evaluated_findings": [dict],
            "hard_stop_triggered": bool,
            "warnings": [str],
            "errors": [str]
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        verification_data = pipeline_context.get("verification", {})
        verified_biomarkers = verification_data.get("biomarkers", [])
        overall_ocr_conf = float(extracted_data.get("confidence", 0.95))

        reason_codes = []
        warnings = []
        errors = []
        evaluated_findings = []
        
        # Check if model loads cleanly
        pipeline_obj = None
        model_version = "Scikit-Learn DecisionTree 1.0 (Unavailable)"
        try:
            pipeline_obj = load_tabular_ml_model()
            if pipeline_obj:
                model_name = pipeline_obj.get('model_name', 'DecisionTree')
                model_version = f"Scikit-Learn {model_name} 1.0"
        except Exception as e:
            logger.warning(f"ML Model load exception: {e}")
            warnings.append(f"ML model loading failed ({e}). Failing safe to needs_manual_review.")

        # Fail safe if no biomarkers or invalid input
        if not verified_biomarkers:
            reason_codes.append("empty_or_unverified_input")
            warnings.append("No verified biomarkers available for ML safety classification.")
            pipeline_context["safety"] = {
                "safety_status": "needs_manual_review",
                "confidence": 0.50,
                "classification_confidence": 0.50,
                "reason_codes": reason_codes,
                "model_version": model_version,
                "evaluated_findings": [],
                "hard_stop_triggered": False,
                "warnings": warnings,
                "errors": errors
            }
            return pipeline_context

        has_deterministic_hard_stop = (verification_data.get("overall_status") == "hard_stop")
        has_manual_review = False
        min_conf = 1.0
        conf_sum = 0.0

        for verif_bm in verified_biomarkers:
            finding_dict = {
                "test_name": verif_bm.get("name", "Unknown"),
                "normalized_test_name": verif_bm.get("normalized_name", ""),
                "result_value": verif_bm.get("value"),
                "unit": verif_bm.get("unit", ""),
                "range_description": verif_bm.get("reference_range", ""),
                "reference_status": "AVAILABLE" if verif_bm.get("reference_source") != "unavailable" else "NOT_AVAILABLE",
                "ocr_confidence": verif_bm.get("confidence", overall_ocr_conf),
                "extraction_confidence": verif_bm.get("confidence", overall_ocr_conf),
                "evidence": verif_bm.get("source_text", ""),
                "rule_conflict": 1.0 if verif_bm.get("verification_status") in ["invalid", "suspicious"] else 0.0
            }

            # 1. Deterministic Hard-Stop Check (Precedence Rule)
            verif_status = verif_bm.get("verification_status")
            if not isinstance(verif_bm, dict) or verif_bm.get("name") is None or not isinstance(verif_bm.get("value"), (int, float, type(None))):
                has_manual_review = True
                pred_class = "needs_manual_review"
                class_conf = 0.50
                reason_codes.append("malformed_or_corrupted_finding")
            elif verif_status in ["invalid", "suspicious"]:
                has_deterministic_hard_stop = True
                pred_class = "hard_stop"
                class_conf = 0.99
                reason_codes.append(f"deterministic_{verif_status}_{str(verif_bm.get('name', 'biomarker')).lower().replace(' ', '_')}")
            elif verif_status in ["unverified", "unknown", "reference_range_unavailable", "unit_missing"] or verif_status is None:
                has_manual_review = True
                pred_class = "needs_manual_review"
                class_conf = 0.85
                reason_codes.append(f"verification_{verif_status or 'unverified'}")
            elif pipeline_obj is None:
                # Model unavailable -> fail safe
                pred_class = "needs_manual_review"
                class_conf = 0.50
                reason_codes.append("model_unavailable_fail_safe")
                has_manual_review = True
            else:
                try:
                    ml_res = predict_finding_safety(finding_dict, ocr_confidence=overall_ocr_conf)
                    pred_class = ml_res["ml_safety_class"]
                    class_conf = float(ml_res["confidence"])
                except Exception as ml_err:
                    logger.warning(f"ML prediction error on {verif_bm.get('name')}: {ml_err}")
                    pred_class = "needs_manual_review"
                    class_conf = 0.50
                    warnings.append(f"Prediction error on {verif_bm.get('name')}: {ml_err}")
                    has_manual_review = True

            # Enforce Deterministic Hard Stop Overriding ML
            if verif_status in ["invalid", "suspicious"]:
                pred_class = "hard_stop"
                has_deterministic_hard_stop = True

            if pred_class == "hard_stop":
                has_deterministic_hard_stop = True
            elif pred_class == "needs_manual_review":
                has_manual_review = True

            min_conf = min(min_conf, class_conf)
            conf_sum += class_conf

            evaluated_findings.append({
                "name": verif_bm.get("name"),
                "value": verif_bm.get("value"),
                "unit": verif_bm.get("unit"),
                "verification_status": verif_status,
                "ml_safety_class": pred_class,
                "confidence": class_conf
            })

        # Calculate overall safety classification
        avg_conf = round(conf_sum / len(evaluated_findings), 4) if evaluated_findings else 0.50

        if has_deterministic_hard_stop:
            overall_safety = "hard_stop"
            if "critical_rule_conflict_or_invalid_value" not in reason_codes:
                reason_codes.append("critical_rule_conflict_or_invalid_value")
        elif has_manual_review or overall_ocr_conf < 0.80:
            overall_safety = "needs_manual_review"
            if overall_ocr_conf < 0.80:
                reason_codes.append("low_ocr_confidence_requires_review")
            else:
                reason_codes.append("minor_verification_uncertainty")
        else:
            overall_safety = "safe_to_display"
            reason_codes.extend([
                "all_key_findings_verified",
                "reference_ranges_available",
                "high_extraction_confidence"
            ])

        # De-duplicate reason codes
        reason_codes = list(dict.fromkeys(reason_codes))

        pipeline_context["safety"] = {
            "safety_status": overall_safety,
            "confidence": avg_conf,
            "classification_confidence": avg_conf,
            "reason_codes": reason_codes,
            "model_version": model_version,
            "evaluated_findings": evaluated_findings,
            "hard_stop_triggered": has_deterministic_hard_stop,
            "warnings": warnings,
            "errors": errors
        }

        if warnings:
            pipeline_context["warnings"].extend(warnings)

        return pipeline_context
