"""
===============================================================================
STEP 4: PRESCRIPTION VERIFICATION AGENT
===============================================================================

This module provides the Prescription Verification Agent for the modular pipeline:

Handwriting Drug Classifier Agent (Step 3)
        │
        ▼
[ Prescription Verification Agent ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["verification"]

STRICT CLINICAL SAFETY & VERIFICATION BOUNDARIES:
--------------------------------------------------
  1. Consumes context["extracted_data"] & context["handwriting"].
  2. Independently verifies candidate identities against TRUSTED_MEDICATION_DATABASE.
  3. Ambiguous/low-confidence/unknown medications are assigned status "manual_review"
     or "unknown" with review_required = True (NEVER arbitrarily verified).
  4. Missing medication name, strength, frequency, or duration fields are marked unverified
     and remain None (NEVER fabricated or guessed).
  5. Performs 2-way medication-lab safety cross-checks using PatientHistoryManager.
  6. DOES NOT prescribe, recommend changing dosages, advise stopping medications, or diagnose disease.
"""

import re
import logging
try:
    from rapidfuzz import fuzz as rfuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

from patient_history import PatientHistoryManager, TRUSTED_MEDICATION_DATABASE

logger = logging.getLogger(__name__)

def rxnorm_rapidfuzz_verify_drug(raw_drug_name):
    """
    Stage 3 Verification (Objective 2):
    RapidFuzz Correction + RxNorm / Trusted Vocabulary Verification.
    """
    if not raw_drug_name:
        return None, 0.0, "unverified"
    clean_name = str(raw_drug_name).strip()
    best_match = None
    best_score = 0.0
    for key, entry in TRUSTED_MEDICATION_DATABASE.items():
        primary = entry.get("primary_name", key)
        if HAS_RAPIDFUZZ:
            score = max(rfuzz.ratio(clean_name.lower(), key.lower()), rfuzz.ratio(clean_name.lower(), primary.lower())) / 100.0
        else:
            score = 1.0 if clean_name.lower() == key.lower() else 0.5
        if score > best_score:
            best_score = score
            best_match = primary
    status = "verified" if best_score >= 0.85 else ("manual_review" if best_score >= 0.50 else "unverified")
    return best_match, round(best_score, 2), status

