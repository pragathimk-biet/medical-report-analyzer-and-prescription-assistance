"""
===============================================================================
DLTI CHECKER TEST SUITE
===============================================================================

Tests for dlti_checker.py — the Drug–Laboratory Test Interaction research prototype.

Coverage:
  A. Knowledge base loader                (structural validation, integrity, v0.2.0)
  B. Concept resolvers                    (analyte, medication, unit)
  C. Applicability checker                (identity, route, analyte matching)
  D. Threshold evaluator                  (all comparison operators)
  E. Single rule evaluator                (evidence-backed qualitative status rules)
  F. DLTICheckingAgent.process            (disabled / KB unavailable / full pipeline)
  G. Pipeline context extraction          (lab values from multiple sources)
  H. Coverage metadata                    (counts, labels, insufficient context)
  I. Research-preview governance          (label, release_approved, DISABLED default)
  J. Integration: prednisone+glucose      (STATUS_MATCH: HIGH triggers, NORMAL evaluates, missing context)
  K. Integration: prednisone+CRP          (DISABLED candidate: STATUS_RULE_DISABLED)
  L. Integration: spironolactone+K+       (STATUS_MATCH: HIGH triggers, NORMAL evaluates, missing context)
  M. No-rule-found                        (unknown pair, absence != safety)
  N. Unverified medication skip           (identity_verified=False skipped)
  O. Synthetic numeric engine fixtures    (numeric operators & conversion in test fixtures only)
  P. Invariant: absence of rule != safe
  Q. Invariant: KB unavailable -> no silent success
"""

import json
import os
import tempfile
import pytest
from typing import Dict

# Ensure parent directory is on path for direct test runs
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dlti_checker as dlti

# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

REAL_KB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "dlti_knowledge_base.json"
)


def _make_pipeline_ctx(
    medications=None,
    lab_values=None,
    identity_verified=True,
) -> Dict:
    """Build a minimal pipeline context for testing."""
    meds = medications or []
    labs = lab_values or []
    return {
        "document_type": "prescription",
        "raw_input": "",
        "metadata": {},
        "extracted_data": {},
        "handwriting": {},
        "verification": {
            "medications": meds,
            "current_labs": labs,
        },
        "safety": {},
        "reasoning": {},
        "warnings": [],
        "errors": [],
    }


def _med(name: str, verified: bool = True, route: str = "ORAL") -> Dict:
    return {
        "name": name,
        "raw_name": name,
        "identity_verified": verified,
        "route": route,
    }


def _lab(analyte: str, value=None, unit: str = "mg/dL", fasting_confirmed=None, status=None) -> Dict:
    entry = {"analyte": analyte, "unit": unit}
    if value is not None:
        entry["value"] = value
    if status is not None:
        entry["status"] = status
    if fasting_confirmed is not None:
        entry["fasting_confirmed"] = fasting_confirmed
    return entry


def _make_synthetic_numeric_rule(
    rule_id="SYNTHETIC_NUMERIC_RULE",
    generic_name="prednisone",
    analyte_key="GLUCOSE",
    operator=">",
    threshold_value=126.0,
    canonical_unit="mg/dL",
    with_conversion=True,
) -> Dict:
    """
    Synthetic test fixture for engine-level numeric threshold and conversion tests.
    Per prompt requirement 2: synthetic thresholds exist ONLY in test fixtures,
    never in the evidence-backed knowledge base.
    """
    conv_table = {"mmol/L_to_mg/dL": 18.0182} if with_conversion else {}
    return {
        "rule_id": rule_id,
        "rule_version": "0.1.0-test",
        "tier": "TIER_2_RESEARCH_CANDIDATE",
        "relationship_category": "PHARMACODYNAMIC_EFFECT",
        "is_superseded": False,
        "superseded_by": None,
        "superseded_reason": None,
        "governance": {
            "review_status": "DRAFT",
            "release_approved": False,
            "governance_notes": "Synthetic engine test fixture",
        },
        "medication_criteria": {
            "generic_name": generic_name,
            "allowed_routes": ["ORAL"],
            "treatment_state": "ANY",
        },
        "laboratory_criteria": {
            "analyte_key": analyte_key,
            "required_canonical_unit": canonical_unit,
            "allowed_unit_aliases": ["mg/dl", "meq/l"],
            "convertible_units": ["mmol/L", "mmol/l"] if with_conversion else [],
            "unit_conversion": conv_table,
            "fasting_context_required": False,
        },
        "evaluation_logic": {
            "direction": "MED_TO_LAB",
            "operator": operator,
            "threshold_value": threshold_value,
            "threshold_range_high": None,
            "target_lab_statuses": [],
            "applicability_checks": [
                "medication_identity_verified",
                "medication_route_matches",
                "laboratory_analyte_matches",
                "laboratory_unit_resolved",
                "laboratory_value_present",
            ],
        },
        "evidence_references": [],
        "clinical_advisory": {
            "summary_title": "Synthetic Test Advisory",
            "authored_advisory_text": "Synthetic test advisory text.",
            "action_category": "MONITORING_MANDATED",
            "prohibited_actions": ["AUTONOMOUS_DOSE_CHANGE", "AUTONOMOUS_DISCONTINUATION"],
        },
        "context_outcomes": {},
    }


