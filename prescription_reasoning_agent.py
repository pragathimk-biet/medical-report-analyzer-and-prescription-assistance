"""
===============================================================================
STEP 5: PRESCRIPTION REASONING AGENT
===============================================================================

This module provides the Prescription Reasoning Agent for the modular pipeline:

Prescription Verification Agent (Step 4)
        │
        ▼
[ Prescription Reasoning Agent ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["reasoning"]

STRICT SAFETY & GOVERNANCE BOUNDARIES:
--------------------------------------
  1. Verification is the ultimate authority. Reasoning MUST NOT override hard_stop,
     manual_review, unknown, or unverified into verified or safe.
  2. HARD STOP PRECEDENCE: If overall_status == 'hard_stop', DO NOT call the LLM (0 calls).
     Return safe review-required response immediately.
  3. MANUAL REVIEW GOVERNANCE: Filters out unverified/ambiguous medications from LLM explanation prompt.
  4. ABSOLUTE PROHIBITION OF DIAGNOSES: Never infers disease diagnoses from medications
     (e.g., Metformin -> "commonly used to help manage blood sugar", NEVER "the patient has diabetes").
  5. ABSOLUTE PROHIBITION OF DOSAGE MODIFICATIONS: Never recommends increasing, decreasing,
     stopping, or starting medications.
  6. Fail-safe deterministic fallback if AI endpoint fails or times out.
"""

import logging

logger = logging.getLogger(__name__)

PRESCRIPTION_DISCLAIMER = (
    "Notice: This prescription explanation is for informational reference only. "
    "It does not constitute medical advice, diagnosis, or treatment instructions. "
    "Always consult a qualified doctor or licensed pharmacist before making any medication decisions."
)

HARD_STOP_MESSAGE = (
    "⚠️ Safety Alert: The prescription contains a critical safety concern or medication-lab conflict "
    "that requires review by a qualified healthcare professional before taking. "
    "Do not make medication changes based solely on automated analysis."
)

