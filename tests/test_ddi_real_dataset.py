"""
===============================================================================
REAL DATASET INTEGRATION TEST SUITE (DDInter 2.0)
===============================================================================

This test module executes integration checks exclusively against the real
downloaded DDInter 2.0 dataset files (ddinter_downloads_code_*.csv).

DISTINCTION FROM UNIT TESTS:
- tests/test_ddi_checker.py contains fixture-based unit tests using synthetic
  in-memory CSV data to test internal logic and edge cases in isolation.
- tests/test_ddi_real_dataset.py contains integration tests that require the
  actual downloaded DDInter 2.0 dataset files in the data directory.

SKIP BEHAVIOR:
If real dataset files are absent, all tests in this module skip with an
explicit, informative skip reason.
"""

import glob
import hashlib
import json
import os
import sys
import unittest

# Ensure project root is on Python module search path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ddi_checker import (
    DDICheckingAgent,
    DDInterLoader,
    DDIPairChecker,
    AUTHORITATIVE_IDENTITY_MAPPINGS,
    STATUS_INTERACTION_FOUND,
    STATUS_NO_RECORD_FOUND,
    STATUS_RESOURCE_UNAVAILABLE,
    STATUS_UNRESOLVED_MEDICATION,
)
from prescription_reasoning_agent import (
    PrescriptionReasoningAgent,
    _build_ddi_deterministic_block,
    _validate_llm_output_against_ddi,
)

# Detect presence of real DDInter CSV files
REAL_DATA_DIR = os.getenv(
    "DDI_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
)
REAL_CSV_FILES = sorted(glob.glob(os.path.join(REAL_DATA_DIR, "ddinter_downloads_code_*.csv")))
HAS_REAL_DATASET = len(REAL_CSV_FILES) > 0
REAL_DATASET_SKIP_REASON = (
    f"Real DDInter dataset files (ddinter_downloads_code_*.csv) are absent in '{REAL_DATA_DIR}'. "
    f"Download files from https://ddinter2.scbdd.com/download/ to run real integration tests."
)


def skip_unless_real_dataset(test_func):
    """Decorator to skip test when real dataset files are absent."""
    return unittest.skipUnless(HAS_REAL_DATASET, REAL_DATASET_SKIP_REASON)(test_func)


# Shared loader instance for real tests (loaded once if available)
_shared_real_loader = None


def get_shared_real_loader():
    global _shared_real_loader
    if _shared_real_loader is None and HAS_REAL_DATASET:
        _shared_real_loader = DDInterLoader(data_dir=REAL_DATA_DIR)
    return _shared_real_loader


