# Agentic AI Methodology & System Architecture

This document details the **Agentic AI Architecture** governing the **Medical Report Analyzer** application, highlighting autonomous decision nodes, tool selection mechanisms, multi-LLM orchestration, and task decomposition sub-agents.

---

## 🤖 Visual Agentic AI Architecture Diagram

![Agentic AI System Architecture & Methodology](C:/Users/pruth/.gemini/antigravity/brain/0831d9a9-d9cb-4550-b4c7-f79bb41ea8c5/agentic_ai_methodology_diagram_1786537669394.jpg)

---

## 📊 Agentic Decision & Control Flowchart (Mermaid)

```mermaid
graph TD
    %% User Request Initiator
    USER["User Request / Data Upload (PDF, JPG, Text, Symptoms)"]

    %% PERCEPTION AGENT
    subgraph PERCEPTION_AGENT["Perception Agent (Data Extraction & Validation)"]
        P1{"Detect Input Format"}
        P2["Invoke PyPDF Text Extractor"]
        P3{"Check PyTesseract Binary"}
        P4["Execute PyTesseract Engine"]
        P5["Autonomous Failover: WinRT Windows Native OCR"]
        P6{"Validation Agent: Is Extracted Text Valid?"}
        P7["Return Extraction Error Guard (Reject Prompt Injection/Failures)"]
    end

    %% REASONING AGENT
    subgraph REASONING_AGENT["Multi-Provider Reasoning Agent (Decision Engine Core)"]
        R1{"Check NVIDIA API Key in .env"}
        R2["Route to NVIDIA Cloud API (Nemotron Super 49B)"]
        R3{"Query Local Ollama API (/api/tags)"}
        R4["Autonomous Model Discovery & Selection (DeepSeek-R1 / Llama3)"]
        R5["Diagnostic Preview Fallback Agent (Offline Mode)"]
    end

    %% TASK DECOMPOSITION AGENTS
    subgraph DECOMPOSITION_AGENTS["Task Decomposition Sub-Agents"]
        S1["Benchmark & Reference Range Evaluator Agent"]
        S2["Clinical Synthesizer Agent (Executive Summary)"]
        S3["Dietary & Lifestyle Mitigation Advisor Agent"]
        S4["Targeted Action Plan Formulator Agent"]
    end

    %% OUTPUT AGENT
    subgraph OUTPUT_AGENT["Clinical Presentation Agent"]
        O1["Structured Markdown Output Rendering"]
        O2["On-Demand Multilingual Translation Agent (Bangla / English)"]
    end

    %% Control Flow Links
    USER --> P1
    P1 -- PDF File --> P2
    P1 -- Image File --> P3
    P1 -- Direct Text / Symptoms --> P6

    P2 --> P6
    P3 -- Active --> P4
    P3 -- Missing/Failed --> P5
    P4 --> P6
    P5 --> P6

    P6 -- Text Valid --> R1
    P6 -- Extraction Failed --> P7

    R1 -- Present --> R2
    R1 -- Absent --> R3
    R3 -- Ollama Active --> R4
    R3 -- Ollama Offline --> R5

    R2 --> S1
    R4 --> S1
    R5 --> S1

    S1 --> S2
    S2 --> S3
    S3 --> S4

    S4 --> O1
    O1 --> O2
```

---

## 🔬 Core Agentic AI Components & Behaviors

### 1. Perception & Tool Selection Agent
* **Autonomous File Inspection**: Inspects uploaded document structures to choose native stream parsers vs optical character recognition.
* **Self-Healing OCR Failover**: When `PyTesseract` binaries are missing or fail, the agent autonomously fallback-reroutes to `Windows WinRT OCR` via PowerShell bridge without throwing unhandled crashes or prompting the user.
* **Extraction Guard Agent**: Inspects raw OCR text for errors or empty strings to prevent passing unreadable tool outputs into the LLM context.

### 2. Multi-Provider Reasoning Agent
* **Infrastructure Discovery**: Autonomously inspects available compute environments (Cloud NIM API vs Local Ollama server).
* **Dynamic Model Selection**: Queries local model registries (`/api/tags`) and picks the best available model (`deepseek-r1:14b` $\rightarrow$ `deepseek-r1:1.5b` $\rightarrow$ `llama3.2`).
* **Offline Resiliency**: Automatically switches to Diagnostic Fallback Agent if network/compute services are offline.

### 3. Task Decomposition Sub-Agents
The reasoning engine delegates complex clinical analysis into specialized sub-agent tasks:
1. **Benchmark & Reference Range Evaluator Agent**: Compares numerical test results against clinical reference benchmarks (e.g. Normal `<5.7%`, Prediabetes `5.7%–6.4%`, Diabetes `≥6.5%`).
2. **Clinical Synthesizer Agent**: Generates a crisp, 1-2 sentence executive summary of overall patient health.
3. **Dietary & Lifestyle Mitigation Advisor Agent**: Identifies specific high-glycemic or refined food groups to reduce.
4. **Targeted Action Plan Formulator Agent**: Outlines step-by-step exercise, hydration, and follow-up medical consultation schedules.
