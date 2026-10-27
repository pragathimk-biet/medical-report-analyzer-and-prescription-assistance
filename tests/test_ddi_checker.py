"""
DDI Checker — Comprehensive Regression Test Suite
=================================================

Tests organised into logical groups:

Group A  — DDInterLoader: no dataset, malformed dataset, valid dataset
Group B  — _split_to_ingredients: simple, combination, unknown combo
Group C  — DDIPairChecker: resource unavailable, known pair, reversed order,
           NO_RECORD_FOUND, unresolved name, duplicate deduplication
Group D  — DDICheckingAgent.process: full pipeline context, partial coverage,
           no verified meds, historical med isolation (patient scoping),
           combination product expansion
Group E  — PrescriptionReasoningAgent: DDI block in deterministic fallback,
           LLM failure fallback, DDI output validation (fabrication patterns,
           false safe-claim), NO_RECORD_FOUND not rendered as safe,
           partial/unavailable coverage reported explicitly
Group F  — Patient isolation: different patients get different history scopes
Group G  — Edge cases: empty prescription, single ingredient, all unresolved,
           zero pairs, duplicate records in dataset
"""

import csv
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ddi_checker import (
    DDICheckingAgent,
    DDInterLoader,
    DDIPairChecker,
    COMBINATION_PRODUCT_INGREDIENTS,
    STATUS_INTERACTION_FOUND,
    STATUS_NO_RECORD_FOUND,
    STATUS_RESOURCE_UNAVAILABLE,
    STATUS_UNRESOLVED_MEDICATION,
    TrustedPatientAuthContract,
    _split_to_ingredients,
)
from prescription_reasoning_agent import (
    PrescriptionReasoningAgent,
    _build_ddi_deterministic_block,
    _validate_llm_output_against_ddi,
    _DDI_SECTION_HEADER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv_content(rows: list) -> str:
    """Builds CSV text with the standard DDInter header + given rows."""
    header = "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level"
    lines = [header] + [",".join(str(c) for c in r) for r in rows]
    return "\n".join(lines)


def _write_csv(tmpdir: str, letter: str, content: str) -> str:
    path = os.path.join(tmpdir, f"ddinter_downloads_code_{letter}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _make_loader_with_rows(rows: list) -> DDInterLoader:
    """Creates a DDInterLoader backed by a single temporary CSV file."""
    tmpdir = tempfile.mkdtemp()
    _write_csv(tmpdir, "A", _make_csv_content(rows))
    return DDInterLoader(data_dir=tmpdir)


def _make_pipeline_context(
    verified_med_names=None,
    unverified_med_names=None,
    unsupported_med_names=None,
    metadata=None,
):
    """Builds a minimal pipeline_context dict for testing."""
    verified = []
    for name in (verified_med_names or []):
        verified.append({
            "verified_name":       name,
            "name":                name,
            "identity_verified":   True,
            "verification_status": "verified",
        })
    unverified = []
    for name in (unverified_med_names or []):
        unverified.append({
            "verified_name":       None,
            "name":                name,
            "identity_verified":   False,
            "verification_status": "unknown",
        })
    unsupported = []
    for name in (unsupported_med_names or []):
        unsupported.append({
            "verified_name":       name,
            "name":                name,
            "identity_verified":   False,
            "is_unsupported":      True,
            "verification_status": "unsupported",
        })

    meta = dict(metadata) if metadata else {"patient_name": "Test Patient"}

    patient_name_str = meta.get("patient_name", "Test Patient")
    return {
        "document_type":  "prescription",
        "raw_input":      "",
        "metadata":       meta,
        "extracted_data": {"patient_info": {"patient_name": patient_name_str}},
        "handwriting":    {},
        "verification":   {
            "medications":           verified + unverified + unsupported,
            "medication_lab_checks": [],
            "active_medication_checks": [],
            "overall_status":        "verified",
            "warnings":              [],
        },
        "safety":    {},
        "reasoning": {},
        "warnings":  [],
        "errors":    [],
    }



# ---------------------------------------------------------------------------
# Group A: DDInterLoader — no dataset / malformed / valid
# ---------------------------------------------------------------------------

class TestDDInterLoaderNoDataset(unittest.TestCase):

    def test_empty_dir_returns_unavailable(self):
        tmpdir = tempfile.mkdtemp()
        loader = DDInterLoader(data_dir=tmpdir)
        self.assertFalse(loader.is_available)

    def test_resolve_returns_none_when_unavailable(self):
        tmpdir = tempfile.mkdtemp()
        loader = DDInterLoader(data_dir=tmpdir)
        self.assertIsNone(loader.resolve_drug_name("Warfarin"))

    def test_lookup_returns_resource_unavailable(self):
        tmpdir = tempfile.mkdtemp()
        loader = DDInterLoader(data_dir=tmpdir)
        status, records = loader.lookup_pair("Warfarin", "Aspirin")
        self.assertEqual(status, STATUS_RESOURCE_UNAVAILABLE)
        self.assertEqual(records, [])

    def test_schema_info_reports_unavailable(self):
        tmpdir = tempfile.mkdtemp()
        loader = DDInterLoader(data_dir=tmpdir)
        info = loader.get_schema_info()
        self.assertFalse(info["dataset_available"])
        self.assertEqual(info["total_pairs_loaded"], 0)


class TestDDInterLoaderMalformedDataset(unittest.TestCase):

    def test_missing_required_columns_skips_file(self):
        tmpdir = tempfile.mkdtemp()
        bad_content = "DrugX,DrugY,SeverityLevel\nA,B,Major\n"
        _write_csv(tmpdir, "A", bad_content)
        loader = DDInterLoader(data_dir=tmpdir)
        self.assertFalse(loader.is_available)
        self.assertTrue(len(loader._missing_columns) > 0)

    def test_empty_fields_counted_as_malformed(self):
        rows = [
            ("DDInter1", "Warfarin", "DDInter2", "", "Major"),  # empty Drug_B
            ("DDInter3", "Aspirin",  "DDInter4", "Ibuprofen", ""),  # empty Level
        ]
        tmpdir = tempfile.mkdtemp()
        _write_csv(tmpdir, "A", _make_csv_content(rows))
        loader = DDInterLoader(data_dir=tmpdir)
        self.assertEqual(loader._malformed_rows, 2)
        # No valid rows -> unavailable
        self.assertFalse(loader.is_available)

    def test_mixed_valid_and_malformed_loads_partial(self):
        rows = [
            ("DDInter1", "Warfarin",  "DDInter2", "Aspirin",   "Major"),  # valid
            ("DDInter3", "Metformin", "DDInter4", "",           "Minor"),  # malformed
        ]
        loader = _make_loader_with_rows(rows)
        self.assertTrue(loader.is_available)
        self.assertEqual(loader._malformed_rows, 1)
        self.assertEqual(loader._total_rows, 2)


class TestDDInterLoaderValidDataset(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1",  "Warfarin",    "DDInter2",  "Aspirin",      "Major"),
            ("DDInter3",  "Warfarin",    "DDInter4",  "Ibuprofen",    "Major"),
            ("DDInter5",  "Metformin",   "DDInter6",  "Alcohol",      "Moderate"),
            ("DDInter7",  "Lisinopril",  "DDInter8",  "Spironolactone", "Moderate"),
            ("DDInter9",  "Simvastatin", "DDInter10", "Amlodipine",   "Minor"),
            # Duplicate of row 1 — should be deduplicated
            ("DDInter1",  "Warfarin",    "DDInter2",  "Aspirin",      "Major"),
        ]
        cls.loader = _make_loader_with_rows(rows)

    def test_loader_available(self):
        self.assertTrue(self.loader.is_available)

    def test_known_drug_count(self):
        # 8 unique drug names (Warfarin appears twice in pairs but is one name)
        info = self.loader.get_schema_info()
        self.assertGreaterEqual(info["known_drug_count"], 8)

    def test_deduplication_of_identical_rows(self):
        # 5 unique pairs (6th row is duplicate of 1st)
        info = self.loader.get_schema_info()
        self.assertEqual(info["total_pairs_loaded"], 5)

    def test_resolve_known_drug(self):
        result = self.loader.resolve_drug_name("Warfarin")
        self.assertEqual(result, "warfarin")

    def test_resolve_case_insensitive(self):
        result = self.loader.resolve_drug_name("WARFARIN")
        self.assertEqual(result, "warfarin")

    def test_resolve_unknown_drug_returns_none(self):
        result = self.loader.resolve_drug_name("FantasyDrug999")
        self.assertIsNone(result)

    def test_lookup_known_interaction(self):
        status, records = self.loader.lookup_pair("Warfarin", "Aspirin")
        self.assertEqual(status, STATUS_INTERACTION_FOUND)
        self.assertGreater(len(records), 0)
        self.assertEqual(records[0]["Level"], "Major")

    def test_lookup_order_independent(self):
        """Pair lookup must be symmetric."""
        s1, r1 = self.loader.lookup_pair("Warfarin", "Aspirin")
        s2, r2 = self.loader.lookup_pair("Aspirin", "Warfarin")
        self.assertEqual(s1, s2)
        self.assertEqual(len(r1), len(r2))

    def test_lookup_no_record_found(self):
        """Both drugs known but pair has no interaction entry."""
        status, records = self.loader.lookup_pair("Metformin", "Warfarin")
        self.assertEqual(status, STATUS_NO_RECORD_FOUND)
        self.assertEqual(records, [])

    def test_lookup_one_unresolved(self):
        status, records = self.loader.lookup_pair("Warfarin", "UnknownDrug")
        self.assertEqual(status, STATUS_UNRESOLVED_MEDICATION)

    def test_lookup_both_unresolved(self):
        status, records = self.loader.lookup_pair("DrugX", "DrugY")
        self.assertEqual(status, STATUS_UNRESOLVED_MEDICATION)

    def test_level_preserved_verbatim(self):
        _, records = self.loader.lookup_pair("Warfarin", "Aspirin")
        self.assertEqual(records[0]["Level"], "Major")  # not remapped


# ---------------------------------------------------------------------------
# Group B: _split_to_ingredients
# ---------------------------------------------------------------------------

class TestSplitToIngredients(unittest.TestCase):

    def test_simple_drug_returns_itself(self):
        self.assertEqual(_split_to_ingredients("Warfarin"), ["Warfarin"])

    def test_known_combo_product_splits(self):
        result = _split_to_ingredients("amoxicillin/clavulanate")
        self.assertIn("amoxicillin", result)
        self.assertIn("clavulanate", result)
        self.assertEqual(len(result), 2)

    def test_combo_case_insensitive(self):
        result = _split_to_ingredients("Amoxicillin/Clavulanate")
        self.assertIn("amoxicillin", result)

    def test_amoxiclav_alias(self):
        result = _split_to_ingredients("amoxiclav")
        self.assertIn("amoxicillin", result)
        self.assertIn("clavulanate", result)

    def test_unknown_combo_returns_original(self):
        """An unknown slash-containing name is NOT auto-split; kept as-is."""
        result = _split_to_ingredients("UnknownDrug/Something")
        self.assertEqual(result, ["UnknownDrug/Something"])

    def test_trimethoprim_sulfamethoxazole(self):
        result = _split_to_ingredients("trimethoprim/sulfamethoxazole")
        self.assertEqual(set(result), {"trimethoprim", "sulfamethoxazole"})


# ---------------------------------------------------------------------------
# Group C: DDIPairChecker
# ---------------------------------------------------------------------------

class TestDDIPairCheckerResourceUnavailable(unittest.TestCase):

    def setUp(self):
        tmpdir = tempfile.mkdtemp()
        self.loader = DDInterLoader(data_dir=tmpdir)
        self.checker = DDIPairChecker(loader=self.loader)

    def test_all_pairs_return_resource_unavailable(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "Aspirin"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], STATUS_RESOURCE_UNAVAILABLE)

    def test_note_mentions_configure(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "Aspirin"])
        self.assertIn("DDI_DATA_DIR", results[0]["note"])


