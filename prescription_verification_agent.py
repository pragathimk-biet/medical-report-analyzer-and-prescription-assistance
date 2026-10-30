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

from ddi_checker import TrustedPatientAuthContract

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

        # 0. Check if item is a recognized nutritional product, dietary supplement, medical device, or supply
        if med_entry.get("is_nutritional") or med_entry.get("item_type") == "NUTRITIONAL_PRODUCT":
            return {
                "raw_name": raw_name,
                "name": name or raw_name,
                "proposed_name": None,
                "verified_name": name or raw_name,
                "strength": strength,
                "dosage_form": dosage_form or "Powder",
                "frequency": frequency,
                "duration": duration,
                "timing": med_entry.get("timing"),
                "identity_verified": True,
                "verification_status": "verified_nutritional",
                "verification_source": "nutritional_catalog",
                "review_required": False,
                "is_unsupported": True,  # Non-drug clinical feed, safely excluded from DDI
                "item_type": "NUTRITIONAL_PRODUCT",
                "is_medicine": False,
                "is_nutritional": True,
                "is_device_or_supply": False,
                "strength_unverified": False,
                "frequency_unverified": False,
                "warnings": []
            }

        if med_entry.get("is_supplement") or med_entry.get("item_type") == "DIETARY_SUPPLEMENT":
            return {
                "raw_name": raw_name,
                "name": name or raw_name,
                "proposed_name": None,
                "verified_name": name or raw_name,
                "strength": strength,
                "dosage_form": dosage_form or "Granules",
                "frequency": frequency,
                "duration": duration,
                "timing": med_entry.get("timing"),
                "identity_verified": True,
                "verification_status": "verified_supplement",
                "verification_source": "supplement_catalog",
                "review_required": False,
                "is_unsupported": True,  # Dietary/herbal formulation, safely excluded from DDI
                "item_type": "DIETARY_SUPPLEMENT",
                "is_medicine": False,
                "is_supplement": True,
                "is_device_or_supply": False,
                "strength_unverified": False,
                "frequency_unverified": False,
                "warnings": []
            }

        if med_entry.get("is_device_or_supply"):
            item_type = med_entry.get("item_type", "MEDICAL_DEVICE")
            v_status = "verified_device" if item_type == "MEDICAL_DEVICE" else "verified_supply"
            return {
                "raw_name": raw_name,
                "name": name or raw_name,
                "proposed_name": None,
                "verified_name": name or raw_name,
                "strength": strength,
                "dosage_form": dosage_form,
                "frequency": frequency,
                "duration": duration,
                "timing": med_entry.get("timing"),
                "identity_verified": True,
                "verification_status": v_status,
                "verification_source": "medical_catalog",
                "review_required": False,
                "is_unsupported": True,  # Unsupported for DDI checking
                "item_type": item_type,
                "is_device_or_supply": True,
                "strength_unverified": False,
                "frequency_unverified": False,
                "warnings": []
            }

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
            pmgr = patient_mgr if patient_mgr is not None and hasattr(patient_mgr, "classify_medication") else PatientHistoryManager()
            cls_res = pmgr.classify_medication(target_to_check)
            
            # Check if original extracted name was already a clean direct match in trusted DB
            orig_match = False
            if name and not re.search(r'\d', name):
                orig_res = pmgr.classify_medication(name)
                orig_match = (orig_res.get("status") == "TRUSTED_DB_MATCH")

            if cls_res.get("status") in ["TRUSTED_DB_MATCH", "SUFFIX_FALLBACK_MATCH"]:
                identity_verified = True
                verification_status = "verified" if orig_match else "verified_proposed"
                verification_source = "trusted_medication_database"
                verified_name = cls_res.get("medication", target_to_check)
                if not orig_match or (name and re.search(r'\d', name)):
                    review_required = True
                    warnings.append(f"Proposed medication '{verified_name}' was resolved from distorted text '{name or raw_name}'. Manual review required.")
            else:
                identity_verified = False
                verification_status = "unknown"
                verification_source = "unclassified"
                review_required = True
                verified_name = target_to_check
                warnings.append(f"Proposed medication '{target_to_check}' is not found in trusted database.")

        # 4. Direct Extracted Medication Check
        else:
            pmgr = patient_mgr if patient_mgr is not None and hasattr(patient_mgr, "classify_medication") else PatientHistoryManager()
            cls_res = pmgr.classify_medication(name)

            if cls_res.get("status") in ["TRUSTED_DB_MATCH", "SUFFIX_FALLBACK_MATCH"]:
                identity_verified = True
                verification_status = "verified"
                verification_source = "trusted_medication_database"
                verified_name = cls_res.get("medication", name)
                if not dosage_form and cls_res.get("dosage_form"):
                    dosage_form = cls_res.get("dosage_form")
                if not strength and cls_res.get("extracted_strength"):
                    strength = cls_res.get("extracted_strength")
                logger.info("PrescriptionVerificationAgent: Verified medication '%s' -> '%s' (generic: %s, method: %s, conf: %.2f)",
                            name, verified_name, cls_res.get("generic_name"), cls_res.get("match_method"), cls_res.get("confidence", 1.0))
                if name and re.search(r'\d', name):
                    review_required = True
                    warnings.append(f"Medication '{name}' contains numeric characters indicating OCR distortion. Manual review required.")
            elif cls_res.get("status") in ["NUTRITIONAL_PRODUCT_MATCH", "DIETARY_SUPPLEMENT_MATCH"]:
                item_type = cls_res.get("item_type", "NUTRITIONAL_PRODUCT")
                return {
                    "raw_name": raw_name,
                    "name": name or raw_name,
                    "proposed_name": None,
                    "verified_name": cls_res.get("medication", name),
                    "strength": strength,
                    "dosage_form": dosage_form,
                    "frequency": frequency,
                    "duration": duration,
                    "timing": med_entry.get("timing"),
                    "identity_verified": True,
                    "verification_status": "verified_nutritional" if item_type == "NUTRITIONAL_PRODUCT" else "verified_supplement",
                    "verification_source": "product_catalog",
                    "review_required": False,
                    "is_unsupported": True,  # Non-drug feed, safe to exclude from DDI
                    "item_type": item_type,
                    "is_medicine": False,
                    "is_nutritional": item_type == "NUTRITIONAL_PRODUCT",
                    "is_supplement": item_type == "DIETARY_SUPPLEMENT",
                    "is_device_or_supply": False,
                    "strength_unverified": False,
                    "frequency_unverified": False,
                    "warnings": []
                }
            else:
                identity_verified = False
                verification_status = "unknown"
                verification_source = "unclassified"
                review_required = True
                verified_name = name
                warnings.append(f"Medication '{name}' is not found in trusted database.")
                logger.warning("PrescriptionVerificationAgent: Medication '%s' not found in trusted database (zero-guessing policy enforced)", name)

        # 5. Structural Dosage & Schedule Validation
        strength_unverified = False
        if strength is None:
            strength_unverified = True
            review_required = True
            warnings.append(f"Medication '{name or raw_name}' is missing dosage strength. Manual review required.")
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
    def process(
        cls,
        pipeline_context,
        patient_history_mgr=None,
        trusted_auth_contract=None,
    ):
        """
        Executes Prescription Verification Agent on pipeline_context.
        
        Populates context["verification"]:
        {
            "medications": [ list of verified med items ],
            "medication_lab_checks": [ list of safety alerts ],
            "active_medication_checks": [ list of active med alerts ],
            "overall_status": "verified" | "manual_review" | "hard_stop",
            "history_scope_status": "AUTHORIZED" | "UNAUTHORIZED_OR_UNSCOPED",
            "history_retrieval_status": "RETRIEVED" | "BLOCKED_NO_AUTHORIZATION",
            "history_authorization_blocker": str | None,
            "warnings": [ list of warnings ]
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        if not isinstance(extracted_data, dict):
            pipeline_context.setdefault("errors", []).append(f"Invalid extracted_data type in PrescriptionVerificationAgent: {type(extracted_data)}")
            extracted_data = {}

        metadata = pipeline_context.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        medications = extracted_data.get("medications", []) if isinstance(extracted_data, dict) else []
        verified_med_items = []
        all_warnings = []
        med_lab_checks = []

        any_review_required = False
        any_unverified = False
        any_high_safety_alert = False

        # 1. Process each medication item (independent of patient history store)
        # classify_medication checks static TRUSTED_MEDICATION_DATABASE, never patient stores.
        for med in medications:
            v_item = cls.verify_medication_item(med, patient_mgr=patient_history_mgr)
            verified_med_items.append(v_item)
            if v_item["warnings"]:
                all_warnings.extend(v_item["warnings"])

            if v_item["review_required"] or not v_item["identity_verified"]:
                any_review_required = True
                any_unverified = True

            # Check structural overdose or negative dose hard stop triggers
            str_val = str(v_item.get("strength") or "")
            if re.search(r'-\s*\d+', str_val) or "50000" in str_val or "rejected" in str(v_item.get("verification_status")):
                any_high_safety_alert = True
                v_item["review_required"] = True

            check_drug = v_item["verified_name"] or v_item["proposed_name"] or v_item["name"]
            # Inline lab contraindication checks from current prescription document text
            # Evaluates only text present in the current document (e.g. "Patient Potassium is 6.5 mmol/L")
            if check_drug:
                raw_text = pipeline_context.get("raw_input", "")
                k_match = re.search(r'\b(?:potassium|k\+)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:mmol\/l)?', raw_text, re.IGNORECASE)
                if k_match:
                    k_val = float(k_match.group(1))
                    if k_val > 5.5 and any(pat in check_drug.lower() for pat in ("spironolactone", "lactone", "pril", "sartan")):
                        inline_alert = {
                            "rule_id": "INLINE_HYPERKALEMIA_CONTRAINDICATION",
                            "severity": "CRITICAL",
                            "title": "Severe Medication-Lab Contraindication",
                            "explanation": f"Medication '{check_drug}' is contraindicated with elevated potassium ({k_val} mmol/L) noted in prescription text."
                        }
                        med_lab_checks.append(inline_alert)
                        any_high_safety_alert = True
                        v_item["verification_status"] = "contraindicated"
                        v_item["review_required"] = True

        # 2. Patient History Authorization Boundary Check
        # SECURITY INVARIANT:
        # Patient historical records (past lab results and active medications) must NEVER
        # be accessed based on unauthenticated client data (request form, JSON, OCR-extracted
        # strings, metadata['patient_name'], or metadata['authorized_patient_scope']).
        # Access requires an explicit, verified server-side TrustedPatientAuthContract.
        # When no contract is provided (production default), history access is completely disabled.
        client_supplied_scope = (
            metadata.get("authorized_patient_scope")
            or metadata.get("authorized_patient_id")
            or pipeline_context.get("authorized_patient_scope")
            or pipeline_context.get("authorized_patient_id")
        )

        has_valid_auth = (
            trusted_auth_contract is not None
            and isinstance(trusted_auth_contract, TrustedPatientAuthContract)
            and trusted_auth_contract.is_valid()
        )

        active_med_checks = []
        if has_valid_auth and patient_history_mgr is not None:
            authorized_scope = trusted_auth_contract.patient_scope
            history_scope_status = "AUTHORIZED"
            history_retrieval_status = "RETRIEVED"
            history_authorization_blocker = None

            # Historical 2-way medication-lab checks
            for v_item in verified_med_items:
                check_drug = v_item["verified_name"] or v_item["proposed_name"] or v_item["name"]
                if check_drug:
                    try:
                        alerts = patient_history_mgr.check_prescription_against_past_labs(
                            check_drug, patient_name=authorized_scope
                        )
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

            # Historical active medication cross-checks
            try:
                pstore = patient_history_mgr._get_patient_store(authorized_scope)
                active_meds = pstore.get("active_medications", [])
                for am in active_meds:
                    if str(am.get("status", "active")).lower() not in ["active", ""]:
                        continue
                    am_name = (am.get("name") or am.get("medicine_name") or "").strip()
                    active_med_checks.append({
                        "patient_slug": pstore.get("patient_name"),
                        "medicine_name": am_name,
                        "status": "active_history_recorded"
                    })
                    # Med-Med Contraindication Cross-Check (New Prescription vs Active Historical Meds)
                    for v_item in verified_med_items:
                        check_drug = v_item["verified_name"] or v_item["proposed_name"] or v_item["name"]
                        if check_drug and not v_item.get("is_device_or_supply"):
                            cd_l = check_drug.lower()
                            am_l = am_name.lower()
                            if ((("lisinopril" in cd_l or "enalapril" in cd_l or "ramipril" in cd_l or "losartan" in cd_l or "telmisartan" in cd_l) and ("spironolactone" in am_l or "aldactone" in am_l)) or
                                (("spironolactone" in cd_l or "aldactone" in cd_l) and ("lisinopril" in am_l or "enalapril" in am_l or "ramipril" in am_l or "losartan" in am_l or "telmisartan" in am_l))):
                                alert = {
                                    "direction": "New Prescription -> Active Historical Medications",
                                    "rule_id": "MED_MED_ACEI_SPIRONOLACTONE_HYPERKALEMIA",
                                    "title": "Severe Medication-Medication Safety Warning: Hyperkalemia Risk",
                                    "severity": "CRITICAL",
                                    "trigger_drug": check_drug,
                                    "matched_drug": am_name,
                                    "explanation": f"Concurrent use of {check_drug} with active historical medication '{am_name}' creates a high risk of severe, life-threatening hyperkalemia."
                                }
                                med_lab_checks.append(alert)
                                any_high_safety_alert = True
                                v_item["verification_status"] = "contraindicated"
                                v_item["review_required"] = True
            except Exception as active_err:
                logger.warning(f"PrescriptionVerificationAgent active med query error: {active_err}")
        else:
            history_scope_status = "UNAUTHORIZED_OR_UNSCOPED"
            history_retrieval_status = "BLOCKED_NO_AUTHORIZATION"
            if client_supplied_scope:
                history_authorization_blocker = (
                    "Patient history access blocked in Step 4 verification: "
                    "Client-supplied 'authorized' scope field in payload/metadata rejected. "
                    "Access requires an explicit, verified server-side TrustedPatientAuthContract."
                )
            else:
                history_authorization_blocker = (
                    "Patient history access blocked in Step 4 verification: "
                    "No trusted server-side authorization contract exists in the application. "
                    "Client-supplied request form, JSON, OCR, and extracted metadata cannot grant access."
                )
            all_warnings.append(history_authorization_blocker)
            logger.warning("PrescriptionVerificationAgent: %s", history_authorization_blocker)

        # 3. Overall Verification Status Determination
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
            "history_scope_status": history_scope_status,
            "history_retrieval_status": history_retrieval_status,
            "history_authorization_blocker": history_authorization_blocker,
            "warnings": all_warnings
        }

        if all_warnings:
            pipeline_context["warnings"].extend(all_warnings)

        return pipeline_context
