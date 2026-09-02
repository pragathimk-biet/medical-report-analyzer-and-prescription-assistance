# Agentic AI Methodology & System Architecture

This document details the **Agentic AI Architecture**, **Deterministic-First Validation Gate**, **Longitudinal Patient Analytics**, **Bidirectional Safety Engine**, and **Benchmark-Grounded Reasoning** governing the **Medical Report Analyzer & Prescription Assistant** application.

---

## 🤖 Visual Agentic AI Architecture

The platform operates as a hybrid **Deterministic-First, Multi-Agent Orchestration Pipeline**. Generative AI models are strictly scoped as natural language explanation and translation agents, while clinical status determinations, unit verifications, evidence tracking, medication-lab safety cross-checks, and condition-level pattern matches remain 100% governed by deterministic, testable code engines.

```mermaid
graph TD
    %% User Request Initiator
    USER["User Request / Upload (PDF, JPG, PNG, Text, Prescription)"]

    %% AGENT 1: PERCEPTION & EXTRACTION AGENT
    subgraph AGENT_1["1. PerceptionExtractionAgent"]
        P1{"Detect Input Format"}
        P2["PyPDF Text Extractor Stream Parser"]
        P3["RapidOCR ONNX Runtime Engine (Global Instance)"]
        P4["PyTesseract Engine (System Fallback)"]
        P5["Windows Native OCR (WinRT PowerShell Bridge)"]
    end

    %% AGENT 2: LABORATORY EVALUATION & VALIDATION GATE AGENT
    subgraph AGENT_2["2. LaboratoryEvaluationAgent & Validation Gate"]
        E1["MedicalRuleEngine Parsing & Alias Normalization"]
        E2["FindingValidator: 7-Layer Clinical Validation Gate"]
        E3["Multi-Layer Confidence Scoring (OCR, Extraction, Mapping, Ref, Evidence)"]
        E4["Construct Validated Intermediate Representation (ValidatedFinding)"]
    end

    %% AGENT 3: PATIENT HISTORY & LONGITUDINAL AGENT
    subgraph AGENT_3["3. PatientHistoryAgent"]
        H1["PatientHistoryManager Persistence (patient_history_store.json)"]
        H2["Compute Directional Trends (INCREASING, DECREASING, STABLE)"]
        H3["Compute Abnormality Transitions (NEWLY_ABNORMAL, RESOLVED_ABNORMALITY)"]
    end

    %% AGENT 4 & 5: PRESCRIPTION & BIDIRECTIONAL SAFETY AGENT
    subgraph AGENT_4_5["4 & 5. PrescriptionAgent & SafetyCrossCheckAgent"]
        M1["Trusted Medication Knowledge Layer (Tier 1 DB -> Tier 2 Suffix -> Tier 3 Unclassified)"]
        M2["Direction A: Prescription -> Past Labs (check_prescription_against_past_labs)"]
        M3["Direction B: New Labs -> Active Meds (check_new_labs_against_active_meds)"]
    end

    %% BENCHMARK & CONDITION ENGINE
    subgraph BENCHMARK_ENGINE["ClinicalBenchmarkEngine"]
        B1["Condition-Level Pattern Engine (Glucose, Anemia, Kidney, Thyroid, Liver, Widal)"]
        B2["3-Level Disease Interpretation Hierarchy (Level 1, Level 2, Level 3)"]
        B3["Widal Combined Multi-Antigen Interpretation"]
        B4["Evidence-Based Specialist Doctor Category Mapping"]
    end

    %% AGENT 6: EXPLANATION AGENT
    subgraph AGENT_6["6. ExplanationAgent"]
        X1["Patient-Friendly Prompt Formulator"]
        X2["NVIDIA NIM Cloud API / Local Ollama Failover Engine"]
        X3["Generate Plain-Language Patient Explanation"]
    end

    %% AGENT 7: VALIDATION & SAFETY GUARDRAIL AGENT
    subgraph AGENT_7["7. ValidationGuardrailAgent"]
        G1["LLMConsistencyValidator Audit Engine"]
        G2["Check Status Integrity & Numeric Value Consistency"]
        G3["Enforce Prohibition of Forbidden Diagnostic Terms"]
        G4{"Passed Safety Gate?"}
        G5["Constrained Safety Correction Retry"]
        G6["Safe Code-Generated Deterministic Fallback"]
        G7["Attach Collapsible Technical Evidence Details (<details>)"]
    end

    %% Control Flow Links
    USER --> P1
    P1 -- PDF File --> P2
    P1 -- Image File --> P3
    P3 -- Failure --> P4
    P4 -- Failure --> P5

    P2 --> E1
    P3 --> E1
    P4 --> E1
    P5 --> E1

    E1 --> E2
    E2 --> E3
    E3 --> E4

    E4 --> H1
    H1 --> H2
    H2 --> H3

    E4 --> M1
    M1 --> M2
    M1 --> M3

    E4 --> B1
    B1 --> B2
    B2 --> B3
    B3 --> B4

    E4 --> X1
    M2 --> X1
    M3 --> X1
    H3 --> X1
    B4 --> X1

    X1 --> X2
    X2 --> X3
    X3 --> G1

    G1 --> G2
    G2 --> G3
    G3 --> G4

    G4 -- YES --> G7
    G4 -- NO --> G5
    G5 --> G4
    G5 -- Retry Failed --> G6
    G6 --> G7
```