class TestDDIPairCheckerWithDataset(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1", "Warfarin",   "DDInter2", "Aspirin",   "Major"),
            ("DDInter3", "Metformin",  "DDInter4", "Alcohol",   "Moderate"),
        ]
        cls.loader = _make_loader_with_rows(rows)
        cls.checker = DDIPairChecker(loader=cls.loader)

    def test_known_pair_interaction_found(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "Aspirin"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], STATUS_INTERACTION_FOUND)
        self.assertEqual(results[0]["level"], "Major")

    def test_reversed_pair_same_result(self):
        r1 = self.checker.check_ingredient_pairs(["Warfarin", "Aspirin"])
        r2 = self.checker.check_ingredient_pairs(["Aspirin", "Warfarin"])
        self.assertEqual(r1[0]["status"], r2[0]["status"])

    def test_no_record_found(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "Metformin"])
        self.assertEqual(results[0]["status"], STATUS_NO_RECORD_FOUND)
        note_lower = results[0]["note"].lower()
        # Must NOT claim the pair is safe (positive safe-claim)
        self.assertNotIn("safe to", note_lower)
        self.assertNotIn("is safe", note_lower)
        self.assertNotIn("no interaction", note_lower)
        # Must contain an explicit non-safety disclaimer
        self.assertIn("does not", note_lower)

    def test_unresolved_ingredient(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "DrugXYZ"])
        self.assertEqual(results[0]["status"], STATUS_UNRESOLVED_MEDICATION)

    def test_three_drugs_generates_three_pairs(self):
        results = self.checker.check_ingredient_pairs(["Warfarin", "Aspirin", "Metformin"])
        self.assertEqual(len(results), 3)

    def test_duplicate_ingredient_deduplicated(self):
        """Duplicate entries must be removed before pairing."""
        results = self.checker.check_ingredient_pairs(
            ["Warfarin", "Warfarin", "Aspirin"]
        )
        # After dedup: [Warfarin, Aspirin] -> 1 pair
        self.assertEqual(len(results), 1)

    def test_source_map_preserves_product_reference(self):
        source_map = {"warfarin": "Warfarin (Brand X)", "aspirin": "Aspirin 75mg"}
        results = self.checker.check_ingredient_pairs(
            ["Warfarin", "Aspirin"], source_map=source_map
        )
        self.assertIn("Warfarin (Brand X)", results[0]["source_product_a"] + results[0]["source_product_b"])

    def test_single_ingredient_produces_no_pairs(self):
        results = self.checker.check_ingredient_pairs(["Warfarin"])
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Group D: DDICheckingAgent.process — pipeline context tests
# ---------------------------------------------------------------------------

