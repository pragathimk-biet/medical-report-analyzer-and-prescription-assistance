"""
===============================================================================
STEP 5: REPORT REASONING AGENT
===============================================================================

This module provides the Report Reasoning Agent for the target pipeline:

  Patient Upload
        │
        ▼
   Input Router
        │
        ▼
Report Extraction Agent
        │
        ▼
Report Verification Agent
        │
        ▼
ML Safety / Reliability Classifier
        │
        ▼
[ Report Reasoning Agent ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["reasoning"]

STRICT SAFETY & REASONING BOUNDARIES:
--------------------------------------
  1. Respects ML Safety Status (safe_to_display | needs_manual_review | hard_stop).
  2. If safety_status == 'hard_stop': DO NOT generate medical interpretation. Return a safe
     review-required message.
  3. LLM/Gemini output can NEVER override hard_stop -> safe_to_display or needs_manual_review -> safe_to_display.
  4. Never invent laboratory values, units, reference ranges, patient history, or disease diagnoses.
  5. If AI endpoint fails/times out, fail safe to code-generated deterministic fallback.
"""

import logging

logger = logging.getLogger(__name__)

HARD_STOP_MESSAGE = "The report contains information that could not be reliably verified. Please have the original report reviewed by a qualified healthcare professional."
MEDICAL_DISCLAIMER = "Notice: This AI-generated report summary is for educational and informational reference only. It does not constitute a clinical diagnosis, medical opinion, or treatment plan. Always review lab findings with a qualified physician."

class ReportReasoningAgent:
    """
    Step 5 Report Reasoning Agent.
    Generates patient-friendly explanations for verified report findings
    in strict compliance with ML Safety governance classifications.
    """

    @classmethod
    def generate_deterministic_summary(cls, verified_biomarkers, safety_status):
        """Generates safe deterministic text summary if LLM is unavailable or halted."""
        if not verified_biomarkers:
            return "No verified laboratory findings available for summary."

        lines = [f"# Medical Report Summary (Safety Status: {safety_status})"]
        lines.append("\n## Evaluated Findings")
        
        for bm in verified_biomarkers:
            name = bm.get("name", "Unknown")
            val = bm.get("value")
            unit = bm.get("unit", "")
            status = bm.get("result_status", "unknown").upper()
            ref_range = bm.get("reference_range", "")

            val_str = f"{val} {unit}".strip() if val is not None else "Value Unavailable"
            lines.append(f"- **{name}**: {val_str} (Status: {status}, Reference Range: {ref_range})")

        lines.append(f"\n{MEDICAL_DISCLAIMER}")
        return "\n".join(lines)

    @classmethod
    def process(cls, pipeline_context, ai_generator_func=None):
        """
        Executes Report Reasoning Agent on pipeline_context.
        
        Populates context["reasoning"]:
        {
            "summary": str,
            "findings": list,
            "explanations": list,
            "warnings": list,
            "disclaimer": str,
            "generated_by": str,
            "safety_status_used": str
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        verification = pipeline_context.get("verification", {})
        safety = pipeline_context.get("safety", {})

        safety_status = safety.get("safety_status", "needs_manual_review")
        verified_biomarkers = verification.get("biomarkers", [])
        warnings = []

        # =========================================================================
        # CASE C — hard_stop: Immediate Safe Review-Required Halted Response
        # =========================================================================
        if safety_status == "hard_stop" or safety.get("hard_stop_triggered"):
            logger.info("ReportReasoningAgent: hard_stop triggered. Returning safe review-required response.")
            warnings.append("Hard-stop triggered by ML Safety Classifier. Automated medical interpretation halted.")
            
            pipeline_context["reasoning"] = {
                "summary": HARD_STOP_MESSAGE,
                "findings": [],
                "explanations": [HARD_STOP_MESSAGE],
                "warnings": warnings,
                "disclaimer": MEDICAL_DISCLAIMER,
                "generated_by": "Rule Engine Precedence Layer (Hard Stop)",
                "safety_status_used": "hard_stop"
            }
            return pipeline_context

        # Filter verified biomarkers
        valid_findings = [bm for bm in verified_biomarkers if bm.get("verification_status") in ["verified", "unit_missing"]]
        unverified_findings = [bm for bm in verified_biomarkers if bm.get("verification_status") not in ["verified", "unit_missing"]]

        if unverified_findings:
            warnings.append(f"{len(unverified_findings)} finding(s) could not be fully verified and require manual medical review.")

        # =========================================================================
        # CASE B — needs_manual_review: Explain ONLY Verified Findings
        # =========================================================================
        if safety_status == "needs_manual_review":
            logger.info("ReportReasoningAgent: Processing under needs_manual_review governance.")

        # =========================================================================
        # Build Verified Prompt (NO Raw Untrusted OCR Sent as Truth)
        # =========================================================================
        verified_summary = cls.generate_deterministic_summary(valid_findings, safety_status)
        explanations_list = []
        generator_used = "Code-Generated Deterministic Engine"

        if ai_generator_func and valid_findings and safety_status == "safe_to_display":
            try:
                prompt_lines = ["Verified Report Data for Patient Explanation:"]
                for bm in valid_findings:
                    ref_r = bm.get("reference_range", "Unavailable")
                    res_s = bm.get("result_status", "unknown")
                    prompt_lines.append(f"- {bm.get('name', 'Biomarker')}: {bm.get('value')} {bm.get('unit', '')} (Status: {res_s}, Reference Range: {ref_r})")
                prompt_str = "\n".join(prompt_lines)

                sys_prompt = "You are a clinical explainer AI. Explain these verified laboratory findings in simple, patient-friendly plain language. DO NOT diagnose disease or invent values."
                
                logger.info("Calling AI Generator Function for safe_to_display report reasoning...")
                ai_output = ai_generator_func(prompt_str, system_prompt=sys_prompt)
                if isinstance(ai_output, Exception):
                    raise ai_output
                
                if ai_output and isinstance(ai_output, str) and not ai_output.startswith("Error"):
                    verified_summary = ai_output
                    generator_used = "NVIDIA NIM / Ollama AI Model"
                else:
                    warnings.append("AI generation returned empty/error response. Using safe deterministic summary fallback.")
            except Exception as ai_err:
                logger.warning(f"AI generation exception: {ai_err}. Using deterministic fallback.")
                warnings.append(f"AI generation exception ({ai_err}). Using safe deterministic summary fallback.")

        # Populate context["reasoning"]
        pipeline_context["reasoning"] = {
            "summary": verified_summary,
            "findings": valid_findings,
            "explanations": [verified_summary],
            "warnings": warnings,
            "disclaimer": MEDICAL_DISCLAIMER,
            "generated_by": generator_used,
            "safety_status_used": safety_status
        }

        if warnings:
            pipeline_context["warnings"].extend(warnings)

        return pipeline_context
