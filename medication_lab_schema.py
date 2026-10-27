"""
===============================================================================
MEDICATION-LABORATORY KNOWLEDGE BASE: SCHEMA & GOVERNANCE VALIDATOR
===============================================================================

Defines the formal schema, structural validator, and release eligibility
validator for medication-laboratory clinical rules and research candidates.

GOVERNANCE INVARIANTS:
1. Strict separation between rule definitions and observed patient context.
2. Draft rules and research candidates MUST pass structural validation but
   FAIL release eligibility.
3. Reviewer fields may be null for drafts. Reviewer identities must NEVER be invented.
4. Release approval requires verified retrieval and exact quote matching.
   Failed retrieval or source mismatches disqualify rules from release.
5. Incomplete context outcomes are strictly preserved:
   - Missing history -> UNKNOWN (never defaulted to INITIATION).
   - Unknown assay architecture -> INDETERMINATE_ASSAY_CONTEXT.
   - Generic ABNORMAL -> rejected for direction-specific rules.
   - Safe-to-proceed claims are strictly prohibited.
"""

import re
from typing import Dict, Any, List, Tuple, Optional

# Supported operators and endpoints
MILESTONE_STATUS = (
    "Governance/schema implementation complete.\n"
    "Clinical evidence curation and reviewer approval pending.\n"
    "Medication–lab evaluation inactive."
)

VALID_OPERATORS = {"<", "<=", ">", ">=", "==", "BETWEEN", "STATUS_MATCH"}
VALID_INTERVAL_ENDPOINTS = {"OPEN", "CLOSED", "LEFT_CLOSED", "RIGHT_CLOSED", "NOT_APPLICABLE"}
VALID_TIERS = {"TIER_1_EXECUTABLE", "TIER_2_RESEARCH_CANDIDATE"}
VALID_CATEGORIES = {
    "PHARMACODYNAMIC_EFFECT",
    "ANALYTICAL_INTERFERENCE",
    "CLINICAL_SAFETY_MONITORING"
}
VALID_REVIEW_STATUSES = {"DRAFT", "PEER_REVIEWED", "APPROVED", "DEPRECATED", "SUPERSEDED"}
VALID_DIRECTIONS = {"MED_TO_LAB", "LAB_TO_MED", "BIDIRECTIONAL"}
VALID_TREATMENT_STATES = {"INITIATION", "CONTINUATION", "ANY", "UNKNOWN"}
VALID_RETRIEVAL_STATUSES = {"RETRIEVED", "RETRIEVAL_FAILED", "SOURCE_MISMATCH"}
VALID_QUOTE_MATCH_OUTCOMES = {
    "EXACT_MATCH",
    "QUOTE_MISMATCH",
    "SOURCE_MISMATCH",
    "UNVERIFIED_RETRIEVAL_FAILED"
}
VALID_ASSAY_ARCHITECTURES = {
    "SANDWICH_IMMUNOMETRIC",
    "COMPETITIVE_IMMUNOASSAY",
    "ENZYMATIC_COLORIMETRIC",
    "ELECTROCHEMICAL_REDOX",
    "ANY",
    "NOT_APPLICABLE"
}
VALID_CLINICAL_IMPORTANCE = {
    "CRITICAL_SAFETY",
    "SIGNIFICANT_MONITORING",
    "ANALYTICAL_INTERPRETATION",
    "INFORMATIONAL"
}
VALID_ACTION_CATEGORIES = {
    "CONTRAINDICATION_ALERT",
    "MONITORING_MANDATED",
    "INTERFERENCE_CAUTION",
    "CLINICAL_DISCRETION"
}

# ---------------------------------------------------------------------------
# Structural Validation
# ---------------------------------------------------------------------------

def _is_non_empty_str(val: Any) -> bool:
    return isinstance(val, str) and len(val.strip()) > 0


def _is_https_url(val: Any) -> bool:
    return isinstance(val, str) and val.strip().startswith("https://")