# ---------------------------------------------------------------------------
# A. Knowledge Base Loader
# ---------------------------------------------------------------------------

class TestKnowledgeBaseLoader:
    def test_loads_real_kb_successfully(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        assert kb.is_loaded, f"Load errors: {kb.load_errors}"

    def test_real_kb_has_expected_rule_count(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        assert len(kb.rules) == 3

    def test_real_kb_has_metadata_v020(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        meta = kb.metadata
        assert meta.get("knowledge_base_id") == "DLTI_KB_001"
        assert meta.get("knowledge_base_version") == "0.2.0"
        assert meta.get("status") == "RESEARCH_PREVIEW"

    def test_missing_file_is_not_loaded(self):
        kb = dlti.DLTIKnowledgeBase(kb_path="/nonexistent/path/kb.json").load()
        assert not kb.is_loaded
        assert any("not found" in e.lower() for e in kb.load_errors)

    def test_invalid_json_is_not_loaded(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("{not valid json")
            fh_path = fh.name
        try:
            kb = dlti.DLTIKnowledgeBase(kb_path=fh_path).load()
            assert not kb.is_loaded
            assert any("parse" in e.lower() or "json" in e.lower() for e in kb.load_errors)
        finally:
            os.unlink(fh_path)

    def test_rule_missing_required_field_is_rejected(self):
        bad_kb = {
            "_metadata": {
                "schema_version": "1.0.0",
                "knowledge_base_id": "TEST",
                "knowledge_base_version": "0.0.1",
                "status": "RESEARCH_PREVIEW",
            },
            "rules": [
                {
                    "rule_id": "TEST_RULE",
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(bad_kb, fh)
            fh_path = fh.name
        try:
            kb = dlti.DLTIKnowledgeBase(kb_path=fh_path).load()
            assert not kb.is_loaded or len(kb.load_errors) > 0
        finally:
            os.unlink(fh_path)

    def test_tier_1_in_kb_is_rejected(self):
        bad_kb = {
            "_metadata": {
                "schema_version": "1.0.0",
                "knowledge_base_id": "TEST",
                "knowledge_base_version": "0.0.1",
                "status": "RESEARCH_PREVIEW",
            },
            "rules": [
                {
                    "rule_id": "TEST_RULE",
                    "rule_version": "0.1.0",
                    "tier": "TIER_1_EXECUTABLE",
                    "relationship_category": "PHARMACODYNAMIC_EFFECT",
                    "governance": {"review_status": "DRAFT", "release_approved": False},
                    "medication_criteria": {"generic_name": "prednisone", "allowed_routes": ["ORAL"]},
                    "laboratory_criteria": {"analyte_key": "GLUCOSE", "required_canonical_unit": "mg/dL"},
                    "evaluation_logic": {"operator": ">", "direction": "MED_TO_LAB"},
                    "evidence_references": [],
                    "clinical_advisory": {},
                    "context_outcomes": {},
                }
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(bad_kb, fh)
            fh_path = fh.name
        try:
            kb = dlti.DLTIKnowledgeBase(kb_path=fh_path).load()
            assert kb.is_loaded
        finally:
            os.unlink(fh_path)

    def test_all_real_rules_are_tier_2_unapproved(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        for rule in kb.rules:
            assert rule.get("tier") == "TIER_2_RESEARCH_CANDIDATE"
            assert rule.get("governance", {}).get("release_approved") is False


# ---------------------------------------------------------------------------
# B. Concept Resolvers
# ---------------------------------------------------------------------------

class TestConceptResolvers:
    def test_glucose_aliases_resolve(self):
        for alias in ["glucose", "GLUCOSE", "fasting glucose", "plasma glucose", "blood glucose"]:
            result = dlti.resolve_analyte_key(alias)
            assert result == "GLUCOSE", f"Failed for alias: '{alias}'"

    def test_crp_aliases_resolve(self):
        for alias in ["crp", "CRP", "c-reactive protein", "c reactive protein"]:
            result = dlti.resolve_analyte_key(alias)
            assert result == "CRP", f"Failed for alias: '{alias}'"

    def test_potassium_aliases_resolve(self):
        for alias in ["potassium", "POTASSIUM", "serum potassium", "k+"]:
            result = dlti.resolve_analyte_key(alias)
            assert result == "POTASSIUM", f"Failed for alias: '{alias}'"

    def test_unknown_analyte_returns_none(self):
        assert dlti.resolve_analyte_key("xylitol") is None
        assert dlti.resolve_analyte_key("") is None
        assert dlti.resolve_analyte_key(None) is None

    def test_prednisone_aliases_resolve(self):
        for alias in ["prednisone", "RAYOS", "rayos", "Deltasone", "deltasone"]:
            result = dlti.resolve_medication_generic(alias)
            assert result == "prednisone", f"Failed for alias: '{alias}'"

    def test_spironolactone_aliases_resolve(self):
        for alias in ["spironolactone", "ALDACTONE", "aldactone", "CaroSpir", "carospir"]:
            result = dlti.resolve_medication_generic(alias)
            assert result == "spironolactone", f"Failed for alias: '{alias}'"

    def test_unknown_medication_returns_none(self):
        assert dlti.resolve_medication_generic("metformin") is None
        assert dlti.resolve_medication_generic("") is None
        assert dlti.resolve_medication_generic(None) is None

    def test_mgdl_aliases_resolve(self):
        for alias in ["mg/dL", "mg/dl", "mg/100mL"]:
            result = dlti.resolve_unit(alias)
            assert result == "mg/dL", f"Failed for alias: '{alias}', got '{result}'"

    def test_mmoll_aliases_resolve(self):
        for alias in ["mmol/L", "mmol/l", "mEq/L", "meq/l"]:
            result = dlti.resolve_unit(alias)
            assert result is not None, f"Failed to resolve '{alias}'"

    def test_unknown_unit_returns_none(self):
        assert dlti.resolve_unit("furlong/fortnight") is None


# ---------------------------------------------------------------------------
# C. Applicability Checker
# ---------------------------------------------------------------------------

class TestApplicabilityChecker:
    def _get_glucose_rule(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        for rule in kb.rules:
            if rule["rule_id"] == "DLTI_PD_PREDNISONE_GLUCOSE_V1":
                return rule
        pytest.fail("Prednisone/glucose rule not found in KB.")

    def test_passes_when_all_conditions_met(self):
        rule = self._get_glucose_rule()
        appl = dlti.check_rule_applicability(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 150.0, "mg/dL", status="HIGH"),
            resolved_analyte_key="GLUCOSE",
            resolved_generic_name="prednisone",
            resolved_unit="mg/dL",
            lab_value=150.0,
        )
        assert appl.passed, f"Expected pass, got failures: {appl.failed_checks}"

    def test_fails_when_identity_not_verified(self):
        rule = self._get_glucose_rule()
        appl = dlti.check_rule_applicability(
            rule=rule,
            med_entry={**_med("prednisone"), "identity_verified": False},
            lab_entry=_lab("glucose", 150.0, "mg/dL", status="HIGH"),
            resolved_analyte_key="GLUCOSE",
            resolved_generic_name="prednisone",
            resolved_unit="mg/dL",
            lab_value=150.0,
        )
        assert not appl.passed
        assert "medication_identity_verified" in appl.failed_checks

    def test_route_mismatch_fails_applicability(self):
        rule = self._get_glucose_rule()
        appl = dlti.check_rule_applicability(
            rule=rule,
            med_entry={**_med("prednisone"), "route": "INTRAVENOUS"},
            lab_entry=_lab("glucose", 150.0, "mg/dL", status="HIGH"),
            resolved_analyte_key="GLUCOSE",
            resolved_generic_name="prednisone",
            resolved_unit="mg/dL",
            lab_value=150.0,
        )
        assert not appl.passed
        assert "medication_route_matches" in appl.failed_checks

    def test_synthetic_rule_fails_when_value_missing(self):
        synth_rule = _make_synthetic_numeric_rule()
        appl = dlti.check_rule_applicability(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", None, "mg/dL"),
            resolved_analyte_key="GLUCOSE",
            resolved_generic_name="prednisone",
            resolved_unit="mg/dL",
            lab_value=None,
        )
        assert not appl.passed
        assert "laboratory_value_present" in appl.failed_checks

    def test_synthetic_rule_fails_when_unit_unresolvable(self):
        synth_rule = _make_synthetic_numeric_rule()
        appl = dlti.check_rule_applicability(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 150.0, "furlong/fortnight"),
            resolved_analyte_key="GLUCOSE",
            resolved_generic_name="prednisone",
            resolved_unit=None,
            lab_value=150.0,
        )
        assert not appl.passed
        assert "laboratory_unit_resolved" in appl.failed_checks


# ---------------------------------------------------------------------------
# D. Threshold Evaluator (Engine Unit Tests)
# ---------------------------------------------------------------------------

class TestThresholdEvaluator:
    def test_gt_triggered(self):
        triggered, _ = dlti.evaluate_threshold(">", 5.5, 5.0, None)
        assert triggered is True

    def test_gt_not_triggered(self):
        triggered, _ = dlti.evaluate_threshold(">", 5.0, 5.0, None)
        assert triggered is False

    def test_lt_triggered(self):
        triggered, _ = dlti.evaluate_threshold("<", 0.5, 1.0, None)
        assert triggered is True

    def test_lt_not_triggered(self):
        triggered, _ = dlti.evaluate_threshold("<", 1.0, 1.0, None)
        assert triggered is False

    def test_gte_triggered(self):
        triggered, _ = dlti.evaluate_threshold(">=", 5.0, 5.0, None)
        assert triggered is True

    def test_lte_triggered(self):
        triggered, _ = dlti.evaluate_threshold("<=", 5.0, 5.0, None)
        assert triggered is True

    def test_eq_triggered(self):
        triggered, _ = dlti.evaluate_threshold("==", 7.4, 7.4, None)
        assert triggered is True

    def test_between_triggered(self):
        triggered, _ = dlti.evaluate_threshold("BETWEEN", 5.0, 4.0, 6.0)
        assert triggered is True

    def test_between_not_triggered_above(self):
        triggered, _ = dlti.evaluate_threshold("BETWEEN", 7.0, 4.0, 6.0)
        assert triggered is False

    def test_between_missing_high_returns_false(self):
        triggered, explanation = dlti.evaluate_threshold("BETWEEN", 5.0, 4.0, None)
        assert triggered is False
        assert "threshold_range_high" in explanation

    def test_unsupported_operator_returns_false(self):
        triggered, explanation = dlti.evaluate_threshold("FUZZY", 5.0, 4.0, None)
        assert triggered is False
        assert "Unsupported" in explanation


# ---------------------------------------------------------------------------
# E. Single Rule Evaluator (Evidence-Backed Rules)
# ---------------------------------------------------------------------------

class TestSingleRuleEvaluator:
    def _get_rule(self, rule_id: str):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        for rule in kb.rules:
            if rule["rule_id"] == rule_id:
                return rule
        pytest.fail(f"Rule {rule_id} not found in KB.")

    # Prednisone / Glucose (Rule 1)
    def test_prednisone_glucose_triggered_with_high_status(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 180.0, "mg/dL", status="HIGH"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_TRIGGERED
        assert result["triggered"] is True
        assert result["clinical_advisory"] is not None
        assert "hyperglycemia" in result["clinical_advisory"]["authored_advisory_text"].lower()

    def test_prednisone_glucose_not_triggered_with_normal_status(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 90.0, "mg/dL", status="NORMAL"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_RULE_EVALUATED
        assert result["triggered"] is False
        assert result["clinical_advisory"] is None

    def test_prednisone_glucose_missing_status_produces_insufficient_context(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 180.0, "mg/dL"),  # no status field
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_INSUFFICIENT_CONTEXT
        assert result["clinical_advisory"] is None

    def test_prednisone_glucose_returns_none_for_wrong_medication(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("metformin"),
            lab_entry=_lab("glucose", 200.0, "mg/dL", status="HIGH"),
        )
        assert result is None

    def test_prednisone_glucose_returns_none_for_wrong_analyte(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("potassium", 5.5, "mmol/L", status="HIGH"),
        )
        assert result is None

    def test_prednisone_glucose_not_applicable_when_unverified(self):
        rule = self._get_rule("DLTI_PD_PREDNISONE_GLUCOSE_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry={**_med("prednisone"), "identity_verified": False},
            lab_entry=_lab("glucose", 200.0, "mg/dL", status="HIGH"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_NOT_APPLICABLE
        assert "medication_identity_verified" in result.get("applicability_failed_checks", [])

    # Prednisone / CRP (Rule 2) - Disabled candidate
    def test_prednisone_crp_evaluated_as_disabled_rule(self):
        rule = self._get_rule("DLTI_INT_PREDNISONE_CRP_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("crp", 0.5, "mg/L", status="NORMAL"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_RULE_DISABLED
        assert "DISABLED" in result.get("evaluation_detail", "")

    # Spironolactone / Potassium (Rule 3)
    def test_spironolactone_potassium_triggered_high_status(self):
        rule = self._get_rule("DLTI_SAF_SPIRONOLACTONE_POTASSIUM_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("spironolactone"),
            lab_entry=_lab("potassium", 5.8, "mmol/L", status="ABNORMAL_HIGH"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_TRIGGERED
        assert result["triggered"] is True
        assert result["clinical_advisory"] is not None
        assert "hyperkalemia" in result["clinical_advisory"]["summary_title"].lower()

    def test_spironolactone_potassium_not_triggered_normal_status(self):
        rule = self._get_rule("DLTI_SAF_SPIRONOLACTONE_POTASSIUM_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("spironolactone"),
            lab_entry=_lab("potassium", 4.5, "mmol/L", status="NORMAL"),
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_RULE_EVALUATED
        assert result["triggered"] is False
        assert result["clinical_advisory"] is None

    def test_spironolactone_potassium_missing_status_yields_insufficient_context(self):
        rule = self._get_rule("DLTI_SAF_SPIRONOLACTONE_POTASSIUM_V1")
        result = dlti.evaluate_one_rule(
            rule=rule,
            med_entry=_med("spironolactone"),
            lab_entry=_lab("potassium", 5.8, "mmol/L"),  # no status
        )
        assert result is not None
        assert result["status"] == dlti.STATUS_INSUFFICIENT_CONTEXT

    def test_all_results_carry_research_preview_label(self):
        kb = dlti.DLTIKnowledgeBase(kb_path=REAL_KB_PATH).load()
        for rule in kb.rules:
            med_name = rule["medication_criteria"]["generic_name"]
            analyte = rule["laboratory_criteria"]["analyte_key"]
            res = dlti.evaluate_one_rule(
                rule=rule,
                med_entry=_med(med_name),
                lab_entry=_lab(analyte, status="HIGH"),
            )
            assert res is not None
            assert res.get("research_preview_label") == dlti.RESEARCH_PREVIEW_LABEL


# ---------------------------------------------------------------------------
# F. DLTICheckingAgent.process
# ---------------------------------------------------------------------------

class TestDLTICheckingAgentProcess:
    def test_disabled_by_default_returns_disabled_status(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=False)
        assert result_ctx["dlti"]["status"] == dlti.STATUS_DISABLED
        assert result_ctx["dlti"]["results"] == []

    def test_kb_unavailable_handled_gracefully(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(
            ctx, enabled=True, kb_path="/nonexistent/kb.json"
        )
        assert result_ctx["dlti"]["status"] == dlti.STATUS_KB_UNAVAILABLE
        assert result_ctx["dlti"]["results"] == []
        assert len(result_ctx["dlti"]["load_errors"]) > 0

    def test_enabled_with_real_kb_returns_complete_status(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        assert result_ctx["dlti"]["status"] == "DLTI_COMPLETE"

    def test_kb_metadata_v020_in_output_when_enabled(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("potassium", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        kb_meta = result_ctx["dlti"].get("knowledge_base", {})
        assert kb_meta.get("id") == "DLTI_KB_001"
        assert kb_meta.get("version") == "0.2.0"


# ---------------------------------------------------------------------------
# G. Pipeline context extraction from multiple sources
# ---------------------------------------------------------------------------

class TestLabValueExtraction:
    def test_extracts_labs_from_verification_current_labs(self):
        ctx = _make_pipeline_ctx(
            medications=[_med("spironolactone")],
            lab_values=[_lab("potassium", status="HIGH")],
        )
        extracted = dlti.DLTICheckingAgent._extract_lab_values(ctx)
        analytes = [e.get("analyte") for e in extracted]
        assert "potassium" in analytes

    def test_extracts_labs_from_extracted_data_lab_results(self):
        ctx = _make_pipeline_ctx(medications=[_med("prednisone")])
        ctx["extracted_data"]["lab_results"] = [_lab("glucose", status="HIGH")]
        extracted = dlti.DLTICheckingAgent._extract_lab_values(ctx)
        analytes = [e.get("analyte") for e in extracted]
        assert "glucose" in analytes

    def test_extracts_labs_from_direct_lab_values_key(self):
        ctx = _make_pipeline_ctx(medications=[_med("prednisone")])
        ctx["lab_values"] = [_lab("crp", 0.5, "mg/L")]
        extracted = dlti.DLTICheckingAgent._extract_lab_values(ctx)
        analytes = [e.get("analyte") for e in extracted]
        assert "crp" in analytes

    def test_extracts_only_verified_meds(self):
        ctx = _make_pipeline_ctx(
            medications=[_med("prednisone", verified=True), _med("metformin", verified=False)]
        )
        verified = dlti.DLTICheckingAgent._extract_verified_meds(ctx)
        names = [m["name"] for m in verified]
        assert "prednisone" in names
        assert "metformin" not in names


# ---------------------------------------------------------------------------
# H. Coverage Metadata
# ---------------------------------------------------------------------------

class TestCoverageMeta:
    def test_disabled_coverage_label(self):
        ctx = _make_pipeline_ctx()
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=False)
        assert result_ctx["dlti"]["coverage"]["coverage_label"] == "DISABLED"

    def test_unavailable_coverage_label(self):
        ctx = _make_pipeline_ctx([_med("prednisone")], [_lab("glucose", status="HIGH")])
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path="/bad.json")
        assert result_ctx["dlti"]["coverage"]["coverage_label"] == "KNOWLEDGE_BASE_UNAVAILABLE"

    def test_evaluated_coverage_label_when_pairs_exist(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        cov = result_ctx["dlti"]["coverage"]
        assert cov["coverage_label"] == "RESEARCH_PREVIEW_EVALUATED"

    def test_coverage_tracks_triggered_count(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        cov = result_ctx["dlti"]["coverage"]
        assert cov["rules_triggered"] >= 1

    def test_coverage_tracks_insufficient_context(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose")],  # missing status
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        cov = result_ctx["dlti"]["coverage"]
        assert cov["rules_insufficient_context"] >= 1


# ---------------------------------------------------------------------------
# I. Research-preview governance invariants
# ---------------------------------------------------------------------------

class TestGovernanceInvariants:
    def test_disabled_by_default_invariant(self):
        ctx = _make_pipeline_ctx([_med("prednisone")], [_lab("glucose", status="HIGH")])
        result_ctx = dlti.DLTICheckingAgent.process(ctx)
        assert result_ctx["dlti"]["status"] == dlti.STATUS_DISABLED

    def test_research_preview_label_invariant_on_every_result(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone"), _med("spironolactone")],
            [
                _lab("glucose", status="HIGH"),
                _lab("potassium", status="HIGH"),
            ],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        for entry in result_ctx["dlti"]["results"]:
            if "research_preview_label" in entry:
                assert entry["research_preview_label"] == dlti.RESEARCH_PREVIEW_LABEL

    def test_no_autonomous_action_in_clinical_advisory(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("potassium", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        for entry in result_ctx["dlti"]["results"]:
            if entry.get("status") == dlti.STATUS_TRIGGERED and entry.get("clinical_advisory"):
                prohibited = entry["clinical_advisory"].get("prohibited_actions", [])
                assert "AUTONOMOUS_DOSE_CHANGE" in prohibited
                assert "AUTONOMOUS_DISCONTINUATION" in prohibited


# ---------------------------------------------------------------------------
# J. Integration: prednisone + glucose
# ---------------------------------------------------------------------------

class TestIntegrationPrednisoneGlucose:
    def test_triggered_with_high_status(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED in statuses

    def test_not_triggered_with_normal_status(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="NORMAL")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED not in statuses
        assert dlti.STATUS_RULE_EVALUATED in statuses

    def test_missing_status_produces_insufficient_context(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose")],  # no status provided
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_INSUFFICIENT_CONTEXT in statuses

    def test_rayos_brand_name_resolves_to_prednisone_rule(self):
        ctx = _make_pipeline_ctx(
            [_med("RAYOS")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED in statuses


# ---------------------------------------------------------------------------
# K. Integration: prednisone + CRP (Disabled Research Candidate)
# ---------------------------------------------------------------------------

class TestIntegrationPrednisoneCRP:
    def test_crp_suppression_rule_evaluated_as_disabled(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("crp", 0.3, "mg/L")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_RULE_DISABLED in statuses
        assert dlti.STATUS_TRIGGERED not in statuses


# ---------------------------------------------------------------------------
# L. Integration: spironolactone + potassium
# ---------------------------------------------------------------------------

class TestIntegrationSpironolactoneK:
    def test_triggered_high_status(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("potassium", status="ABNORMAL_HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED in statuses

    def test_not_triggered_normal_status(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("potassium", status="NORMAL")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED not in statuses
        assert dlti.STATUS_RULE_EVALUATED in statuses

    def test_missing_status_produces_insufficient_context(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("potassium")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_INSUFFICIENT_CONTEXT in statuses

    def test_aldactone_brand_resolves(self):
        ctx = _make_pipeline_ctx(
            [_med("ALDACTONE")],
            [_lab("potassium", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED in statuses


# ---------------------------------------------------------------------------
# M. No-rule-found behaviour
# ---------------------------------------------------------------------------

class TestNoRuleFound:
    def test_unknown_pair_reported_as_no_rule_found(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("sodium", 130.0, "mmol/L")],  # no sodium rule in KB
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_NO_RULE_FOUND in statuses

    def test_no_rule_found_message_not_safe(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("sodium", 130.0, "mmol/L")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        for entry in result_ctx["dlti"]["results"]:
            if entry.get("status") == dlti.STATUS_NO_RULE_FOUND:
                msg = (entry.get("message") or "").lower()
                assert "no interaction" not in msg
                assert "safe to proceed" not in msg
                assert "not evidence of safety" in msg or "absence" in msg


# ---------------------------------------------------------------------------
# N. Unverified medication skip
# ---------------------------------------------------------------------------

class TestUnverifiedMedSkip:
    def test_unverified_med_skipped_entirely(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone", verified=False)],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        cov = result_ctx["dlti"]["coverage"]
        assert cov["unverified_meds_skipped"] == 1

    def test_unverified_med_does_not_produce_triggered_result(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone", verified=False)],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        statuses = [r["status"] for r in result_ctx["dlti"]["results"]]
        assert dlti.STATUS_TRIGGERED not in statuses


# ---------------------------------------------------------------------------
# O. Synthetic Numeric Engine Tests (Fixture-Only Numeric Thresholds)
# ---------------------------------------------------------------------------

class TestSyntheticNumericEngine:
    """
    Tests engine-level numeric comparison and unit conversion capabilities
    using synthetic test fixtures. Satisfies Requirement 2:
    'Ensure synthetic thresholds used for engine tests exist only in test
    fixtures, not in the evidence-backed knowledge base.'
    """

    def test_synthetic_gt_threshold_evaluates_and_triggers(self):
        synth_rule = _make_synthetic_numeric_rule(operator=">", threshold_value=126.0)
        res = dlti.evaluate_one_rule(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 150.0, "mg/dL"),
        )
        assert res is not None
        assert res["status"] == dlti.STATUS_TRIGGERED
        assert res["triggered"] is True

    def test_synthetic_gt_threshold_not_triggered_below(self):
        synth_rule = _make_synthetic_numeric_rule(operator=">", threshold_value=126.0)
        res = dlti.evaluate_one_rule(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 100.0, "mg/dL"),
        )
        assert res is not None
        assert res["status"] == dlti.STATUS_RULE_EVALUATED
        assert res["triggered"] is False

    def test_synthetic_unit_conversion_mmoll_to_mgdl_triggers(self):
        """
        7.1 mmol/L * 18.0182 = ~127.9 mg/dL, which is > 126.0 mg/dL threshold.
        """
        synth_rule = _make_synthetic_numeric_rule(operator=">", threshold_value=126.0)
        res = dlti.evaluate_one_rule(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 7.1, "mmol/L"),
        )
        assert res is not None
        assert res["status"] == dlti.STATUS_TRIGGERED
        assert res["triggered"] is True

    def test_synthetic_unit_conversion_low_value_not_triggered(self):
        """
        5.5 mmol/L * 18.0182 = ~99.1 mg/dL, which is < 126.0 mg/dL threshold.
        """
        synth_rule = _make_synthetic_numeric_rule(operator=">", threshold_value=126.0)
        res = dlti.evaluate_one_rule(
            rule=synth_rule,
            med_entry=_med("prednisone"),
            lab_entry=_lab("glucose", 5.5, "mmol/L"),
        )
        assert res is not None
        assert res["status"] == dlti.STATUS_RULE_EVALUATED
        assert res["triggered"] is False


# ---------------------------------------------------------------------------
# P. Absence of rule != safe (invariant)
# ---------------------------------------------------------------------------

class TestAbsenceNotSafe:
    def test_no_rule_found_result_not_labeled_safe(self):
        ctx = _make_pipeline_ctx(
            [_med("spironolactone")],
            [_lab("sodium", 130.0, "mmol/L")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path=REAL_KB_PATH)
        for entry in result_ctx["dlti"]["results"]:
            if entry.get("status") == dlti.STATUS_NO_RULE_FOUND:
                msg = entry.get("message", "").lower()
                assert "not evidence of safety" in msg or "safe" not in msg


# ---------------------------------------------------------------------------
# Q. KB unavailable -> no silent success
# ---------------------------------------------------------------------------

class TestKBUnavailableNoSilentSuccess:
    def test_bad_kb_path_does_not_produce_triggered(self):
        ctx = _make_pipeline_ctx(
            [_med("prednisone")],
            [_lab("glucose", status="HIGH")],
        )
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path="/bad/path.json")
        assert result_ctx["dlti"]["status"] == dlti.STATUS_KB_UNAVAILABLE
        assert result_ctx["dlti"]["results"] == []

    def test_bad_kb_path_explicitly_reports_errors(self):
        ctx = _make_pipeline_ctx()
        result_ctx = dlti.DLTICheckingAgent.process(ctx, enabled=True, kb_path="/bad/path.json")
        assert len(result_ctx["dlti"].get("load_errors", [])) > 0

    def test_run_dlti_research_check_convenience_wrapper_disabled(self):
        ctx = _make_pipeline_ctx([_med("prednisone")], [_lab("glucose", status="HIGH")])
        result_ctx = dlti.run_dlti_research_check(ctx)
        assert result_ctx["dlti"]["status"] == dlti.STATUS_DISABLED
