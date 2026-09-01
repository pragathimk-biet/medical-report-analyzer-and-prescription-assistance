import os
import sys
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rule_engine import MedicalRuleEngine
from patient_history import PatientHistoryManager
from finding_validator import FindingValidator, ValidatedFinding
from clinical_benchmarks import ClinicalBenchmarkEngine
from app import LLMConsistencyValidator, ValidationGuardrailAgent, generate_safe_deterministic_fallback

class TestBenchmarkGroundedReasoning(unittest.TestCase):
    def setUp(self):
        self.rule_engine = MedicalRuleEngine()
        self.patient_history = PatientHistoryManager(storage_file="scratch_test_patient_history.json")
        self.patient_history.clear()

    def tearDown(self):
        if os.path.exists("scratch_test_patient_history.json"):
            try:
                os.remove("scratch_test_patient_history.json")
            except Exception:
                pass

    # TEST 1: Normal report
    def test_01_completely_normal_report(self):
        report_text = "Fasting Glucose 90.0 mg/dL\nHemoglobin 14.5 g/dL\nSodium 140.0 mmol/L\nPotassium 4.2 mmol/L"
        results = self.rule_engine.parse_and_evaluate(report_text)
        conditions = ClinicalBenchmarkEngine.evaluate_conditions(results, report_text)
        
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r["status"] == "NORMAL" for r in results))
        self.assertEqual(len(conditions), 0, "Normal report must NOT trigger health-condition patterns.")

    # TEST 2: Single abnormal laboratory result
    def test_02_single_abnormal_result(self):
        report_text = "Fasting Glucose 110.0 mg/dL\nHemoglobin 14.5 g/dL"
        results = self.rule_engine.parse_and_evaluate(report_text)
        conditions = ClinicalBenchmarkEngine.evaluate_conditions(results, report_text)

        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0]["condition_id"], "COND_DIABETES_GLUCOSE_001")
        self.assertEqual(conditions[0]["interpretation_level"], "Level 2: Possible / Suggestive Finding")

    # TEST 3: Multiple abnormal results suggesting one condition
    def test_03_multiple_findings_suggesting_one_condition(self):
        report_text = "Hemoglobin 10.2 g/dL\nHematocrit 31.0 %\nMCV 72.0 fL"
        results = self.rule_engine.parse_and_evaluate(report_text)
        conditions = ClinicalBenchmarkEngine.evaluate_conditions(results, report_text)

        self.assertTrue(len(conditions) >= 1)
        anemia_cond = next(c for c in conditions if c["condition_id"] == "COND_ANEMIA_001")
        self.assertTrue(len(anemia_cond["matching_findings"]) >= 2)

    # TEST 4: Widal report combined interpretation
    def test_04_widal_combined_interpretation(self):
        report_text = "Salmonella Typhi O : 1:40\nSalmonella Typhi H : 1:40\nSalmonella Paratyphi AH : 1:20\nSalmonella Paratyphi BH : 1:160"
        results = self.rule_engine.parse_and_evaluate(report_text)
        widal_combined = ClinicalBenchmarkEngine.evaluate_widal_combined(results)

        self.assertEqual(widal_combined["widal_status"], "REACTIVE_TITRE")
        self.assertIn("1 antibody titre(s) (Salmonella Paratyphi BH) exceeded", widal_combined["summary"])
        self.assertIn("does NOT confirm an active typhoid infection", widal_combined["interpretation"])

    # TEST 5: HbA1c + Mean Blood Glucose -> Remain separate, no false disease trigger on derived MBG alone
    def test_05_hba1c_and_mbg_separate(self):
        report_text = "HbA1c: 6.2 %\nMean Blood Glucose (eAG): 121.6 mg/dL"
        results = self.rule_engine.parse_and_evaluate(report_text)
        
        hba1c_res = next(r for r in results if r["normalized_test_name"] == "hba1c")
        mbg_res = next(r for r in results if r["normalized_test_name"] == "mean_blood_glucose")

        self.assertEqual(hba1c_res["measurement_type"], "DIRECT")
        self.assertEqual(mbg_res["measurement_type"], "DERIVED")

    # TEST 6: Missing numerical value
    def test_06_missing_value_handled_safely(self):
        report_text = "HbA1c: missing_value\nPotassium 4.0 mmol/l"
        results = self.rule_engine.parse_and_evaluate(report_text)
        
        potassium_res = next(r for r in results if r["normalized_test_name"] == "potassium")
        self.assertEqual(potassium_res["status"], "NORMAL")
        self.assertFalse(any(r["normalized_test_name"] == "hba1c" and r["result_value"] is not None for r in results))

    # TEST 7: Incorrect unit -> Incompatible unit flagged as REVIEW_REQUIRED
    def test_07_incorrect_unit_flagged(self):
        candidate = {
            "finding_id": "LAB-001", "parameter": "HbA1c", "key": "hba1c",
            "value": 121.6, "unit": "mg/dL", "status": "HIGH",
            "rule_id": "RULE_001", "range_description": "Standard", "range_source": "DEFAULT_JSON",
            "provenance_source": "Unavailable", "provenance_status": "UNAVAILABLE",
            "source_line_number": 1, "raw_source_line": "HbA1c 121.6 mg/dL"
        }
        vf = FindingValidator.validate_candidate_finding(candidate, raw_report_text="HbA1c 121.6 mg/dL")
        
        self.assertEqual(vf.validation_status, "REVIEW_REQUIRED")
        self.assertTrue(any("Incompatible unit" in err for err in vf.validation_errors))

    # TEST 8: Incompatible reference range -> Rejected & switched to default
    def test_08_incompatible_reference_range(self):
        report_text = "Sodium 140.0 mmol/L (Ref: 0.26 - 1.01 mg/dL)"
        results = self.rule_engine.parse_and_evaluate(report_text)
        
        sodium_res = results[0]
        self.assertEqual(sodium_res["status"], "NORMAL")
        self.assertEqual(sodium_res["reference_status"], "NOT_AVAILABLE")

    # TEST 9: Status NORMAL + LLM says HIGH -> Guardrail rejects contradiction
    def test_09_llm_contradiction_rejected(self):
        eval_results = [{
            "finding_id": "LAB-001", "test_name": "Potassium", "parameter": "Potassium",
            "normalized_test_name": "potassium", "result_value": 4.0, "value": 4.0,
            "unit": "mmol/L", "status": "NORMAL", "range_description": "3.5 - 5.2 mmol/L",
            "validation_status": "VALIDATED"
        }]

        simulated_contradictory_llm = """# Medical Report Analysis
## 🩺 Potassium
### Status
🔴 High
- **What does this mean?** Your potassium level is higher than normal range."""

        is_valid, violations = LLMConsistencyValidator.validate(simulated_contradictory_llm, eval_results)
        self.assertFalse(is_valid)

        safe_output = ValidationGuardrailAgent.validate_and_enforce(simulated_contradictory_llm, eval_results)
        self.assertNotIn("🔴 High", safe_output)

    # TEST 10: Previous abnormal + current normal -> Resolved trend
    def test_10_historical_trend_resolved(self):
        v1_eval = [{"test_name": "Potassium", "parameter": "Potassium", "normalized_test_name": "potassium", "key": "potassium", "result_value": 5.6, "value": 5.6, "unit": "mmol/L", "status": "HIGH", "validation_status": "VALIDATED"}]
        self.patient_history.add_lab_results(v1_eval, visit_id="VISIT-001")

        v2_eval = [{"test_name": "Potassium", "parameter": "Potassium", "normalized_test_name": "potassium", "key": "potassium", "result_value": 4.2, "value": 4.2, "unit": "mmol/L", "status": "NORMAL", "validation_status": "VALIDATED"}]
        trends = self.patient_history.analyze_parameter_trends(v2_eval)

        self.assertEqual(trends[0]["abnormality_pattern"], "RESOLVED_ABNORMALITY")

    # TEST 11: Explicit diagnosis written in source report -> Level 3 Diagnosis Explicitly Reported
    def test_11_explicit_diagnosis_reported(self):
        report_text = "Patient Name: Dummy\nClinical Diagnosis: Type 2 Diabetes Mellitus\nHbA1c: 7.2 %"
        results = self.rule_engine.parse_and_evaluate(report_text)
        conditions = ClinicalBenchmarkEngine.evaluate_conditions(results, report_text)

        self.assertTrue(len(conditions) > 0)
        self.assertEqual(conditions[0]["interpretation_level"], "Level 3: Diagnosis Explicitly Reported in Source Document")
        self.assertIn("Type 2 Diabetes Mellitus", conditions[0]["level_explanation"])

    # TEST 12: Specialist Recommendation Mapping
    def test_12_specialist_recommendation_mapping(self):
        report_text = "Serum Creatinine 1.85 mg/dL\nUrea 58.0 mg/dL"
        results = self.rule_engine.parse_and_evaluate(report_text)
        conditions = ClinicalBenchmarkEngine.evaluate_conditions(results, report_text)

        self.assertTrue(len(conditions) > 0)
        self.assertEqual(conditions[0]["recommended_specialist"], "Nephrologist")

    # TEST 13: Multi-Patient Database & Two-Way Medication–Lab Safety Checking
    def test_13_multi_patient_two_way_safety(self):
        # Patient 1: Alice Smith (Past High Potassium)
        alice_labs = [{"test_name": "Potassium", "parameter": "Potassium", "normalized_test_name": "potassium", "key": "potassium", "result_value": 5.6, "value": 5.6, "unit": "mmol/L", "status": "HIGH", "validation_status": "VALIDATED"}]
        self.patient_history.add_lab_results(alice_labs, patient_name="Alice Smith")

        # Direction 1: New Prescription -> Past Labs (Alice gets Spironolactone)
        dir_a_alerts = self.patient_history.check_prescription_against_past_labs("Spironolactone", patient_name="Alice Smith")
        self.assertTrue(len(dir_a_alerts) > 0)
        self.assertIn("Direction A", dir_a_alerts[0]["direction"])
        self.assertEqual(dir_a_alerts[0]["matched_lab"], "Potassium")

        # Patient 2: Bob Jones (Active Ibuprofen)
        self.patient_history.add_active_medication("Ibuprofen", dosage="400 mg", patient_name="Bob Jones")

        # Direction 2: New Lab Result -> Active Meds (Bob gets Serum Creatinine HIGH)
        bob_new_labs = [{"test_name": "Serum Creatinine", "parameter": "Creatinine", "normalized_test_name": "creatinine", "key": "creatinine", "result_value": 1.9, "value": 1.9, "unit": "mg/dL", "status": "HIGH", "validation_status": "VALIDATED"}]
        dir_b_alerts = self.patient_history.check_new_labs_against_active_meds(bob_new_labs, patient_name="Bob Jones")
        self.assertTrue(len(dir_b_alerts) > 0)
        self.assertIn("Direction B", dir_b_alerts[0]["direction"])
        self.assertEqual(dir_b_alerts[0]["matched_drug"], "Ibuprofen")

        # Verify Patients List
        patients = self.patient_history.list_all_patients()
        patient_names = [p["patient_name"] for p in patients]
        self.assertIn("Alice Smith", patient_names)
        self.assertIn("Bob Jones", patient_names)

if __name__ == "__main__":
    unittest.main()
