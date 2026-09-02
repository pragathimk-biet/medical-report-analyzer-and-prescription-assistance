"""
===============================================================================
TABULAR ML ENGINE & AGENT FOR MEDICAL REPORT FINDING SAFETY CLASSIFICATION
===============================================================================

Provides feature extraction, inference pipeline loading, and the TabularMLAgent
to classify extracted laboratory findings into:
  - safe_to_display
  - needs_manual_review
  - hard_stop

Strict Governance Guarantee:
----------------------------
Deterministic validation remains the final safety authority.
ML predictions NEVER override a deterministic hard_stop or severe rule conflict.
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

from finding_validator import ANALYTE_VALIDATION_REGISTRY

logger = logging.getLogger(__name__)

MODEL_FILE = "tabular_ml_model.joblib"
_cached_pipeline = None

FEATURE_NAMES = [
    'value',
    'unit_validity',
    'ref_range_validity',
    'ocr_confidence',
    'extraction_confidence',
    'evidence_availability',
    'rule_conflict',
    'analyte_validity'
]

CLASS_MAP = {
    0: 'safe_to_display',
    1: 'needs_manual_review',
    2: 'hard_stop'
}

def load_tabular_ml_model():
    """Loads and caches the saved Tabular ML Model pipeline from disk."""
    global _cached_pipeline
    if _cached_pipeline is not None:
        return _cached_pipeline

    if not os.path.exists(MODEL_FILE):
        logger.warning(f"Model file '{MODEL_FILE}' not found. Training model now...")
        from train_tabular_ml import train_and_evaluate_models
        train_and_evaluate_models()

    try:
        _cached_pipeline = joblib.load(MODEL_FILE)
        logger.info(f"Successfully loaded Tabular ML model '{_cached_pipeline.get('model_name')}' from {MODEL_FILE}")
        return _cached_pipeline
    except Exception as e:
        logger.error(f"Failed to load Tabular ML model: {e}")
        return None

def extract_finding_features(finding, ocr_confidence=0.95):
    """
    Extracts numerical feature vector for a single lab finding.
    
    Returns:
      pandas.DataFrame with single row containing FEATURE_NAMES.
    """
    # 1. Numerical Value
    raw_val = finding.get('result_value', finding.get('value', 0.0))
    rule_conf = 0.0
    try:
        if raw_val is not None and not isinstance(raw_val, (int, float)):
            val = float(raw_val)
        else:
            val = float(raw_val) if raw_val is not None else 0.0
    except Exception:
        val = 0.0
        rule_conf = 1.0  # Malformed string value triggers rule conflict / fail-safe

    # 2. Unit Validity
    unit = str(finding.get('unit', '') or '').strip().lower()
    norm_name = str(finding.get('normalized_test_name', finding.get('key', '')) or '').strip().lower()
    unit_val = 1.0
    if norm_name in ANALYTE_VALIDATION_REGISTRY:
        reg_units = [u.lower() for u in ANALYTE_VALIDATION_REGISTRY[norm_name].get('valid_units', [])]
        if reg_units and unit and unit not in reg_units:
            unit_val = 0.0
    elif not unit and val != 0.0:
        unit_val = 0.0

    # 3. Reference Range Validity
    ref_status = str(finding.get('reference_status', '')).upper()
    range_desc = str(finding.get('range_description', '')).strip()
    ref_val = 1.0
    if ref_status in ['NOT_AVAILABLE', 'INVALID', 'REJECTED'] or not range_desc:
        ref_val = 0.0

    # 4. OCR Confidence
    ocr_conf = float(finding.get('ocr_confidence', ocr_confidence if ocr_confidence is not None else 0.95))

    # 5. Extraction Confidence
    ext_conf = float(finding.get('extraction_confidence', 0.95))

    # 6. Evidence Availability
    ev_line = finding.get('raw_line', finding.get('evidence', ''))
    ev_avail = 1.0 if (ev_line and str(ev_line).strip()) else 0.0

    # 7. Rule Conflict & Biological Plausibility
    if norm_name in ANALYTE_VALIDATION_REGISTRY:
        min_p = ANALYTE_VALIDATION_REGISTRY[norm_name].get('min_plausible', -1e9)
        max_p = ANALYTE_VALIDATION_REGISTRY[norm_name].get('max_plausible', 1e9)
        if val < min_p or val > max_p:
            rule_conf = 1.0
    if val < 0.0 or val >= 9999.0 or finding.get('status_conflict') or finding.get('rule_conflict'):
        rule_conf = 1.0

    # 8. Analyte Validity
    analyte_val = 1.0 if (norm_name in ANALYTE_VALIDATION_REGISTRY or finding.get('test_name')) else 0.0

    feature_dict = {
        'value': val,
        'unit_validity': unit_val,
        'ref_range_validity': ref_val,
        'ocr_confidence': ocr_conf,
        'extraction_confidence': ext_conf,
        'evidence_availability': ev_avail,
        'rule_conflict': rule_conf,
        'analyte_validity': analyte_val
    }

    return pd.DataFrame([feature_dict])[FEATURE_NAMES]

def predict_finding_safety(finding, ocr_confidence=0.95):
    """
    Predicts safety category for a lab finding:
      - safe_to_display
      - needs_manual_review
      - hard_stop
      
    Guarantees deterministic safety authority: Deterministic hard_stop or rule conflict
    can NEVER be overridden to 'safe_to_display'.
    """
    features_df = extract_finding_features(finding, ocr_confidence=ocr_confidence)
    pipeline_obj = load_tabular_ml_model()

    if pipeline_obj is None:
        # Safe fallback if model is unavailable
        return {
            'ml_safety_class': 'needs_manual_review',
            'confidence': 0.50,
            'probabilities': {'safe_to_display': 0.33, 'needs_manual_review': 0.34, 'hard_stop': 0.33},
            'features': features_df.iloc[0].to_dict()
        }

    clf = pipeline_obj['model']
    scaler = pipeline_obj.get('scaler')

    if scaler is not None:
        scaled_features = scaler.transform(features_df)
        pred_class_idx = int(clf.predict(scaled_features)[0])
        probs = clf.predict_proba(scaled_features)[0]
    else:
        pred_class_idx = int(clf.predict(features_df)[0])
        probs = clf.predict_proba(features_df)[0]

    predicted_class = CLASS_MAP.get(pred_class_idx, 'needs_manual_review')
    confidence_score = round(float(probs[pred_class_idx]), 4)

    # === DETERMINISTIC SAFETY GOVERNANCE LAYER ===
    # Rule: ML model must never override a deterministic hard_stop or severe rule conflict.
    rule_conflict = features_df.iloc[0]['rule_conflict']
    unit_validity = features_df.iloc[0]['unit_validity']
    ocr_conf = features_df.iloc[0]['ocr_confidence']

    if rule_conflict == 1.0 or unit_validity == 0.0 or ocr_conf < 0.50:
        predicted_class = 'hard_stop'
        confidence_score = max(confidence_score, 0.99)
    elif ocr_conf < 0.80 and predicted_class == 'safe_to_display':
        predicted_class = 'needs_manual_review'

    prob_dict = {
        CLASS_MAP[i]: round(float(probs[i]), 4) for i in range(len(probs))
    }

    return {
        'ml_safety_class': predicted_class,
        'confidence': confidence_score,
        'probabilities': prob_dict,
        'features': features_df.iloc[0].to_dict()
    }

class TabularMLAgent:
    """Agent: Tabular ML Finding Safety Classification & Governance Agent."""
    @staticmethod
    def predict_finding_safety(finding, ocr_confidence=0.95, model_pipeline=Ellipsis):
        if model_pipeline is None:
            return {
                'predicted_class': 'needs_manual_review',
                'ml_safety_class': 'needs_manual_review',
                'confidence': 0.50
            }
        res = predict_finding_safety(finding, ocr_confidence=ocr_confidence)
        res['predicted_class'] = res.get('ml_safety_class')
        return res

    @staticmethod
    def evaluate_report(eval_results, ocr_metadata=None):
        """
        Evaluates safety classification for all extracted laboratory findings in a report.
        """
        if not eval_results or not isinstance(eval_results, list):
            return {
                'overall_safety': 'safe_to_display',
                'findings_evaluation': []
            }

        avg_ocr_conf = 0.95
        if ocr_metadata and isinstance(ocr_metadata, list) and len(ocr_metadata) > 0:
            confs = [item.get('confidence', 0.95) for item in ocr_metadata if isinstance(item, dict)]
            if confs:
                avg_ocr_conf = sum(confs) / len(confs)

        evaluations = []
        has_hard_stop = False
        has_manual_review = False

        for finding in eval_results:
            ml_res = predict_finding_safety(finding, ocr_confidence=avg_ocr_conf)
            finding['ml_safety_class'] = ml_res['ml_safety_class']
            finding['ml_safety_confidence'] = ml_res['confidence']

            evaluations.append({
                'test_name': finding.get('test_name', 'Unknown'),
                'value': finding.get('result_value', finding.get('value')),
                'unit': finding.get('unit'),
                'status': finding.get('status'),
                'ml_safety_class': ml_res['ml_safety_class'],
                'confidence': ml_res['confidence'],
                'probabilities': ml_res['probabilities']
            })

            if ml_res['ml_safety_class'] == 'hard_stop':
                has_hard_stop = True
            elif ml_res['ml_safety_class'] == 'needs_manual_review':
                has_manual_review = True

        if has_hard_stop:
            overall = 'hard_stop'
        elif has_manual_review:
            overall = 'needs_manual_review'
        else:
            overall = 'safe_to_display'

        return {
            'overall_safety': overall,
            'findings_evaluation': evaluations
        }