---

## 🔬 Specialized Executable Agent Pipeline Details

### 1. **`PerceptionExtractionAgent` (Data Perception & OCR Extractor)**
- **Multi-Engine Pipeline**: Prioritizes native PDF stream extraction via `PyPDF`, then `RapidOCR` ONNX runtime engine, falling back to `PyTesseract` or `Windows Native OCR (WinRT)` via PowerShell bridge.
- **Line Metadata Capture**: Captures 1-indexed line numbers (`source_line_number`), raw line snippets (`raw_source_line`), and line-level OCR confidence scores.

### 2. **`LaboratoryEvaluationAgent` & 7-Layer `FindingValidator`**
- **Validated Intermediate Representation (`ValidatedFinding`)**: Converts raw extracted text into structured clinical objects containing `finding_id`, `test_name`, `normalized_test_name`, `result_value`, `result_text`, `unit`, `reference_low`, `reference_high`, `reference_text`, `status`, `evidence_text`, `source_line`, `extraction_confidence`, `validation_status`, `validation_errors`, `source_location`, `rule_id`, `provenance_source`, `provenance_status`, `measurement_type` (`DIRECT` vs `DERIVED`).
- **7-Layer Clinical Validation Gate**:
  1. *Test Name & Analyte Association Validation*: Prevents attaching `Mean Blood Glucose` (e.g. `121.6 mg/dL`) to `HbA1c` (%) or header noise words.
  2. *Unit Compatibility Validation*: Analyte-specific unit checking (`ANALYTE_VALIDATION_REGISTRY`).
  3. *Reference Range Integrity*: Rejects incompatible reference ranges (e.g. neonatal Creatinine ranges attached to Sodium) and falls back to `Configured Default Reference Range`.
  4. *Evidence Link Integrity*: Verifies `raw_source_line` against analyte keywords and filters document header/address noise (`"JANANASHANKARA"`, `"Bypass Road"`).
  5. *Derived Value Detection*: Automatically marks calculated values (e.g. `Mean Blood Glucose (eAG)` derived from `HbA1c`) as `DERIVED`.
  6. *Multi-Layer Confidence Metrics*: `overall_confidence = min(ocr, extraction, mapping, reference, evidence)`.
  7. *Fault-Tolerant Status Assignment*: Assigns `VALIDATED`, `PARTIALLY_VALIDATED`, `AMBIGUOUS`, `UNVERIFIED`, `REVIEW_REQUIRED`.

### 3. **`PatientHistoryAgent` (Longitudinal Trend Analytics)**
- **Multi-Visit Store (`PatientHistoryManager`)**: Stores only validated laboratory findings across visits.
- **Trend Computation**: Computes directional trends (**`INCREASING_TREND`**, **`DECREASING_TREND`**, **`STABLE_TREND`**) and transition patterns (**`NEWLY_ABNORMAL`**, **`PERSISTENTLY_ABNORMAL`**, **`RESOLVED_ABNORMALITY`**).