@skip_unless_real_dataset
class TestDDInterRealDatasetManifest(unittest.TestCase):
    """Verifies the real dataset files on disk match the dataset manifest."""

    def setUp(self):
        self.manifest_path = os.path.join(REAL_DATA_DIR, "ddinter_manifest.json")

    def test_manifest_file_exists(self):
        self.assertTrue(
            os.path.isfile(self.manifest_path),
            f"Expected dataset manifest at {self.manifest_path}"
        )

    def test_manifest_checksums_match_disk_files(self):
        with open(self.manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)

        file_manifest = manifest.get("files", {})
        self.assertGreaterEqual(len(file_manifest), 8)

        for filename, expected_meta in file_manifest.items():
            filepath = os.path.join(REAL_DATA_DIR, filename)
            self.assertTrue(os.path.isfile(filepath), f"File {filename} missing on disk.")

            # Verify size
            disk_size = os.path.getsize(filepath)
            self.assertEqual(
                disk_size, expected_meta["size_bytes"],
                f"File size mismatch for {filename}: expected {expected_meta['size_bytes']}, got {disk_size}"
            )

            # Verify SHA256 checksum
            sha = hashlib.sha256()
            with open(filepath, "rb") as fh:
                while chunk := fh.read(65536):
                    sha.update(chunk)
            computed_hash = sha.hexdigest()
            self.assertEqual(
                computed_hash, expected_meta["sha256"],
                f"SHA256 checksum mismatch for {filename}."
            )

    def test_manifest_measured_statistics(self):
        with open(self.manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)

        stats = manifest.get("measured_import_statistics", {})
        self.assertEqual(stats.get("file_count"), 8)
        self.assertEqual(stats.get("total_csv_rows"), 222383)
        self.assertEqual(stats.get("unique_unordered_pairs"), 160235)
        self.assertEqual(stats.get("unique_drug_names_exact"), 1939)

        # Raw rows distribution (denominator 222,383)
        raw_dist = stats.get("severity_distribution_raw_rows", {})
        self.assertEqual(raw_dist.get("denominator"), 222383)
        self.assertTrue(raw_dist.get("sums_to_denominator"))
        raw_counts = raw_dist.get("counts", {})
        self.assertEqual(sum(raw_counts.values()), 222383)
        self.assertEqual(raw_counts.get("Moderate"), 130367)
        self.assertEqual(raw_counts.get("Major"), 33896)
        self.assertEqual(raw_counts.get("Minor"), 10938)
        self.assertEqual(raw_counts.get("Unknown"), 47182)
        # Check percentage labels mention raw rows denominator
        self.assertIn("222,383 raw rows", raw_dist["percentages"]["Unknown"]["formatted"])

        # Unique pairs distribution (denominator 160,235)
        pair_dist = stats.get("severity_distribution_unique_pairs", {})
        self.assertEqual(pair_dist.get("denominator"), 160235)
        self.assertTrue(pair_dist.get("sums_to_denominator"))
        pair_counts = pair_dist.get("counts", {})
        self.assertEqual(sum(pair_counts.values()), 160235)
        self.assertEqual(pair_counts.get("Moderate"), 96675)
        self.assertEqual(pair_counts.get("Major"), 26914)
        self.assertEqual(pair_counts.get("Minor"), 6833)
        self.assertEqual(pair_counts.get("Unknown"), 29813)
        # Check percentage labels mention unique pairs denominator
        self.assertIn("160,235 unique pairs", pair_dist["percentages"]["Unknown"]["formatted"])


@skip_unless_real_dataset
class TestDDInterRealDatasetLoader(unittest.TestCase):
    """Verifies real DDInterLoader loading, pair indexing, and diagnostics."""

    @classmethod
    def setUpClass(cls):
        cls.loader = get_shared_real_loader()

    def test_loader_availability(self):
        self.assertTrue(self.loader.is_available)

    def test_schema_info_measured_counts(self):
        info = self.loader.get_schema_info()
        self.assertTrue(info["dataset_available"])
        self.assertEqual(info["total_pairs_loaded"], 160235)
        self.assertEqual(info["known_drug_count"], 1939)
        self.assertEqual(info["malformed_rows"], 0)
        self.assertEqual(info["missing_columns_detected"], [])
        self.assertTrue(info["manifest_available"])