class TestDDICheckingAgentNoDataset(unittest.TestCase):

    def _make_unavailable_loader(self):
        tmpdir = tempfile.mkdtemp()
        return DDInterLoader(data_dir=tmpdir)

    def test_resource_unavailable_overall_status(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        loader = self._make_unavailable_loader()
        ctx = DDICheckingAgent.process(ctx, loader=loader)
        self.assertEqual(ctx["ddi"]["overall_status"], "resource_unavailable")

    def test_resource_unavailable_never_no_interactions(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        loader = self._make_unavailable_loader()
        ctx = DDICheckingAgent.process(ctx, loader=loader)
        ddi = ctx["ddi"]
        # "no interactions" must NOT appear anywhere in warnings or pairs
        all_text = str(ddi.get("warnings", "")) + str(ddi.get("pairs", ""))
        self.assertNotIn("no interactions", all_text.lower())

    def test_coverage_dataset_available_false(self):
        ctx = _make_pipeline_context(verified_med_names=["Aspirin"])
        loader = self._make_unavailable_loader()
        ctx = DDICheckingAgent.process(ctx, loader=loader)
        self.assertFalse(ctx["ddi"]["coverage"]["dataset_available"])


class TestDDICheckingAgentWithDataset(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1", "Warfarin",    "DDInter2", "Aspirin",        "Major"),
            ("DDInter3", "Lisinopril",  "DDInter4", "Spironolactone", "Moderate"),
        ]
        cls.loader = _make_loader_with_rows(rows)

    def test_interaction_found_in_pairs(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        self.assertEqual(len(ctx["ddi"]["interactions_found"]), 1)
        self.assertEqual(ctx["ddi"]["interactions_found"][0]["level"], "Major")

    def test_overall_status_checked_when_all_resolved(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        self.assertEqual(ctx["ddi"]["overall_status"], "checked")

    def test_partial_coverage_when_unresolved_ingredient(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "DrugXYZ"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        self.assertEqual(ctx["ddi"]["overall_status"], "partial")
        self.assertIn("DrugXYZ", ctx["ddi"]["coverage"]["unresolved_ingredients"])

    def test_no_pairs_when_single_verified_med(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        self.assertEqual(ctx["ddi"]["overall_status"], "no_pairs")

    def test_unverified_meds_excluded(self):
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            unverified_med_names=["Aspirin"],  # Aspirin unverified -> excluded
        )
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        # Only Warfarin is verified: single ingredient, no pairs
        self.assertEqual(ctx["ddi"]["coverage"]["verified_meds"], 1)
        self.assertEqual(ctx["ddi"]["coverage"]["total_pairs_checked"], 0)

    def test_warning_added_for_unverified_exclusion(self):
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            unverified_med_names=["Aspirin"],
        )
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        warnings_text = " ".join(ctx["ddi"]["warnings"])
        self.assertIn("excluded from DDI check", warnings_text)

    def test_combination_product_expanded_to_ingredients(self):
        """amoxiclav -> [amoxicillin, clavulanate]; both checked as separate ingredients."""
        ctx = _make_pipeline_context(verified_med_names=["amoxiclav"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        # 2 ingredients from combo: amoxicillin + clavulanate
        self.assertEqual(ctx["ddi"]["coverage"]["total_ingredients_checked"], 2)

    def test_combination_product_source_preserved(self):
        ctx = _make_pipeline_context(verified_med_names=["amoxiclav", "Warfarin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        # Source map should map ingredient back to "amoxiclav"
        all_source_refs = [
            p.get("source_product_a", "") + p.get("source_product_b", "")
            for p in ctx["ddi"]["pairs"]
        ]
        self.assertTrue(any("amoxiclav" in s for s in all_source_refs))

    def test_coverage_reported_in_output(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        cov = ctx["ddi"]["coverage"]
        self.assertIn("total_pairs_checked", cov)
        self.assertIn("total_ingredients_checked", cov)
        self.assertIn("dataset_available", cov)


class TestDDICheckingAgentPatientIsolation(unittest.TestCase):
    """
    Verifies that active historical medications are scoped ONLY to the
    authenticated patient. A different patient's history must not leak.
    """

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1", "Warfarin", "DDInter2", "Aspirin", "Major"),
        ]
        cls.loader = _make_loader_with_rows(rows)

    def _make_mock_mgr(self, patient_name: str, active_meds: list):
        """Creates a PatientHistoryManager mock scoped to one patient."""
        mgr = MagicMock()
        def get_store(name):
            if name == patient_name:
                return {"active_medications": active_meds}
            return {"active_medications": []}  # other patients get nothing
        mgr._get_patient_store.side_effect = get_store
        return mgr

    def test_patient_a_gets_own_active_meds(self):
        active_meds_a = [{"name": "Aspirin", "status": "active"}]
        mgr = self._make_mock_mgr("Patient A", active_meds_a)
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Patient A"},
        )
        auth = TrustedPatientAuthContract(patient_scope="Patient A", issuer="hospital_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mgr, loader=self.loader, trusted_auth_contract=auth)
        # Warfarin (rx) + Aspirin (historical for Patient A) -> INTERACTION_FOUND
        self.assertEqual(len(ctx["ddi"]["interactions_found"]), 1)

    def test_patient_b_does_not_see_patient_a_history(self):
        active_meds_a = [{"name": "Aspirin", "status": "active"}]
        mgr = self._make_mock_mgr("Patient A", active_meds_a)
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Patient B"},  # different patient
        )
        auth = TrustedPatientAuthContract(patient_scope="Patient B", issuer="hospital_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mgr, loader=self.loader, trusted_auth_contract=auth)
        # Patient B has no historical meds -> only 1 ingredient -> no pairs
        self.assertEqual(ctx["ddi"]["coverage"]["historical_active_meds"], 0)
        self.assertEqual(ctx["ddi"]["coverage"]["total_pairs_checked"], 0)

    def test_history_error_adds_warning_not_crash(self):
        mgr = MagicMock()
        mgr._get_patient_store.side_effect = RuntimeError("DB connection failed")
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Patient X"},
        )
        auth = TrustedPatientAuthContract(patient_scope="Patient X", issuer="hospital_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mgr, loader=self.loader, trusted_auth_contract=auth)
        warnings_text = " ".join(ctx["ddi"]["warnings"])
        self.assertIn("retrieval error", warnings_text.lower())

    def test_pseudonym_not_in_ddi_output(self):
        """Real patient name must not appear in ddi warnings or pair data."""
        real_name = "Irani Gangadharappa"
        mgr = self._make_mock_mgr(real_name, [])
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": real_name},
        )
        auth = TrustedPatientAuthContract(patient_scope=real_name, issuer="hospital_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mgr, loader=self.loader, trusted_auth_contract=auth)
        ddi_str = str(ctx["ddi"])
        self.assertNotIn(real_name, ddi_str)

    def test_only_active_status_meds_included(self):
        """inactive/discharged historical meds must NOT be included."""
        active_meds = [
            {"name": "Aspirin",    "status": "active"},
            {"name": "Ibuprofen",  "status": "discontinued"},  # must be excluded
            {"name": "Metformin",  "status": "inactive"},      # must be excluded
        ]
        mgr = self._make_mock_mgr("Test Patient", active_meds)
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Test Patient"},
        )
        auth = TrustedPatientAuthContract(patient_scope="Test Patient", issuer="hospital_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mgr, loader=self.loader, trusted_auth_contract=auth)
        # Only Aspirin is active -> 2 ingredients total (Warfarin + Aspirin)
        self.assertEqual(ctx["ddi"]["coverage"]["historical_active_meds"], 1)


# ---------------------------------------------------------------------------
# Group E: PrescriptionReasoningAgent — DDI integration & output validation
# ---------------------------------------------------------------------------

class TestDDIDeterministicBlock(unittest.TestCase):
    """_build_ddi_deterministic_block must always render from structured data."""

    def _make_ddi_resource_unavailable(self):
        return {
            "overall_status": "resource_unavailable",
            "coverage": {
                "dataset_available":         False,
                "total_prescription_meds":   2,
                "verified_meds":             2,
                "unresolved_ingredients":    [],
                "historical_active_meds":    0,
                "total_ingredients_checked": 2,
                "total_pairs_checked":       0,
                "schema_info":               {},
            },
            "pairs":              [],
            "interactions_found": [],
            "warnings":           [],
        }

    def _make_ddi_interaction_found(self):
        return {
            "overall_status": "checked",
            "coverage": {
                "dataset_available":         True,
                "total_prescription_meds":   2,
                "verified_meds":             2,
                "unresolved_ingredients":    [],
                "historical_active_meds":    0,
                "total_ingredients_checked": 2,
                "total_pairs_checked":       1,
                "schema_info":               {},
            },
            "pairs": [{
                "drug_a":           "Warfarin",
                "drug_b":           "Aspirin",
                "source_product_a": "Warfarin",
                "source_product_b": "Aspirin",
                "status":           STATUS_INTERACTION_FOUND,
                "level":            "Major",
                "records":          [{"DDInterID_A": "DDInter1", "Drug_A": "Warfarin",
                                      "DDInterID_B": "DDInter2", "Drug_B": "Aspirin",
                                      "Level": "Major"}],
                "note":             "Interaction record(s) found in DDInter dataset (Level: Major).",
            }],
            "interactions_found": [],  # populated below
            "warnings": [],
        }

    def test_resource_unavailable_block_contains_configure_notice(self):
        ddi = self._make_ddi_resource_unavailable()
        block = _build_ddi_deterministic_block(ddi)
        self.assertIn("not configured", block.lower())
        self.assertIn(_DDI_SECTION_HEADER, block)

    def test_interaction_found_block_shows_level_verbatim(self):
        ddi = self._make_ddi_interaction_found()
        ddi["interactions_found"] = ddi["pairs"]
        block = _build_ddi_deterministic_block(ddi)
        self.assertIn("Major", block)
        self.assertIn("INTERACTION_FOUND", block)

    def test_no_record_found_block_never_says_safe(self):
        ddi = {
            "overall_status": "checked",
            "coverage": {
                "dataset_available": True,
                "total_prescription_meds": 2, "verified_meds": 2,
                "unresolved_ingredients": [], "historical_active_meds": 0,
                "total_ingredients_checked": 2, "total_pairs_checked": 1,
                "schema_info": {},
            },
            "pairs": [{
                "drug_a": "Metformin", "drug_b": "Warfarin",
                "source_product_a": "Metformin", "source_product_b": "Warfarin",
                "status": STATUS_NO_RECORD_FOUND,
                "level": None,
                "records": [],
                "note": "No record found. Absence does NOT confirm safety.",
            }],
            "interactions_found": [],
            "warnings": [],
        }
        block = _build_ddi_deterministic_block(ddi)
        block_lower = block.lower()
        # Must not make a positive safe-claim ("safe to", "is safe")
        self.assertNotIn("safe to", block_lower)
        self.assertNotIn("is safe", block_lower)
        self.assertNotIn("no interactions", block_lower)
        # Must include explicit negation phrasing
        self.assertIn("does not", block_lower)

    def test_partial_block_reports_unresolved(self):
        ddi = {
            "overall_status": "partial",
            "coverage": {
                "dataset_available": True,
                "total_prescription_meds": 2, "verified_meds": 2,
                "unresolved_ingredients": ["DrugXYZ"],
                "historical_active_meds": 0, "total_ingredients_checked": 2,
                "total_pairs_checked": 1, "schema_info": {},
            },
            "pairs": [],
            "interactions_found": [],
            "warnings": [],
        }
        block = _build_ddi_deterministic_block(ddi)
        self.assertIn("DrugXYZ", block)
        self.assertIn("Partial", block)

    def test_empty_ddi_returns_empty_string(self):
        block = _build_ddi_deterministic_block({})
        self.assertEqual(block, "")


class TestDDIOutputValidation(unittest.TestCase):
    """_validate_llm_output_against_ddi catches fabrication and false safe-claims."""

    def _base_ddi(self, overall="checked", interactions=None):
        return {
            "overall_status":     overall,
            "interactions_found": interactions or [],
            "coverage": {
                "dataset_available": True,
                "unresolved_ingredients": [],
            },
        }

    def test_clean_text_passes_validation(self):
        ddi = self._base_ddi()
        is_valid, violations = _validate_llm_output_against_ddi(
            "Please follow your doctor's instructions.", ddi
        )
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

    def test_stop_taking_pattern_fails(self):
        ddi = self._base_ddi()
        is_valid, violations = _validate_llm_output_against_ddi(
            "You should stop taking Warfarin immediately.", ddi
        )
        self.assertFalse(is_valid)
        self.assertGreater(len(violations), 0)

    def test_discontinue_pattern_fails(self):
        ddi = self._base_ddi()
        is_valid, violations = _validate_llm_output_against_ddi(
            "The doctor recommends to discontinue the medication.", ddi
        )
        self.assertFalse(is_valid)

    def test_false_safe_claim_with_interaction_found_fails(self):
        interaction = [{"drug_a": "Warfarin", "drug_b": "Aspirin", "level": "Major"}]
        ddi = self._base_ddi(interactions=interaction)
        is_valid, violations = _validate_llm_output_against_ddi(
            "There are no drug interactions between your medications.", ddi
        )
        self.assertFalse(is_valid)
        self.assertTrue(any("no interactions" in v.lower() for v in violations))

    def test_false_safe_claim_with_partial_coverage_fails(self):
        ddi = self._base_ddi(overall="partial")
        is_valid, violations = _validate_llm_output_against_ddi(
            "No interactions found — safe to combine.", ddi
        )
        self.assertFalse(is_valid)

    def test_false_safe_claim_resource_unavailable_fails(self):
        ddi = self._base_ddi(overall="resource_unavailable")
        is_valid, violations = _validate_llm_output_against_ddi(
            "No known interactions detected.", ddi
        )
        self.assertFalse(is_valid)

    def test_none_text_passes_without_crash(self):
        ddi = self._base_ddi()
        is_valid, violations = _validate_llm_output_against_ddi(None, ddi)
        self.assertTrue(is_valid)

    def test_empty_text_passes_without_crash(self):
        ddi = self._base_ddi()
        is_valid, violations = _validate_llm_output_against_ddi("", ddi)
        self.assertTrue(is_valid)


class TestPrescriptionReasoningAgentDDI(unittest.TestCase):
    """Full PrescriptionReasoningAgent tests with DDI data."""

    def _base_context(self, ddi=None):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        if ddi is not None:
            ctx["ddi"] = ddi
        return ctx

    def _make_ddi_interaction(self):
        return {
            "overall_status": "checked",
            "coverage": {
                "dataset_available": True, "total_prescription_meds": 2,
                "verified_meds": 2, "unresolved_ingredients": [],
                "historical_active_meds": 0, "total_ingredients_checked": 2,
                "total_pairs_checked": 1, "schema_info": {},
            },
            "pairs": [{
                "drug_a": "Warfarin", "drug_b": "Aspirin",
                "source_product_a": "Warfarin", "source_product_b": "Aspirin",
                "status": STATUS_INTERACTION_FOUND, "level": "Major",
                "records": [{"DDInterID_A": "DDInter1", "Drug_A": "Warfarin",
                              "DDInterID_B": "DDInter2", "Drug_B": "Aspirin",
                              "Level": "Major"}],
                "note": "Interaction found.",
            }],
            "interactions_found": [{
                "drug_a": "Warfarin", "drug_b": "Aspirin", "level": "Major",
            }],
            "warnings": [],
        }

    def test_deterministic_summary_includes_ddi_block(self):
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        self.assertIn(_DDI_SECTION_HEADER, ctx["reasoning"]["summary"])

    def test_ddi_block_always_present_in_reasoning(self):
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        self.assertIn("ddi_block", ctx["reasoning"])
        self.assertIn(_DDI_SECTION_HEADER, ctx["reasoning"]["ddi_block"])

    def test_llm_failure_falls_back_to_deterministic_with_ddi(self):
        """If LLM raises, deterministic fallback still includes DDI block."""
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)

        def failing_llm(prompt, sys_prompt):
            raise RuntimeError("LLM service unavailable")

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=failing_llm)
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")
        self.assertIn(_DDI_SECTION_HEADER, ctx["reasoning"]["summary"])

    def test_llm_fabrication_rejected_falls_back_to_deterministic(self):
        """LLM output containing 'stop taking' must be rejected, fallback used."""
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)

        def bad_llm(prompt, sys_prompt):
            return "You should stop taking Aspirin due to interaction."

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=bad_llm)
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")
        self.assertGreater(len(ctx["reasoning"]["ddi_validation_violations"]), 0)

    def test_llm_false_safe_claim_rejected(self):
        """LLM claiming 'no drug interactions' despite INTERACTION_FOUND is rejected."""
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)

        def lying_llm(prompt, sys_prompt):
            return "No drug interactions were found. Safe to take together."

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=lying_llm)
        self.assertEqual(ctx["reasoning"]["generated_by"], "deterministic_fallback")

    def test_valid_llm_output_appends_ddi_block(self):
        """Valid LLM output must have the structured DDI block appended."""
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)

        def good_llm(prompt, sys_prompt):
            return "Warfarin is a blood thinner. Follow your doctor's schedule exactly."

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=good_llm)
        self.assertEqual(ctx["reasoning"]["generated_by"], "ai_generator")
        self.assertIn(_DDI_SECTION_HEADER, ctx["reasoning"]["summary"])

    def test_hard_stop_includes_ddi_block(self):
        """hard_stop response must still contain the DDI block."""
        ddi = self._make_ddi_interaction()
        ctx = self._base_context(ddi=ddi)
        ctx["verification"]["overall_status"] = "hard_stop"
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        self.assertIn(_DDI_SECTION_HEADER, ctx["reasoning"]["summary"])

    def test_no_ddi_data_does_not_crash(self):
        """If ddi key is absent (DDICheckingAgent not run), reasoning still works."""
        ctx = _make_pipeline_context(verified_med_names=["Warfarin"])
        # deliberately no "ddi" key
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        self.assertIn("summary", ctx["reasoning"])

    def test_resource_unavailable_ddi_reported_explicitly(self):
        ddi_unavailable = {
            "overall_status": "resource_unavailable",
            "coverage": {
                "dataset_available": False, "total_prescription_meds": 2,
                "verified_meds": 2, "unresolved_ingredients": [],
                "historical_active_meds": 0, "total_ingredients_checked": 2,
                "total_pairs_checked": 0, "schema_info": {},
            },
            "pairs": [], "interactions_found": [], "warnings": [],
        }
        ctx = self._base_context(ddi=ddi_unavailable)
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        summary_lower = ctx["reasoning"]["summary"].lower()
        self.assertNotIn("no interactions", summary_lower)
        self.assertIn("not configured", summary_lower)


