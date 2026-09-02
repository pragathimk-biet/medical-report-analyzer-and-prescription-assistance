# Medical Report Analyzer & Prescription Assistant

An intelligent, patient-friendly medical report analysis, prescription safety, and longitudinal health monitoring platform built with Python/Flask, RapidOCR, NVIDIA NIM / Ollama AI, and a hybrid Deterministic-First Architecture.

---

## 🌟 Technical Architecture & Novelty Claims

1. **Benchmark-Grounded Fault-Tolerant Clinical Validation Gate (`finding_validator.py`)**
   - Converts raw OCR extraction into a structured **`ValidatedFinding`** Intermediate Representation containing `finding_id`, `test_name`, `normalized_test_name`, `result_value`, `unit`, `reference_text`, `status`, `evidence_text`, `source_line`, `ocr_confidence`, `validation_status`, `rule_id`, `provenance_source`, and `measurement_type` (`DIRECT` vs `DERIVED`).
   - Runs a 7-layer validation gate enforcing analyte-value mapping, unit compatibility, reference range rejection/fallback, header noise filtering, and multi-layer confidence scoring.

2. **Condition-Level Clinical Benchmark Engine (`clinical_benchmarks.py`)**
   - Evaluates multi-analyte condition patterns (`Glucose-related Abnormality Pattern`, `Possible Anemia-related Pattern`, `Possible Kidney-Function Pattern`, `Possible Thyroid-Axis Pattern`, `Serological Reactivity Pattern`).
   - Enforces a **3-Level Disease Interpretation Hierarchy**:
     - *Level 1: No evidence from available report*
     - *Level 2: Possible / Suggestive Finding* (Evidence matches a configured health-condition pattern but does NOT confirm a disease)
     - *Level 3: Diagnosis Explicitly Reported in Source Document* (Source text explicitly writes a formal diagnosis block)
   - Evaluates Widal combined multi-antigen antibody titres and maps findings to appropriate specialist doctor categories (*Diabetologist/Endocrinologist*, *Nephrologist*, *Hematologist*, *Cardiologist*, *Gastroenterologist*, *General Physician*).

3. **Longitudinal Patient History & Multi-Visit Trend Analytics (`patient_history.py`)**
   - Tracks laboratory test values across multiple visits (`PatientHistoryManager`).
   - Computes directional trends (**`INCREASING_TREND`**, **`DECREASING_TREND`**, **`STABLE_TREND`**) and transition patterns (**`NEWLY_ABNORMAL`**, **`PERSISTENTLY_ABNORMAL`**, **`RESOLVED_ABNORMALITY`**).

4. **True Bidirectional Medication / Lab Safety Engine (`patient_history.py`)**
   - **Direction A (`check_prescription_against_past_labs`)**: Evaluates new prescriptions against patient historical lab findings (e.g., prescribing *Spironolactone* when past Potassium was `HIGH` $\rightarrow$ hyperkalemia alert).
   - **Direction B (`check_new_labs_against_active_meds`)**: Evaluates new lab report findings against active patient medications (e.g., new *Serum Creatinine HIGH* while taking active *NSAIDs* $\rightarrow$ renal clearance alert).

5. **Trusted Medication Knowledge Layer (`patient_history.py`)**
   - **Multi-Tier Resolution**:
     1. *Tier 1 (Exact DB Match)*: Known drug lookup in `TRUSTED_MEDICATION_DATABASE`.
     2. *Tier 2 (Pharmacological Suffix Fallback)*: Dynamic pattern matching (`-pril`, `-sartan`, `-olol`, `-dipine`, `-statin`, `-parin`, `-oxacin`, `-mycin`, `-zone`, `-flozin`, `-glutide`).
     3. *Tier 3 (Unclassified)*: Unknown medications return `"Medication could not be confidently classified."` without guessing.

6. **LLM Consistency Validator & Fail-Closed Safety Engine (`app.py`)**
   - Candidate LLM explanations are programmatically audited by `LLMConsistencyValidator` against Rule Engine source-of-truth findings.
   - Detects status overrides, forbidden diagnostic phrases (*"kidney failure"*, *"renal disease"*, *"active typhoid infection"*), or ungrounded claims.
   - Triggers a constrained correction retry, failing closed to a 100% code-generated deterministic fallback if safety rules are violated.