@skip_unless_real_dataset
class TestAspirinParacetamolRealMapping(unittest.TestCase):
    """
    Verifies Aspirin and Paracetamol naming resolution, authoritative vocabulary
    synonym verification, DDInter record mapping, and provenance storage.
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = get_shared_real_loader()

    def test_aspirin_identity_resolution_and_provenance(self):
        identity = self.loader.resolve_drug_identity("Aspirin")
        self.assertIsNotNone(identity)
        self.assertEqual(identity["canonical_name"], "Acetylsalicylic acid")
        self.assertEqual(identity["canonical_name_lower"], "acetylsalicylic acid")
        self.assertEqual(identity["ddinter_id"], "DDInter20")

        # Verify authoritative provenance metadata
        prov = identity.get("provenance", {})
        self.assertIn("RxNorm", prov.get("source_vocabulary", ""))
        self.assertEqual(prov.get("rxnorm_rxcui"), "1191")
        self.assertEqual(prov.get("who_atc"), "N02BA01")
        self.assertEqual(prov.get("mesh_id"), "D001241")
        self.assertEqual(prov.get("match_method"), "curated_authoritative_synonym")

    def test_paracetamol_identity_resolution_and_provenance(self):
        identity = self.loader.resolve_drug_identity("Paracetamol")
        self.assertIsNotNone(identity)
        self.assertEqual(identity["canonical_name"], "Acetaminophen")
        self.assertEqual(identity["canonical_name_lower"], "acetaminophen")
        self.assertEqual(identity["ddinter_id"], "DDInter14")

        # Verify authoritative provenance metadata
        prov = identity.get("provenance", {})
        self.assertIn("WHO INN", prov.get("source_vocabulary", ""))
        self.assertEqual(prov.get("who_inn"), "Paracetamol")
        self.assertEqual(prov.get("rxnorm_rxcui"), "161")
        self.assertEqual(prov.get("who_atc"), "N02BE01")
        self.assertEqual(prov.get("match_method"), "curated_authoritative_synonym")

    def test_paracetamol_compound_string_resolution(self):
        identity = self.loader.resolve_drug_identity("Paracetamol (Acetaminophen)")
        self.assertIsNotNone(identity)
        self.assertEqual(identity["canonical_name"], "Acetaminophen")
        self.assertEqual(identity["ddinter_id"], "DDInter14")

    def test_no_unrestricted_fuzzy_matching(self):
        """Typo variants must stay unresolved -- no fuzzy guessing."""
        self.assertIsNone(self.loader.resolve_drug_identity("Aspiring"))
        self.assertIsNone(self.loader.resolve_drug_identity("Paracetamolo"))
        self.assertIsNone(self.loader.resolve_drug_identity("Warfarinn"))

    def test_aspirin_paracetamol_real_pair_lookup(self):
        """
        Aspirin + Paracetamol in DDInter 2.0 maps to DDInter14 ↔ DDInter20.
        Dataset records show Level: Unknown.
        """
        status, records = self.loader.lookup_pair("Aspirin", "Paracetamol")
        self.assertEqual(status, STATUS_INTERACTION_FOUND)
        self.assertGreaterEqual(len(records), 1)

        # Confirm exact IDs and names in matched records
        record = records[0]
        ddinter_ids = {record["DDInterID_A"], record["DDInterID_B"]}
        drug_names = {record["Drug_A"], record["Drug_B"]}
        self.assertEqual(ddinter_ids, {"DDInter14", "DDInter20"})
        self.assertEqual(drug_names, {"Acetaminophen", "Acetylsalicylic acid"})

        # Preserved verbatim Level
        self.assertEqual(record["Level"], "Unknown")


@skip_unless_real_dataset
class TestUnknownSeverityPreservation(unittest.TestCase):
    """
    Verifies that Level: Unknown is preserved verbatim and NEVER interpreted
    as Minor, harmless, or safe.
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = get_shared_real_loader()
        cls.checker = DDIPairChecker(loader=cls.loader)

    def test_unknown_severity_note_in_pair_check(self):
        results = self.checker.check_ingredient_pairs(["Aspirin", "Paracetamol"])
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["status"], STATUS_INTERACTION_FOUND)
        self.assertEqual(res["level"], "Unknown")

        # Note must explicitly warn not to assume Minor, harmless, or safe
        note = res["note"]
        self.assertIn("Unknown", note)
        self.assertIn("Do NOT interpret Unknown as Minor, harmless, or safe", note)

        # Provenance must be stored on the pair
        self.assertEqual(res["canonical_a"], "Acetylsalicylic acid")
        self.assertEqual(res["canonical_b"], "Acetaminophen")
        self.assertEqual(res["ddinter_id_a"], "DDInter20")
        self.assertEqual(res["ddinter_id_b"], "DDInter14")
        self.assertIsNotNone(res["provenance_a"])
        self.assertIsNotNone(res["provenance_b"])

    def test_unknown_severity_in_deterministic_block(self):
        results = self.checker.check_ingredient_pairs(["Aspirin", "Paracetamol"])
        ddi = {
            "overall_status": "checked",
            "execution_completion": "COMPLETED",
            "coverage_completeness": "FULL",
            "coverage": {
                "dataset_available": True,
                "submitted_medications": 2,
                "checked_medications": 2,
                "total_prescription_meds": 2,
                "verified_meds": 2,
                "unresolved_ingredients": [],
                "historical_active_meds": 0,
                "total_ingredients_checked": 2,
                "total_pairs_checked": 1,
            },
            "pairs": results,
            "interactions_found": results,
            "warnings": [],
        }
        block = _build_ddi_deterministic_block(ddi)

        # Must show Level verbatim
        self.assertIn("`Unknown`", block)
        # Must contain explicit warning against interpreting Unknown as Minor or safe
        self.assertIn("must NOT be interpreted as Minor, harmless, or safe", block)

    def test_llm_minimization_of_unknown_rejected(self):
        ddi = {
            "overall_status": "checked",
            "interactions_found": [{"level": "Unknown"}],
        }
        # Attempt to claim unknown is minor
        bad_text = "The interaction has unknown severity which is minor and harmless to take."
        valid, violations = _validate_llm_output_against_ddi(bad_text, ddi)
        self.assertFalse(valid)
        self.assertTrue(any("Unknown" in v for v in violations))