# ---------------------------------------------------------------------------
# Group G: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rows = [("DDInter1", "Warfarin", "DDInter2", "Aspirin", "Major")]
        cls.loader = _make_loader_with_rows(rows)

    def test_empty_ingredient_list(self):
        checker = DDIPairChecker(loader=self.loader)
        self.assertEqual(checker.check_ingredient_pairs([]), [])

    def test_all_unresolved_gives_partial_status(self):
        ctx = _make_pipeline_context(verified_med_names=["DrugA", "DrugB"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        # Both unresolved -> pairs exist but all UNRESOLVED_MEDICATION -> partial
        self.assertEqual(ctx["ddi"]["overall_status"], "partial")

    def test_zero_checked_pairs_never_says_no_interactions(self):
        ctx = _make_pipeline_context(verified_med_names=["Warfarin"])
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        self.assertEqual(ctx["ddi"]["overall_status"], "no_pairs")
        all_text = str(ctx["ddi"])
        self.assertNotIn("no interactions", all_text.lower())

    def test_duplicate_records_in_dataset_deduplicated(self):
        """Duplicate doc_id rows in the CSV must be loaded as one pair entry."""
        rows = [
            ("DDInter1", "Warfarin", "DDInter2", "Aspirin", "Major"),
            ("DDInter1", "Warfarin", "DDInter2", "Aspirin", "Major"),  # exact dup
        ]
        loader = _make_loader_with_rows(rows)
        info = loader.get_schema_info()
        self.assertEqual(info["total_pairs_loaded"], 1)

    def test_malformed_dataset_does_not_crash_agent(self):
        """A fully malformed CSV must not crash DDICheckingAgent."""
        tmpdir = tempfile.mkdtemp()
        _write_csv(tmpdir, "A", "garbage,columns,here\n1,2,3\n")
        loader = DDInterLoader(data_dir=tmpdir)
        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        ctx = DDICheckingAgent.process(ctx, loader=loader)
        # Dataset unavailable -> resource_unavailable
        self.assertEqual(ctx["ddi"]["overall_status"], "resource_unavailable")

    def test_combination_product_two_prescriptions_deduplicated(self):
        """amoxiclav + amoxicillin as separate items: ingredients deduplicated."""
        # amoxiclav -> [amoxicillin, clavulanate]
        # amoxicillin -> [amoxicillin] (already present)
        # Result: [amoxicillin, clavulanate] — no self-pair, no dup pair
        ctx = _make_pipeline_context(
            verified_med_names=["amoxiclav", "Amoxicillin"]
        )
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        # amoxicillin deduped: only [amoxicillin, clavulanate] -> 1 unique pair
        self.assertEqual(ctx["ddi"]["coverage"]["total_ingredients_checked"], 2)
        self.assertEqual(ctx["ddi"]["coverage"]["total_pairs_checked"], 1)



class TestDDIBoundedRemediationPass(unittest.TestCase):
    """
    Focused tests reproducing each defect before remediation:
    1. Alias-versus-alias self-pairs (Aspirin vs Acetylsalicylic acid).
    2. Unauthenticated scope or 'Default Patient' history access blocked.
    3. Requested history failure distinguishing prescription-only coverage.
    4. Dataset completeness vs availability and failed/skipped files tracking.
    5. Counter separation (submitted/resolved ingredients, attempted/evaluated pairs).
    6. Curated mapping inconsistency detection and rejection.
    """

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1", "Warfarin", "DDInter20", "Acetylsalicylic acid", "Major"),
            ("DDInter1", "Warfarin", "DDInter14", "Acetaminophen", "Moderate"),
        ]
        cls.loader = _make_loader_with_rows(rows)

    def test_defect_alias_versus_alias_self_pair_prevented(self):
        """
        DEFECT: When 'Aspirin' and 'Acetylsalicylic acid' are submitted together,
        pair checker previously created an alias-vs-alias self-pair because it deduplicated
        by raw string name instead of resolving canonical identity first.
        """
        checker = DDIPairChecker(loader=self.loader)
        source_map = {
            "aspirin": "Ecosprin 75",
            "acetylsalicylic acid": "Disprin",
        }
        pairs = checker.check_ingredient_pairs(["Aspirin", "Acetylsalicylic acid"], source_map=source_map)
        # Must resolve both to DDInter20 and produce ZERO self-pairs
        self.assertEqual(len(pairs), 0)

    def test_defect_alias_versus_alias_with_third_drug_preserves_sources(self):
        """
        DEFECT: When 'Aspirin', 'Acetylsalicylic acid', and 'Warfarin' are submitted,
        it must produce exactly ONE pair (Warfarin vs Acetylsalicylic acid), NOT 3 pairs.
        All originating product references must be preserved.
        """
        checker = DDIPairChecker(loader=self.loader)
        source_map = {
            "aspirin": "Ecosprin 75",
            "acetylsalicylic acid": "Disprin",
            "warfarin": "Coumadin",
        }
        pairs = checker.check_ingredient_pairs(
            ["Aspirin", "Acetylsalicylic acid", "Warfarin"],
            source_map=source_map
        )
        self.assertEqual(len(pairs), 1)
        p = pairs[0]
        # Originating product references must contain both Ecosprin 75 and Disprin
        combined_sources = p["source_product_a"] + " " + p["source_product_b"]
        self.assertIn("Ecosprin 75", combined_sources)
        self.assertIn("Disprin", combined_sources)

    def test_defect_unauthorized_scope_blocks_history_access(self):
        """
        DEFECT: Callers without an authorized patient scope previously fell back
        to 'Default Patient' or extracted OCR name. If no authorization contract exists,
        history access must be blocked explicitly and recorded in coverage/warnings.
        """
        mock_mgr = MagicMock()
        mock_mgr._get_patient_store.return_value = {
            "active_medications": [{"name": "Aspirin", "status": "active"}]
        }
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Default Patient"},  # No authorized scope!
        )
        # Explicitly remove authorized_patient_scope if set by helper
        ctx["metadata"].pop("authorized_patient_scope", None)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mock_mgr, loader=self.loader)

        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["history_scope_status"], "UNAUTHORIZED_OR_UNSCOPED")
        self.assertEqual(cov["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
        self.assertIsNotNone(cov["history_authorization_blocker"])
        self.assertEqual(cov["historical_active_meds"], 0)
        # Requested history blocked -> must distinguish prescription-only coverage
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")
        mock_mgr._get_patient_store.assert_not_called()

    def test_defect_history_retrieval_failure_distinguishes_prescription_only(self):
        """
        DEFECT: When requested history retrieval fails, coverage previously silently
        yielded FULL coverage. It must distinguish PRESCRIPTION_ONLY coverage.
        """
        mock_mgr = MagicMock()
        mock_mgr._get_patient_store.side_effect = RuntimeError("Storage connection failed")
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"authorized_patient_scope": "AUTH_PT_999"},
        )
        auth = TrustedPatientAuthContract(patient_scope="AUTH_PT_999", issuer="test_auth", is_verified=True)
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mock_mgr, loader=self.loader, trusted_auth_contract=auth)

        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")
        self.assertEqual(ctx["ddi"]["overall_status"], "prescription_only")
        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["history_retrieval_status"], "FAILED")
        self.assertTrue(cov["prescription_only_coverage"])

    def test_defect_dataset_availability_separated_from_completeness(self):
        """
        DEFECT: Loader previously set dataset_available=True and equated loaded rows
        with an intact snapshot, without tracking failed/skipped files.
        """
        tmpdir = tempfile.mkdtemp()
        _write_csv(tmpdir, "A", "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\nDDInter1,Warfarin,DDInter20,Aspirin,Major\n")
        _write_csv(tmpdir, "B", "BadHeader1,BadHeader2\n1,2\n")  # Skipped file

        loader = DDInterLoader(data_dir=tmpdir)
        info = loader.get_schema_info()
        self.assertTrue(loader.is_available)
        self.assertIn("ddinter_downloads_code_B.csv", info["skipped_files"])
        self.assertEqual(info["dataset_completeness_status"], "PARTIAL")

    def test_defect_counters_separate_submitted_resolved_and_attempted_evaluated(self):
        """
        DEFECT: Counters previously did not separate submitted vs resolved ingredients
        or attempted vs evaluated pairs, and unsupported medications could count as checked.
        """
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            unsupported_med_names=["HerbalExtract"],
        )
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)
        cov = ctx["ddi"]["coverage"]
        self.assertIn("submitted_ingredients_count", cov)
        self.assertIn("resolved_ingredients_count", cov)
        self.assertIn("unresolved_ingredients_count", cov)
        self.assertIn("attempted_pairs_count", cov)
        self.assertIn("evaluated_pairs_count", cov)
        # Unsupported medication must not count as checked
        self.assertEqual(cov["checked_medications"], 1)
        self.assertEqual(cov["submitted_medications"], 2)

    def test_defect_curated_mapping_inconsistency_rejected(self):
        """
        DEFECT: Curated mapping inconsistent with loaded records was not detected.
        """
        # Create loader where Aspirin has a conflicting DDInterID
        rows = [("DDInter999", "Acetylsalicylic acid", "DDInter1", "Warfarin", "Major")]
        loader = _make_loader_with_rows(rows)
        # Curated mapping expects DDInter20, but dataset has DDInter999
        self.assertIn("aspirin", loader._inconsistent_mappings)
        # Inconsistent mapping must be rejected from identity resolution
        res = loader.resolve_drug_identity("aspirin")
        self.assertIsNone(res)


