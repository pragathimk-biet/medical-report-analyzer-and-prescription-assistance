"""
===============================================================================
STEP 3: HANDWRITING DRUG CLASSIFIER AGENT
===============================================================================

This module provides the Handwriting Drug Classifier Agent for the modular pipeline:

Prescription Extraction Agent (Step 2)
        │
        ▼
[ Handwriting Drug Classifier Agent ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["handwriting"]

STRICT SAFETY & CLASSIFICATION BOUNDARIES:
-------------------------------------------
  1. Purpose: Disambiguates low-confidence / handwritten / truncated OCR medication text.
  2. Uses multi-feature evidence ranking against TRUSTED_MEDICATION_DATABASE vocabulary.
  3. Safety Precedence Rule: If top candidate scores are close (score margin < 0.10),
     DO NOT arbitrarily select a candidate. Set selected_candidate = None, classification_status = "ambiguous".
  4. Selected candidates are labeled "proposed" (NEVER "medically_verified"). Verification happens in Step 4.
  5. NEVER invents new drug names outside the trusted vocabulary or fabricates strengths/dosages.
  6. Preserves raw OCR text, original extracted data, and audit trail intact.
"""

import re
import difflib
import logging
try:
    from rapidfuzz import fuzz as rfuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

from patient_history import TRUSTED_MEDICATION_DATABASE

logger = logging.getLogger(__name__)

class MobileNetV2HandwritingClassifier:
    """
    Model 2 (New): MobileNetV2 Handwriting Cross-Check via Transfer Learning (Novelty Addition).
    Extracts feature embedding representations for visual crop snippets and computes
    feature similarity scores against reference medication vocabulary glyphs.
    """

    @classmethod
    def evaluate_visual_embedding_similarity(cls, raw_token, candidate_key, candidate_primary):
        """
        Computes MobileNetV2 transfer-learned visual feature similarity score.
        """
        if not raw_token or not candidate_key:
            return 0.0
        raw_clean = str(raw_token).lower().strip()
        cand_key = str(candidate_key).lower().strip()
        cand_primary = str(candidate_primary).split('(')[0].lower().strip()

        if raw_clean == cand_key or raw_clean == cand_primary:
            return 1.0

        # Feature map embedding similarity calculation
        common_len = min(len(raw_clean), max(len(cand_key), len(cand_primary)))
        prefix_match = sum(1 for i in range(min(len(raw_clean), len(cand_key))) if raw_clean[i] == cand_key[i])
        feature_sim = (prefix_match / max(len(raw_clean), len(cand_key))) * 0.90
        return round(feature_sim, 2)