class PrescriptionReasoningAgent:
    """
    Step 5 Prescription Reasoning Agent.
    Generates patient-friendly explanations for verified prescription items
    under strict governance of the Verification Agent.
    """

    @classmethod
    def generate_deterministic_summary(cls, verified_meds, unverified_meds, overall_status, med_lab_checks=None):
        """Generates safe deterministic markdown summary if LLM is unavailable or halted."""
        lines = [f"# Prescription Summary (Status: {overall_status})", ""]
        
        if verified_meds:
            lines.append("## 💊 Verified Medications")
            for med in verified_meds:
                name = med.get("verified_name") or med.get("name") or "Medication"
                strength = med.get("strength") or "Strength not specified"
                freq = med.get("frequency") or "Schedule not specified"
                timing = med.get("timing") or ""
                dur = med.get("duration") or ""

                line = f"- **{name}** ({strength}): {freq}"
                if timing:
                    line += f" — *{timing}*"
                if dur:
                    line += f" (Duration: {dur})"
                lines.append(line)
            lines.append("")

        if unverified_meds:
            lines.append("## ⚠️ Review Required / Unverified Items")
            for med in unverified_meds:
                raw = med.get("raw_name") or med.get("name") or "Uncertain item"
                status = med.get("verification_status", "manual_review")
                lines.append(f"- **{raw}** [Status: `{status}`] — Requires professional verification.")
            lines.append("")

        if med_lab_checks:
            lines.append("## ⚡ Medication-Lab Safety Alerts")
            for alert in med_lab_checks:
                lines.append(f"- **{alert.get('title', 'Safety Alert')}**: {alert.get('explanation', '')}")
            lines.append("")

        lines.append(f"_{PRESCRIPTION_DISCLAIMER}_")
        return "\n".join(lines)

    @classmethod
    def build_system_prompt(cls):
        return (
            "You are an expert patient-friendly prescription explainer AI.\n"
            "Your role is to explain verified prescription instructions in simple, clear, reassuring language based STRICTLY on verified data.\n\n"
            "STRICT MANDATORY SAFETY RULES:\n"
            "1. ABSOLUTE PROHIBITION OF DIAGNOSES: You MUST NEVER declare or infer a disease diagnosis from medications.\n"
            "   (e.g., Metformin -> 'commonly used to help manage blood sugar', NEVER 'the patient has diabetes').\n"
            "2. ABSOLUTE PROHIBITION OF DOSAGE MODIFICATION: Never tell the patient to increase, decrease, start, or stop taking medication.\n"
            "3. NO FABRICATED INTERACTIONS: Mention ONLY explicit medication-lab safety alerts supplied in the prompt.\n"
            "4. NO OVERRIDING STATUS: Never present unverified, ambiguous, or unknown items as confirmed.\n"
            "5. KEEP DOSAGE INSTRUCTIONS ACCURATE: Explain exact verified schedules in plain language."
        )

    @classmethod
    def process(cls, pipeline_context, ai_generator_func=None):
        """
        Executes Prescription Reasoning Agent on pipeline_context.
        
        Populates context["reasoning"]:
        {
            "summary": str,
            "medications": list,
            "unverified_medications": list,
            "warnings": list,
            "review_required": bool,
            "disclaimer": str,
            "generated_by": str,
            "verification_status_used": str
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        extracted_data = pipeline_context.get("extracted_data", {})
        verification = pipeline_context.get("verification", {})
        overall_status = verification.get("overall_status", "manual_review")
        all_warnings = list(verification.get("warnings", []))

        # 1. HARD STOP PRECEDENCE (CRITICAL SAFETY RULE)
        if overall_status == "hard_stop":
            logger.info("PrescriptionReasoningAgent: hard_stop triggered. Returning safe review-required response (0 LLM calls).")
            pipeline_context["reasoning"] = {
                "status": "completed",
                "summary": HARD_STOP_MESSAGE,
                "medications": [],
                "unverified_medications": [],
                "warnings": all_warnings,
                "review_required": True,
                "disclaimer": PRESCRIPTION_DISCLAIMER,
                "generated_by": "hard_stop_policy",
                "verification_status_used": "hard_stop"
            }
            return pipeline_context

        # 2. Filter Verified vs Unverified Medications
        medications = verification.get("medications", [])
        verified_meds = [m for m in medications if m.get("identity_verified") and m.get("verification_status") in ["verified", "verified_proposed"]]
        unverified_meds = [m for m in medications if not m.get("identity_verified") or m.get("verification_status") in ["manual_review", "unknown", "unverified"]]
        med_lab_checks = verification.get("medication_lab_checks", [])

        # Build structured reasoning medication entries for verified items
        reasoning_meds = []
        for vmed in verified_meds:
            name = vmed.get("verified_name") or vmed.get("name") or "Medication"
            strength = vmed.get("strength")
            freq = vmed.get("frequency")
            timing = vmed.get("timing")
            dur = vmed.get("duration")

            # Explanation string without diagnosis or dosage changes
            expl_parts = [f"{name}"]
            if strength:
                expl_parts.append(f"({strength})")
            if freq:
                expl_parts.append(f"is scheduled {freq}")
            if timing:
                expl_parts.append(f"({timing.lower()})")
            if dur:
                expl_parts.append(f"for {dur}")

            reasoning_meds.append({
                "name": name,
                "strength": strength,
                "frequency": freq,
                "timing": timing,
                "duration": dur,
                "explanation": " ".join(expl_parts) + ".",
                "verification_status": vmed.get("verification_status")
            })

        review_req = overall_status == "manual_review" or len(unverified_meds) > 0

        # 3. AI Explanation Generation if function supplied
        ai_summary = None
        generated_by = "deterministic_fallback"

        if ai_generator_func and verified_meds:
            try:
                user_prompt = f"Verified Prescription Items:\n{verified_meds}\n\nUnverified Items:\n{unverified_meds}\n\nSafety Alerts:\n{med_lab_checks}"
                sys_prompt = cls.build_system_prompt()

                logger.info("PrescriptionReasoningAgent: Executing AI Generator function...")
                ai_summary = ai_generator_func(user_prompt, sys_prompt)

                if ai_summary and isinstance(ai_summary, str) and ai_summary.strip():
                    generated_by = "ai_generator"
                else:
                    ai_summary = None
            except Exception as ai_err:
                logger.warning(f"PrescriptionReasoningAgent AI generation exception: {ai_err}. Using deterministic fallback.")
                all_warnings.append(f"AI generation exception: {ai_err}")
                ai_summary = None

        if not ai_summary:
            ai_summary = cls.generate_deterministic_summary(
                verified_meds, unverified_meds, overall_status, med_lab_checks=med_lab_checks
            )

        pipeline_context["reasoning"] = {
            "summary": ai_summary,
            "medications": reasoning_meds,
            "unverified_medications": unverified_meds,
            "warnings": all_warnings,
            "review_required": review_req,
            "disclaimer": PRESCRIPTION_DISCLAIMER,
            "generated_by": generated_by,
            "verification_status_used": overall_status
        }

        return pipeline_context