class TestDDIIntegrationVerificationPass(unittest.TestCase):
    """
    Focused integration tests verifying authorization boundaries, coverage status
    propagation, dimension separation, canonical source references, and LLM fallback.
    """

    @classmethod
    def setUpClass(cls):
        rows = [
            ("DDInter1", "Warfarin", "DDInter20", "Acetylsalicylic acid", "Major"),
            ("DDInter3", "Lisinopril", "DDInter4", "Spironolactone", "Moderate"),
        ]
        cls.loader = _make_loader_with_rows(rows)

    def test_no_trusted_authorization_blocks_history(self):
        """1. No trusted authorization contract -> history access blocked, prescription-only."""
        mock_mgr = MagicMock()
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={"patient_name": "Unverified Patient"},
        )
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mock_mgr, loader=self.loader)
        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["history_scope_status"], "UNAUTHORIZED_OR_UNSCOPED")
        self.assertEqual(cov["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
        self.assertEqual(cov["historical_active_meds"], 0)
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")
        self.assertEqual(ctx["ddi"]["overall_status"], "prescription_only")
        mock_mgr._get_patient_store.assert_not_called()

    def test_forged_scope_field_in_client_metadata_blocks_history(self):
        """2. Forged scope field in client payload/metadata -> explicitly rejected."""
        mock_mgr = MagicMock()
        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin"],
            metadata={
                "patient_name": "Attacker",
                "authorized_patient_scope": "VictimPatient123",
                "authorized_patient_id": "VictimPatient123",
            },
        )
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mock_mgr, loader=self.loader)
        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
        self.assertEqual(cov["historical_active_meds"], 0)
        self.assertIn("rejected", cov["history_authorization_blocker"].lower())
        mock_mgr._get_patient_store.assert_not_called()

    def test_history_failure_and_unresolved_prescription_shows_both_limitations(self):
        """3. History failure + unresolved prescription -> both limitations shown, not concealed."""
        mock_mgr = MagicMock()
        mock_mgr._get_patient_store.side_effect = RuntimeError("Database timeout connecting to replica")
        auth = TrustedPatientAuthContract(patient_scope="PT_AUTH_77", issuer="server_auth", is_verified=True)

        ctx = _make_pipeline_context(
            verified_med_names=["Warfarin", "UnresolvableDrug99"],
            metadata={"patient_name": "Valid Patient"},
        )
        ctx = DDICheckingAgent.process(
            ctx,
            patient_history_mgr=mock_mgr,
            loader=self.loader,
            trusted_auth_contract=auth,
        )
        # PARTIAL prescription coverage must not be concealed by PRESCRIPTION_ONLY
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PARTIAL")
        self.assertEqual(ctx["ddi"]["overall_status"], "partial")
        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["prescription_coverage"], "PARTIAL")
        self.assertEqual(cov["history_retrieval_status"], "FAILED")
        self.assertTrue(cov["prescription_only_coverage"])

        # Reasoner output must display both limitations explicitly
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        summary = ctx["reasoning"].get("summary", "")
        self.assertIn("Partial DDI coverage (PARTIAL)", summary)
        self.assertIn("Notice on Patient History", summary)

    def test_dataset_integrity_failure_prevents_unqualified_full_coverage(self):
        """4. Dataset integrity failure -> qualified coverage, never unqualified FULL."""
        tmpdir = tempfile.mkdtemp()
        _write_csv(tmpdir, "A", "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\nDDInter1,Warfarin,DDInter20,Aspirin,Major\n")
        _write_csv(tmpdir, "B", "BadCol1,BadCol2\nVal1,Val2\n")  # Skipped file -> PARTIAL dataset

        partial_loader = DDInterLoader(data_dir=tmpdir)
        self.assertEqual(partial_loader.get_schema_info()["dataset_completeness_status"], "PARTIAL")

        ctx = _make_pipeline_context(verified_med_names=["Warfarin", "Aspirin"])
        ctx = DDICheckingAgent.process(ctx, loader=partial_loader)

        self.assertNotEqual(ctx["ddi"]["coverage_completeness"], "FULL")
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PARTIAL_DATASET")
        self.assertEqual(ctx["ddi"]["overall_status"], "partial")

        # Deterministic output must show notice on dataset integrity
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        summary = ctx["reasoning"].get("summary", "")
        self.assertIn("Notice on Dataset Integrity (PARTIAL)", summary)

    def test_alias_deduplication_preserves_all_product_references_in_deterministic_block(self):
        """5. Alias deduplication -> no self-pair, all product references preserved in output."""
        ctx = _make_pipeline_context(
            verified_med_names=["Aspirin", "Acetylsalicylic acid", "Warfarin"]
        )
        ctx["verification"]["medications"][0]["name"] = "Aspirin 81mg"
        ctx["verification"]["medications"][1]["name"] = "Acetylsalicylic acid 325mg"
        ctx["verification"]["medications"][2]["name"] = "Warfarin 5mg"
        ctx = DDICheckingAgent.process(ctx, loader=self.loader)

        # Confirm no self-pair between Aspirin and Acetylsalicylic acid
        pairs = ctx["ddi"]["pairs"]
        for p in pairs:
            self.assertFalse(
                p["drug_a"].lower() in ("aspirin", "acetylsalicylic acid")
                and p["drug_b"].lower() in ("aspirin", "acetylsalicylic acid"),
                "Self-pair between alias and canonical drug must not exist."
            )

        # Confirm source product list preserved in pair
        wf_pair = [p for p in pairs if "Warfarin" in (p["drug_a"], p["drug_b"])][0]
        asp_sources = (
            wf_pair["source_products_a"]
            if "warfarin" not in wf_pair["drug_a"].lower()
            else wf_pair["source_products_b"]
        )
        self.assertIn("Aspirin 81mg", asp_sources)
        self.assertIn("Acetylsalicylic acid 325mg", asp_sources)

        # Confirm deterministic output renders both source products
        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        summary = ctx["reasoning"].get("summary", "")
        self.assertIn("Aspirin 81mg", summary)
        self.assertIn("Acetylsalicylic acid 325mg", summary)

    def test_llm_failure_preserves_all_deterministic_limitations(self):
        """6. LLM failure -> deterministic limitations remain visible in fallback."""
        def failing_llm(*args, **kwargs):
            raise RuntimeError("LLM API service unavailable")

        ctx = _make_pipeline_context(verified_med_names=["Warfarin"])
        mock_mgr = MagicMock()
        # Request history with no trusted authorization -> PRESCRIPTION_ONLY
        ctx = DDICheckingAgent.process(ctx, patient_history_mgr=mock_mgr, loader=self.loader)
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=failing_llm)
        summary = ctx["reasoning"].get("summary", "")
        self.assertIn(_DDI_SECTION_HEADER, summary)
        self.assertIn("PRESCRIPTION_ONLY", summary)
        self.assertIn("Prescription-only DDI coverage (PRESCRIPTION_ONLY)", summary)
        self.assertIn("Coverage Summary", summary)

    def test_router_boundary_propagates_prescription_only_when_history_unauthorized(self):
        """7. Router boundary -> client-supplied patient_name or scope does not unlock history, PRESCRIPTION_ONLY rendered."""
        from input_router import DDICheckingAgentBoundary
        pipeline_ctx = {
            "document_type": "prescription",
            "metadata": {
                "patient_name": "Test Client Patient",
                "authorized_patient_scope": "ForgedScope123",
            },
            "extracted_data": {
                "medications": [{"name": "Warfarin 5mg"}],
            },
            "verification": {
                "medications": [
                    {
                        "name": "Warfarin 5mg",
                        "verified_name": "Warfarin",
                        "identity_verified": True,
                        "verification_status": "verified",
                    }
                ],
            },
            "warnings": [],
            "errors": [],
        }
        mock_mgr = MagicMock()
        with patch("ddi_checker.get_loader", return_value=self.loader):
            ctx = DDICheckingAgentBoundary.check_interactions(
                pipeline_ctx,
                patient_history_mgr=mock_mgr,
            )
        cov = ctx["ddi"]["coverage"]
        self.assertEqual(cov["history_retrieval_status"], "BLOCKED_NO_AUTHORIZATION")
        self.assertEqual(ctx["ddi"]["coverage_completeness"], "PRESCRIPTION_ONLY")
        mock_mgr._get_patient_store.assert_not_called()

        ctx = PrescriptionReasoningAgent.process(ctx, ai_generator_func=None)
        summary = ctx["reasoning"].get("summary", "")
        self.assertIn("PRESCRIPTION_ONLY", summary)
        self.assertIn("Prescription-only DDI coverage (PRESCRIPTION_ONLY)", summary)
        self.assertIn("Patient historical medications could not be verified or retrieved", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)


