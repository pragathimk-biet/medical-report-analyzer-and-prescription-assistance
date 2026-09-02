# Modular Agentic Medical System Architecture

This document describes the refactoring of the Medical Report Analyzer towards a modular, agent-based pipeline architecture.

---

## Step 1: Foundation (Current State)

### Architecture Comparison

#### Current Architecture
```
Patient Upload (PDF / Image / Text)
       │
       ▼
Perception Agent (OCR Extraction)
       │
       ▼
Direct Agent Orchestrator Pipeline
 (Laboratory Evaluation → Patient History → Safety Cross-Check → ML Safety Classifier → Explanation Agent)
```

#### Target Architecture (Modular Step-Based Evolution)
```
 Patient Upload (PDF / Image / Text)
        │
        ▼
   Input Router  ◄── Classifies document_type: 'medical_report' | 'prescription'
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
Report Pipeline         Prescription Pipeline
(Step 2+ Future)           (Step 2+ Future)
  ├── Extraction Agent       ├── Handwriting Classifier
  ├── Verification Agent     ├── Medication Extractor
  ├── ML Safety Classifier   └── Safety Cross-Check
  └── Reasoning Agent
```

> **Note**: Individual pipeline stages (Report Extraction Agent, Report Verification Agent, ML Safety Classifier Agent, Report Reasoning Agent, Prescription Pipeline, Handwriting Classifier, Cross-Visit Correlator) will be implemented iteratively in subsequent steps.

---

## Foundation Core Specifications

### 1. Input Router (`input_router.py`)
Classifies incoming documents into:
```json
{
    "document_type": "medical_report"
}
```
or
```json
{
    "document_type": "prescription"
}
```
or `unsupported` for empty/invalid payloads.

### 2. Common Pipeline Interface (`create_pipeline_context`)
Standardized payload passed between processing stages:
```json
{
    "document_type": "medical_report",
    "raw_input": "...",
    "metadata": {},
    "extracted_data": {},
    "verification": {},
    "safety": {},
    "reasoning": {},
    "warnings": [],
    "errors": []
}
```

### 3. Prepared Agent Boundaries (`input_router.py`)
- `InputRouter`
- `ReportExtractionAgentBoundary` (Stub for Step 2)
- `ReportVerificationAgentBoundary` (Stub)
- `MLSafetyAgentBoundary` (Stub)
- `ReportReasoningAgentBoundary` (Stub)
- `PrescriptionPipelineBoundary` (Stub)
