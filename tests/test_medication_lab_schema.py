"""
===============================================================================
TEST SUITE: MEDICATION-LABORATORY SCHEMA AND GOVERNANCE
===============================================================================

Validates structural schema rules, governance boundaries, release eligibility,
and context handling invariants.
Non-executable: does not wire into clinical pipelines or activate clinical rules.
"""

import copy
import inspect
import pytest
from medication_lab_schema import (
    validate_rule_schema,
    validate_release_eligibility,
    evaluate_observed_context,
    PROPOSED_DRAFT_RULES,
    AUTHORITATIVE_CURRENT_SPECIFICATION,
    SUPERSEDED_SPECIFICATION,
    MILESTONE_STATUS,
)


# =============================================================================
# 1. Structural Schema Validation Tests
# =============================================================================

class TestStructuralValidation:
    """Tests schema enforcement, rejecting malformed, incomplete, or unknown properties."""

    def test_all_authoritative_rules_pass_structural_schema(self):
        """All 6 authoritative current rules must be structurally valid."""
        for rule_id, rule in AUTHORITATIVE_CURRENT_SPECIFICATION.items():
            valid, errors = validate_rule_schema(rule)
            assert valid is True, f"Rule {rule_id} failed structural schema: {errors}"
            assert len(errors) == 0

    def test_all_superseded_rules_pass_structural_schema(self):
        """Superseded rules must pass structural schema while flagged as superseded."""
        for rule_id, rule in SUPERSEDED_SPECIFICATION.items():
            valid, errors = validate_rule_schema(rule)
            assert valid is True, f"Rule {rule_id} failed structural schema: {errors}"
            assert len(errors) == 0

    def test_reject_unknown_top_level_property(self):
        """Reject unknown properties at top level (additionalProperties: false)."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["unknown_field"] = "malicious_or_unsupported_data"
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("Unknown top-level properties detected" in err for err in errors)

    def test_reject_unknown_nested_property(self):
        """Reject unknown properties within nested structures (e.g. governance)."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["governance"]["extra_field"] = "not_in_schema"
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("Unknown properties in governance" in err for err in errors)

    def test_reject_empty_required_evidence_strings(self):
        """Reject empty strings in evidence reference requirements."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["evidence_references"][0]["verbatim_passage"] = "   "
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("verbatim_passage must be a non-empty string" in err for err in errors)

        rule2 = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule2["evidence_references"][0]["document_id"] = ""
        valid2, errors2 = validate_rule_schema(rule2)
        assert valid2 is False
        assert any("document_id must be a non-empty string" in err for err in errors2)

    def test_require_https_urls(self):
        """Evidence URLs must be HTTPS, not insecure HTTP or plain text."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["evidence_references"][0]["source_url"] = "http://www.fda.gov/insecure"
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("source_url must be an HTTPS URL" in err for err in errors)

        rule2 = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule2["evidence_references"][0]["source_url"] = "not_a_url"
        valid2, errors2 = validate_rule_schema(rule2)
        assert valid2 is False
        assert any("source_url must be an HTTPS URL" in err for err in errors2)

    def test_enforce_route_and_dosage_form_separation(self):
        """Route and dosage form must be separate non-empty lists."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["medication_criteria"]["allowed_routes"] = []
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("allowed_routes must be a non-empty list" in err for err in errors)

        rule2 = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule2["medication_criteria"]["allowed_dosage_forms"] = "TABLET"  # Not a list
        valid2, errors2 = validate_rule_schema(rule2)
        assert valid2 is False
        assert any("allowed_dosage_forms must be a non-empty list" in err for err in errors2)

    def test_between_operator_requires_valid_range_and_endpoints(self):
        """BETWEEN operator requires low < high and explicit interval endpoints."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["evaluation_logic"]["threshold_value"] = 50.0
        rule["evaluation_logic"]["threshold_range_high"] = 30.0  # low > high invalid
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("threshold_value < threshold_range_high" in err for err in errors)

        rule2 = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule2["evaluation_logic"]["interval_endpoints"] = "INVALID_ENDPOINT"
        valid2, errors2 = validate_rule_schema(rule2)
        assert valid2 is False
        assert any("interval_endpoints" in err for err in errors2)

    def test_prohibit_safe_to_proceed_claims(self):
        """Authored advisory text must never claim 'safe to proceed'."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["clinical_advisory"]["authored_advisory_text"] = "eGFR is acceptable; safe to proceed with administration."
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("safe to proceed" in err for err in errors)

    def test_prohibit_broad_assay_brand_immunity_assumption(self):
        """Assay requirements must reject broad brand immunity assumptions."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_INT_BIOTIN_IMMUNOASSAY_V2"])
        rule["laboratory_criteria"]["assay_platform_requirement"]["allow_brand_immunity_assumption"] = True
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("allow_brand_immunity_assumption MUST be false" in err for err in errors)

    def test_failed_retrieval_cannot_produce_verified_quotation_status(self):
        """REGRESSION: Failed retrieval cannot produce VERIFIED quotation status."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        assert rule["evidence_references"][0]["retrieval_status"] == "RETRIEVAL_FAILED"
        # Attempting to declare EXACT_MATCH on an unretrieved document must fail structural validation
        rule["evidence_references"][0]["quote_match_outcome"] = "EXACT_MATCH"
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("Failed retrieval cannot produce VERIFIED quotation status" in err for err in errors)

    def test_retrieval_failure_reason_remains_unknown(self):
        """REGRESSION: Retrieval failure reason must remain UNKNOWN unless evidenced."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        rule["evidence_references"][0]["retrieval_failure_reason"] = "agency_restructuring_speculation"
        valid, errors = validate_rule_schema(rule)
        assert valid is False
        assert any("Retrieval failure cause remains UNKNOWN unless evidenced" in err for err in errors)