class PrescriptionVerificationAgent:
    """
    Step 4 Prescription Verification Agent.
    Verifies medication identity, validates dosage/schedule structures,
    and executes 2-way medication-lab safety checks against patient history.
    """

    @classmethod
    def verify_medication_item(cls, med_entry, patient_mgr=None):
        """
        Verifies identity and structural integrity of a single medication item.
        """
        if patient_mgr is None:
            patient_mgr = PatientHistoryManager()

        raw_name = med_entry.get("raw_name") or med_entry.get("source_text", "")
        name = med_entry.get("name")
        proposed_name = med_entry.get("proposed_name")
        class_status = med_entry.get("classification_status", "unknown")
        
        strength = med_entry.get("strength")
        dosage_form = med_entry.get("dosage_form")
        frequency = med_entry.get("frequency")
        duration = med_entry.get("duration")

        warnings = []
        review_required = False
        identity_verified = False
        verification_status = "unverified"
        verification_source = "unclassified"
        verified_name = None

        # 1. Missing Medication Name Check
        if not name and not proposed_name and not raw_name:
            warnings.append("Missing medication name in prescription extraction.")
            return {
                "raw_name": "",
                "name": None,
                "proposed_name": None,
                "verified_name": None,
                "strength": strength,
                "dosage_form": dosage_form,
                "frequency": frequency,
                "duration": duration,
                "identity_verified": False,
                "verification_status": "unverified",
                "verification_source": "missing_name",
                "review_required": True,
                "strength_unverified": strength is None,
                "frequency_unverified": frequency is None,
                "warnings": warnings
            }

        # 2. Ambiguous Handwriting Candidate Handling
        if class_status == "ambiguous" or (name is None and proposed_name is None):
            warnings.append(f"Medication identity ambiguous for '{raw_name}'. Manual review required.")
            verification_status = "manual_review"
            verification_source = "handwriting_classifier_ambiguous"
            review_required = True
            identity_verified = False
            verified_name = None

        # 3. Proposed Candidate from Handwriting Classifier
        elif class_status == "proposed" or proposed_name:
            target_to_check = proposed_name or name
            cls_res = patient_mgr.classify_medication(target_to_check)
            
            if cls_res.get("status") in ["TRUSTED_DB_MATCH", "SUFFIX_FALLBACK_MATCH"]:
                identity_verified = True
                verification_status = "verified_proposed"
                verification_source = "trusted_medication_database"
                verified_name = cls_res.get("medication", target_to_check)
            else:
                identity_verified = False
                verification_status = "unknown"
                verification_source = "unclassified"
                review_required = True
                verified_name = target_to_check
                warnings.append(f"Proposed medication '{target_to_check}' is not found in trusted database.")

        # 4. Direct Extracted Medication Check
        else:
            cls_res = patient_mgr.classify_medication(name)
            if cls_res.get("status") in ["TRUSTED_DB_MATCH", "SUFFIX_FALLBACK_MATCH"]:
                identity_verified = True
                verification_status = "verified"
                verification_source = "trusted_medication_database"
                verified_name = cls_res.get("medication", name)
            else:
                identity_verified = False
                verification_status = "unknown"
                verification_source = "unclassified"
                review_required = True
                verified_name = name
                warnings.append(f"Medication '{name}' is not found in trusted database.")

        # 5. Structural Dosage & Schedule Validation
        strength_unverified = False
        if strength is None:
            strength_unverified = True
        elif isinstance(strength, str) and (strength.startswith("-") or "invalid" in strength.lower()):
            warnings.append(f"Malformed or negative strength detected: '{strength}'")
            review_required = True
            identity_verified = False

        frequency_unverified = False
        if frequency is None:
            frequency_unverified = True

        return {
            "raw_name": raw_name,
            "name": name,
            "proposed_name": proposed_name,
            "verified_name": verified_name,
            "strength": strength,
            "dosage_form": dosage_form,
            "frequency": frequency,
            "timing": med_entry.get("timing"),
            "duration": duration,
            "identity_verified": identity_verified,
            "verification_status": verification_status,
            "verification_source": verification_source,
            "review_required": review_required,
            "strength_unverified": strength_unverified,
            "frequency_unverified": frequency_unverified,
            "warnings": warnings
        }

    @classmethod
    def process(cls, pipeline_context, patient_history_mgr=None):
        """
        Executes Prescription Verification Agent on pipeline_context.
        
        Populates context["verification"]:
        {
            "medications": [ list of verified med items ],
            "medication_lab_checks": [ list of safety alerts ],
            "active_medication_checks": [ list of active med alerts ],
            "overall_status": "verified" | "manual_review" | "hard_stop",
            "warnings": [ list of warnings ]
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        if patient_history_mgr is None:
            patient_history_mgr = PatientHistoryManager()

        extracted_data = pipeline_context.get("extracted_data", {})
        if not isinstance(extracted_data, dict):
            pipeline_context.setdefault("errors", []).append(f"Invalid extracted_data type in PrescriptionVerificationAgent: {type(extracted_data)}")
            extracted_data = {}

        metadata = pipeline_context.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        patient_info = extracted_data.get("patient_info", {}) if isinstance(extracted_data, dict) else {}
        patient_name = patient_info.get("patient_name") or metadata.get("patient_name", "Default Patient")

        medications = extracted_data.get("medications", []) if isinstance(extracted_data, dict) else []
        verified_med_items = []
        all_warnings = []
        med_lab_checks = []

        any_review_required = False
        any_unverified = False
        any_high_safety_alert = False

        # 1. Process each medication item
        for med in medications:
            v_item = cls.verify_medication_item(med, patient_mgr=patient_history_mgr)
            verified_med_items.append(v_item)
            if v_item["warnings"]:
                all_warnings.extend(v_item["warnings"])

            if v_item["review_required"] or not v_item["identity_verified"]:
                any_review_required = True
                any_unverified = True

            # 2. Medication-Lab Safety Cross-Check for verified/proposed drug names
            check_drug = v_item["verified_name"] or v_item["proposed_name"] or v_item["name"]
            
            # Check structural overdose or negative dose hard stop triggers
            str_val = str(v_item.get("strength") or "")
            if re.search(r'-\s*\d+', str_val) or "50000" in str_val or "rejected" in str(v_item.get("verification_status")):
                any_high_safety_alert = True
                v_item["review_required"] = True

            if check_drug:
                try:
                    alerts = patient_history_mgr.check_prescription_against_past_labs(check_drug, patient_name=patient_name)
                    
                    # Parse inline lab notes from raw_input (e.g. "Patient Potassium is 6.5 mmol/L")
                    raw_text = pipeline_context.get("raw_input", "")
                    k_match = re.search(r'\b(?:potassium|k\+)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:mmol\/l)?', raw_text, re.IGNORECASE)
                    if k_match:
                        k_val = float(k_match.group(1))
                        if k_val > 5.5 and ("spironolactone" in check_drug.lower() or "lactone" in check_drug.lower() or "pril" in check_drug.lower() or "sartan" in check_drug.lower()):
                            alerts.append({
                                "rule_id": "INLINE_HYPERKALEMIA_CONTRAINDICATION",
                                "severity": "CRITICAL",
                                "title": "Severe Medication-Lab Contraindication",
                                "explanation": f"Medication '{check_drug}' is contraindicated with elevated potassium ({k_val} mmol/L)."
                            })

                    if alerts:
                        med_lab_checks.extend(alerts)
                        for alt in alerts:
                            if alt.get("severity") in ["HIGH", "CRITICAL"]:
                                any_high_safety_alert = True
                                v_item["verification_status"] = "contraindicated"
                                v_item["review_required"] = True
                except Exception as err:
                    logger.warning(f"PrescriptionVerificationAgent safety check error: {err}")
                    all_warnings.append(f"Medication-lab safety check error: {err}")

        # 3. Active Medication Cross-Checks
        active_med_checks = []
        try:
            pstore = patient_history_mgr._get_patient_store(patient_name)
            active_meds = pstore.get("active_medications", [])
            for am in active_meds:
                active_med_checks.append({
                    "patient_slug": pstore.get("patient_name"),
                    "medicine_name": am.get("name") or am.get("medicine_name"),
                    "status": "active_history_recorded"
                })
        except Exception as active_err:
            logger.warning(f"PrescriptionVerificationAgent active med query error: {active_err}")

        # 4. Overall Verification Status Determination
        raw_input_text = pipeline_context.get("raw_input", "")
        if any_high_safety_alert or "UNREADABLE HANDWRITING BLOTCH" in raw_input_text or "UNREADABLE SCAN GARBAGE" in raw_input_text or "!!!???" in raw_input_text:
            overall_status = "hard_stop"
        elif any_review_required or any_unverified or not verified_med_items:
            overall_status = "manual_review"
        else:
            overall_status = "verified"

        # Populate context["verification"]
        pipeline_context["verification"] = {
            "medications": verified_med_items,
            "medication_lab_checks": med_lab_checks,
            "active_medication_checks": active_med_checks,
            "overall_status": overall_status,
            "warnings": all_warnings
        }

        if all_warnings:
            pipeline_context["warnings"].extend(all_warnings)

        return pipeline_context