### 4 & 5. **`PrescriptionAgent` & `SafetyCrossCheckAgent` (Bidirectional Safety Engine)**
- **Trusted Medication Knowledge Layer**:
  - *Tier 1 (Exact DB Match)*: Known drug lookup in `TRUSTED_MEDICATION_DATABASE`.
  - *Tier 2 (Pharmacological Suffix Fallback)*: Dynamic suffix map (`-pril`, `-sartan`, `-olol`, `-dipine`, `-statin`, `-parin`, `-oxacin`, `-mycin`, `-zone`, `-flozin`, `-glutide`).
  - *Tier 3 (Unclassified)*: Returns `"Medication could not be confidently classified."` without guessing.
- **True Bidirectional Medication/Lab Safety Engine**:
  - *Direction A (`check_prescription_against_past_labs`)*: Evaluates new prescriptions against patient historical lab findings (e.g., prescribing *Spironolactone* when past Potassium was `HIGH` $\rightarrow$ hyperkalemia alert).
  - *Direction B (`check_new_labs_against_active_meds`)*: Evaluates new lab report findings against active patient medications (e.g., new *Serum Creatinine HIGH* while taking active *NSAIDs* $\rightarrow$ renal clearance alert).
  - Excludes `AMBIGUOUS`, `UNVERIFIED`, or `REVIEW_REQUIRED` findings from triggering high-confidence warnings.

### 6. **`ClinicalBenchmarkEngine` (Benchmark-Grounded Reasoning)**
- **Condition-Level Pattern Engine**: Evaluates multi-analyte condition patterns (`Glucose-related Abnormality Pattern`, `Possible Anemia-related Pattern`, `Possible Kidney-Function Pattern`, `Possible Thyroid-Axis Pattern`, `Possible Hepatic Transaminase Pattern`, `Serological Reactivity Pattern`).
- **3-Level Disease Interpretation Hierarchy**:
  - *Level 1: No evidence from available report*
  - *Level 2: Possible / Suggestive Finding* (Evidence matches a configured health-condition pattern but does NOT confirm a disease)
  - *Level 3: Diagnosis Explicitly Reported in Source Document* (Source text explicitly states a clinical diagnosis)
- **Widal Combined Interpretation**: Combines Widal antigen titres (`S. Typhi O/H`, `S. Paratyphi AH/BH`) against thresholds, explaining that a reactive titre alone does NOT establish an active typhoid fever diagnosis.
- **Specialist Doctor Category Mapping**: Recommends appropriate doctor categories (e.g., *Diabetologist / Endocrinologist*, *Nephrologist*, *Hematologist*, *Cardiologist*, *Gastroenterologist*, *General Physician / Primary Care Doctor*).

### 7. **`ExplanationAgent` & `ValidationGuardrailAgent` (Safety Guardrails & Presentation)**
- **Patient-Friendly Output Structure**:
  - `## 🩺 [Test Name]` (`Your Result`, `Status` badges ✅ ⚠️ 🔴 🔵 ❓, `What does this mean?`, `Does this suggest a health condition?`, `What should you do?`, `Which doctor should I consult?`)
  - `## 📋 Overall Health Summary` & `## Important Findings` (`🔴 Needs Attention:` vs `✅ Normal:`)
  - `## Recommended Next Step`
- **Collapsible Technical Details**: Appends `<details><summary>🔬 View Technical & Evidence Details</summary> ... </details>` at the bottom so full technical evidence auditability remains accessible.
- **Fail-Closed Safety Engine (`LLMConsistencyValidator`)**: Audits LLM outputs against Rule Engine findings for status overrides, forbidden diagnostic terms (*"kidney failure"*, *"renal disease"*, *"active typhoid infection"*), or ungrounded claims. Executes constrained retry, failing closed to a safe code-generated deterministic fallback if safety rules are violated.

---

## 🧪 Verification & Automated Regression Testing

The methodology is verified against a 3-tier automated test suite:

1. **`scratch/test_novelty_features.py`**: 12 comprehensive unit & safety tests covering all benchmark-grounded fault-tolerance scenarios.
2. **`scratch/test_rule_engine.py`**: Deterministic Rule Engine multi-panel test suite.
3. **`scratch/test_suite.py`**: End-to-end API regression test suite verifying all 7 Flask endpoints (`/upload`, `/upload-prescription`, `/analyze-symptoms`, `/analyze-medicine`, `/translate`, file validation).