def validate_rule_schema(rule: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates structural conformity of a medication-laboratory rule definition.
    Enforces no unknown top-level or nested properties, non-empty required strings,
    HTTPS URLs, operator/threshold consistency, and route/form separation.
    """
    errors: List[str] = []

    if not isinstance(rule, dict):
        return False, ["Rule definition must be a dictionary."]

    # 1. Top-Level Required Keys and Additional Property Ban
    allowed_top_keys = {
        "rule_id",
        "rule_version",
        "tier",
        "category",
        "is_superseded",
        "superseded_by",
        "superseded_reason",
        "governance",
        "medication_criteria",
        "laboratory_criteria",
        "evaluation_logic",
        "evidence_references",
        "clinical_advisory",
        "context_outcomes"
    }
    actual_top_keys = set(rule.keys())
    unknown_top_keys = actual_top_keys - allowed_top_keys
    if unknown_top_keys:
        errors.append(f"Unknown top-level properties detected: {sorted(unknown_top_keys)}")

    base_required_keys = {
        "rule_id",
        "rule_version",
        "tier",
        "category",
        "governance",
        "medication_criteria",
        "laboratory_criteria",
        "evaluation_logic",
        "evidence_references",
        "clinical_advisory",
        "context_outcomes"
    }
    missing_top_keys = base_required_keys - actual_top_keys
    if missing_top_keys:
        errors.append(f"Missing required top-level properties: {sorted(missing_top_keys)}")
        return False, errors

    # 2. Basic metadata
    rule_id = rule.get("rule_id")
    if not _is_non_empty_str(rule_id) or not re.match(r"^MED_LAB_(PD|INT|SAF)_[A-Z0-9_]{3,40}_V[0-9]+$", rule_id):
        errors.append(f"Invalid rule_id format: '{rule_id}'")

    if not _is_non_empty_str(rule.get("rule_version")) or not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", rule.get("rule_version", "")):
        errors.append(f"Invalid rule_version format: '{rule.get('rule_version')}'")

    if rule.get("tier") not in VALID_TIERS:
        errors.append(f"Invalid tier: '{rule.get('tier')}'. Must be one of {sorted(VALID_TIERS)}")

    if rule.get("category") not in VALID_CATEGORIES:
        errors.append(f"Invalid category: '{rule.get('category')}'. Must be one of {sorted(VALID_CATEGORIES)}")

    # 3. Governance
    gov = rule.get("governance", {})
    if not isinstance(gov, dict):
        errors.append("governance must be a dictionary.")
    else:
        allowed_gov_keys = {
            "review_status",
            "clinical_reviewer_name",
            "clinical_reviewer_credential",
            "review_date",
            "release_approved",
            "approval_hash",
            "governance_notes"
        }
        unknown_gov = set(gov.keys()) - allowed_gov_keys
        if unknown_gov:
            errors.append(f"Unknown properties in governance: {sorted(unknown_gov)}")

        if gov.get("review_status") not in VALID_REVIEW_STATUSES:
            errors.append(f"Invalid review_status: '{gov.get('review_status')}'.")

        if not isinstance(gov.get("release_approved"), bool):
            errors.append("governance.release_approved must be a boolean.")

        # Reviewer fields can be null for drafts, but if provided must be non-empty strings
        for field in ("clinical_reviewer_name", "clinical_reviewer_credential", "review_date", "approval_hash"):
            val = gov.get(field)
            if val is not None and not _is_non_empty_str(val):
                errors.append(f"governance.{field} must be a non-empty string or null.")

    # 4. Medication Criteria (Route and Dosage Form MUST be separate)
    med = rule.get("medication_criteria", {})
    if not isinstance(med, dict):
        errors.append("medication_criteria must be a dictionary.")
    else:
        allowed_med_keys = {
            "generic_name",
            "rxnorm_cui",
            "who_atc_code",
            "mapping_status",
            "allowed_routes",
            "allowed_dosage_forms",
            "treatment_state"
        }
        unknown_med = set(med.keys()) - allowed_med_keys
        if unknown_med:
            errors.append(f"Unknown properties in medication_criteria: {sorted(unknown_med)}")

        if not _is_non_empty_str(med.get("generic_name")):
            errors.append("medication_criteria.generic_name must be a non-empty string.")

        if not _is_non_empty_str(med.get("rxnorm_cui")):
            errors.append("medication_criteria.rxnorm_cui must be a non-empty string (or 'UNKNOWN').")

        if med.get("mapping_status") not in {"CURATED_EXACT", "DATASET_CANONICAL", "UNMAPPED_UNKNOWN"}:
            errors.append(f"Invalid mapping_status: '{med.get('mapping_status')}'.")

        routes = med.get("allowed_routes")
        if not isinstance(routes, list) or len(routes) == 0 or not all(_is_non_empty_str(r) for r in routes):
            errors.append("medication_criteria.allowed_routes must be a non-empty list of route strings.")

        forms = med.get("allowed_dosage_forms")
        if not isinstance(forms, list) or len(forms) == 0 or not all(_is_non_empty_str(f) for f in forms):
            errors.append("medication_criteria.allowed_dosage_forms must be a non-empty list of dosage form strings.")

        if med.get("treatment_state") not in VALID_TREATMENT_STATES:
            errors.append(f"Invalid treatment_state: '{med.get('treatment_state')}'. Must be one of {sorted(VALID_TREATMENT_STATES)}")

    # 5. Laboratory Criteria
    lab = rule.get("laboratory_criteria", {})
    if not isinstance(lab, dict):
        errors.append("laboratory_criteria must be a dictionary.")
    else:
        allowed_lab_keys = {
            "analyte_key",
            "canonical_display_name",
            "loinc_code",
            "loinc_mapping_status",
            "fasting_context",
            "required_canonical_unit",
            "allowed_unit_aliases",
            "convertible_units",
            "specimen_type",
            "assay_platform_requirement"
        }
        unknown_lab = set(lab.keys()) - allowed_lab_keys
        if unknown_lab:
            errors.append(f"Unknown properties in laboratory_criteria: {sorted(unknown_lab)}")

        if not _is_non_empty_str(lab.get("analyte_key")):
            errors.append("laboratory_criteria.analyte_key must be a non-empty string.")

        if not _is_non_empty_str(lab.get("required_canonical_unit")):
            errors.append("laboratory_criteria.required_canonical_unit must be a non-empty string.")

        aliases = lab.get("allowed_unit_aliases")
        if aliases is not None:
            if not isinstance(aliases, list) or not all(_is_non_empty_str(a) for a in aliases):
                errors.append("laboratory_criteria.allowed_unit_aliases must be a list of non-empty strings.")

        convertible = lab.get("convertible_units")
        if convertible is not None:
            if not isinstance(convertible, list) or not all(_is_non_empty_str(c) for c in convertible):
                errors.append("laboratory_criteria.convertible_units must be a list of non-empty strings.")


        assay = lab.get("assay_platform_requirement", {})
        if not isinstance(assay, dict):
            errors.append("laboratory_criteria.assay_platform_requirement must be a dictionary.")
        else:
            allowed_assay_keys = {
                "architecture",
                "susceptible_technologies",
                "immune_technologies",
                "allow_brand_immunity_assumption"
            }
            unknown_assay = set(assay.keys()) - allowed_assay_keys
            if unknown_assay:
                errors.append(f"Unknown properties in assay_platform_requirement: {sorted(unknown_assay)}")

            if assay.get("architecture") not in VALID_ASSAY_ARCHITECTURES:
                errors.append(f"Invalid assay architecture: '{assay.get('architecture')}'.")

            # Invariant: Broad brand immunity assumptions are forbidden
            if assay.get("allow_brand_immunity_assumption") is True:
                errors.append("allow_brand_immunity_assumption MUST be false. Broad brand immunity is not clinically valid.")

    # 6. Evaluation Logic & Operator Consistency
    eval_logic = rule.get("evaluation_logic", {})
    if not isinstance(eval_logic, dict):
        errors.append("evaluation_logic must be a dictionary.")
    else:
        allowed_eval_keys = {
            "direction",
            "operator",
            "threshold_value",
            "threshold_range_high",
            "interval_endpoints",
            "target_lab_statuses",
            "timing_window_days"
        }
        unknown_eval = set(eval_logic.keys()) - allowed_eval_keys
        if unknown_eval:
            errors.append(f"Unknown properties in evaluation_logic: {sorted(unknown_eval)}")

        if eval_logic.get("direction") not in VALID_DIRECTIONS:
            errors.append(f"Invalid direction: '{eval_logic.get('direction')}'.")

        op = eval_logic.get("operator")
        if op not in VALID_OPERATORS:
            errors.append(f"Invalid operator: '{op}'. Must be one of {sorted(VALID_OPERATORS)}")
        else:
            t_val = eval_logic.get("threshold_value")
            t_high = eval_logic.get("threshold_range_high")
            endpoints = eval_logic.get("interval_endpoints")

            if op in {"<", "<=", ">", ">="}:
                if not isinstance(t_val, (int, float)):
                    errors.append(f"Operator '{op}' requires numeric threshold_value, got {t_val}.")

            elif op == "BETWEEN":
                if not isinstance(t_val, (int, float)) or not isinstance(t_high, (int, float)):
                    errors.append(f"Operator 'BETWEEN' requires numeric threshold_value and threshold_range_high.")
                elif t_val >= t_high:
                    errors.append(f"Operator 'BETWEEN' requires threshold_value < threshold_range_high ({t_val} >= {t_high}).")

                if endpoints not in {"OPEN", "CLOSED", "LEFT_CLOSED", "RIGHT_CLOSED"}:
                    errors.append(f"Operator 'BETWEEN' requires defined interval_endpoints, got '{endpoints}'.")

            elif op == "STATUS_MATCH":
                statuses = eval_logic.get("target_lab_statuses")
                if not isinstance(statuses, list) or len(statuses) == 0:
                    errors.append("Operator 'STATUS_MATCH' requires non-empty target_lab_statuses.")
                elif "ABNORMAL" in statuses and rule.get("category") == "CLINICAL_SAFETY_MONITORING":
                    errors.append("Generic 'ABNORMAL' must not substitute for a direction-specific result in safety rules.")

    # 7. Evidence References (Separate from Authored Advisory)
    refs = rule.get("evidence_references")
    if not isinstance(refs, list) or len(refs) == 0:
        errors.append("evidence_references must be a non-empty list of reference objects.")
    else:
        allowed_ref_keys = {
            "source_name",
            "evidence_entry_type",
            "event_description",
            "exact_product_name",
            "active_ingredient",
            "actual_document_title",
            "document_id",
            "section",
            "page_or_section",
            "publication_or_revision_date",
            "label_currency_status",
            "current_official_label_status",
            "currency_notes",
            "source_url",
            "attempted_url",
            "resolved_url",
            "requested_url",
            "actual_http_final_url",
            "replacement_source_url",
            "retrieval_status",
            "retrieval_date",
            "retrieval_failure_reason",
            "document_sha256",
            "verbatim_passage",
            "quote_match_outcome",
            "quote_match_method",
            "quotation_verification_notes",
            "supported_claim",
            "clinical_applicability_assessment",
            "source_text_verification_status",
            "clinical_applicability_review_status",
            "reuse_review_status",
            "reuse_notes",
            "reuse_review_rationale",
            "release_approval_status",
            "license_type"
        }
        for idx, ref in enumerate(refs):
            if not isinstance(ref, dict):
                errors.append(f"evidence_references[{idx}] must be a dictionary.")
                continue

            unknown_ref = set(ref.keys()) - allowed_ref_keys
            if unknown_ref:
                errors.append(f"Unknown properties in evidence_references[{idx}]: {sorted(unknown_ref)}")

            for req_str in ("source_name", "document_id", "section", "publication_or_revision_date", "verbatim_passage", "license_type"):
                if not _is_non_empty_str(ref.get(req_str)):
                    errors.append(f"evidence_references[{idx}].{req_str} must be a non-empty string.")

            url = ref.get("source_url")
            if not _is_https_url(url):
                errors.append(f"evidence_references[{idx}].source_url must be an HTTPS URL, got '{url}'.")

            for opt_url in ("attempted_url", "resolved_url", "requested_url", "actual_http_final_url", "replacement_source_url"):
                val = ref.get(opt_url)
                if val is not None and not _is_https_url(val):
                    errors.append(f"evidence_references[{idx}].{opt_url} must be an HTTPS URL, got '{val}'.")

            ret_status = ref.get("retrieval_status")
            if ret_status not in VALID_RETRIEVAL_STATUSES:
                errors.append(f"evidence_references[{idx}].retrieval_status invalid: '{ret_status}'.")

            quote_outcome = ref.get("quote_match_outcome")
            if quote_outcome not in VALID_QUOTE_MATCH_OUTCOMES:
                errors.append(f"evidence_references[{idx}].quote_match_outcome invalid: '{quote_outcome}'.")

            # Invariant: Failed retrieval cannot produce VERIFIED quotation status or have document_sha256
            if ret_status == "RETRIEVAL_FAILED":
                if quote_outcome in {"EXACT_MATCH", "VERIFIED"}:
                    errors.append(f"evidence_references[{idx}]: Failed retrieval cannot produce VERIFIED quotation status.")
                if ref.get("document_sha256") is not None:
                    errors.append(f"evidence_references[{idx}]: Failed retrieval event must have document_sha256=None.")
                fail_reason = ref.get("retrieval_failure_reason")
                if fail_reason is not None and fail_reason not in {"UNKNOWN", "HTTP_404_NOT_FOUND"}:
                    errors.append(f"evidence_references[{idx}]: Retrieval failure cause remains UNKNOWN unless evidenced.")

            # Invariant: Successful retrieval requires non-empty cryptographic hash
            if ret_status == "RETRIEVED":
                if not _is_non_empty_str(ref.get("document_sha256")):
                    errors.append(f"evidence_references[{idx}]: Successful retrieval event requires non-empty document_sha256.")

            # Invariant: Source mismatch must produce SOURCE_MISMATCH quote outcome
            if ret_status == "SOURCE_MISMATCH" and quote_outcome != "SOURCE_MISMATCH":
                errors.append(f"evidence_references[{idx}]: SOURCE_MISMATCH retrieval requires SOURCE_MISMATCH quote_match_outcome.")

    # 8. Clinical Advisory (Authored Text Separated from Source Quote)
    adv = rule.get("clinical_advisory", {})
    if not isinstance(adv, dict):
        errors.append("clinical_advisory must be a dictionary.")
    else:
        allowed_adv_keys = {
            "clinical_importance",
            "action_category",
            "summary_title",
            "authored_advisory_text",
            "prohibited_actions"
        }
        unknown_adv = set(adv.keys()) - allowed_adv_keys
        if unknown_adv:
            errors.append(f"Unknown properties in clinical_advisory: {sorted(unknown_adv)}")

        if adv.get("clinical_importance") not in VALID_CLINICAL_IMPORTANCE:
            errors.append(f"Invalid clinical_importance: '{adv.get('clinical_importance')}'.")

        if adv.get("action_category") not in VALID_ACTION_CATEGORIES:
            errors.append(f"Invalid action_category: '{adv.get('action_category')}'.")

        if not _is_non_empty_str(adv.get("summary_title")):
            errors.append("clinical_advisory.summary_title must be a non-empty string.")

        authored_text = adv.get("authored_advisory_text", "")
        if not _is_non_empty_str(authored_text):
            errors.append("clinical_advisory.authored_advisory_text must be a non-empty string.")
        elif "safe to proceed" in authored_text.lower():
            errors.append("clinical_advisory.authored_advisory_text must NOT make 'safe to proceed' claims.")

    # 9. Context Outcomes
    outcomes = rule.get("context_outcomes", {})
    if not isinstance(outcomes, dict):
        errors.append("context_outcomes must be a dictionary.")
    else:
        allowed_outcome_keys = {
            "on_missing_unit",
            "on_incompatible_unit",
            "on_missing_value",
            "on_unknown_assay",
            "on_unknown_treatment_state"
        }
        unknown_out = set(outcomes.keys()) - allowed_outcome_keys
        if unknown_out:
            errors.append(f"Unknown properties in context_outcomes: {sorted(unknown_out)}")

        # Missing history MUST remain UNKNOWN, not INITIATION
        if outcomes.get("on_unknown_treatment_state") != "REMAIN_UNKNOWN_REQUIRE_REVIEW":
            errors.append("context_outcomes.on_unknown_treatment_state MUST be 'REMAIN_UNKNOWN_REQUIRE_REVIEW' (never default to initiation).")

        if outcomes.get("on_unknown_assay") != "INDETERMINATE_ASSAY_CONTEXT":
            errors.append("context_outcomes.on_unknown_assay MUST be 'INDETERMINATE_ASSAY_CONTEXT'.")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Release Eligibility Validator
# ---------------------------------------------------------------------------

def validate_release_eligibility(rule: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Asserts whether a rule is eligible for release into the active clinical pipeline.
    Drafts, research candidates, rules with unverified citations, or rules with null
    reviewer approvals MUST fail release eligibility.
    """
    eligible = True
    reasons: List[str] = []

    # 1. Structural validity first
    is_valid, struct_errors = validate_rule_schema(rule)
    if not is_valid:
        return False, [f"Structural failure: {err}" for err in struct_errors]

    gov = rule.get("governance", {})

    # 2. Superseded constraint
    if rule.get("is_superseded") is True or gov.get("review_status") == "SUPERSEDED":
        eligible = False
        reasons.append("Rule is SUPERSEDED and cannot be selected for release.")

    # 3. Tier constraint
    if rule.get("tier") != "TIER_1_EXECUTABLE":
        eligible = False
        reasons.append(f"Rule tier is '{rule.get('tier')}'; only 'TIER_1_EXECUTABLE' is eligible for release.")

    # 4. Governance Approval Constraints
    gov = rule.get("governance", {})
    if gov.get("review_status") != "APPROVED":
        eligible = False
        reasons.append(f"Governance review_status is '{gov.get('review_status')}'; must be 'APPROVED'.")

    if gov.get("release_approved") is not True:
        eligible = False
        reasons.append("governance.release_approved is False; rule has not received release approval.")

    for req_gov in ("clinical_reviewer_name", "clinical_reviewer_credential", "review_date", "approval_hash"):
        if not _is_non_empty_str(gov.get(req_gov)):
            eligible = False
            reasons.append(f"governance.{req_gov} is missing or null; release requires documented human reviewer approval.")

    # 5. Evidence Retrieval & Quote Match Verification Constraints
    refs = rule.get("evidence_references", [])
    active_supporting_refs: List[Tuple[int, dict]] = []
    historical_audit_refs: List[Tuple[int, dict]] = []

    for idx, ref in enumerate(refs):
        entry_type = ref.get("evidence_entry_type")
        if entry_type in {"HISTORICAL_AUDIT_RECORD", "FAILED_REQUEST_EVENT"}:
            historical_audit_refs.append((idx, ref))
        else:
            active_supporting_refs.append((idx, ref))

    # Invariant: Every active claim must have verified, approved supporting evidence.
    # An unsupported claim cannot be released merely by relabeling its evidence as historical.
    if not active_supporting_refs:
        eligible = False
        reasons.append("Rule has no active verified supporting evidence; historical audit events alone cannot support release of an active claim.")

    # Validate all active supporting evidence entries
    for idx, ref in active_supporting_refs:
        ret_status = ref.get("retrieval_status")
        quote_outcome = ref.get("quote_match_outcome")

        if ret_status != "RETRIEVED":
            eligible = False
            reasons.append(f"Active reference[{idx}] retrieval_status is '{ret_status}'; release requires 'RETRIEVED'.")

        if quote_outcome != "EXACT_MATCH":
            eligible = False
            reasons.append(f"Active reference[{idx}] quote_match_outcome is '{quote_outcome}'; release requires 'EXACT_MATCH'.")

        if quote_outcome in {"SOURCE_MISMATCH", "UNVERIFIED_RETRIEVAL_FAILED", "QUOTE_MISMATCH"}:
            eligible = False
            reasons.append(f"Active reference[{idx}] quote verification status is '{quote_outcome}'; unverified or mismatched quotation blocks release.")

        if not _is_non_empty_str(ref.get("document_sha256")):
            eligible = False
            reasons.append(f"Active reference[{idx}] document_sha256 is missing; verified cryptographic hash required for release.")

        reuse_status = ref.get("reuse_review_status")
        if reuse_status != "APPROVED":
            eligible = False
            reasons.append(f"Active reference[{idx}] reuse_review_status is '{reuse_status}'; release requires 'APPROVED' reuse review.")

    return eligible, reasons


# ---------------------------------------------------------------------------
# Inactive Context-Validation Scaffold
# ---------------------------------------------------------------------------

def evaluate_observed_context(rule: Dict[str, Any], patient_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inactive Context-Validation Scaffold.

    NOTE: This function is an inactive context-validation scaffold, NOT an
    implemented clinical trigger engine or automated clinical decision support system.
    It performs structural context checking and validation only and does NOT perform
    numeric evaluation, dosing calculation, or autonomous treatment guidance.

    Enforces the complete release-eligibility gate before evaluating observed context.
    Two editable fields (e.g. tier and release_approved) cannot bypass reviewer
    credentials, cryptographic approval hash, exact quote matching, or reuse review.
    Draft rules, research candidates, or rules lacking verified reviewer/evidence/reuse
    approvals cannot be evaluated against patient context.

    Guarantees:
    - Ineligible rules return advisory_status: RULE_NOT_RELEASED_INELIGIBLE.
    - Missing history returns treatment_state: UNKNOWN (never INITIATION).
    - Unknown assay architecture returns INDETERMINATE_ASSAY_CONTEXT.
    - Generic ABNORMAL lab status is rejected for directional rules.
    - Zero 'safe to proceed' claims are made.
    """
    rule_id = rule.get("rule_id", "UNKNOWN_RULE")
    output: Dict[str, Any] = {
        "rule_id": rule_id,
        "evaluated": False,
        "triggered": False,
        "applicability_confidence": "NONE",
        "advisory_status": "NOT_EVALUATED",
        "notes": []
    }

    # Enforce complete release-eligibility gate
    is_eligible, eligibility_reasons = validate_release_eligibility(rule)
    if not is_eligible:
        output["advisory_status"] = "RULE_NOT_RELEASED_INELIGIBLE"
        output["eligibility_reasons"] = eligibility_reasons
        output["notes"].append("Rule failed release-eligibility gate: " + "; ".join(eligibility_reasons))
        return output

    # Check observed treatment state
    observed_history = patient_context.get("history_available", False)
    if not observed_history:
        output["observed_treatment_state"] = "UNKNOWN"
        output["applicability_confidence"] = "LOW_INCOMPLETE_CONTEXT"
        output["advisory_status"] = "REQUIRE_MANUAL_REVIEW_UNKNOWN_HISTORY"
        output["notes"].append("Patient history is missing; treatment state remains UNKNOWN.")
        return output

    # Check assay architecture for analytical interference
    if rule.get("category") == "ANALYTICAL_INTERFERENCE":
        observed_assay = patient_context.get("assay_architecture")
        required_assay = rule.get("laboratory_criteria", {}).get("assay_platform_requirement", {}).get("architecture")
        if not observed_assay or observed_assay == "UNKNOWN":
            output["advisory_status"] = "INDETERMINATE_ASSAY_CONTEXT"
            output["applicability_confidence"] = "INDETERMINATE"
            output["notes"].append("Assay architecture unknown; cannot confirm or exclude analytical interference.")
            return output

    # Check direction-specific status match
    op = rule.get("evaluation_logic", {}).get("operator")
    if op == "STATUS_MATCH":
        observed_status = patient_context.get("lab_status")
        target_statuses = rule.get("evaluation_logic", {}).get("target_lab_statuses", [])
        if observed_status == "ABNORMAL" and "ABNORMAL" not in target_statuses:
            output["advisory_status"] = "AMBIGUOUS_DIRECTION_UNRESOLVED"
            output["applicability_confidence"] = "NONE"
            output["notes"].append("Generic ABNORMAL lab status cannot satisfy direction-specific requirement.")
            return output

    output["evaluated"] = True
    return output


# ---------------------------------------------------------------------------
# Specification Version 1.0.0 (SUPERSEDED)
# ---------------------------------------------------------------------------
# Marked SUPERSEDED due to conflicting product/application identities
# (e.g., Coumadin NDA 009218 attributed to Prednisone, Aldactone NDA 012151
# attributed to Warfarin, Rayos NDA 202020 attributed to Spironolactone),
# speculative URLs, and unverified quotations. Cannot be selected for release.

SUPERSEDED_SPECIFICATION: Dict[str, Dict[str, Any]] = {
    "MED_LAB_SAF_METFORMIN_EGFR_V1": {
        "rule_id": "MED_LAB_SAF_METFORMIN_EGFR_V1",
        "rule_version": "1.0.0",
        "tier": "TIER_1_EXECUTABLE",
        "category": "CLINICAL_SAFETY_MONITORING",
        "is_superseded": True,
        "superseded_by": "AUTHORITATIVE_CURRENT_SPECIFICATION",
        "superseded_reason": "Superseded by authoritative Specification V2 (bounded metadata cleanup).",
        "governance": {
            "review_status": "SUPERSEDED",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "SUPERSEDED: Earlier candidate specification replaced by Authoritative Specification V2."
        },
        "medication_criteria": {
            "generic_name": "metformin",
            "rxnorm_cui": "6809",
            "who_atc_code": "A10BA02",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET", "EXTENDED_RELEASE_TABLET", "ORAL_SOLUTION"],
            "treatment_state": "INITIATION"
        },
        "laboratory_criteria": {
            "analyte_key": "EGFR",
            "canonical_display_name": "Estimated Glomerular Filtration Rate",
            "loinc_code": "33914-3",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "mL/min/1.73 m2",
            "allowed_unit_aliases": ["mL/min/1.73m2", "mL/min/1.73 m^2"],
            "specimen_type": "SERUM_OR_PLASMA",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "LAB_TO_MED",
            "operator": "BETWEEN",
            "threshold_value": 30.0,
            "threshold_range_high": 45.0,
            "interval_endpoints": "CLOSED",
            "target_lab_statuses": ["ABNORMAL_LOW"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Prescribing Information",
                "document_id": "NDA 020357 / Glucophage",
                "section": "Dosage and Administration - Recommendations for Use in Renal Impairment",
                "publication_or_revision_date": "2017-01-01",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/020357s037s038lbl.pdf",
                "retrieval_status": "RETRIEVAL_FAILED",
                "document_sha256": None,
                "verbatim_passage": "[SUPERSEDED passage: retrieval failed; unverified.]",
                "quote_match_outcome": "UNVERIFIED_RETRIEVAL_FAILED",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "CRITICAL_SAFETY",
            "action_category": "CONTRAINDICATION_ALERT",
            "summary_title": "Metformin Renal Boundary (Superseded)",
            "authored_advisory_text": "Superseded specification draft. Non-executable.",
            "prohibited_actions": ["AUTONOMOUS_DOSE_CHANGE", "AUTONOMOUS_DISCONTINUATION"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },
    "MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V1": {
        "rule_id": "MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V1",
        "rule_version": "1.0.0",
        "tier": "TIER_2_RESEARCH_CANDIDATE",
        "category": "CLINICAL_SAFETY_MONITORING",
        "is_superseded": True,
        "superseded_by": "AUTHORITATIVE_CURRENT_SPECIFICATION",
        "superseded_reason": "Conflicted application identity (cited Aldactone NDA 012151 instead of Coumadin NDA 009218).",
        "governance": {
            "review_status": "SUPERSEDED",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "SUPERSEDED: Contained application identity conflict (NDA 012151 is Aldactone, not Coumadin)."
        },
        "medication_criteria": {
            "generic_name": "warfarin",
            "rxnorm_cui": "11289",
            "who_atc_code": "B01AA03",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "HEMOGLOBIN",
            "canonical_display_name": "Hemoglobin",
            "loinc_code": "718-7",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "g/dL",
            "allowed_unit_aliases": ["g/dl", "g/L"],
            "specimen_type": "WHOLE_BLOOD",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "LAB_TO_MED",
            "operator": "<",
            "threshold_value": 8.0,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ABNORMAL_LOW"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Prescribing Information",
                "document_id": "NDA 012151 [MISMATCH]",
                "section": "Warnings and Precautions",
                "publication_or_revision_date": "2011-10-01",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2011/012151s070lbl.pdf",
                "retrieval_status": "RETRIEVAL_FAILED",
                "document_sha256": None,
                "verbatim_passage": "[SUPERSEDED: Mismatched application identity.]",
                "quote_match_outcome": "UNVERIFIED_RETRIEVAL_FAILED",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "CRITICAL_SAFETY",
            "action_category": "CONTRAINDICATION_ALERT",
            "summary_title": "Warfarin Bleeding Risk (Superseded)",
            "authored_advisory_text": "Superseded specification draft. Non-executable.",
            "prohibited_actions": ["AUTONOMOUS_ANTICOAGULATION_REVERSAL"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    }
}


# ---------------------------------------------------------------------------
# Authoritative Current Specification (Version 2.0.0 - Bounded Cleanup)
# ---------------------------------------------------------------------------
# All rules are DRAFT, release_approved=False, and non-executable.
# Conflicting application numbers resolved from official FDA metadata.
# Exact quotes, URLs, and retrieval statuses honestly recorded.

AUTHORITATIVE_CURRENT_SPECIFICATION: Dict[str, Dict[str, Any]] = {
    # 1. Metformin & eGFR (Tier 1 Executable Candidate - DRAFT)
    "MED_LAB_SAF_METFORMIN_EGFR_V2": {
        "rule_id": "MED_LAB_SAF_METFORMIN_EGFR_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_1_EXECUTABLE",
        "category": "CLINICAL_SAFETY_MONITORING",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "Draft candidate. Retrieval failed with HTTP 404; retrieval failure cause remains UNKNOWN. Document unread; neither presence nor absence of thresholds can be confirmed against an unread document. Release strictly blocked."
        },
        "medication_criteria": {
            "generic_name": "metformin",
            "rxnorm_cui": "6809",
            "who_atc_code": "A10BA02",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET", "EXTENDED_RELEASE_TABLET", "ORAL_SOLUTION"],
            "treatment_state": "INITIATION"
        },
        "laboratory_criteria": {
            "analyte_key": "EGFR",
            "canonical_display_name": "Estimated Glomerular Filtration Rate",
            "loinc_code": "33914-3",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "mL/min/1.73 m2",
            "allowed_unit_aliases": ["mL/min/1.73m2", "mL/min/1.73 m^2"],
            "specimen_type": "SERUM_OR_PLASMA",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "LAB_TO_MED",
            "operator": "BETWEEN",
            "threshold_value": 30.0,
            "threshold_range_high": 45.0,
            "interval_endpoints": "CLOSED",
            "target_lab_statuses": ["ABNORMAL_LOW"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "GLUCOPHAGE / GLUCOPHAGE XR Tablets",
                "active_ingredient": "metformin hydrochloride",
                "actual_document_title": "GLUCOPHAGE (metformin hydrochloride) Prescribing Information",
                "document_id": "NDA 020357",
                "section": "Dosage and Administration - Recommendations for Use in Renal Impairment",
                "page_or_section": "Section 2 Dosage and Administration",
                "publication_or_revision_date": "2017-01-01",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/020357s037s038lbl.pdf",
                "attempted_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/020357s037s038lbl.pdf",
                "resolved_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/020357s037s038lbl.pdf",
                "retrieval_status": "RETRIEVAL_FAILED",
                "retrieval_failure_reason": "UNKNOWN",
                "document_sha256": None,
                "verbatim_passage": "[UNVERIFIED: Document unread due to HTTP 404 retrieval failure. Proposed quote: 'Initiation of GLUCOPHAGE in patients with an eGFR between 30 and 45 mL/minute/1.73 m2 is not recommended. GLUCOPHAGE is contraindicated in patients with an eGFR below 30 mL/minute/1.73 m2.']",
                "quote_match_outcome": "UNVERIFIED_RETRIEVAL_FAILED",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "CRITICAL_SAFETY",
            "action_category": "CONTRAINDICATION_ALERT",
            "summary_title": "Metformin Renal Boundary - Initiation Advisory (Draft)",
            "authored_advisory_text": "Draft advisory: In patients initiating metformin therapy with confirmed eGFR 30-45 mL/min/1.73 m2, initiation is generally not recommended due to lactic acidosis risk. For continuation, assess benefit-risk. If eGFR is below 30 mL/min/1.73 m2, metformin is contraindicated.",
            "prohibited_actions": ["AUTONOMOUS_DOSE_CHANGE", "AUTONOMOUS_DISCONTINUATION"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },

    # 2. Biotin & Immunoassays (Tier 1 Executable Candidate - DRAFT)
    "MED_LAB_INT_BIOTIN_IMMUNOASSAY_V2": {
        "rule_id": "MED_LAB_INT_BIOTIN_IMMUNOASSAY_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_1_EXECUTABLE",
        "category": "ANALYTICAL_INTERFERENCE",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "Draft candidate. FDA Safety Communication URL returned HTTP 404; retrieval failure cause remains UNKNOWN. Document unread; unverified against local document. Release blocked."
        },
        "medication_criteria": {
            "generic_name": "biotin",
            "rxnorm_cui": "1502",
            "who_atc_code": "A11HA05",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL", "INTRAVENOUS"],
            "allowed_dosage_forms": ["TABLET", "CAPSULE", "INJECTION"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "TROPONIN_OR_THYROID",
            "canonical_display_name": "Biotin-Streptavidin Susceptible Immunoassays",
            "loinc_code": "UNKNOWN",
            "loinc_mapping_status": "UNMAPPED_UNKNOWN",
            "required_canonical_unit": "VARIOUS",
            "allowed_unit_aliases": [],
            "specimen_type": "SERUM_OR_PLASMA",
            "assay_platform_requirement": {
                "architecture": "SANDWICH_IMMUNOMETRIC",
                "susceptible_technologies": ["STREPTAVIDIN_BIOTIN_CAPTURE"],
                "immune_technologies": ["NON_BIOTIN_CHEMILUMINESCENT"],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "MED_TO_LAB",
            "operator": "STATUS_MATCH",
            "threshold_value": None,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ANY_VALUE"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Safety Communication",
                "exact_product_name": "In Vitro Diagnostic Devices (Biotin Guidance)",
                "active_ingredient": "biotin",
                "actual_document_title": "FDA Warns that Biotin May Interfere with Lab Tests: FDA Safety Communication",
                "document_id": "FDA-2017-A-BIOTIN",
                "section": "Safety Alerts for Human Medical Products",
                "page_or_section": "Safety Alerts Section",
                "publication_or_revision_date": "2019-11-05",
                "source_url": "https://www.fda.gov/medical-devices/safety-communications/fda-warns-biotin-may-interfere-lab-tests",
                "attempted_url": "https://www.fda.gov/medical-devices/safety-communications/fda-warns-biotin-may-interfere-lab-tests",
                "resolved_url": "https://www.fda.gov/medical-devices/safety-communications/fda-warns-biotin-may-interfere-lab-tests",
                "retrieval_status": "RETRIEVAL_FAILED",
                "retrieval_failure_reason": "UNKNOWN",
                "document_sha256": None,
                "verbatim_passage": "[UNVERIFIED: Document unread due to HTTP 404 retrieval failure. Proposed quote: 'Biotin in patient samples can cause falsely high or falsely low test results, depending on the test design. In competitive immunoassays, biotin interference generally causes falsely high results. In sandwich immunoassays, it generally causes falsely low results.']",
                "quote_match_outcome": "UNVERIFIED_RETRIEVAL_FAILED",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "ANALYTICAL_INTERPRETATION",
            "action_category": "INTERFERENCE_CAUTION",
            "summary_title": "Biotin Immunoassay Interference Risk (Draft)",
            "authored_advisory_text": "Draft advisory: Exogenous biotin interferes with streptavidin-biotinylated immunoassays: sandwich assays may yield falsely low results, whereas competitive assays may yield falsely high results. If assay methodology is unknown, analytical validity remains indeterminate.",
            "prohibited_actions": ["AUTONOMOUS_INTERPRETATION_OVERRIDE"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },

    # 3. Ascorbic Acid & Glucose Meter (Tier 1 Executable Candidate - DRAFT / SOURCE_MISMATCH)
    "MED_LAB_INT_ASCORBIC_ACID_GLUCOSE_V2": {
        "rule_id": "MED_LAB_INT_ASCORBIC_ACID_GLUCOSE_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_1_EXECUTABLE",
        "category": "ANALYTICAL_INTERFERENCE",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "AUDIT FINDING: Citation FDA K121674 retrieved document is FUJIFILM FDR MS-2500 Digital Mammography System. Citation is marked SOURCE_MISMATCH and all claims UNVERIFIED. Failed retrieval is not verification. Rule cannot be released."
        },
        "medication_criteria": {
            "generic_name": "ascorbic acid",
            "rxnorm_cui": "1151",
            "who_atc_code": "A11GA01",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL", "INTRAVENOUS"],
            "allowed_dosage_forms": ["TABLET", "INJECTION"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "BLOOD_GLUCOSE",
            "canonical_display_name": "Capillary Blood Glucose",
            "loinc_code": "2339-0",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "mg/dL",
            "allowed_unit_aliases": ["mg/dl", "mmol/L"],
            "specimen_type": "CAPILLARY_WHOLE_BLOOD",
            "assay_platform_requirement": {
                "architecture": "ELECTROCHEMICAL_REDOX",
                "susceptible_technologies": ["GLUCOSE_DEHYDROGENASE_PQQ", "GLUCOSE_OXIDASE_ELECTROCHEMICAL"],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "MED_TO_LAB",
            "operator": "STATUS_MATCH",
            "threshold_value": None,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ANY_VALUE"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA 510(k) Premarket Notification",
                "exact_product_name": "Capillary Blood Glucose Meter (Cited 510(k))",
                "active_ingredient": "ascorbic acid",
                "actual_document_title": "FUJIFILM Medical Systems U.S.A., Inc. - Aspire HD Plus / FDR MS-2500 Full Field Digital Mammography System",
                "document_id": "K121674",
                "section": "Submitter Information / Device Description",
                "page_or_section": "510(k) Summary (Page 1-5)",
                "publication_or_revision_date": "2012-06-01",
                "source_url": "https://www.accessdata.fda.gov/cdrh_docs/pdf12/K121674.pdf",
                "attempted_url": "https://www.accessdata.fda.gov/cdrh_docs/pdf12/K121674.pdf",
                "resolved_url": "https://www.accessdata.fda.gov/cdrh_docs/pdf12/K121674.pdf",
                "retrieval_status": "SOURCE_MISMATCH",
                "retrieval_failure_reason": "NONE",
                "document_sha256": "e55b80433ba501bca0af90510c059259719e0cc06712c44e71d87cda71ec4493",
                "verbatim_passage": "[CITATION MISMATCH: Retrieved document is FUJIFILM Medical Systems Aspire HD Plus FDR MS-2500 Digital Mammography System; does not concern glucose meters or ascorbic acid.]",
                "quote_match_outcome": "SOURCE_MISMATCH",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "ANALYTICAL_INTERPRETATION",
            "action_category": "INTERFERENCE_CAUTION",
            "summary_title": "Ascorbic Acid Glucose Meter Interference (Unverified Citation)",
            "authored_advisory_text": "Ascorbic acid may cause analytical interference in electrochemical glucose sensors. However, cited 510(k) K121674 is a Fujifilm mammography clearance (SOURCE_MISMATCH). Clinical claims remain UNVERIFIED pending primary device literature.",
            "prohibited_actions": ["AUTONOMOUS_INSULIN_ADJUSTMENT"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },

    # 4. Prednisone & Blood Glucose (Tier 2 Research Candidate - DRAFT)
    # RESOLVED IDENTITY: RAYOS (prednisone) delayed-release tablets, NDA 202020
    # (Deltasone legacy tablets were NDA 010374, discontinued; NDA 009218 was Coumadin).
    "MED_LAB_PD_PREDNISONE_GLUCOSE_V2": {
        "rule_id": "MED_LAB_PD_PREDNISONE_GLUCOSE_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_2_RESEARCH_CANDIDATE",
        "category": "PHARMACODYNAMIC_EFFECT",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "Research candidate. Rayos NDA 202020 label retrieved. Section 5.1 (Page 5) verified verbatim for hyperglycemia during chronic use. The curated source concerns RAYOS delayed-release tablets; other prednisone formulations (e.g. immediate-release tablets, oral solution) and unspecified/acute treatment durations remain proposed, unapproved extensions, not verified applicability. Antidiabetic-agent dose adjustment guidance is located in Section 7.5 (corrected from 7.1). Glucose terminology preserves unknown fasting context; fasting-specific LOINC 1558-6 is not assigned and mapping remains unverified (loinc_code UNKNOWN, loinc_mapping_status UNVERIFIED). mmol/L is separated as a convertible unit, not a spelling alias. Failed original request and replacement retrieval separated into distinct events. Source revision recorded as 2012-07 (HISTORICAL_LABEL); current official label is CURRENT_LABEL_NOT_VERIFIED without guessing URLs. Reuse review is PENDING (commercial sponsor authored; FDA hosting does not establish federal government authorship under 17 U.S.C. 105). Non-executable; release strictly blocked."
        },
        "medication_criteria": {
            "generic_name": "prednisone",
            "rxnorm_cui": "8640",
            "who_atc_code": "H02AB07",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["DELAYED_RELEASE_TABLET", "TABLET", "ORAL_SOLUTION"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "BLOOD_GLUCOSE",
            "canonical_display_name": "Blood Glucose (Fasting Status Unknown)",
            "loinc_code": "UNKNOWN",
            "loinc_mapping_status": "UNVERIFIED",
            "fasting_context": "UNKNOWN",
            "required_canonical_unit": "mg/dL",
            "allowed_unit_aliases": ["mg/dl", "MG/DL", "mg/dL"],
            "convertible_units": ["mmol/L"],
            "specimen_type": "SERUM_OR_PLASMA",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "MED_TO_LAB",
            "operator": "STATUS_MATCH",
            "threshold_value": None,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ABNORMAL_HIGH", "HIGH"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "evidence_entry_type": "FAILED_REQUEST_EVENT",
                "event_description": "Original failed HTTP request attempting to retrieve Deltasone label via speculative URL",
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "Deltasone (historical speculative citation)",
                "active_ingredient": "prednisone",
                "actual_document_title": "Unretrieved (speculative URL)",
                "document_id": "NDA 009218 (citation error; pertained to Coumadin)",
                "section": "Section 5 Warnings and Precautions",
                "page_or_section": "Unknown (failed retrieval)",
                "publication_or_revision_date": "2015",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/009218s112lbl.pdf",
                "requested_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/009218s112lbl.pdf",
                "actual_http_final_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/009218s112lbl.pdf",
                "replacement_source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "retrieval_status": "RETRIEVAL_FAILED",
                "retrieval_date": "2026-10-16",
                "retrieval_failure_reason": "HTTP_404_NOT_FOUND",
                "document_sha256": None,
                "verbatim_passage": "[RETRIEVAL FAILED: HTTP 404 Not Found at requested URL. Erroneous application 009218 pertained to Coumadin; document could not be retrieved.]",
                "quote_match_outcome": "UNVERIFIED_RETRIEVAL_FAILED",
                "quote_match_method": "NONE",
                "quotation_verification_notes": "Original request failed with HTTP 404. Application 009218 was a citation mismatch/error. Document was not retrieved; hash is None.",
                "supported_claim": "None (retrieval failed).",
                "clinical_applicability_assessment": "Failed retrieval event; cannot support clinical decision-making.",
                "source_text_verification_status": "UNVERIFIED_RETRIEVAL_FAILED",
                "clinical_applicability_review_status": "NOT_APPLICABLE",
                "reuse_review_status": "NOT_APPLICABLE",
                "release_approval_status": False,
                "license_type": "UNKNOWN"
            },
            {
                "evidence_entry_type": "HISTORICAL_AUDIT_RECORD",
                "event_description": "Historical proposed quotation tested against the successfully retrieved replacement RAYOS label",
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "RAYOS (prednisone) delayed-release tablets",
                "active_ingredient": "prednisone",
                "actual_document_title": "RAYOS (prednisone) delayed-release tablets, HORIZON PHARMA INC",
                "document_id": "NDA 202020",
                "section": "Section 5.1 Alterations in Endocrine Function",
                "page_or_section": "Section 5.1 (Page 5)",
                "publication_or_revision_date": "2012-07",
                "label_currency_status": "HISTORICAL_LABEL",
                "current_official_label_status": "CURRENT_LABEL_NOT_VERIFIED",
                "currency_notes": "Retrieved document 202020s000lbl.pdf represents initial approval labeling from 2012-07 (HISTORICAL_LABEL). Catalog lookup for current official labeling was attempted but unavailable via direct endpoint; recorded as CURRENT_LABEL_NOT_VERIFIED without guessing URLs.",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "requested_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "actual_http_final_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "replacement_source_url": None,
                "retrieval_status": "RETRIEVED",
                "retrieval_date": "2026-10-16",
                "retrieval_failure_reason": "NONE",
                "document_sha256": "4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427",
                "verbatim_passage": "[Historical Proposed Quote]: Corticosteroids can produce elevations of blood glucose, worsen pre-existing diabetes, and predispose patients on long-term therapy to diabetes mellitus.",
                "quote_match_outcome": "QUOTE_MISMATCH",
                "quote_match_method": "CASE_INSENSITIVE_NORMALIZED_EXACT_SUBSTRING_MATCH",
                "quotation_verification_notes": "The earlier proposed quotation from Deltasone literature was searched against the retrieved RAYOS label (SHA-256 4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427). The text was absent from the document (QUOTE_MISMATCH). Linked to the successful replacement document hash.",
                "supported_claim": "None (unsupported due to quotation mismatch against retrieved document).",
                "clinical_applicability_assessment": "Unverified historical quotation; cannot support clinical decision-making. Preserved solely as historical audit evidence.",
                "source_text_verification_status": "UNVERIFIED_MISMATCH",
                "clinical_applicability_review_status": "PENDING",
                "reuse_review_status": "PENDING",
                "reuse_notes": "Document-specific reuse review is PENDING. The package insert was authored by commercial sponsor Horizon Pharma Inc.; FDA hosting/approval does not establish federal-government authorship under 17 U.S.C. 105. Institutional reuse review required.",
                "release_approval_status": False,
                "license_type": "PENDING_REVIEW"
            },
            {
                "evidence_entry_type": "CURATED_SOURCE_RECORD",
                "event_description": "Verified Section 5.1 primary source quotation from retrieved RAYOS label",
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "RAYOS (prednisone) delayed-release tablets",
                "active_ingredient": "prednisone",
                "actual_document_title": "RAYOS (prednisone) delayed-release tablets, HORIZON PHARMA INC",
                "document_id": "NDA 202020",
                "section": "Section 5.1 Alterations in Endocrine Function",
                "page_or_section": "Section 5.1 (Page 5)",
                "publication_or_revision_date": "2012-07",
                "label_currency_status": "HISTORICAL_LABEL",
                "current_official_label_status": "CURRENT_LABEL_NOT_VERIFIED",
                "currency_notes": "Retrieved document 202020s000lbl.pdf represents initial approval labeling from 2012-07 (HISTORICAL_LABEL). Catalog lookup for current official labeling was attempted but unavailable via direct endpoint; recorded as CURRENT_LABEL_NOT_VERIFIED without guessing URLs.",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "requested_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "actual_http_final_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf",
                "replacement_source_url": None,
                "retrieval_status": "RETRIEVED",
                "retrieval_date": "2026-10-16",
                "retrieval_failure_reason": "NONE",
                "document_sha256": "4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427",
                "verbatim_passage": "Hypothalamic-pituitary-adrenal (HPA) axis suppression, Cushing’s syndrome, and hyperglycemia. Monitor patients for these conditions with chronic use.",
                "quote_match_outcome": "EXACT_MATCH",
                "quote_match_method": "CASE_INSENSITIVE_NORMALIZED_EXACT_SUBSTRING_MATCH",
                "quotation_verification_notes": "Matches verbatim on Page 5, Section 5.1 of the retrieved FDA label PDF (SHA-256 4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427).",
                "supported_claim": "Qualitative pharmacodynamic relationship: chronic corticosteroid therapy (prednisone) can produce hyperglycemia, and patients should be monitored for hyperglycemia with chronic use.",
                "clinical_applicability_assessment": "Source text is verified and document is valid FDA prescribing information. However, exact quotation matching establishes source text validity only; clinical applicability to automated decision-support is pending independent medical reviewer evaluation. The curated source concerns RAYOS delayed-release tablets (NDA 202020) and the quotation specifically refers to monitoring during chronic use; other prednisone formulations and unspecified treatment durations remain proposed, unapproved extensions—not verified applicability. The candidate adds no numeric glucose cutoff, fixed monitoring interval, causal diagnosis, or autonomous treatment instruction. Antidiabetic-agent dose adjustment guidance in Section 7.5 provides clinical context for clinician consideration, but is not encoded as an automated action.",
                "source_text_verification_status": "VERIFIED",
                "clinical_applicability_review_status": "PENDING",
                "reuse_review_status": "PENDING",
                "reuse_notes": "Document-specific reuse review is PENDING. Drug package insert was authored by commercial sponsor Horizon Pharma Inc. and submitted to FDA for approval. Under 17 U.S.C. 105, federal government hosting/approval does not establish federal-government authorship or public domain status. An applicable institutional policy and documented legal/licensing rationale must be established before intended reuse.",
                "release_approval_status": False,
                "license_type": "PENDING_REVIEW"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "SIGNIFICANT_MONITORING",
            "action_category": "MONITORING_MANDATED",
            "summary_title": "Corticosteroid Hyperglycemia Monitoring Consideration (Qualitative)",
            "authored_advisory_text": "Chronic therapy with systemic corticosteroids (including prednisone delayed-release tablets) can produce hyperglycemia. Official package insert advises monitoring patients for hyperglycemia with chronic use (Section 5.1) and notes dosage adjustments of antidiabetic agents may be required (Section 7.5). Other prednisone formulations and unspecified treatment durations remain proposed, unapproved extensions. The candidate adds no numeric glucose cutoff, fixed monitoring interval, causal diagnosis, or autonomous treatment instruction.",
            "prohibited_actions": [
                "AUTONOMOUS_INSULIN_INITIATION",
                "AUTONOMOUS_DOSE_CHANGE",
                "AUTONOMOUS_CAUSAL_DIAGNOSIS",
                "UNSUPPORTED_NUMERIC_CUTOFF"
            ]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },

    # 5. Warfarin & Hemoglobin/Platelets (Tier 2 Research Candidate - DRAFT)
    # RESOLVED IDENTITY: COUMADIN (warfarin sodium) Tablets / Injection, NDA 009218
    # (NDA 012151 was Aldactone, not Coumadin).
    "MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V2": {
        "rule_id": "MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_2_RESEARCH_CANDIDATE",
        "category": "CLINICAL_SAFETY_MONITORING",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "Research candidate. Coumadin NDA 009218 label retrieved. General bleeding warning in Section 5.1 (Page 10) and unexplained fall in hemoglobin in Section 10.2 (Page 19). However, synthetic triggers (Hb < 8.0 g/dL, Platelets < 50,000/uL) are absent from the label. Earlier proposed quote was a paraphrase (QUOTE_MISMATCH). Non-executable."
        },
        "medication_criteria": {
            "generic_name": "warfarin",
            "rxnorm_cui": "11289",
            "who_atc_code": "B01AA03",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "HEMOGLOBIN",
            "canonical_display_name": "Hemoglobin",
            "loinc_code": "718-7",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "g/dL",
            "allowed_unit_aliases": ["g/dl", "g/L"],
            "specimen_type": "WHOLE_BLOOD",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "LAB_TO_MED",
            "operator": "<",
            "threshold_value": 8.0,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ABNORMAL_LOW"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "COUMADIN Tablets / COUMADIN for Injection",
                "active_ingredient": "warfarin sodium",
                "actual_document_title": "COUMADIN (warfarin sodium) Tablets / COUMADIN for Injection Label",
                "document_id": "NDA 009218",
                "section": "Section 5.1 Hemorrhage, Section 10 Overdosage",
                "page_or_section": "Section 5.1 (Page 10), Section 10.2 (Page 19)",
                "publication_or_revision_date": "2011-10-01",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2011/009218s107lbl.pdf",
                "attempted_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2011/012151s070lbl.pdf",
                "resolved_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2011/009218s107lbl.pdf",
                "retrieval_status": "RETRIEVED",
                "retrieval_failure_reason": "NONE",
                "document_sha256": "254db82ed36191a5c4589ff0674714add375d6c6b0f78a8323d521f8f6ed1c8e",
                "verbatim_passage": "COUMADIN can cause major or fatal bleeding. Bleeding is more likely to occur within the first month. Risk factors for bleeding include high intensity of anticoagulation (INR >4.0), age greater than or equal to 65...",
                "quote_match_outcome": "QUOTE_MISMATCH",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "CRITICAL_SAFETY",
            "action_category": "CONTRAINDICATION_ALERT",
            "summary_title": "Warfarin Bleeding Risk with Anemia (Research Candidate)",
            "authored_advisory_text": "Warfarin increases major bleeding risks. Hemoglobin < 8.0 g/dL suggests active or severe blood loss requiring clinical evaluation. The specific numeric trigger is an unverified research candidate cutoff not in the FDA label.",
            "prohibited_actions": ["AUTONOMOUS_ANTICOAGULATION_REVERSAL"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    },

    # 6. Spironolactone & Serum Potassium (Tier 2 Research Candidate - DRAFT)
    # RESOLVED IDENTITY: ALDACTONE (spironolactone) Tablets, NDA 012151
    # (NDA 202020 was Rayos, not Aldactone; CaroSpir oral suspension is NDA 209478).
    "MED_LAB_SAF_SPIRONOLACTONE_POTASSIUM_V2": {
        "rule_id": "MED_LAB_SAF_SPIRONOLACTONE_POTASSIUM_V2",
        "rule_version": "2.0.0",
        "tier": "TIER_2_RESEARCH_CANDIDATE",
        "category": "CLINICAL_SAFETY_MONITORING",
        "governance": {
            "review_status": "DRAFT",
            "clinical_reviewer_name": None,
            "clinical_reviewer_credential": None,
            "review_date": None,
            "release_approved": False,
            "approval_hash": None,
            "governance_notes": "Research candidate. Aldactone NDA 012151 label retrieved. Warnings describe hyperkalemia risks (Page 8-10) and heart failure initiation when potassium <= 5.0 mEq/L (Page 15). Proposed quote was a paraphrase (QUOTE_MISMATCH). Non-executable."
        },
        "medication_criteria": {
            "generic_name": "spironolactone",
            "rxnorm_cui": "9997",
            "who_atc_code": "C03DA01",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET", "ORAL_SUSPENSION"],
            "treatment_state": "ANY"
        },
        "laboratory_criteria": {
            "analyte_key": "POTASSIUM",
            "canonical_display_name": "Serum Potassium",
            "loinc_code": "2823-3",
            "loinc_mapping_status": "CURATED_EXACT",
            "required_canonical_unit": "mmol/L",
            "allowed_unit_aliases": ["mEq/L", "meq/l"],
            "specimen_type": "SERUM_OR_PLASMA",
            "assay_platform_requirement": {
                "architecture": "NOT_APPLICABLE",
                "susceptible_technologies": [],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False
            }
        },
        "evaluation_logic": {
            "direction": "LAB_TO_MED",
            "operator": ">",
            "threshold_value": 5.0,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "target_lab_statuses": ["ABNORMAL_HIGH"],
            "timing_window_days": None
        },
        "evidence_references": [
            {
                "source_name": "US FDA Prescribing Information",
                "exact_product_name": "ALDACTONE (spironolactone) Tablets",
                "active_ingredient": "spironolactone",
                "actual_document_title": "Aldactone (spironolactone) 25 mg, 50 mg, and 100 mg Tablets, GD SEARLE LLC",
                "document_id": "NDA 012151",
                "section": "Warnings: Hyperkalemia, Dosage and Administration: Severe Heart Failure",
                "page_or_section": "Warnings (Page 8-10), Dosage (Page 15)",
                "publication_or_revision_date": "2014-10-23",
                "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2014/012151s072lbl.pdf",
                "attempted_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/202020s000lbl.pdf",
                "resolved_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2014/012151s072lbl.pdf",
                "retrieval_status": "RETRIEVED",
                "retrieval_failure_reason": "NONE",
                "document_sha256": "993588c057b217c11cd6e6f58d1156ab2691ab117a610966c883560abb3e0854",
                "verbatim_passage": "Hyperkalemia may occur in patients with impaired renal function or excessive potassium intake and can cause cardiac irregularities, which may be fatal.",
                "quote_match_outcome": "QUOTE_MISMATCH",
                "license_type": "PUBLIC_DOMAIN_US_GOVERNMENT"
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "CRITICAL_SAFETY",
            "action_category": "CONTRAINDICATION_ALERT",
            "summary_title": "Spironolactone Hyperkalemia Advisory (Research Candidate)",
            "authored_advisory_text": "Spironolactone can cause serious hyperkalemia. Concomitant potassium elevations require clinical monitoring and possible dose modification. Specific threshold > 5.0 mmol/L is an unverified research candidate cutoff.",
            "prohibited_actions": ["AUTONOMOUS_DOSE_CHANGE", "AUTONOMOUS_DISCONTINUATION"]
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_EVALUATION",
            "on_incompatible_unit": "CONVERT_OR_REJECT",
            "on_missing_value": "REJECT_EVALUATION",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW"
        }
    }
}

# Alias for backwards-compatible loading of authoritative specification
PROPOSED_DRAFT_RULES = AUTHORITATIVE_CURRENT_SPECIFICATION


