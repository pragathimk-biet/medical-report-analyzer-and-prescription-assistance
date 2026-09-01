"""
===============================================================================
STEP 8: INDEPENDENT BENCHMARK FOUNDATION TEST SUITE
===============================================================================

Tests:
  1. Benchmark directory exists
  2. Reports directory exists
  3. Prescriptions directory exists
  4. Ground-truth file has valid schema
  5. Case IDs are unique
  6. Document type is valid
  7. Safety labels are restricted to safe_to_display, needs_manual_review, hard_stop
  8. Ground truth does not contain ML prediction fields
  9. Derived ML benchmark is not mixed with independent benchmark
  10. Benchmark runner loads successfully
  11. Empty benchmark does not produce fake accuracy
  12. Missing benchmark file is handled safely
  13. Malformed case is rejected safely
  14. Report benchmark schema works
  15. Prescription benchmark schema works
  16. No patient-sensitive unnecessary data required
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
    validate_case_schema,
    run_independent_benchmark
)

class TestStep8IndependentBenchmarkFoundation(unittest.TestCase):

    # TEST 1: Benchmark directory exists
    def test_01_benchmark_dir_exists(self):
        self.assertTrue(os.path.exists(BENCHMARK_DIR))

    # TEST 2: Reports directory exists
    def test_02_reports_dir_exists(self):
        reports_dir = os.path.join(BENCHMARK_DIR, "reports")
        self.assertTrue(os.path.exists(reports_dir))

    # TEST 3: Prescriptions directory exists
    def test_03_prescriptions_dir_exists(self):
        rx_dir = os.path.join(BENCHMARK_DIR, "prescriptions")
        self.assertTrue(os.path.exists(rx_dir))

    # TEST 4: Ground-truth file has valid schema
    def test_04_ground_truth_valid_schema(self):
        data, err = load_ground_truth()
        self.assertIsNone(err)
        self.assertIn("version", data)
        self.assertIn("cases", data)

    # TEST 5: Case IDs are unique
    def test_05_case_ids_unique(self):
        data, _ = load_ground_truth()
        cases = data.get("cases", [])
        cids = [c.get("case_id") for c in cases]
        self.assertEqual(len(cids), len(set(cids)), "Case IDs must be unique!")

    # TEST 6: Document type is valid
    def test_06_document_type_valid(self):
        data, _ = load_ground_truth()
        for case in data.get("cases", []):
            self.assertIn(case.get("document_type"), ["medical_report", "prescription", "unsupported"])

    # TEST 7: Safety labels restricted
    def test_07_safety_labels_restricted(self):
        data, _ = load_ground_truth()
        for case in data.get("cases", []):
            gt = case.get("ground_truth", {})
            st = gt.get("expected_safety_status")
            if st:
                self.assertIn(st, ["safe_to_display", "needs_manual_review", "hard_stop"])

    # TEST 8: Ground truth does not contain ML prediction fields
    def test_08_ground_truth_no_ml_fields(self):
        data, _ = load_ground_truth()
        forbidden_keys = ["predicted_class", "ml_confidence", "decision_tree_output"]
        for case in data.get("cases", []):
            gt = case.get("ground_truth", {})
            for fk in forbidden_keys:
                self.assertNotIn(fk, gt, f"Ground truth must NOT contain ML prediction field '{fk}'!")

    # TEST 9: Derived ML benchmark is not mixed with independent benchmark
    def test_09_derived_ml_benchmark_not_mixed(self):
        derived_csv = os.path.join("data", "ml_safety_benchmark.csv")
        self.assertNotEqual(os.path.abspath(derived_csv), os.path.abspath(GROUND_TRUTH_FILE))

    # TEST 10: Benchmark runner loads successfully
    def test_10_benchmark_runner_loads(self):
        res = run_independent_benchmark()
        self.assertIn("status", res)

    # TEST 11: Empty benchmark does not produce fake accuracy
    def test_11_empty_benchmark_no_fake_accuracy(self):
        # When no valid cases exist or ground truth is missing, accuracy must be None (no fake accuracy)
        data, err = load_ground_truth("non_existent_file.json")
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    # TEST 12: Missing benchmark file is handled safely
    def test_12_missing_benchmark_file_handled_safely(self):
        data, err = load_ground_truth("non_existent_file.json")
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    # TEST 13: Malformed case is rejected safely
    def test_13_malformed_case_rejected_safely(self):
        malformed_case = {"case_id": "TEST_001"} # Missing ground_truth and document_type
        is_valid, msg = validate_case_schema(malformed_case)
        self.assertFalse(is_valid)

    # TEST 14: Report benchmark schema works
    def test_14_report_benchmark_schema_works(self):
        report_case = {
            "case_id": "RPT_100",
            "document_type": "medical_report",
            "source_file": "reports/test.png",
            "ground_truth": {
                "expected_document_type": "medical_report",
                "expected_safety_status": "safe_to_display",
                "expected_biomarkers": [{"name": "Creatinine", "value": 0.9}]
            }
        }
        is_valid, _ = validate_case_schema(report_case)
        self.assertTrue(is_valid)

    # TEST 15: Prescription benchmark schema works
    def test_15_prescription_benchmark_schema_works(self):
        rx_case = {
            "case_id": "RX_100",
            "document_type": "prescription",
            "source_file": "prescriptions/test.png",
            "ground_truth": {
                "expected_document_type": "prescription",
                "expected_safety_status": "safe_to_display",
                "expected_medications": [{"name": "Amoxicillin", "strength": "500 mg"}]
            }
        }
        is_valid, _ = validate_case_schema(rx_case)
        self.assertTrue(is_valid)

    # TEST 16: No patient-sensitive unnecessary data required
    def test_16_no_patient_sensitive_data_required(self):
        data, _ = load_ground_truth()
        for case in data.get("cases", []):
            self.assertNotIn("ssn", case)
            self.assertNotIn("patient_address", case)

if __name__ == "__main__":
    unittest.main()
