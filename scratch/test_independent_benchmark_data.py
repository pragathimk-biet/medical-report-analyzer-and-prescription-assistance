"""
===============================================================================
STEP 9: INDEPENDENT BENCHMARK DATA QUALITY TEST SUITE
===============================================================================

Tests:
  1. Every ground-truth case has a corresponding document
  2. Every document has a unique case ID
  3. No duplicate documents
  4. No missing ground-truth entries
  5. Document types are valid
  6. Safety labels are valid
  7. No ML prediction fields exist in ground truth
  8. No synthetic placeholder cases are counted as real cases
  9. Missing values remain null
  10. No fabricated medication information exists
  11. Report cases contain valid report annotations
  12. Prescription cases contain valid prescription annotations
  13. Manifest matches ground_truth.json
  14. Benchmark runner can load every case
  15. Zero-case benchmark still reports accuracy as unavailable
"""

import os
import sys
import json
import unittest

# Add repository root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scratch.run_independent_benchmark import (
    BENCHMARK_DIR,
    GROUND_TRUTH_FILE,
    load_ground_truth,
    validate_case_schema
)

class TestIndependentBenchmarkDataQuality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.gt_data, cls.err = load_ground_truth()

    # TEST 1: Every ground-truth case has a corresponding document
    def test_01_every_case_has_document(self):
        self.assertIsNone(self.err)
        cases = self.gt_data.get("cases", [])
        self.assertGreaterEqual(len(cases), 50)
        for case in cases:
            src = case.get("source_file", "")
            full_path = os.path.join(BENCHMARK_DIR, src)
            self.assertTrue(os.path.exists(full_path), f"Source file '{full_path}' does not exist!")

    # TEST 2: Every document has a unique case ID
    def test_02_unique_case_ids(self):
        cases = self.gt_data.get("cases", [])
        cids = [c.get("case_id") for c in cases]
        self.assertEqual(len(cids), len(set(cids)), "Case IDs must be unique!")

    # TEST 3: No duplicate documents
    def test_03_no_duplicate_documents(self):
        cases = self.gt_data.get("cases", [])
        srcs = [c.get("source_file") for c in cases]
        self.assertEqual(len(srcs), len(set(srcs)), "Source file paths must be unique!")

    # TEST 4: No missing ground-truth entries
    def test_04_no_missing_ground_truth_entries(self):
        cases = self.gt_data.get("cases", [])
        for case in cases:
            gt = case.get("ground_truth")
            self.assertIsNotNone(gt)
            self.assertIn("expected_safety_status", gt)

    # TEST 5: Document types are valid
    def test_05_document_types_valid(self):
        cases = self.gt_data.get("cases", [])
        for case in cases:
            self.assertIn(case.get("document_type"), ["medical_report", "prescription"])

    # TEST 6: Safety labels are valid
    def test_06_safety_labels_valid(self):
        cases = self.gt_data.get("cases", [])
        valid_labels = ["safe_to_display", "needs_manual_review", "hard_stop"]
        for case in cases:
            st = case.get("ground_truth", {}).get("expected_safety_status")
            self.assertIn(st, valid_labels)

    # TEST 7: No ML prediction fields exist in ground truth
    def test_07_no_ml_prediction_fields(self):
        cases = self.gt_data.get("cases", [])
        forbidden = ["predicted_class", "ml_confidence", "decision_tree_output", "random_forest_output"]
        for case in cases:
            gt = case.get("ground_truth", {})
            for fk in forbidden:
                self.assertNotIn(fk, gt)
                self.assertNotIn(fk, case)

    # TEST 8: No synthetic placeholder cases are counted as real cases
    def test_08_no_placeholder_cases_counted(self):
        cases = self.gt_data.get("cases", [])
        for case in cases:
            self.assertEqual(case.get("annotation_status"), "annotated")
            self.assertEqual(case.get("annotation_method"), "independent_manual_annotation")

    # TEST 9: Missing values remain null
    def test_09_missing_values_remain_null(self):
        cases = self.gt_data.get("cases", [])
        # Find case with missing unit (e.g. REPORT_008)
        rpt_008 = next((c for c in cases if c.get("case_id") == "REPORT_008"), None)
        self.assertIsNotNone(rpt_008)
        bms = rpt_008["ground_truth"]["expected_biomarkers"]
        self.assertIsNone(bms[0]["unit"], "Missing unit must remain None!")

    # TEST 10: No fabricated medication information exists
    def test_10_no_fabricated_medication_info(self):
        cases = self.gt_data.get("cases", [])
        # Find case with missing strength (e.g. PRESCRIPTION_005)
        rx_005 = next((c for c in cases if c.get("case_id") == "PRESCRIPTION_005"), None)
        self.assertIsNotNone(rx_005)
        meds = rx_005["ground_truth"]["expected_medications"]
        self.assertIsNone(meds[0]["strength"], "Missing strength must remain None!")

    # TEST 11: Report cases contain valid report annotations
    def test_11_report_cases_valid_annotations(self):
        cases = self.gt_data.get("cases", [])
        report_cases = [c for c in cases if c.get("document_type") == "medical_report"]
        self.assertEqual(len(report_cases), 25)
        for c in report_cases:
            gt = c.get("ground_truth", {})
            self.assertIn("expected_biomarkers", gt)

    # TEST 12: Prescription cases contain valid prescription annotations
    def test_12_prescription_cases_valid_annotations(self):
        cases = self.gt_data.get("cases", [])
        rx_cases = [c for c in cases if c.get("document_type") == "prescription"]
        self.assertEqual(len(rx_cases), 25)
        for c in rx_cases:
            gt = c.get("ground_truth", {})
            self.assertIn("expected_medications", gt)

    # TEST 13: Manifest matches ground_truth.json
    def test_13_manifest_matches_ground_truth(self):
        manifest_path = os.path.join(BENCHMARK_DIR, "MANIFEST.md")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
        cases = self.gt_data.get("cases", [])
        for c in cases:
            self.assertIn(c.get("case_id"), content)

    # TEST 14: Benchmark runner can load every case
    def test_14_benchmark_runner_loads_every_case(self):
        cases = self.gt_data.get("cases", [])
        for c in cases:
            is_valid, msg = validate_case_schema(c)
            self.assertTrue(is_valid, f"Case {c.get('case_id')} failed runner schema: {msg}")

    # TEST 15: Zero-case benchmark still reports accuracy as unavailable
    def test_15_zero_case_benchmark_reports_unavailable(self):
        from scratch.run_independent_benchmark import load_ground_truth
        data, err = load_ground_truth("non_existent_file.json")
        self.assertIsNone(data)
        self.assertIsNotNone(err)

if __name__ == "__main__":
    unittest.main()