@skip_unless_real_dataset
class TestCoverageReportingWithExclusions(unittest.TestCase):
    """
    Verifies overall coverage reporting when medications are excluded.
    Specifically tests the 3-medication example with FantasyDrug excluded:
    - Submitted medications: 3
    - Checked medications: 2
    - Coverage: PARTIAL
    - Excluded medication and reason: displayed explicitly
    - Separate fields for execution completion and coverage completeness
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = get_shared_real_loader()

    def test_three_medication_example_with_fantasydrug_excluded(self):
        pipeline_context = {
            "verification": {
                "overall_status": "verified",
                "medications": [
                    {
                        "name": "Warfarin",
                        "verified_name": "Warfarin",
                        "identity_verified": True,
                        "verification_status": "verified",
                    },
                    {
                        "name": "Aspirin",
                        "verified_name": "Aspirin",
                        "identity_verified": True,
                        "verification_status": "verified",
                    },
                    {
                        "name": "FantasyDrug",
                        "verified_name": None,
                        "identity_verified": False,
                        "verification_status": "unverified",
                    },
                ],
            },
            "metadata": {"patient_name": "Test Patient Real"},
        }

        ctx = DDICheckingAgent.process(pipeline_context, loader=self.loader)
        ddi = ctx["ddi"]

        # Execution completion vs Coverage completeness separate fields
        self.assertEqual(ddi["execution_completion"], "COMPLETED")
        self.assertEqual(ddi["coverage_completeness"], "PARTIAL")
        self.assertEqual(ddi["overall_status"], "partial")

        cov = ddi["coverage"]
        self.assertEqual(cov["submitted_medications"], 3)
        self.assertEqual(cov["checked_medications"], 2)
        self.assertEqual(cov["coverage_completeness"], "PARTIAL")
        self.assertEqual(cov["coverage"], "PARTIAL")

        # Excluded medication and reason
        excluded = cov["excluded_medications"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["name"], "FantasyDrug")
        self.assertEqual(excluded[0]["reason"], "identity_unverified")
        self.assertIn("not verified", excluded[0]["details"])

        # Remaining pair (Warfarin + Aspirin) was checked in real dataset
        self.assertEqual(len(ddi["pairs"]), 1)
        self.assertEqual(ddi["pairs"][0]["status"], STATUS_INTERACTION_FOUND)
        self.assertEqual(ddi["pairs"][0]["level"], "Major")

        # Verify deterministic block display
        block = _build_ddi_deterministic_block(ddi)
        self.assertIn("Submitted medications | 3", block)
        self.assertIn("Checked medications | 2", block)
        self.assertIn("Coverage completeness | PARTIAL", block)
        self.assertIn("Execution status | COMPLETED", block)
        self.assertIn("#### Excluded Medications & Reasons", block)
        self.assertIn("`FantasyDrug`", block)
        self.assertIn("identity_unverified", block)
        self.assertIn("Partial DDI coverage (PARTIAL)", block)


if __name__ == "__main__":
    unittest.main()