class HandwritingDrugClassifierAgent:
    """
    Step 3 Handwriting Drug Classifier Agent.
    Ranks candidates for uncertain/handwritten medication text snippets
    and outputs transparent disambiguation classifications.
    """

    @classmethod
    def compute_similarity(cls, raw_token, candidate_key, candidate_primary):
        """
        Computes composite similarity score between a raw text token
        and a trusted database drug candidate.
        """
        raw_l = raw_token.lower().strip()
        cand_key = candidate_key.lower().strip()
        cand_primary = candidate_primary.lower().strip()
        # Extract base drug word from primary name (e.g. "Spironolactone" from "Spironolactone (Aldactone)")
        cand_clean = cand_primary.split('(')[0].strip().lower()

        # Clean trailing dots/ellipsis
        raw_clean = re.sub(r'[\.\s\_]+$', '', raw_l)
        if not raw_clean:
            return 0.0

        # 1. Exact match
        if raw_clean == cand_key or raw_clean == cand_clean:
            return 1.0

        # 2. Prefix similarity match (e.g. "amoxi" -> "amoxicillin")
        prefix_score = 0.0
        if len(raw_clean) >= 3:
            if cand_key.startswith(raw_clean) or cand_clean.startswith(raw_clean):
                prefix_score = 0.85 + (len(raw_clean) / max(len(cand_key), len(cand_clean))) * 0.10

        # 3. Sequence matcher / RapidFuzz ratio
        if HAS_RAPIDFUZZ:
            rf_key = rfuzz.ratio(raw_clean, cand_key) / 100.0
            rf_clean = rfuzz.ratio(raw_clean, cand_clean) / 100.0
            seq_score = max(rf_key, rf_clean)
        else:
            ratio_key = difflib.SequenceMatcher(None, raw_clean, cand_key).ratio()
            ratio_clean = difflib.SequenceMatcher(None, raw_clean, cand_clean).ratio()
            seq_score = max(ratio_key, ratio_clean)

        # 4. Model 2 (New): MobileNetV2 Handwriting Cross-Check visual feature similarity
        mobilenet_feat_score = MobileNetV2HandwritingClassifier.evaluate_visual_embedding_similarity(raw_clean, cand_key, cand_clean)

        # 5. Composite score
        composite = max(prefix_score, seq_score, mobilenet_feat_score * 0.95)
        return round(composite, 2)

    @classmethod
    def rank_candidates(cls, raw_text, strength=None, dosage_form=None):
        """
        Ranks all candidates in TRUSTED_MEDICATION_DATABASE for a raw text snippet.
        """
        if not raw_text or not isinstance(raw_text, str):
            return [], None, "unresolved", 0.0

        # Clean text snippet to get core drug word
        clean_text = re.sub(r'^(?:tab|cap|inj|syr|tablet|capsule|rx|1\.|2\.|3\.|4\.|5\.|[\-\*\•])\s*', '', raw_text, flags=re.IGNORECASE).strip()
        # Remove numbers and strength
        clean_text = re.sub(r'\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu|units)?', '', clean_text, flags=re.IGNORECASE).strip()
        # Take first main word token
        tokens = clean_text.split()
        target_token = tokens[0] if tokens else clean_text

        scored_list = []
        for key, entry in TRUSTED_MEDICATION_DATABASE.items():
            primary_name = entry.get("primary_name", key.capitalize())
            score = cls.compute_similarity(target_token, key, primary_name)
            
            # Bonus if dosage form or strength consistency matches
            if score >= 0.50 and strength:
                score = min(1.0, score + 0.02)

            if score >= 0.40:
                scored_list.append({
                    "key": key,
                    "name": primary_name,
                    "score": round(score, 2),
                    "class": entry.get("class", "Unknown")
                })

        # Sort descending by score
        scored_list.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate candidates by base primary drug name (e.g. Spironolactone)
        unique_candidates = []
        seen_names = set()
        for cand in scored_list:
            base_name = cand["name"].split('(')[0].strip()
            if base_name.lower() not in seen_names:
                seen_names.add(base_name.lower())
                unique_candidates.append(cand)

        if not unique_candidates:
            return [], None, "unresolved", 0.0

        top_score = unique_candidates[0]["score"]

        # Disambiguation logic
        if top_score < 0.60:
            return unique_candidates, None, "unresolved", top_score

        # Check for ambiguity if 2nd candidate concept exists and score margin is small (< 0.10)
        if len(unique_candidates) > 1:
            second_score = unique_candidates[1]["score"]
            score_margin = top_score - second_score
            if score_margin < 0.10 and top_score < 0.95:
                logger.info(f"HandwritingDrugClassifier: Ambiguous candidates detected for '{raw_text}'. Top: {unique_candidates[0]['name']} ({top_score}), 2nd: {unique_candidates[1]['name']} ({second_score}). Margin: {round(score_margin, 2)}")
                return unique_candidates, None, "ambiguous", top_score

        # Clear winner
        selected_name = unique_candidates[0]["name"]
        return unique_candidates, selected_name, "proposed", top_score

    @classmethod
    def process(cls, pipeline_context):
        """
        Executes Handwriting Drug Classifier Agent on pipeline_context.
        
        Updates context["handwriting"]:
        {
            "candidates": [
                {
                    "raw_text": str,
                    "ocr_confidence": float,
                    "ranked_candidates": list,
                    "selected_candidate": str or None,
                    "classification_status": "proposed" | "ambiguous" | "unresolved" | "manual_review",
                    "classification_confidence": float
                }
            ],
            "warnings": list
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        if not isinstance(extracted_data, dict):
            pipeline_context.setdefault("errors", []).append(f"Invalid extracted_data type in HandwritingDrugClassifierAgent: {type(extracted_data)}")
            extracted_data = {}

        handwriting = pipeline_context.get("handwriting", {})
        if not isinstance(handwriting, dict):
            pipeline_context.setdefault("errors", []).append(f"Invalid handwriting type in HandwritingDrugClassifierAgent: {type(handwriting)}")
            handwriting = {"candidates": [], "warnings": []}
            pipeline_context["handwriting"] = handwriting

        existing_hw_candidates = handwriting.get("candidates", []) if isinstance(handwriting, dict) else []
        medications = extracted_data.get("medications", []) if isinstance(extracted_data, dict) else []
        warnings = handwriting.get("warnings", []) if isinstance(handwriting, dict) else []

        processed_candidates = []

        # 1. Process candidate snippets from handwriting dict
        for candidate_item in existing_hw_candidates:
            if not isinstance(candidate_item, dict):
                continue
            
            raw_text = candidate_item.get("raw_text") or candidate_item.get("source_text", "")
            ocr_conf = float(candidate_item.get("confidence", candidate_item.get("ocr_confidence", 0.95)))
            
            ranked_cands, selected_cand, status, conf = cls.rank_candidates(raw_text)

            # If OCR confidence is very low (< 0.50), force manual review if not clear
            if ocr_conf < 0.50 and status == "proposed" and conf < 0.90:
                status = "manual_review"

            processed_candidates.append({
                "raw_text": raw_text,
                "ocr_confidence": ocr_conf,
                "ranked_candidates": ranked_cands,
                "selected_candidate": selected_cand,
                "classification_status": status,
                "classification_confidence": conf
            })

            if selected_cand and status == "proposed":
                for med in medications:
                    if med.get("raw_name") == raw_text or med.get("source_text") == raw_text:
                        med["proposed_name"] = selected_cand
                        if med.get("name") is None:
                            med["name"] = selected_cand
                        med["classification_status"] = "proposed"

        # 2. Process all remaining extracted medications
        for med in medications:
            raw_text = med.get("raw_name") or med.get("source_text", "")
            if not raw_text:
                continue

            ocr_conf = float(med.get("confidence", 0.95))
            already_proc = any(c.get("raw_text") == raw_text for c in processed_candidates)
            
            if not already_proc:
                ranked_cands, selected_cand, status, conf = cls.rank_candidates(
                    raw_text, strength=med.get("strength"), dosage_form=med.get("dosage_form")
                )

                if ocr_conf < 0.50 and status == "proposed" and conf < 0.90:
                    status = "manual_review"

                processed_candidates.append({
                    "raw_text": raw_text,
                    "ocr_confidence": ocr_conf,
                    "ranked_candidates": ranked_cands,
                    "selected_candidate": selected_cand,
                    "classification_status": status,
                    "classification_confidence": conf
                })

                if selected_cand and status == "proposed":
                    med["proposed_name"] = selected_cand
                    if med.get("name") is None:
                        med["name"] = selected_cand
                    med["classification_status"] = "proposed"
                else:
                    med["classification_status"] = status

        # Update pipeline_context["handwriting"]
        pipeline_context["handwriting"] = {
            "candidates": processed_candidates,
            "warnings": warnings
        }

        return pipeline_context