7. **Methodology Novelty Additions (Fig. 1)**:
   - **Model 1 (New)**: Report Reliability Classifier — Scikit-learn Decision Tree trained on real MIMIC-III format lab features (`tabular_ml_engine.py`).
   - **Model 2 (New)**: MobileNetV2 Handwriting Cross-Check via Transfer Learning feature embeddings for handwritten medication visual crops (`handwriting_drug_classifier.py`).
   - **Custom RAG Chatbot (New)**: Structured Patient History Retrieval Chatbot (`/api/patient-chat` endpoint) in `app.py`.
   - **RapidFuzz + RxNorm Drug Verification**: RapidFuzz sequence distance matching and RxNorm trusted vocabulary verification (`prescription_verification_agent.py`).
   - **Image Enhancement Preprocessing**: Grayscale conversion, FastNlMeans denoising, and deskew angle alignment prior to OCR.

---

## 🛠️ Architecture & Technology Stack

- **Backend**: Python 3.11+, Flask Web Framework
- **OCR Engines**: RapidOCR (ONNX Runtime), PyTesseract, Windows Native OCR (WinRT), PyPDF
- **Deterministic Validation & Benchmarks**: `FindingValidator` (`finding_validator.py`), `MedicalRuleEngine` (`rule_engine.py`), `ClinicalBenchmarkEngine` (`clinical_benchmarks.py`), `reference_ranges.json`
- **Longitudinal & Safety Engine**: `PatientHistoryManager` (`patient_history.py`)
- **AI Infrastructure**: NVIDIA NIM API (`meta/llama-3.1-8b-instruct`) with local Ollama fallback (`deepseek-r1:14b`)
- **Frontend**: Vanilla JavaScript (ES6+), HTML5, CSS3, Tailwind CSS, Marked.js, html2pdf.js

---

## 🚀 Installation & Setup

1. **Clone & Virtual Environment**:
   ```bash
   git clone https://github.com/SrujanCA/Medical_Report_Analyzer.git
   cd Medical-report-analyzer-main
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**:
   ```bash
   python app.py
   ```
   Navigate to `http://127.0.0.1:5000`.

---

## 🧪 Automated Test Suite & Independent Benchmark Evaluation

### Final Independent Benchmark Results (50 Cases)
On the 50-case independent synthetic-anonymized benchmark (`data/independent_benchmark/`), the candidate final system achieved:
- **Overall Safety Classification Accuracy**: **64.00%** (32 / 50 cases correct)
- **Macro F1 Score**: **0.6265**
- **Hard-Stop Safety Recall**: **100.00%** (8 / 8 actual hard-stop cases correctly detected)
- **False-Safe Error Rate**: **0.00%** (0 false-safe errors; zero clinical risk)

### Evaluation Metrics Breakdown
| Metric Category | Metric | Score | Note |
| :--- | :--- | :---: | :--- |
| **Safety Governance** | Safety Classification Accuracy | **64.00%** | Independent real-document evaluation |
| | Hard-Stop Recall | **100.00%** | 8 / 8 critical safety cases detected |
| | False-Safe Rate | **0.00%** | 0 / 8 false-safe errors |
| **Report Extraction** | Analyte Name Accuracy | **100.00%** | 37 / 37 analytes matched |
| | Numeric Value Accuracy | **89.19%** | 33 / 37 values matched |
| | Unit Accuracy | **78.38%** | 29 / 37 units matched |
| | Reference Range Accuracy | **78.38%** | 29 / 37 reference ranges matched |
| **Prescription Extraction** | Medication Name Accuracy | **88.89%** | 24 / 27 medications matched |
| | Strength Accuracy | **88.89%** | 24 / 27 strengths matched |
| | Frequency Accuracy | **88.89%** | 24 / 27 frequencies matched |
| | Timing Accuracy | **81.48%** | 22 / 27 timings matched |
| | Duration Accuracy | **88.89%** | 24 / 27 durations matched |

### Running Test Suites (282 / 282 Unit Tests Passing 100%)
```bash
# Run remediation regression test suite
python scratch/test_remediation_regression.py

# Run independent benchmark runner
python scratch/run_independent_benchmark.py

# Run benchmark data & foundation test suites
python scratch/test_independent_benchmark_data.py
python scratch/test_independent_benchmark_foundation.py

# Run ML model evaluation & safety agent suites
python scratch/test_ml_model_evaluation.py
python scratch/test_tabular_ml.py
python scratch/test_ml_safety.py

# Run complete report pipeline test suite
python scratch/test_complete_report_pipeline.py

# Run complete prescription pipeline test suite
python scratch/test_complete_prescription_pipeline.py
```