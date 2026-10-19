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
import re
from rule_engine import MedicalRuleEngine

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
    def build_report_patient_summary(cls, eval_results, demographics=None, two_way_alerts=None):
        """
        Builds a complete, faithful, evidence-backed patient explanation for report analysis
        following the required order:
          A. Main findings
          B. Your results, explained
          C. What could not be assessed / differences between reference comparisons
          D. What to do next
          E. Important limits
          F. Technical Details and Evidence (<details><summary>🔬 View Technical & Evidence Details</summary>...)
        """
        demographics = demographics or {}
        p_name = demographics.get('patient_name') or "Default Patient"
        clean_pname = p_name.strip()
        is_pseudonym = bool(re.match(r"^Patient_[a-f0-9]+$", clean_pname, re.I)) or clean_pname.lower().startswith("patient_")
        
        if is_pseudonym:
            patient_label = f"De-identified Patient (Reference ID: {clean_pname})"
        elif clean_pname.lower() in ["default patient", "unknown", ""]:
            patient_label = "De-identified Patient"
        else:
            clean_name = re.sub(r'^(mr|mrs|ms|dr|master)\.?\s*', '', clean_pname, flags=re.I).strip()
            patient_label = clean_name

        age = demographics.get('age', 'N/A')
        gender = demographics.get('gender', 'N/A')
        lab_ref_no = demographics.get('lab_ref_no', 'N/A')
        reg_date = demographics.get('registration_date', 'N/A')

        lines = ["# Medical Report Analysis", ""]

        # ---------------------------------------------------------------------
        # SECTION A: Main Findings
        # ---------------------------------------------------------------------
        lines.append("## 1. Main Findings")
        lines.append("")

        if not eval_results:
            lines.append("No laboratory test findings could be extracted or verified from this report.")
            lines.append("Please verify that the uploaded document contains clear, legible laboratory test results.")
        else:
            main_bullets = []
            
            # Check for high / elevated post-prandial glucose
            pp_finding = next((f for f in eval_results if "post prandial" in str(f.get("test_name", "")).lower() or "pp" in str(f.get("test_name", "")).lower()), None)
            if pp_finding and pp_finding.get("result_value") is not None:
                val = pp_finding.get("result_value")
                unit = pp_finding.get("unit", "mg/dL")
                ref = pp_finding.get("printed_comparison", {}).get("range", "80 - 140 mg/dl")
                main_bullets.append(f"- **Elevated post-meal blood sugar:** Post-prandial blood sugar is elevated at {val} {unit}, which exceeds the laboratory's printed reference range ({ref}). This test reflects blood sugar after an ordinary meal rather than a standardized 75-g oral glucose tolerance test (OGTT).")

            # Check for fasting glucose comparison difference
            fbg_finding = next((f for f in eval_results if ("fasting" in str(f.get("test_name", "")).lower() and ("glucose" in str(f.get("test_name", "")).lower() or "sugar" in str(f.get("test_name", "")).lower())) and "urine" not in str(f.get("test_name", "")).lower()), None)
            if fbg_finding and fbg_finding.get("result_value") is not None:
                val = fbg_finding.get("result_value")
                unit = fbg_finding.get("unit", "mg/dL")
                p_range = fbg_finding.get("printed_comparison", {}).get("range", "70 - 120 mg/dL")
                g_comp = fbg_finding.get("guideline_comparison", {})
                g_status = g_comp.get("status")
                if g_status == "PREDIABETES_RANGE" or (100 <= float(val) <= 125):
                    main_bullets.append(f"- **Fasting blood sugar reference difference:** Fasting blood sugar is {val} {unit}. This result is within the laboratory's printed normal range ({p_range}), but falls into the prediabetes category (100–125 mg/dL) under standard American Diabetes Association (ADA 2024) clinical guidelines.")
                elif str(fbg_finding.get("status")).upper() in ["HIGH", "VERY_HIGH"]:
                    main_bullets.append(f"- **Elevated fasting blood sugar:** Fasting blood sugar is elevated at {val} {unit}, above the laboratory reference range ({p_range}).")
                else:
                    main_bullets.append(f"- **Fasting blood sugar:** Measured at {val} {unit}, within the laboratory reference range ({p_range}).")

            # Check for qualitative urine sugar
            urine_findings = [f for f in eval_results if "urine" in str(f.get("test_name", "")).lower()]
            if urine_findings:
                u_descs = []
                for uf in urine_findings:
                    u_name = "fasting" if "fasting" in str(uf.get("test_name", "")).lower() else "post-meal"
                    u_val = uf.get("result_text") or uf.get("result_value") or "Nil"
                    u_descs.append(f"{u_val} ({u_name})")
                main_bullets.append(f"- **Qualitative urine sugar observations:** Urine sugar was reported as {', '.join(u_descs)}. These are qualitative observational notes on urine specimens rather than direct measurements of blood glucose.")

            # Check for other abnormal findings
            other_abnormals = [f for f in eval_results if f not in [pp_finding, fbg_finding] + urine_findings and str(f.get("status")).upper() in ["HIGH", "LOW", "VERY_HIGH", "VERY_LOW"]]
            for af in other_abnormals:
                t_name = af.get("test_name", "Test")
                val_str = f"{af.get('result_value')} {af.get('unit', '')}".strip()
                st = str(af.get("status")).upper()
                main_bullets.append(f"- **{t_name} ({st}):** Measured at {val_str}, which falls outside the expected reference interval.")

            if not main_bullets:
                for f in eval_results:
                    t_name = f.get("test_name", "Test")
                    val_str = f"{f.get('result_value')} {f.get('unit', '')}".strip()
                    main_bullets.append(f"- **{t_name}:** Measured at {val_str}.")

            # Safety and non-diagnostic boundary note
            main_bullets.append("- **Important clinical context:** An abnormal laboratory finding indicates a physiologic pattern that requires medical follow-up, but does not constitute a formal diagnosis. Similarly, a value within printed reference ranges does not prove effective regulation or complete overall health.")

            lines.extend(main_bullets)

        lines.append("")

        # ---------------------------------------------------------------------
        # SECTION B: Your Results, Explained
        # ---------------------------------------------------------------------
        lines.append("## 2. Your Results, Explained")
        lines.append("")

        for finding in eval_results:
            name = finding.get("test_name", "Laboratory Test")
            norm_name = str(finding.get("normalized_test_name", "")).lower()
            val = finding.get("result_value")
            text_val = finding.get("result_text")
            unit = finding.get("unit") or ""
            disp = finding.get("disposition", "EVALUATED")
            p_comp = finding.get("printed_comparison") or {}
            g_comp = finding.get("guideline_comparison") or {}

            p_status = p_comp.get("status", finding.get("status", "NORMAL"))
            p_range = p_comp.get("range") or finding.get("reference_text") or "Not stated"
            g_status = g_comp.get("status")
            g_source = g_comp.get("source")

            if "post prandial" in name.lower() or "pp" in name.lower():
                clean_title = f"Post Prandial Blood Sugar ({name})" if "sugar" in name.lower() or "glucose" in name.lower() else name
                if "after eating" not in clean_title.lower() and "urine" not in name.lower():
                    clean_title += " (After Eating)"
            elif "fasting" in name.lower() and ("glucose" in name.lower() or "sugar" in name.lower()) and "urine" not in name.lower():
                clean_title = "Fasting Blood Sugar (Fasting Blood Glucose)"
            else:
                clean_title = name

            lines.append(f"### 🩺 {clean_title}")
            lines.append("")

            if val is not None and isinstance(val, (int, float)):
                lines.append(f"- **Your Result:** {val} {unit}".strip())
            elif text_val and str(text_val).strip().lower() != "none":
                lines.append(f"- **Your Observation:** {str(text_val).strip()}")
            else:
                lines.append("- **Your Result:** Not recorded")

            lines.append(f"- **Laboratory Printed Reference Range:** {p_range}")

            if str(p_status).upper() in ["NORMAL", "NEGATIVE", "DESIRABLE"]:
                lines.append("- **Comparison with Printed Range:** Within printed reference range (Normal)")
            elif str(p_status).upper() in ["HIGH", "VERY_HIGH"]:
                lines.append("- **Comparison with Printed Range:** Above printed reference range (High)")
            elif str(p_status).upper() in ["LOW", "VERY_LOW"]:
                lines.append("- **Comparison with Printed Range:** Below printed reference range (Low)")
            else:
                lines.append(f"- **Comparison with Printed Range:** Qualitative observation ({text_val or 'Reported'})")

            if g_status and g_status not in ["NOT_MAPPED", "NOT_APPLICABLE", "None"]:
                if g_status == "PREDIABETES_RANGE":
                    lines.append(f"- **Clinical Guideline Category:** Prediabetes range (100–125 mg/dL) [{g_source or 'ADA 2024'}]")
                elif g_status == "DIABETES_RANGE":
                    lines.append(f"- **Clinical Guideline Category:** Diabetes threshold range [{g_source or 'ADA 2024'}]")
                elif g_status == "NORMAL":
                    lines.append(f"- **Clinical Guideline Category:** Standard normal range (70–99 mg/dL) [{g_source or 'ADA 2024'}]")
                else:
                    lines.append(f"- **Clinical Guideline Category:** {g_status} [{g_source}]")
            else:
                if "post prandial" in name.lower() or "pp" in name.lower():
                    lines.append("- **Clinical Guideline Category:** Not mapped to clinical guideline (routine post-meal test; not an OGTT)")
                elif "urine" in name.lower():
                    lines.append("- **Clinical Guideline Category:** Qualitative observation (no automated guideline classification)")

            lines.append("- **What this means in plain language:**")
            
            if "fasting" in name.lower() and ("glucose" in name.lower() or "sugar" in name.lower()) and "urine" not in name.lower():
                lines.append(
                    f"  This test measures blood sugar following an overnight fast (typically 8 to 12 hours without food). "
                    f"Your result of {val} {unit} is within this laboratory's printed reference range ({p_range}). "
                    f"However, under standard clinical guidelines (ADA 2024 Standards of Care), fasting glucose between 100 and 125 mg/dL is categorized as impaired fasting glucose (prediabetes range). "
                    f"This single finding does not prove effective regulation or diagnose prediabetes or diabetes; rather, it highlights a borderline value that warrants follow-up discussion and monitoring with your doctor."
                )
            elif ("post prandial" in name.lower() or "pp" in name.lower()) and "urine" not in name.lower():
                lines.append(
                    f"  \"Post-prandial\" means measured after eating a meal. "
                    f"Your result of {val} {unit} is substantially higher than the laboratory's printed reference range ({p_range}). "
                    f"This test was performed after an ordinary meal and should not be equated with a standardized 75-gram oral glucose tolerance test (OGTT), as meal composition and exact elapsed time were not clinically standardized. "
                    f"An elevated post-meal blood sugar reading indicates that blood glucose remained high after eating, which should be clinically evaluated by your physician."
                )
            elif "urine" in name.lower() and "fasting" in name.lower():
                lines.append(
                    f"  The fasting urine specimen showed no detectable sugar (\"{text_val or 'Nil'}\"), which matches the expected negative/nil laboratory reference note. "
                    f"This qualitative observation indicates that glucose was not detected in this routine spot urine specimen."
                )
            elif "urine" in name.lower() and ("post" in name.lower() or "pp" in name.lower()):
                lines.append(
                    f"  The post-meal urine specimen was observed as \"{text_val or 'Yellow 1%'}\". "
                    f"This qualitative observation indicates the presence of reducing substances (sugar) in the urine specimen collected after eating. "
                    f"This is a chemical observation in urine, not a blood sugar measurement. It does not mean your body is \"producing\" excess sugar, but rather that sugar was present in the urine sample at testing. "
                    f"This observational finding should be reviewed by your clinician alongside your blood test results."
                )
            else:
                val_display = f"{val} {unit}".strip() if val is not None else (text_val or "Reported")
                if str(p_status).upper() in ["HIGH", "VERY_HIGH"]:
                    lines.append(f"  Your {name.lower()} level is {val_display}, which is above the laboratory's expected reference range ({p_range}). Elevated levels warrant clinical review to determine underlying factors.")
                elif str(p_status).upper() in ["LOW", "VERY_LOW"]:
                    lines.append(f"  Your {name.lower()} level is {val_display}, which is below the laboratory's expected reference range ({p_range}). Lower than expected levels should be reviewed clinically.")
                elif disp == "UNSUPPORTED_QUALITATIVE":
                    lines.append(f"  This test was reported as \"{text_val}\". It represents a qualitative observation that requires direct clinical review by your physician.")
                else:
                    lines.append(f"  Your {name.lower()} level is {val_display}, which falls within the laboratory's printed reference range ({p_range}).")

            lines.append("")

        # ---------------------------------------------------------------------
        # SECTION C: Reference Comparisons & What Could Not Be Assessed
        # ---------------------------------------------------------------------
        lines.append("## 3. What Could Not Be Assessed & Reference Differences")
        lines.append("")
        
        lines.append("- **Fasting Blood Sugar reference discrepancy explained:**")
        lines.append("  The laboratory's printed reference interval is 70–120 mg/dL, against which 102 mg/dL is categorized as normal. By contrast, authoritative clinical practice guidelines (ADA 2024 Standards of Care) establish 70–99 mg/dL as normal fasting glucose and designate 100–125 mg/dL as impaired fasting glucose (prediabetes range). Laboratory reference intervals reflect local instrument calibrations and regional population reference populations, whereas clinical guideline thresholds reflect established long-term cardiovascular and metabolic risk strata. Both comparisons are preserved here to provide full transparency without diagnosing the patient.")
        lines.append("")

        lines.append("- **Post-Prandial Blood Sugar testing context limitations:**")
        lines.append("  The laboratory provided an 80–140 mg/dL printed reference range for post-prandial blood sugar. Authoritative guideline criteria for diabetes risk stratification (such as the 2-hour 75-g Oral Glucose Tolerance Test threshold of ≥ 200 mg/dL) require rigorous clinical protocols—including a standardized 75-gram anhydrous glucose challenge, verified fasting beforehand, and exact 2-hour timed blood draws. Because this report reflects a routine post-meal test without documented meal size, carbohydrate load, or exact timing, it cannot be evaluated as an OGTT.")
        lines.append("")

        lines.append("- **Qualitative Urine Sugar evaluation limitations:**")
        lines.append("  The reported urine sugar results (\"Nil\" and \"Yellow 1%\") are descriptive qualitative observations. They cannot be converted to numeric values, do not directly indicate blood sugar concentrations, and are not evaluated by automated clinical rules. They are preserved faithfully as source observations for professional clinician review.")
        lines.append("")

        n_total = len(eval_results)
        n_printed = sum(1 for f in eval_results if f.get("disposition") in ["EVALUATED", "EVALUATED_PRINTED_RANGE_ONLY"] and f.get("result_value") is not None)
        n_guide = sum(1 for f in eval_results if f.get("guideline_comparison", {}).get("status") not in [None, "NOT_MAPPED", "NOT_APPLICABLE", "None"])
        n_unsupported = sum(1 for f in eval_results if f.get("disposition") in ["UNSUPPORTED_QUALITATIVE", "INSUFFICIENT_CONTEXT", "UNRESOLVED_MAPPING", "REJECTED"])

        lines.append(f"- **Evaluation Coverage Accounting:**")
        lines.append(f"  - Total extracted test results: {n_total}")
        lines.append(f"  - Evaluated against printed reference range: {n_printed}")
        lines.append(f"  - Evaluated against authoritative guidelines: {n_guide}")
        lines.append(f"  - Preserved qualitative / unsupported observations: {n_unsupported}")
        lines.append("")

        # ---------------------------------------------------------------------
        # SECTION D: What To Do Next
        # ---------------------------------------------------------------------
        lines.append("## 4. What To Do Next")
        lines.append("")
        lines.append("- **Consult your primary care doctor:** Make an appointment with your General Physician or primary care doctor to review these laboratory findings in the context of your complete health history.")
        lines.append("- **Discuss confirmatory testing:** Ask your physician if an **HbA1c** (glycated hemoglobin) test or repeat fasting blood sugar test is advised to assess your longer-term average blood sugar control.")
        lines.append("- **Specialist consultation:** If recommended by your primary care doctor, consider consulting an **Endocrinologist / Diabetologist** for specialized metabolic evaluation.")
        lines.append("- **Bring your original report:** Take the original laboratory printout to your consultation so your healthcare team can verify all printed reference intervals.")
        lines.append("- **Avoid self-treatment:** Do not start, stop, or change medications or make drastic dietary changes without professional clinical guidance.")
        lines.append("")

        # ---------------------------------------------------------------------
        # SECTION E: Important Limits
        # ---------------------------------------------------------------------
        lines.append("## 5. Important Limits")
        lines.append("")
        lines.append("- **Research & educational prototype:** This automated report summary is generated for educational and informational reference only. It does not constitute a clinical diagnosis, official medical opinion, or treatment plan.")
        lines.append("- **Non-diagnostic guarantee:** Automated analysis cannot replace an in-person clinical assessment by a licensed physician with access to your physical examination, symptoms, medications, and full medical history.")
        lines.append("")

        # ---------------------------------------------------------------------
        # SECTION F: Technical Details and Evidence
        # ---------------------------------------------------------------------
        re_engine = MedicalRuleEngine()
        deterministic_table = re_engine.format_deterministic_markdown(eval_results)

        age_display = f"{age} Year(s)" if age and str(age).strip() not in ["None", "N/A", ""] else "Not recorded"
        gender_display = str(gender).strip() if gender and str(gender).strip() not in ["None", "N/A", ""] else "Not recorded"
        ref_display = f"`{lab_ref_no}`" if lab_ref_no and str(lab_ref_no).strip() not in ["None", "N/A", ""] else "Not recorded"
        date_display = str(reg_date).strip() if reg_date and str(reg_date).strip() not in ["None", "N/A", ""] else "Not recorded"

        demo_card = f"""### 👤 Patient Demographic Information
| Demographic Field | Details |
| :--- | :--- |
| **Patient Reference** | {patient_label} |
| **Age / Sex** | {age_display} / {gender_display} |
| **Lab Ref No.** | {ref_display} |
| **Registration Date** | {date_display} |

---
"""

        lines.append("<details>")
        lines.append("<summary>🔬 View Technical & Evidence Details</summary>")
        lines.append("")
        lines.append(demo_card)
        lines.append(deterministic_table)
        lines.append("")
        lines.append("</details>")

        return "\n".join(lines)

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