# =============================================================================
# 2. Governance and Release Eligibility Tests
# =============================================================================

class TestGovernanceAndReleaseEligibility:
    """Ensures drafts, research candidates, and unverified citations are blocked from release."""

    def test_all_authoritative_drafts_fail_release_eligibility(self):
        """All 6 authoritative candidate rules must FAIL release eligibility."""
        for rule_id, rule in AUTHORITATIVE_CURRENT_SPECIFICATION.items():
            eligible, reasons = validate_release_eligibility(rule)
            assert eligible is False, f"Rule {rule_id} should NOT be eligible for release"
            assert len(reasons) > 0

    def test_superseded_records_cannot_be_selected_for_release(self):
        """REGRESSION: Superseded records cannot be selected for release."""
        for rule_id, rule in SUPERSEDED_SPECIFICATION.items():
            eligible, reasons = validate_release_eligibility(rule)
            assert eligible is False, f"Superseded rule {rule_id} must be ineligible"
            assert any("Rule is SUPERSEDED and cannot be selected for release" in r for r in reasons)

    def test_unverified_or_mismatched_document_identity_blocks_release(self):
        """REGRESSION: Unverified or mismatched document identity blocks release."""
        # K121674 mammography mismatch
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_INT_ASCORBIC_ACID_GLUCOSE_V2"]
        eligible, reasons = validate_release_eligibility(rule)
        assert eligible is False
        assert any("retrieval_status is 'SOURCE_MISMATCH'" in r for r in reasons)
        assert any("unverified or mismatched quotation blocks release" in r for r in reasons)

        # Coumadin quote mismatch (paraphrase)
        rule2 = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V2"]
        eligible2, reasons2 = validate_release_eligibility(rule2)
        assert eligible2 is False
        assert any("unverified or mismatched quotation blocks release" in r for r in reasons2)

    def test_draft_review_status_blocks_release(self):
        """Rules with review_status == 'DRAFT' cannot be released."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        eligible, reasons = validate_release_eligibility(rule)
        assert eligible is False
        assert any("review_status is 'DRAFT'" in r for r in reasons)

    def test_tier_2_research_candidates_blocked_from_release(self):
        """Tier 2 research candidates are structurally valid but blocked from release."""
        for r_id in [
            "MED_LAB_PD_PREDNISONE_GLUCOSE_V2",
            "MED_LAB_SAF_WARFARIN_HEMOGLOBIN_V2",
            "MED_LAB_SAF_SPIRONOLACTONE_POTASSIUM_V2",
        ]:
            rule = AUTHORITATIVE_CURRENT_SPECIFICATION[r_id]
            valid, errors = validate_rule_schema(rule)
            assert valid is True
            eligible, reasons = validate_release_eligibility(rule)
            assert eligible is False
            assert any("Rule tier is 'TIER_2_RESEARCH_CANDIDATE'" in r for r in reasons)

    def test_null_reviewer_permitted_in_draft_but_blocks_release(self):
        """Null reviewer fields are allowed in draft schema, but block release eligibility."""
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        assert rule["governance"]["clinical_reviewer_name"] is None
        valid, errors = validate_rule_schema(rule)
        assert valid is True

        eligible, reasons = validate_release_eligibility(rule)
        assert eligible is False
        assert any("clinical_reviewer_name is missing or null" in r for r in reasons)


# =============================================================================
# 3. Context Handling and Non-Executable Pipeline Isolation Tests
# =============================================================================

def create_synthetic_eligible_rule(category="ANALYTICAL_INTERFERENCE", rule_id="MED_LAB_INT_SYNTHETIC_TEST_V1") -> dict:
    """Creates a clearly synthetic, fully eligible test fixture strictly for scaffold testing."""
    return {
        "rule_id": rule_id,
        "rule_version": "1.0.0",
        "tier": "TIER_1_EXECUTABLE",
        "category": category,
        "governance": {
            "review_status": "APPROVED",
            "clinical_reviewer_name": "Synthetic Reviewer, MD",
            "clinical_reviewer_credential": "BOARD_CERTIFIED_PATHOLOGY",
            "review_date": "2026-10-16",
            "release_approved": True,
            "approval_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "governance_notes": "Synthetic eligible rule fixture strictly for context scaffold tests.",
        },
        "medication_criteria": {
            "generic_name": "synthetic_drug",
            "rxnorm_cui": "999999",
            "who_atc_code": "V99XX99",
            "mapping_status": "CURATED_EXACT",
            "allowed_routes": ["ORAL"],
            "allowed_dosage_forms": ["TABLET"],
            "treatment_state": "ANY",
        },
        "laboratory_criteria": {
            "analyte_key": "SYNTHETIC_ANALYTE",
            "canonical_display_name": "Synthetic Analyte",
            "loinc_code": "99999-9",
            "loinc_mapping_status": "CURATED_EXACT",
            "fasting_context": "UNKNOWN",
            "required_canonical_unit": "mg/dL",
            "allowed_unit_aliases": ["mg/dL", "mg/dl"],
            "convertible_units": [],
            "specimen_type": "SERUM",
            "assay_platform_requirement": {
                "architecture": "SANDWICH_IMMUNOMETRIC",
                "susceptible_technologies": ["ELECTROCHEMILUMINESCENCE"],
                "immune_technologies": [],
                "allow_brand_immunity_assumption": False,
            },
        },
        "evaluation_logic": {
            "direction": "MED_TO_LAB",
            "operator": "STATUS_MATCH",
            "target_lab_statuses": ["ABNORMAL_LOW"],
            "threshold_value": None,
            "threshold_range_high": None,
            "interval_endpoints": "NOT_APPLICABLE",
            "timing_window_days": None,
        },
        "evidence_references": [
            {
                "source_name": "Synthetic Clinical Guideline",
                "evidence_entry_type": "CURATED_SOURCE_RECORD",
                "event_description": "Synthetic verified evidence record",
                "exact_product_name": "Synthetic Drug 10mg",
                "active_ingredient": "synthetic_drug",
                "actual_document_title": "Synthetic Prescribing Information",
                "document_id": "SYN-NDA-000000",
                "section": "Section 5.1",
                "page_or_section": "Section 5.1",
                "publication_or_revision_date": "2026-01",
                "label_currency_status": "CURRENT_OFFICIAL_LABEL",
                "current_official_label_status": "CURRENT_OFFICIAL_LABEL",
                "currency_notes": "Synthetic official label.",
                "source_url": "https://example.com/synthetic/label.pdf",
                "retrieval_status": "RETRIEVED",
                "retrieval_date": "2026-10-16",
                "document_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "verbatim_passage": "Synthetic passage confirming qualitative interaction.",
                "quote_match_outcome": "EXACT_MATCH",
                "quote_match_method": "CASE_INSENSITIVE_NORMALIZED_EXACT_SUBSTRING_MATCH",
                "quotation_verification_notes": "Synthetic verified quote.",
                "supported_claim": "Synthetic qualitative claim.",
                "clinical_applicability_assessment": "Synthetic applicability assessment.",
                "source_text_verification_status": "VERIFIED",
                "clinical_applicability_review_status": "APPROVED",
                "reuse_review_status": "APPROVED",
                "license_type": "OPEN_ACCESS_TEST",
                "release_approval_status": True,
            }
        ],
        "clinical_advisory": {
            "clinical_importance": "ANALYTICAL_INTERPRETATION",
            "action_category": "INTERFERENCE_CAUTION",
            "summary_title": "Synthetic Advisory Title",
            "authored_advisory_text": "Synthetic authored advisory text for testing.",
            "prohibited_actions": ["AUTONOMOUS_DOSE_CHANGE"],
        },
        "context_outcomes": {
            "on_missing_unit": "REJECT_WITH_METROLOGICAL_ERROR",
            "on_incompatible_unit": "REJECT_WITH_METROLOGICAL_ERROR",
            "on_missing_value": "REJECT_WITH_INSUFFICIENT_DATA",
            "on_unknown_assay": "INDETERMINATE_ASSAY_CONTEXT",
            "on_unknown_treatment_state": "REMAIN_UNKNOWN_REQUIRE_REVIEW",
        },
    }


class TestContextHandlingAndPipelineIsolation:
    """Validates behavior when observed context is incomplete and ensures production isolation."""

    def test_non_executable_guard_rejects_unreleased_rules(self):
        """Evaluating an unreleased draft rule returns RULE_NOT_RELEASED_INELIGIBLE."""
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"]
        out = evaluate_observed_context(rule, {"history_available": True})
        assert out["advisory_status"] == "RULE_NOT_RELEASED_INELIGIBLE"
        assert out["evaluated"] is False
        assert out["applicability_confidence"] == "NONE"

    def test_missing_history_remains_unknown_not_initiation(self):
        """Missing patient history must produce UNKNOWN treatment state, never INITIATION."""
        mock_rule = create_synthetic_eligible_rule(category="CLINICAL_SAFETY_MONITORING", rule_id="MED_LAB_SAF_SYN_V1")
        mock_rule["laboratory_criteria"]["assay_platform_requirement"]["architecture"] = "NOT_APPLICABLE"

        patient_ctx = {"history_available": False}
        out = evaluate_observed_context(mock_rule, patient_ctx)
        assert out["observed_treatment_state"] == "UNKNOWN"
        assert out["advisory_status"] == "REQUIRE_MANUAL_REVIEW_UNKNOWN_HISTORY"
        assert out["applicability_confidence"] == "LOW_INCOMPLETE_CONTEXT"
        assert "treatment state remains UNKNOWN" in out["notes"][0]

    def test_unknown_assay_context_remains_indeterminate(self):
        """Unknown assay architecture for analytical interference produces INDETERMINATE_ASSAY_CONTEXT."""
        mock_rule = create_synthetic_eligible_rule(category="ANALYTICAL_INTERFERENCE", rule_id="MED_LAB_INT_SYN_V1")

        patient_ctx = {
            "history_available": True,
            "assay_architecture": "UNKNOWN"
        }
        out = evaluate_observed_context(mock_rule, patient_ctx)
        assert out["advisory_status"] == "INDETERMINATE_ASSAY_CONTEXT"
        assert out["applicability_confidence"] == "INDETERMINATE"

    def test_generic_abnormal_rejected_for_direction_specific_requirement(self):
        """Generic ABNORMAL lab status cannot satisfy directional requirement."""
        mock_rule = create_synthetic_eligible_rule(category="ANALYTICAL_INTERFERENCE", rule_id="MED_LAB_INT_SYN_V1")
        mock_rule["evaluation_logic"]["target_lab_statuses"] = ["ABNORMAL_LOW"]

        patient_ctx = {
            "history_available": True,
            "assay_architecture": "SANDWICH_IMMUNOMETRIC",
            "lab_status": "ABNORMAL"
        }
        out = evaluate_observed_context(mock_rule, patient_ctx)
        assert out["advisory_status"] == "AMBIGUOUS_DIRECTION_UNRESOLVED"
        assert out["applicability_confidence"] == "NONE"

    def test_runtime_evaluation_not_called_by_production_pipelines(self):
        """
        REGRESSION: Runtime evaluation is not called by production prescription/report
        pipelines while this feature remains inactive.
        """
        import prescription_verification_agent as pva
        import prescription_reasoning_agent as pra
        import report_verification_agent as rva
        import report_reasoning_agent as rra

        for mod in (pva, pra, rva, rra):
            src = inspect.getsource(mod)
            assert "medication_lab_schema" not in src, f"{mod.__name__} must not import medication_lab_schema"
            assert "evaluate_observed_context" not in src, f"{mod.__name__} must not call evaluate_observed_context"


# =============================================================================
# 4. Milestone Governance & Single Candidate Evidence Curation Tests
# =============================================================================

class TestPrednisoneRayosEvidenceCurationAndMilestone:
    """
    Validates the governance milestone closure and evidence curation for ONE candidate only:
    prednisone/RAYOS + elevated blood glucose.
    """

    def test_milestone_wording_verbatim(self):
        """Milestone wording must match exact requirement."""
        expected = (
            "Governance/schema implementation complete.\n"
            "Clinical evidence curation and reviewer approval pending.\n"
            "Medication–lab evaluation inactive."
        )
        assert MILESTONE_STATUS == expected

    def test_prednisone_candidate_separates_failed_request_and_replacement_events(self):
        """
        Original failed request and successful replacement retrieval must be distinct events.
        Cryptographic hash and quote-match results must be linked to the successful event.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        refs = rule["evidence_references"]
        assert len(refs) == 3, "Must contain exactly three evidence reference entries (failed event, historical mismatch, curated record)"

        # Event 1: Original Failed Request Event
        failed_event = refs[0]
        assert failed_event["evidence_entry_type"] == "FAILED_REQUEST_EVENT"
        assert failed_event["requested_url"] == "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/009218s112lbl.pdf"
        assert failed_event["actual_http_final_url"] == "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/009218s112lbl.pdf"
        assert failed_event["replacement_source_url"] == "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf"
        assert failed_event["retrieval_status"] == "RETRIEVAL_FAILED"
        assert failed_event["retrieval_failure_reason"] == "HTTP_404_NOT_FOUND"
        assert failed_event["document_sha256"] is None, "Failed request event must not have a document hash"
        assert failed_event["quote_match_outcome"] == "UNVERIFIED_RETRIEVAL_FAILED"

        # Event 2: Historical Audit Record (Quote Mismatch on Retrieved RAYOS Document)
        mismatch_event = refs[1]
        assert mismatch_event["evidence_entry_type"] == "HISTORICAL_AUDIT_RECORD"
        assert mismatch_event["document_id"] == "NDA 202020"
        assert mismatch_event["source_url"] == "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf"
        assert mismatch_event["retrieval_status"] == "RETRIEVED"
        assert mismatch_event["document_sha256"] == "4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427"
        assert mismatch_event["quote_match_outcome"] == "QUOTE_MISMATCH"
        assert mismatch_event["quote_match_method"] == "CASE_INSENSITIVE_NORMALIZED_EXACT_SUBSTRING_MATCH"
        assert "Deltasone" in mismatch_event["quotation_verification_notes"]

        # Event 3: Curated Source Record (Exact Match on Retrieved RAYOS Document)
        curated_event = refs[2]
        assert curated_event["evidence_entry_type"] == "CURATED_SOURCE_RECORD"
        assert curated_event["document_id"] == "NDA 202020"
        assert curated_event["source_url"] == "https://www.accessdata.fda.gov/drugsatfda_docs/label/2012/202020s000lbl.pdf"
        assert curated_event["retrieval_status"] == "RETRIEVED"
        assert curated_event["document_sha256"] == "4ffe701c3ba0321092c49aebf59e61648afe419420a15ef15276d3fb306fc427"
        assert curated_event["quote_match_outcome"] == "EXACT_MATCH"
        assert curated_event["quote_match_method"] == "CASE_INSENSITIVE_NORMALIZED_EXACT_SUBSTRING_MATCH"
        expected_quote = (
            "Hypothalamic-pituitary-adrenal (HPA) axis suppression, Cushing’s syndrome, "
            "and hyperglycemia. Monitor patients for these conditions with chronic use."
        )
        assert curated_event["verbatim_passage"] == expected_quote

    def test_prednisone_currency_metadata(self):
        """
        Record source label revision as 2012-07 (no unevidenced day).
        Mark as HISTORICAL_LABEL.
        Record CURRENT_LABEL_NOT_VERIFIED without guessing URLs.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        for ref in rule["evidence_references"][1:]:
            assert ref["publication_or_revision_date"] == "2012-07"
            assert ref["label_currency_status"] == "HISTORICAL_LABEL"
            assert ref["current_official_label_status"] == "CURRENT_LABEL_NOT_VERIFIED"
            assert "CURRENT_LABEL_NOT_VERIFIED" in ref["currency_notes"]

    def test_prednisone_reuse_metadata_pending_not_federal_authorship(self):
        """
        FDA hosting/approval does NOT establish federal government authorship under 17 U.S.C. 105.
        Reuse review must be PENDING.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        for ref in rule["evidence_references"][1:]:
            assert ref["reuse_review_status"] == "PENDING"
            assert ref["license_type"] == "PENDING_REVIEW"
            assert "PUBLIC_DOMAIN_US_FEDERAL_GOVERNMENT_WORK" not in ref["reuse_review_status"]
            assert "17 U.S.C. 105" in ref["reuse_notes"]

    def test_prednisone_separate_statuses_and_draft_eligibility(self):
        """
        Source-text verification, clinical applicability review, reuse review,
        and release approval must be separate statuses.
        All rules remain DRAFT and release_approved=False.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        curated = rule["evidence_references"][2]

        assert curated["source_text_verification_status"] == "VERIFIED"
        assert curated["clinical_applicability_review_status"] == "PENDING"
        assert curated["reuse_review_status"] == "PENDING"
        assert curated["release_approval_status"] is False

        assert rule["governance"]["review_status"] == "DRAFT"
        assert rule["governance"]["release_approved"] is False

        eligible, reasons = validate_release_eligibility(rule)
        assert eligible is False
        assert any("release_approved is False" in r for r in reasons)
        assert any("reuse_review_status is 'PENDING'" in r for r in reasons)

    def test_prednisone_source_validity_separated_from_claim_validity(self):
        """Exact quotation matching alone does NOT establish clinical applicability."""
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        curated = rule["evidence_references"][2]
        notes = curated["clinical_applicability_assessment"]

        assert "exact quotation matching establishes source text validity only" in notes.lower()
        assert "clinical applicability to automated decision-support is pending" in notes.lower()

    def test_prednisone_no_numeric_cutoff_or_treatment_instructions(self):
        """
        Must not add a glucose cutoff (>125 mg/dL), monitoring interval, causal diagnosis,
        dose recommendation, or treatment instruction.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        logic = rule["evaluation_logic"]

        assert logic["operator"] == "STATUS_MATCH"
        assert logic["threshold_value"] is None, "Numeric cutoff must NOT be added"
        assert logic["threshold_range_high"] is None
        assert logic["timing_window_days"] is None, "Monitoring interval must NOT be added"

        # Prohibited actions include autonomous treatment/diagnosis
        prohibited = rule["clinical_advisory"]["prohibited_actions"]
        assert "AUTONOMOUS_INSULIN_INITIATION" in prohibited
        assert "AUTONOMOUS_DOSE_CHANGE" in prohibited
        assert "AUTONOMOUS_CAUSAL_DIAGNOSIS" in prohibited
        assert "UNSUPPORTED_NUMERIC_CUTOFF" in prohibited

        # Exact scope statement must be present without claiming the source label lacks guidance
        scope_statement = "The candidate adds no numeric glucose cutoff, fixed monitoring interval, causal diagnosis, or autonomous treatment instruction."
        assert scope_statement in rule["clinical_advisory"]["authored_advisory_text"]
        assert scope_statement in rule["evidence_references"][2]["clinical_applicability_assessment"]

    def test_prednisone_glucose_unit_metadata_and_convertible_separation(self):
        """
        Remove mmol/L from spelling aliases of mg/dL.
        Keep spelling aliases separate from convertible units.
        Do not introduce numeric conversion logic.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        lab = rule["laboratory_criteria"]

        assert lab["required_canonical_unit"] == "mg/dL"
        assert "mmol/L" not in lab["allowed_unit_aliases"], "mmol/L is not a spelling alias of mg/dL"
        assert all(a.lower() == "mg/dl" for a in lab["allowed_unit_aliases"])
        assert "mmol/L" in lab["convertible_units"], "mmol/L must be recorded in separate convertible_units"

    def test_prednisone_glucose_laboratory_terminology(self):
        """
        Do not assign fasting-specific LOINC 1558-6 to generic glucose when fasting status is unknown.
        Preserve unknown fasting context and mark the mapping unverified.
        Do not invent a replacement code.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        lab = rule["laboratory_criteria"]

        assert lab["loinc_code"] == "UNKNOWN", "Fasting-specific LOINC 1558-6 must not be assigned"
        assert lab["loinc_mapping_status"] == "UNVERIFIED"
        assert lab["fasting_context"] == "UNKNOWN"
        assert "Fasting Status Unknown" in lab["canonical_display_name"]

    def test_prednisone_antidiabetic_guidance_section_7_5(self):
        """
        Antidiabetic-agent dose adjustment guidance reference is Section 7.5 (not 7.1).
        Preserve verified Section 5.1 hyperglycemia quotation.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        curated = rule["evidence_references"][2]

        assert curated["section"] == "Section 5.1 Alterations in Endocrine Function"
        assert "Section 7.5" in curated["clinical_applicability_assessment"]
        assert "Section 7.5" in rule["clinical_advisory"]["authored_advisory_text"]
        assert "Section 7.1" not in curated["clinical_applicability_assessment"]
        assert "Section 7.1" not in rule["clinical_advisory"]["authored_advisory_text"]

    def test_prednisone_applicability_boundary_unapproved_extensions(self):
        """
        Curated source concerns RAYOS delayed-release tablets during chronic use.
        Other formulations and unspecified durations remain proposed, unapproved extensions.
        """
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        curated = rule["evidence_references"][2]
        assessment = curated["clinical_applicability_assessment"]

        assert "RAYOS delayed-release tablets" in assessment
        assert "chronic use" in assessment
        assert "unapproved extensions" in assessment

    def test_prednisone_normalized_retrieval_status_spelling(self):
        """Use canonical RETRIEVAL_FAILED consistently; no RETRIEVED_FAILED."""
        rule = AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_PD_PREDNISONE_GLUCOSE_V2"]
        failed_event = rule["evidence_references"][0]
        assert failed_event["retrieval_status"] == "RETRIEVAL_FAILED"


# =============================================================================
# 5. Governance Remediation Defect Tests
# =============================================================================

class TestMedicationLabGovernanceRemediationPass:
    """
    Focused tests reproducing governance defects:
    1. Two editable fields cannot bypass complete release-eligibility gate.
    2. Active supporting evidence required; historical audit events alone cannot release claim.
    3. Documentation explicitly states inactive context-validation scaffold.
    4. Real candidates strictly preserved as DRAFT and release_approved=False.
    """

    def test_defect_two_editable_fields_cannot_bypass_complete_release_gate(self):
        """
        DEFECT: evaluate_observed_context previously checked only tier and release_approved,
        allowing rules with unverified reviewer, missing hash, or unapproved reuse to evaluate.
        """
        rule = copy.deepcopy(AUTHORITATIVE_CURRENT_SPECIFICATION["MED_LAB_SAF_METFORMIN_EGFR_V2"])
        # Attempt to bypass by setting the two editable fields
        rule["tier"] = "TIER_1_EXECUTABLE"
        rule["governance"]["release_approved"] = True
        rule["governance"]["review_status"] = "APPROVED"
        # Clinical reviewer name, hash, and reuse remain null/unapproved
        out = evaluate_observed_context(rule, {"history_available": True})
        assert out["advisory_status"] == "RULE_NOT_RELEASED_INELIGIBLE"
        assert out["evaluated"] is False
        assert len(out.get("eligibility_reasons", [])) > 0
        assert any("clinical_reviewer_name" in r for r in out["eligibility_reasons"])

    def test_defect_historical_audit_records_alone_cannot_release_active_claim(self):
        """
        DEFECT: An unsupported claim must not be released merely by relabeling its
        evidence as historical. Every active claim must have active verified supporting evidence.
        """
        rule = create_synthetic_eligible_rule()
        # Change all evidence references to historical audit records
        for ref in rule["evidence_references"]:
            ref["evidence_entry_type"] = "HISTORICAL_AUDIT_RECORD"
        eligible, reasons = validate_release_eligibility(rule)
        assert eligible is False
        assert any("no active verified supporting evidence" in r for r in reasons)

    def test_scaffold_explicitly_documented_as_inactive(self):
        """
        DEFECT: evaluate_observed_context must be explicitly documented as an inactive
        context-validation scaffold, not an implemented clinical trigger engine.
        """
        doc_norm = " ".join((evaluate_observed_context.__doc__ or "").lower().split())
        assert "inactive context-validation scaffold" in doc_norm
        assert "not an implemented clinical trigger engine" in doc_norm

    def test_all_real_candidates_remain_draft_and_unapproved(self):
        """
        All real medication-lab candidates in the specification must remain DRAFT
        and release_approved=False. Production isolation is strictly preserved.
        """
        for rule_id, rule in AUTHORITATIVE_CURRENT_SPECIFICATION.items():
            assert rule["governance"]["release_approved"] is False, f"{rule_id} must have release_approved=False"
            assert rule["governance"]["review_status"] == "DRAFT", f"{rule_id} must have review_status=DRAFT"
            eligible, reasons = validate_release_eligibility(rule)
            assert eligible is False, f"Real candidate {rule_id} must fail release eligibility"




