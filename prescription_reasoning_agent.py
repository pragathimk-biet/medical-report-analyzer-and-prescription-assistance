"""
===============================================================================
STEP 5: PRESCRIPTION REASONING AGENT
===============================================================================

This module provides the Prescription Reasoning Agent for the modular pipeline:

DDI Checking Agent (Step 4b)
        |
        v
[ Prescription Reasoning Agent ] <-- THIS AGENT
        |
        v
  pipeline_context["reasoning"]

STRICT SAFETY & GOVERNANCE BOUNDARIES:
--------------------------------------
  1. Verification is the ultimate authority. Reasoning MUST NOT override hard_stop,
     manual_review, unknown, or unverified into verified or safe.
  2. HARD STOP PRECEDENCE: If overall_status == 'hard_stop', DO NOT call the LLM (0 calls).
     Return safe review-required response immediately.
  3. MANUAL REVIEW GOVERNANCE: Filters out unverified/ambiguous medications from LLM prompt.
  4. ABSOLUTE PROHIBITION OF DIAGNOSES: Never infers disease diagnoses from medications
     (e.g., Metformin -> "commonly used to help manage blood sugar", NEVER "the patient has diabetes").
  5. ABSOLUTE PROHIBITION OF DOSAGE MODIFICATIONS: Never recommends increasing, decreasing,
     stopping, or starting medications.
  6. Fail-safe deterministic fallback if AI endpoint fails or times out.
  7. DDI FINDINGS: Injected into LLM prompt as-supplied facts ONLY.
     The LLM MUST NOT invent interactions, change severity labels, or recommend
     stopping/replacing medicines. Dataset Level labels are preserved verbatim.
  8. OUTPUT VALIDATION: The LLM explanation is validated against structured DDI
     findings. If validation fails, the deterministic fallback is used instead.
     DDI findings are kept separately from generated text so structured data
     is always available regardless of LLM output quality.
  9. COVERAGE REPORTING: NO_RECORD_FOUND, RESOURCE_UNAVAILABLE, partial coverage,
     and unresolved medications are always reported explicitly. They are NEVER
     collapsed into "no interactions found" in any output path.
"""

import re
import logging
from typing import Any, Dict, List, Optional

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

# Patterns that indicate the LLM has fabricated or overstated DDI information
_DDI_FABRICATION_PATTERNS = [
    r'\bstop\s+taking\b',
    r'\bdiscontinue\b',
    r'\bdo\s+not\s+take\b',
    r'\breplace\b.*\bwith\b',
    r'\bswitch\s+to\b',
    r'\bavoid\s+this\s+combination\b',
    r'\bcontraindicated\b',       # only safe if directly from the dataset record
    r'\bserious\s+risk\b',
    r'\blife[-\s]?threatening\b',
    r'\bfatal\b',
]

# Phrase used to mark where the DDI block is injected in the deterministic summary
_DDI_SECTION_HEADER = "## ⚠️ Drug-Drug Interaction (DDI) Check Results"


def _build_ddi_deterministic_block(ddi: dict) -> str:
    """
    Builds a deterministic, structured DDI results block for inclusion in
    the summary. This block is always produced from raw structured data,
    never from LLM output.

    Coverage state is always reported; partial/unavailable/no-pairs states
    are never rendered as "no interactions found".
    """
    if not ddi:
        return ""

    lines = [_DDI_SECTION_HEADER, ""]
    overall = ddi.get("overall_status", "unknown")
    coverage = ddi.get("coverage", {})
    pairs = ddi.get("pairs", [])
    interactions = ddi.get("interactions_found", [])

    exec_status = (
        ddi.get("execution_completion")
        or coverage.get("execution_completion")
        or ("RESOURCE_UNAVAILABLE" if overall == "resource_unavailable" else "COMPLETED")
    )
    cov_completeness = (
        ddi.get("coverage_completeness")
        or coverage.get("coverage_completeness")
        or (
            "RESOURCE_UNAVAILABLE" if overall == "resource_unavailable" else (
                "PARTIAL" if overall == "partial" else (
                    "NO_PAIRS" if overall == "no_pairs" else "FULL"
                )
            )
        )
    )

    submitted_meds = coverage.get("submitted_medications", coverage.get("total_prescription_meds", "–"))
    checked_meds = coverage.get("checked_medications", coverage.get("verified_meds", "–"))

    # -- Coverage summary --
    lines.append("### Coverage Summary")
    lines.append(
        f"| Item | Value |\n"
        f"| :--- | :--- |\n"
        f"| Execution status | {exec_status} |\n"
        f"| Coverage completeness | {cov_completeness} |\n"
        f"| Prescription coverage | {coverage.get('prescription_coverage', '–')} |\n"
        f"| Dataset integrity | {coverage.get('dataset_completeness_status', '–')} |\n"
        f"| History status | {coverage.get('history_retrieval_status', '–')} |\n"
        f"| Submitted medications | {submitted_meds} |\n"
        f"| Checked medications | {checked_meds} |\n"
        f"| Submitted ingredients | {coverage.get('submitted_ingredients_count', '–')} |\n"
        f"| Resolved ingredients | {coverage.get('resolved_ingredients_count', '–')} |\n"
        f"| Attempted pairs | {coverage.get('attempted_pairs_count', '–')} |\n"
        f"| Evaluated pairs | {coverage.get('evaluated_pairs_count', '–')} |\n"
        f"| Dataset available | {'Yes' if coverage.get('dataset_available') else 'No — configure DDI_DATA_DIR'} |\n"
        f"| Historical active meds | {coverage.get('historical_active_meds', '–')} |\n"
        f"| Total ingredients checked | {coverage.get('total_ingredients_checked', '–')} |\n"
        f"| Total pairs checked | {coverage.get('total_pairs_checked', '–')} |"
    )
    lines.append("")

    # -- Excluded medications display --
    excluded = coverage.get("excluded_medications", [])
    if excluded:
        lines.append("#### Excluded Medications & Reasons")
        for exc in excluded:
            exc_name = exc.get("name", "Unknown")
            exc_reason = exc.get("reason", "excluded")
            exc_details = exc.get("details", "")
            lines.append(f"- `{exc_name}`: {exc_details or exc_reason} (Reason: {exc_reason})")
        lines.append("")

    # -- Coverage status notice --
    if overall == "resource_unavailable" or cov_completeness == "RESOURCE_UNAVAILABLE":
        lines.append(
            "> ⚠️ **DDI dataset not configured.** "
            "Drug-drug interaction checking could not be performed. "
            "Consult a pharmacist for interaction review."
        )
    elif overall == "no_pairs" or cov_completeness == "NO_PAIRS":
        lines.append(
            "> ℹ️ **No pairs to check (NO_PAIRS).** "
            "Fewer than two resolvable drug ingredients were found — DDI pair checking was not performed. "
            "This is not evidence of absence of interactions with other medications. "
            "Consult a licensed pharmacist or physician for medication interaction review."
        )
    elif overall == "prescription_only" or cov_completeness == "PRESCRIPTION_ONLY":
        lines.append(
            "> ⚠️ **Prescription-only DDI coverage (PRESCRIPTION_ONLY).** "
            "Interaction checking was performed on current prescription medications only. "
            "Patient historical medications could not be verified or retrieved "
            f"({coverage.get('history_authorization_blocker') or coverage.get('history_retrieval_status', 'unauthorized')}). "
            "Overall coverage is not full; potential interactions with ongoing treatments are unknown."
        )
    elif overall in ("partial", "partial_dataset") or cov_completeness in ("PARTIAL", "PARTIAL_DATASET"):
        unresolved = coverage.get("unresolved_ingredients", [])
        if excluded:
            exc_summary = ", ".join(f"`{e.get('name')}` ({e.get('reason')})" for e in excluded)
            lines.append(
                f"> ⚠️ **Partial DDI coverage (PARTIAL).** "
                f"{len(excluded)} submitted medication(s)/ingredient(s) excluded: {exc_summary}. "
                f"Remaining pairs were evaluated, but interaction coverage is incomplete. "
                f"Do not assume omitted medications or combinations are safe."
            )
        elif unresolved:
            lines.append(
                f"> ⚠️ **Partial DDI coverage (PARTIAL).** "
                f"{len(unresolved)} ingredient(s) could not be matched to DDInter identities: "
                f"{', '.join(f'`{u}`' for u in unresolved)}. "
                f"Pairs involving these ingredients have unknown DDI status."
            )
        else:
            lines.append(
                "> ⚠️ **Partial DDI coverage (PARTIAL).** "
                "One or more submitted medications were unverified, unresolved, or unsupported."
            )

        # Show second limitation if history was also blocked or failed
        if coverage.get("prescription_only_coverage") or coverage.get("history_retrieval_status") in ("FAILED", "BLOCKED_NO_AUTHORIZATION"):
            lines.append(
                "> ⚠️ **Notice on Patient History:** Historical medication review was also omitted or blocked "
                f"({coverage.get('history_authorization_blocker') or coverage.get('history_retrieval_status')}). "
                "Both prescription and historical coverage limitations apply."
            )

    # Dataset integrity notice
    dataset_status = coverage.get("dataset_completeness_status")
    if dataset_status and dataset_status not in ("COMPLETE", "INTACT", "UNKNOWN", "UNAVAILABLE"):
        lines.append(
            f"> ⚠️ **Notice on Dataset Integrity ({dataset_status}):** "
            "The interaction dataset is incomplete or has unverified integrity. "
            "Unqualified full coverage cannot be claimed."
        )

    lines.append("")

    # -- Pair-level results --
    if pairs:
        lines.append("### Pair Results")
        for pair in pairs:
            a = pair.get("drug_a", "?")
            b = pair.get("drug_b", "?")
            status = pair.get("status", "UNKNOWN")
            level = pair.get("level")
            note = pair.get("note", "")
            src_prods_a = pair.get("source_products_a") or [pair.get("source_product_a", a)]
            src_prods_b = pair.get("source_products_b") or [pair.get("source_product_b", b)]
            src_a_str = ", ".join(dict.fromkeys(str(s) for s in src_prods_a if s))
            src_b_str = ", ".join(dict.fromkeys(str(s) for s in src_prods_b if s))

            badge = {
                "INTERACTION_FOUND":     "🔴",
                "NO_RECORD_FOUND":       "⬜",
                "UNRESOLVED_MEDICATION": "❓",
                "RESOURCE_UNAVAILABLE":  "⚠️",
            }.get(status, "ℹ️")

            pair_heading = f"**{a}** + **{b}**"
            if (src_a_str and src_a_str != a) or (src_b_str and src_b_str != b):
                pair_heading += f" *(from: {src_a_str} / {src_b_str})*"

            lines.append(f"#### {badge} {pair_heading}")
            lines.append(f"- **Status**: `{status}`")
            if level:
                lines.append(
                    f"- **Level** *(verbatim from dataset)*: `{level}`"
                )
                if "unknown" in level.lower():
                    lines.append(
                        "  > ⚠️ **Notice on Unknown Level**: This interaction is recorded in DDInter with severity 'Unknown'. "
                        "Unknown severity is preserved verbatim and must NOT be interpreted as Minor, harmless, or safe. "
                        "Clinical evaluation by a doctor or pharmacist is required."
                    )
            lines.append(f"- {note}")

            # Individual records if interaction found
            if status == "INTERACTION_FOUND":
                records = pair.get("records", [])
                for rec in records:
                    rec_level = rec.get("Level", "–")
                    id_a = rec.get("DDInterID_A", "–")
                    id_b = rec.get("DDInterID_B", "–")
                    lines.append(
                        f"  - Record: `{id_a}` ({rec.get('Drug_A')}) ↔ "
                        f"`{id_b}` ({rec.get('Drug_B')}) — Level: `{rec_level}`"
                    )
                lines.append(
                    "  > ⚠️ **An interaction record exists for this pair.** "
                    "Consult your prescribing doctor or pharmacist before taking both medicines together."
                )
            lines.append("")

    # -- NO_RECORD_FOUND explicit notice (never collapse as "safe") --
    no_record_pairs = [p for p in pairs if p.get("status") == "NO_RECORD_FOUND"]
    if no_record_pairs:
        lines.append(
            f"> ℹ️ **{len(no_record_pairs)} pair(s) had no record in DDInter.** "
            "This does NOT mean those combinations are safe. "
            "The DDInter dataset does not cover all known interactions. "
            "Consult a pharmacist for a complete interaction review."
        )
        lines.append("")

    lines.append(f"_{PRESCRIPTION_DISCLAIMER}_")
    return "\n".join(lines)


def _clean_md_cell(text: Any) -> str:
    """Escapes pipe characters and cleans whitespace for markdown table cells."""
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").strip()
    return s.replace("|", "\\|")


def _format_provenance_value(val_raw: Any, unit_raw: Any, timing_raw: Any = None) -> str:
    """
    Formats the 'Submitted Value' column for the input provenance table.

    Readable text rules:
      - Both absent: "Value and unit not provided"
      - Value absent, unit present: "Value not provided; unit: <submitted unit>"
      - Value present, unit absent: "<submitted value>; unit not provided"
      - Both present: "<submitted value> <submitted unit>"
      - Preserves zero (0, 0.0, "0") as a valid submitted value (no truthiness bug).
      - Preserves explicitly submitted timing: " (<submitted timing>)", without inventing
        timing when absent or unspecified.
      - Escapes markdown table special characters.
    """
    val_present = (
        val_raw is not None
        and str(val_raw).strip() != ""
        and str(val_raw).strip().lower() != "none"
    )
    unit_present = (
        unit_raw is not None
        and str(unit_raw).strip() != ""
        and str(unit_raw).strip().lower() != "none"
    )

    clean_val = _clean_md_cell(val_raw) if val_present else ""
    clean_unit = _clean_md_cell(unit_raw) if unit_present else ""

    if val_present and unit_present:
        base = f"{clean_val} {clean_unit}"
    elif not val_present and not unit_present:
        base = "Value and unit not provided"
    elif not val_present and unit_present:
        base = f"Value not provided; unit: {clean_unit}"
    else:  # val_present and not unit_present
        base = f"{clean_val}; unit not provided"

    timing_str = str(timing_raw).strip() if timing_raw is not None else ""
    timing_present = bool(timing_str) and (
        timing_str.lower() not in ("unspecified", "unknown", "none", "")
    )
    if timing_present:
        clean_timing = _clean_md_cell(timing_str)
        base = f"{base} ({clean_timing})"

    return base


def _clean_patient_text(val: Any) -> str:
    """Escapes user/OCR text for patient-friendly output."""
    if val is None:
        return ""
    s = str(val).replace("\r", " ").replace("\n", " ").strip()
    s = s.replace("|", "").replace("`", "")
    return s


def _format_patient_strength(raw: Optional[Any]) -> Optional[str]:
    """
    Formats recognized strength units readably, e.g. 10mg -> 10 mg.
    Preserves underlying value and unit without altering numeric quantity.
    """
    if raw is None:
        return None
    s = _clean_patient_text(raw)
    if not s or s.lower() == "none":
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z%]+(?:\s*/\s*[a-zA-Z0-9%]+)?)$", s)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return s


def _normalize_frequency(freq: Optional[Any]) -> Optional[str]:
    """
    Normalizes recognized frequency expressions once, without duplication.
    Supports 'OD', 'Once Daily (OD)', and already-expanded 'once daily'.
    Preserves unrecognized frequency wording without guessing.
    """
    if freq is None:
        return None
    s = str(freq).strip()
    if not s or s.lower() == "none":
        return None

    # Recognized once-daily expressions
    if re.fullmatch(r"(?i)od|once\s+daily(?:\s*\(\s*(?:od|once\s+daily)\s*\))?|once\s+daily\s+morning(?:\s*\(\s*1-0-0\s*\))?|1-0-0", s):
        return "once daily"

    # Recognized twice-daily expressions
    if re.fullmatch(r"(?i)bd|bid|twice\s+daily(?:\s*\(\s*(?:bd(?:/1-0-1)?|twice\s+daily)\s*\))?|1-0-1", s):
        return "twice daily"

    # Recognized three-times-daily expressions
    if re.fullmatch(r"(?i)tds|tid|three\s+times\s+daily(?:\s*\(\s*(?:tds(?:/1-1-1)?|three\s+times\s+daily)\s*\))?|1-1-1", s):
        return "three times daily"

    # Recognized four-times-daily expressions
    if re.fullmatch(r"(?i)qid|four\s+times\s+daily(?:\s*\(\s*qid\s*\))?|1-1-1-1|1-0-1-0", s):
        return "four times daily"

    # Recognized as-needed expressions
    if re.fullmatch(r"(?i)prn|as\s+needed(?:\s*\(\s*prn\s*\))?", s):
        return "as needed"

    # Prevent nested duplications like 'Once Daily (once daily)'
    s_cleaned = re.sub(r"(?i)\bonce\s+daily\b\s*\(\s*(?:once\s+daily|od)\s*\)", "once daily", s)
    s_cleaned = re.sub(r"(?i)\bOD\b\s*\(\s*(?:once\s+daily|od)\s*\)", "once daily", s_cleaned)
    if s_cleaned != s:
        return s_cleaned

    if re.search(r"\bOD\b", s):
        return re.sub(r"\bOD\b", "once daily", s)

    return s


def _expand_frequency(freq: Optional[Any]) -> Optional[str]:
    """Backward compatibility wrapper for _normalize_frequency."""
    return _normalize_frequency(freq)


def _format_patient_med_line(med: dict) -> str:
    raw_name = med.get("verified_name") or med.get("name") or "Medication"
    name = _clean_patient_text(raw_name).lower()
    raw_strength = med.get("strength")
    strength = _format_patient_strength(raw_strength)
    raw_freq = med.get("frequency")
    freq = _normalize_frequency(raw_freq)
    timing = _clean_patient_text(med.get("timing"))
    dur = _clean_patient_text(med.get("duration"))

    parts = [name]
    if strength and strength.lower() != "none":
        parts.append(strength)

    line = " ".join(parts)
    if freq and freq.lower() != "none":
        line = f"{line}, {freq}"

    if timing and timing.lower() not in ("unspecified", "none", "unknown", ""):
        line = f"{line} ({timing.lower()})"
    if dur and dur.lower() != "none":
        line = f"{line} for {dur}"

    return line


def _build_dlti_deterministic_block(dlti: Optional[dict]) -> str:
    """
    Renders the deterministic Medication-Laboratory Interaction (DLTI) research preview block.
    Always sourced strictly from structured DLTI results, never generated by LLM.
    Carries prominent research-preview labels and clinical disclaimers.
    """
    if not dlti or not isinstance(dlti, dict):
        return ""

    status = dlti.get("status", "DLTI_DISABLED")
    preview_label = dlti.get("research_preview_label", "Research preview — not clinically validated")
    coverage = dlti.get("coverage", {})
    results = dlti.get("results", [])

    lines = [
        "---",
        "## 🔬 Medication–Laboratory Interaction (DLTI) Research Preview",
        f"> ⚠️ **{preview_label}**",
        "",
    ]

    if status == "DLTI_DISABLED":
        lines.append(
            "> ℹ️ **Status: DLTI_DISABLED.** "
            "DLTI research preview is disabled by default. "
            "Server-side enablement (DLTI_RESEARCH_PREVIEW_ENABLED=True) is required to evaluate research rules."
        )
        lines.append("")
        return "\n".join(lines)

    if status == "DLTI_KB_UNAVAILABLE":
        lines.append(
            "> ⚠️ **Status: DLTI_KB_UNAVAILABLE.** "
            "The DLTI research knowledge base could not be loaded. "
            "No drug-laboratory interaction rules could be evaluated."
        )
        lines.append("")
        return "\n".join(lines)

    # Coverage table
    kb_info = dlti.get("knowledge_base", {})
    kb_id = kb_info.get("id", "DLTI_KB_001")
    kb_ver = kb_info.get("version", "0.2.0")

    lines.append("### DLTI Coverage Summary")
    lines.append(
        f"| Metric | Value |\n"
        f"| :--- | :--- |\n"
        f"| Knowledge Base | `{kb_id}` (v{kb_ver}) |\n"
        f"| Coverage Label | `{coverage.get('coverage_label', 'UNKNOWN')}` |\n"
        f"| Pairs Evaluated | {coverage.get('pairs_evaluated', 0)} |\n"
        f"| Pairs with Matching Rule | {coverage.get('pairs_with_matching_rule', 0)} |\n"
        f"| Rules Triggered | {coverage.get('rules_triggered', 0)} |\n"
        f"| Rules Evaluated (Not Triggered) | {coverage.get('rules_evaluated_not_triggered', 0)} |\n"
        f"| Rules Insufficient Context | {coverage.get('rules_insufficient_context', 0)} |\n"
        f"| Rules Disabled (Research) | {coverage.get('rules_disabled', 0)} |\n"
        f"| Rules Not Applicable | {coverage.get('rules_not_applicable', 0)} |\n"
        f"| Pairs No Rule Found | {coverage.get('pairs_no_rule_found', 0)} |\n"
        f"| Unverified Meds Skipped | {coverage.get('unverified_meds_skipped', 0)} |"
    )
    lines.append("")

    # Input provenance summary table
    prov_records = dlti.get("lab_input_provenance") or []
    sub_measurements = dlti.get("submitted_measurements") or []

    if prov_records or sub_measurements:
        lines.append("### Submitted Laboratory Measurements (Input Provenance)")
        lines.append(
            "| Submitted Analyte | Submitted Value | Validation Status | Reference Range / Rule | Derived Status / Notes |\n"
            "| :--- | :--- | :--- | :--- | :--- |"
        )
        if prov_records:
            for prec in prov_records:
                raw_a = prec.get("submitted_analyte")
                if raw_a is not None and str(raw_a).strip() != "" and str(raw_a).strip().lower() != "none":
                    analyte_col = f"`{_clean_md_cell(raw_a)}`"
                else:
                    analyte_col = "—"

                val_str = _format_provenance_value(
                    prec.get("submitted_value"),
                    prec.get("submitted_unit"),
                    prec.get("submitted_timing")
                )
                v_stat = _clean_md_cell(prec.get("validation_status") or "UNKNOWN")

                rule_id = prec.get("rule_id")
                ref_range = prec.get("reference_range")
                if rule_id and ref_range:
                    rule_info = f"`{_clean_md_cell(rule_id)}` ({_clean_md_cell(ref_range)})"
                elif rule_id:
                    rule_info = f"`{_clean_md_cell(rule_id)}`"
                elif ref_range:
                    rule_info = _clean_md_cell(ref_range)
                else:
                    rule_info = "—"

                notes = _clean_md_cell(prec.get("derived_status") or prec.get("rejection_reason") or "—")
                lines.append(f"| {analyte_col} | {val_str} | `{v_stat}` | {rule_info} | {notes} |")
        else:
            for sm in sub_measurements:
                a_name = sm.get("analyte") or sm.get("name")
                analyte_col = f"`{_clean_md_cell(a_name)}`" if a_name else "—"
                val_str = _format_provenance_value(
                    sm.get("value"),
                    sm.get("unit"),
                    sm.get("timing")
                )
                v_stat = _clean_md_cell(sm.get("status") or "UNCLASSIFIED")
                r_info = _clean_md_cell(sm.get("range_description") or sm.get("rule_id") or "—")
                notes = _clean_md_cell(sm.get("rejection_reason") or "Extracted from context")
                lines.append(f"| {analyte_col} | {val_str} | `{v_stat}` | {r_info} | {notes} |")
        lines.append("")

    if coverage.get('coverage_label') == 'RESEARCH_PREVIEW_NO_PAIRS' or coverage.get('pairs_evaluated', 0) == 0:
        lines.append(
            "> ℹ️ **No evaluated pairs (RESEARCH_PREVIEW_NO_PAIRS).** "
            "No current laboratory measurements were evaluated against verified medications. "
            "This does not indicate absence of drug-laboratory interactions, safety alerts, or warnings."
        )
        lines.append("")

    if results:
        lines.append("### DLTI Evaluation Findings")
        for res in results:
            res_status = res.get("status", "UNKNOWN")
            rule_id = res.get("rule_id", "N/A")
            cat = res.get("relationship_category", "RESEARCH_CANDIDATE")
            advisory = res.get("clinical_advisory")

            if res_status == "DLTI_TRIGGERED":
                title = advisory.get("summary_title", f"{rule_id} Finding") if advisory else f"{rule_id} Triggered"
                adv_text = advisory.get("authored_advisory_text", "") if advisory else ""
                lines.append(f"#### 🔴 {title} (`{rule_id}`)")
                lines.append(f"- **Category**: `{cat}`")
                lines.append(f"- **Status**: `{res_status}`")
                lines.append(f"- **Evaluation Detail**: {res.get('evaluation_detail', '')}")
                if adv_text:
                    lines.append(f"- **Clinical Advisory**: {adv_text}")
                evidence = res.get("evidence_summary") or []
                if evidence:
                    lines.append("- **Source References**:")
                    for ev in evidence:
                        src_name = ev.get("source_name", "Source")
                        doc_id = ev.get("document_id") or ev.get("exact_product_name", "")
                        sec = ev.get("section", "")
                        url = ev.get("source_url", "")
                        ref_str = f"  - *{src_name}* ({doc_id}), Section: {sec}"
                        if url:
                            ref_str += f" [Link]({url})"
                        lines.append(ref_str)
                lines.append("- **Limitations & Scope**: Evaluated strictly against current-request laboratory data; historical laboratory records were not retrieved (prescription-only evaluation). Autonomous dose changes or discontinuation are strictly prohibited.")
                lines.append(
                    "> ⚠️ *Research finding only — not clinically validated. "
                    "Does not establish clinical causation or diagnose any disease.*"
                )
                lines.append("")

            elif res_status == "DLTI_INSUFFICIENT_CONTEXT":
                lines.append(f"#### ❓ {rule_id}: Insufficient Context (`{res_status}`)")
                lines.append(f"- **Category**: `{cat}`")
                for note in res.get("applicability_notes", []):
                    lines.append(f"- {note}")
                lines.append("")

            elif res_status == "DLTI_RULE_DISABLED":
                lines.append(f"#### ⏸️ {rule_id}: Disabled Research Candidate (`{res_status}`)")
                lines.append(f"- **Category**: `{cat}`")
                for note in res.get("applicability_notes", []):
                    lines.append(f"- {note}")
                lines.append("")

            elif res_status == "DLTI_RULE_EVALUATED":
                lines.append(f"#### ⬜ {rule_id}: Rule Evaluated — Condition Not Met (`{res_status}`)")
                lines.append(f"- **Category**: `{cat}`")
                lines.append(f"- **Detail**: {res.get('evaluation_detail', '')}")
                lines.append("")

            elif res_status == "DLTI_NOT_APPLICABLE":
                lines.append(f"#### ⚠️ {rule_id}: Rule Not Applicable (`{res_status}`)")
                for note in res.get("applicability_notes", []):
                    lines.append(f"- {note}")
                lines.append("")

            elif res_status == "DLTI_NO_RULE_FOUND":
                med_raw = res.get("medication_raw", "?")
                analyte_raw = res.get("analyte_raw", "?")
                lines.append(f"#### ℹ️ No Rule Found: {med_raw} + {analyte_raw} (`{res_status}`)")
                lines.append(f"- {res.get('message', 'Absence of a rule is not evidence of safety.')}")
                lines.append("")

    return "\n".join(lines)


def _validate_llm_output_against_ddi(llm_text: str, ddi: dict, dlti: Optional[dict] = None) -> tuple:
    """
    Validates LLM explanation text against structured DDI and DLTI findings.

    Checks:
    1. LLM does not contain fabrication patterns (stop, discontinue, replace, etc.)
    2. LLM does not claim "no interactions" when INTERACTION_FOUND exists.
    3. LLM does not claim "no interactions" when coverage is partial, unavailable, or 0 pairs (no_pairs).
    4. LLM does not interpret "Unknown" severity as Minor, harmless, or safe.
    5. LLM does not claim "no safety alerts or warnings" when DLTI evaluation has 0 pairs,
       is disabled/unavailable, or has insufficient context.

    Returns:
        (is_valid: bool, violations: list[str])
    """
    if not llm_text or not isinstance(llm_text, str):
        return True, []  # empty text is handled by caller; not a fabrication

    violations = []
    text_lower = llm_text.lower()

    # Check fabrication patterns
    for pattern in _DDI_FABRICATION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            violations.append(
                f"LLM output contains prohibited language matching pattern: '{pattern}'"
            )

    # Check false "no interactions" claim when interactions were found
    interactions_found = ddi.get("interactions_found", []) if ddi else []
    overall_status = ddi.get("overall_status", "") if ddi else ""

    no_interaction_patterns = [
        r"\bno\s+drug\s+interactions?\b",
        r"\bno\s+interactions?\s+found\b",
        r"\bno\s+known\s+interactions?\b",
        r"\bsafe\s+to\s+combine\b",
        r"\bno\s+interaction\s+detected\b",
        r"\bno\s+ddi\b",
        r"\bno\s+(?:other\s+)?interactions?\s+with\s+(?:other\s+)?(?:medications?|drugs?)\b",
        r"\bno\s+interactions?\s+with\s+any\s+other\b",
        r"\bwithout\s+(?:any\s+)?interactions?\b",
        r"\bfree\s+of\s+interactions?\b",
        r"\bno\s+(?:other\s+)?interactions?\b",
        r"\b(?:did\s+not|not)\s+find\s+any\s+interactions?\b",
        r"\b(?:did\s+not|not)\s+find\s+any\s+interactions?\s+with\s+(?:other\s+)?(?:medications?|drugs?)\b",
        r"\binteractions?\s+with\s+other\s+(?:medications?|drugs?)\b",
    ]
    makes_safe_claim = any(re.search(pat, text_lower) for pat in no_interaction_patterns)

    if interactions_found and makes_safe_claim:
        violations.append(
            "LLM output claims no interactions despite INTERACTION_FOUND results in DDI data."
        )

    cov_comp = (ddi.get("coverage_completeness") or ddi.get("coverage", {}).get("coverage_completeness", "")) if ddi else ""
    if (overall_status in ("partial", "partial_dataset", "resource_unavailable", "prescription_only", "no_pairs") or cov_comp not in ("FULL", "")) and makes_safe_claim:
        violations.append(
            f"LLM output claims no interactions with other medications but DDI coverage is '{cov_comp or overall_status}' (not unqualified FULL)."
        )

    # Check minimization of Unknown severity
    has_unknown = any(
        "unknown" in str(p.get("level", "")).lower()
        for p in interactions_found
    )
    if has_unknown:
        minimization_patterns = [
            r"unknown.*(?:minor|harmless|safe|low risk|not serious|negligible|mild)",
            r"(?:minor|harmless|safe|mild).*unknown",
        ]
        for pat in minimization_patterns:
            if re.search(pat, text_lower):
                violations.append(
                    "LLM output minimizes 'Unknown' severity interaction as minor, harmless, or safe."
                )
                break

    # DLTI safety validation: missing DLTI evaluation must not become "no safety alerts or warnings"
    # Also, triggered safety alerts must not be contradicted by "no safety alerts"
    if dlti and isinstance(dlti, dict):
        dlti_status = dlti.get("status", "")
        dlti_cov = dlti.get("coverage", {})
        dlti_pairs = dlti_cov.get("pairs_evaluated", 0)
        dlti_triggered = dlti_cov.get("rules_triggered", 0)
        has_insufficient_context = any(
            r.get("status") == "DLTI_INSUFFICIENT_CONTEXT"
            for r in dlti.get("results", [])
        )
        if (
            dlti_status in ("DLTI_DISABLED", "DLTI_KB_UNAVAILABLE")
            or dlti_pairs == 0
            or has_insufficient_context
            or dlti_triggered > 0
        ):
            no_safety_patterns = [
                r"\bno\s+safety\s+alerts?\b",
                r"\bno\s+safety\s+warnings?\b",
                r"\bno\s+safety\s+alerts?\s+or\s+warnings?\b",
                r"\bno\s+safety\s+concerns?\b",
                r"\bno\s+(?:drug-lab|laboratory|medication-lab)\s+interactions?\b",
                r"\bfree\s+of\s+(?:safety\s+)?(?:alerts?|warnings?)\b",
                r"\bno\s+warnings?\b",
            ]
            for pat in no_safety_patterns:
                if re.search(pat, text_lower):
                    violations.append(
                        f"LLM output claims no safety alerts or warnings ('{pat}') when DLTI evaluation has 0 pairs, is disabled/unavailable, lacks required clinical context, or has triggered findings."
                    )
                    break

    return len(violations) == 0, violations


class PrescriptionReasoningAgent:
    """
    Step 5 Prescription Reasoning Agent.
    Generates patient-friendly explanations for verified prescription items
    under strict governance of the Verification and DDI Checking Agents.
    """

    @classmethod
    def build_patient_friendly_summary(
        cls,
        verified_meds,
        unverified_meds,
        ddi: Optional[dict] = None,
        dlti: Optional[dict] = None,
        med_lab_checks: Optional[list] = None,
        overall_status: str = "completed",
        ai_note: Optional[str] = None,
    ) -> str:
        """
        Builds Section A: Patient-friendly summary layer.
        Deterministic, plain-language, non-diagnostic, and non-causal.
        Never leaks internal rule IDs, coverage codes, or authorization details.
        """
        try:
            lines = [
                "## 📋 Patient-Friendly Summary",
                "",
                "> ℹ️ **Important Notice:** This is an informational research tool, not a diagnosis or treatment recommendation. Do not change your medicine based on this report.",
                "",
            ]

            # --- Subsection: Your prescription ---
            lines.append("### Your prescription")
            if verified_meds:
                if len(verified_meds) == 1:
                    med_line = _format_patient_med_line(verified_meds[0])
                    lines.append(f"The uploaded prescription lists {med_line}.")
                else:
                    lines.append("The uploaded prescription lists the following medicines:")
                    for med in verified_meds:
                        med_line = _format_patient_med_line(med)
                        lines.append(f"- {med_line}.")
            else:
                lines.append("The uploaded document did not list any verified prescription medicines.")

            if unverified_meds:
                unverified_names = [
                    _clean_patient_text(m.get("raw_name") or m.get("name") or "unclear item")
                    for m in unverified_meds
                ]
                unverified_str = ", ".join(f"'{n}'" for n in unverified_names if n)
                lines.append(
                    f"The prescription also contains unverified or ambiguous item(s): {unverified_str}, "
                    "which require confirmation with your doctor or pharmacist."
                )
            lines.append("")

            # --- Subsection: What this review found ---
            lines.append("### What this review found")
            lines_found = []

            # 1. DLTI findings
            dlti_results = dlti.get("results", []) if (dlti and isinstance(dlti, dict)) else []
            triggered_dlti = [r for r in dlti_results if r.get("status") == "DLTI_TRIGGERED"]
            dlti_cov = dlti.get("coverage", {}) if (dlti and isinstance(dlti, dict)) else {}
            prov_records = (dlti.get("lab_input_provenance") or []) if (dlti and isinstance(dlti, dict)) else []

            has_prednisone_glucose = False
            for r in triggered_dlti:
                r_id = str(r.get("rule_id", "")).lower()
                r_title = ""
                if r.get("clinical_advisory"):
                    r_title = str(r.get("clinical_advisory", {}).get("summary_title", "")).lower()
                if "prednisone" in r_id or "glucose" in r_id or "corticosteroid" in r_title:
                    has_prednisone_glucose = True
                    break

            if has_prednisone_glucose:
                lines_found.append(
                    "The submitted blood sugar (glucose) test result matched an informational research rule "
                    "concerning prednisone and elevated blood sugar. Prednisone can cause blood sugar levels to rise. "
                    "This finding does not establish prednisone as the cause of your result and does not diagnose diabetes."
                )
            elif triggered_dlti:
                for tr in triggered_dlti:
                    lines_found.append(
                        "The submitted laboratory test result matched an informational research candidate rule "
                        "for the listed medication. This finding does not establish clinical causation and does not diagnose any condition."
                    )

            # Evaluated but not triggered
            if dlti_cov.get("rules_evaluated_not_triggered", 0) > 0:
                lines_found.append("The evaluated research rule did not flag this submitted combination.")

            # Insufficient context outcomes
            # Distinguish: missing numeric value/unit vs missing timing vs generic missing context
            missing_val_records = [
                p for p in prov_records
                if p.get("validation_status") == "REJECTED_MISSING_VALUE"
            ]
            timing_missing_records = [
                p for p in prov_records
                if (
                    p.get("validation_status") == "INSUFFICIENT_CONTEXT"
                    or p.get("rule_id") == "GLUCOSE_TIMING_CONTEXT_REQUIRED"
                    or (p.get("rejection_reason") and "timing" in str(p.get("rejection_reason")).lower())
                ) and p.get("validation_status") != "REJECTED_MISSING_VALUE"
            ]

            if missing_val_records:
                for prec in missing_val_records:
                    raw_a = prec.get("submitted_analyte") or "laboratory test"
                    clean_a = _clean_patient_text(raw_a)
                    raw_u = prec.get("submitted_unit")
                    unit_absent = (not raw_u or str(raw_u).strip() == "" or str(raw_u).strip().lower() == "none")
                    if "glucose" in str(raw_a).lower():
                        if unit_absent:
                            lines_found.append(
                                "The blood sugar check could not be completed because the test result and unit were not provided."
                            )
                        else:
                            lines_found.append(
                                "The blood sugar check could not be completed because the test result was not provided."
                            )
                    else:
                        if unit_absent:
                            lines_found.append(
                                f"The {clean_a} check could not be completed because the test result and unit were not provided."
                            )
                        else:
                            lines_found.append(
                                f"The {clean_a} check could not be completed because the test result was not provided."
                            )
            elif timing_missing_records:
                for prec in timing_missing_records:
                    raw_a = prec.get("submitted_analyte") or "laboratory test"
                    clean_a = _clean_patient_text(raw_a)
                    if "glucose" in str(raw_a).lower():
                        lines_found.append(
                            "The blood sugar check could not be completed because the required test timing context was not provided."
                        )
                    else:
                        lines_found.append(
                            f"The {clean_a} check could not be completed because the required test timing context was not provided."
                        )
            elif dlti_cov.get("rules_insufficient_context", 0) > 0:
                lines_found.append(
                    "The medication–laboratory check could not be completed because required laboratory context was not provided."
                )

            # Disabled / unavailable / no-input DLTI outcomes
            is_no_labs_submitted = any(
                p.get("validation_status") == "NONE_SUBMITTED"
                for p in prov_records
            ) or (
                not prov_records
                and dlti_cov.get("pairs_evaluated", 0) == 0
                and not (dlti and dlti.get("submitted_measurements"))
            )
            if dlti and dlti.get("status") == "DLTI_DISABLED":
                lines_found.append(
                    "Medication–laboratory interaction research review is disabled, so drug–laboratory evaluations were not performed."
                )
            elif dlti and dlti.get("status") == "DLTI_KB_UNAVAILABLE":
                lines_found.append(
                    "The medication–laboratory research knowledge base was unavailable, so drug–laboratory evaluations were not performed."
                )
            elif is_no_labs_submitted and not missing_val_records and not timing_missing_records and not triggered_dlti and dlti_cov.get("rules_evaluated_not_triggered", 0) == 0:
                lines_found.append(
                    "No laboratory test measurements were submitted with this prescription, so potential medication–laboratory interactions could not be assessed."
                )

            # 2. DDI findings
            ddi_interactions = ddi.get("interactions_found", []) if (ddi and isinstance(ddi, dict)) else []
            ddi_cov = ddi.get("coverage", {}) if (ddi and isinstance(ddi, dict)) else {}
            if ddi_interactions:
                for pair in ddi_interactions:
                    drug_a = _clean_patient_text(pair.get("drug_a", "Drug A"))
                    drug_b = _clean_patient_text(pair.get("drug_b", "Drug B"))
                    level = pair.get("level")
                    level_str = ""
                    if level and "unknown" not in str(level).lower():
                        level_str = f" (recorded severity: {_clean_patient_text(level)})"
                    lines_found.append(
                        f"A potential interaction was found between **{drug_a}** and **{drug_b}** in the reference database{level_str}. "
                        "Consult your prescribing doctor or pharmacist before taking both medicines together."
                    )
            elif ddi_cov.get("total_pairs_checked", 0) > 0 and ddi.get("overall_status") == "checked":
                lines_found.append(
                    "No interaction records were found in the reference database for the checked medicine pair(s)."
                )

            # 3. Verification safety alerts
            if med_lab_checks:
                for alert in med_lab_checks:
                    title = _clean_patient_text(alert.get("title", "Safety Alert"))
                    expl = _clean_patient_text(alert.get("explanation", ""))
                    lines_found.append(f"{title}: {expl}")

            # 4. Optional valid AI note
            if ai_note and isinstance(ai_note, str) and ai_note.strip():
                clean_ai = ai_note.strip()
                if not clean_ai.startswith("#") and "patient-friendly summary" not in clean_ai.lower():
                    lines_found.append(clean_ai)

            if not lines_found:
                lines_found.append("No completed interaction or laboratory evaluations were available to report.")

            for lf in lines_found:
                lines.append(lf)
            lines.append("")

            # --- Subsection: What could not be checked ---
            lines.append("### What could not be checked")
            lines_not_checked = []

            prov_records = (dlti.get("lab_input_provenance") or []) if (dlti and isinstance(dlti, dict)) else []

            # Case C: Analyte supplied, numeric value missing
            missing_val_records = [
                p for p in prov_records
                if p.get("validation_status") == "REJECTED_MISSING_VALUE"
            ]
            if missing_val_records:
                for prec in missing_val_records:
                    raw_analyte = prec.get("submitted_analyte") or "laboratory test"
                    raw_unit = prec.get("submitted_unit")
                    clean_analyte = _clean_patient_text(raw_analyte)
                    unit_absent = (not raw_unit or str(raw_unit).strip() == "" or str(raw_unit).strip().lower() == "none")

                    if "glucose" in str(raw_analyte).lower():
                        if unit_absent:
                            lines_not_checked.append(
                                "The glucose result and unit were missing, so the blood sugar check could not be completed. "
                                "This neither establishes nor rules out a problem."
                            )
                        else:
                            lines_not_checked.append(
                                f"The glucose result was missing (unit provided: {raw_unit}), so the blood sugar check could not be completed. "
                                "This neither establishes nor rules out a problem."
                            )
                    else:
                        if unit_absent:
                            lines_not_checked.append(
                                f"The {clean_analyte} result and unit were missing, so the check could not be completed. "
                                "This neither establishes nor rules out a problem."
                            )
                        else:
                            lines_not_checked.append(
                                f"The {clean_analyte} result was missing, so the check could not be completed. "
                                "This neither establishes nor rules out a problem."
                            )

            # Numeric result supplied, timing missing
            timing_missing_records = [
                p for p in prov_records
                if (
                    p.get("validation_status") == "INSUFFICIENT_CONTEXT"
                    or p.get("rule_id") == "GLUCOSE_TIMING_CONTEXT_REQUIRED"
                    or (p.get("rejection_reason") and "timing" in str(p.get("rejection_reason")).lower())
                ) and p.get("validation_status") != "REJECTED_MISSING_VALUE"
            ]
            if timing_missing_records:
                for prec in timing_missing_records:
                    val = prec.get("submitted_value")
                    unit = prec.get("submitted_unit") or ""
                    clean_analyte = _clean_patient_text(prec.get("submitted_analyte") or "Glucose")
                    val_unit_str = f"{val} {unit}".strip() if val is not None else ""

                    if "glucose" in str(clean_analyte).lower():
                        if val_unit_str:
                            lines_not_checked.append(
                                f"The blood sugar (glucose) test was provided ({val_unit_str}), but whether the test "
                                "was taken while fasting or at another time was not specified, so the blood sugar check "
                                "could not be completed. This neither establishes nor rules out a problem."
                            )
                        else:
                            lines_not_checked.append(
                                "The blood sugar (glucose) test was provided, but whether the test was taken while fasting "
                                "or at another time was not specified, so the blood sugar check could not be completed. "
                                "This neither establishes nor rules out a problem."
                            )
                    else:
                        lines_not_checked.append(
                            f"The {clean_analyte} test was provided, but the required clinical timing context "
                            "was not specified, so the check could not be completed. "
                            "This neither establishes nor rules out a problem."
                        )

            # No laboratory measurement submitted
            is_no_labs_submitted = any(
                p.get("validation_status") == "NONE_SUBMITTED"
                for p in prov_records
            ) or (
                not prov_records
                and dlti_cov.get("pairs_evaluated", 0) == 0
                and not (dlti and dlti.get("submitted_measurements"))
            )
            if is_no_labs_submitted and not missing_val_records and not timing_missing_records:
                lines_not_checked.append(
                    "No laboratory test measurements were submitted with this prescription, "
                    "so potential medication–laboratory interactions could not be assessed."
                )

            # Disabled or unavailable DLTI
            if dlti and dlti.get("status") == "DLTI_DISABLED":
                lines_not_checked.append(
                    "Medication–laboratory interaction research review is currently disabled, "
                    "so drug–laboratory evaluations were not performed."
                )
            elif dlti and dlti.get("status") == "DLTI_KB_UNAVAILABLE":
                lines_not_checked.append(
                    "The research interaction knowledge base could not be loaded, "
                    "so medication–laboratory rules could not be evaluated."
                )

            # Unrecognized analyte or invalid numeric
            for p in prov_records:
                v_stat = p.get("validation_status")
                if v_stat == "REJECTED_UNRECOGNIZED_ANALYTE":
                    raw_a = _clean_patient_text(p.get("submitted_analyte") or "test")
                    lines_not_checked.append(
                        f"The submitted laboratory test '{raw_a}' was not recognized in the reference rules, "
                        "so its relationship with your medication could not be evaluated."
                    )
                elif v_stat == "REJECTED_INVALID_NUMERIC":
                    lines_not_checked.append(
                        "The submitted laboratory test value was not recognized as a valid number, "
                        "so it could not be evaluated."
                    )

            # DDI Coverage Limitations
            resolved_count = ddi_cov.get("resolved_ingredients_count")
            if resolved_count is None:
                resolved_count = ddi_cov.get("verified_meds", len(verified_meds) if verified_meds else 0)
            pairs_checked = ddi_cov.get("total_pairs_checked", 0)
            ddi_overall = ddi.get("overall_status", "") if (ddi and isinstance(ddi, dict)) else ""

            if ddi_overall == "no_pairs" or pairs_checked == 0:
                if resolved_count == 1:
                    lines_not_checked.append(
                        "Only one medicine ingredient was available, so no medicine pair could be compared."
                    )
                elif resolved_count == 0:
                    lines_not_checked.append(
                        "No resolved medicine ingredients were available, so no medicine pair could be compared."
                    )
                else:
                    lines_not_checked.append(
                        f"{resolved_count} medicine ingredients were available, but no eligible pairs could be formed to compare."
                    )

            # Historical medication access blocked
            is_history_blocked = (
                ddi_cov.get("history_retrieval_status") in ("BLOCKED_NO_AUTHORIZATION", "FAILED", "UNAUTHORIZED")
                or ddi_cov.get("prescription_only_coverage")
                or ddi_overall == "prescription_only"
            )
            if is_history_blocked:
                lines_not_checked.append(
                    "Medication history was unavailable, so interactions with other medicines could not be assessed."
                )

            # Unresolved ingredients in DDI
            unresolved_ingredients = ddi_cov.get("unresolved_ingredients", [])
            if unresolved_ingredients:
                unres_str = ", ".join(f"'{_clean_patient_text(u)}'" for u in unresolved_ingredients)
                lines_not_checked.append(
                    f"Some medicine ingredients ({unres_str}) could not be resolved in the interaction database, "
                    "so possible interactions involving them could not be checked."
                )

            if ddi_overall == "resource_unavailable":
                lines_not_checked.append(
                    "The drug interaction reference dataset is not configured, so drug-drug interactions could not be checked."
                )

            if not lines_not_checked:
                lines.append("- No additional unassessed items or limitations were identified.")
            else:
                for lnc in lines_not_checked:
                    lines.append(f"- {lnc}")
            lines.append("")

            # --- Subsection: What you can do next ---
            lines.append("### What you can do next")
            lines_next = []

            if missing_val_records:
                lines_next.append(
                    "If you have the test report, enter the result, unit, and timing exactly as recorded. "
                    "If you are unsure, ask your doctor or pharmacist for help."
                )

            if timing_missing_records:
                lines_next.append(
                    "If you have the test report, check whether the blood sugar test was taken while fasting or at random "
                    "and re-enter the test with that timing, or consult your healthcare provider."
                )

            if has_prednisone_glucose:
                lines_next.append(
                    "Discuss this finding and your prescription with your doctor or pharmacist. "
                    "Do not stop, taper, increase, or reduce your medication on your own."
                )
            elif triggered_dlti:
                lines_next.append(
                    "Discuss this research finding with your doctor or pharmacist. "
                    "Do not stop, start, or change your medication on your own."
                )

            if ddi_interactions:
                lines_next.append(
                    "Speak with your prescribing doctor or pharmacist about the potential interaction before combining these medicines."
                )

            if unverified_meds:
                lines_next.append("Ask your doctor or pharmacist to confirm any unclear or unverified prescription items.")

            lines_next.append(
                "Bring your prescription and any recent lab reports with you to your next appointment for professional review."
            )
            lines_next.append(
                "Do not stop, start, or change the dose of any medicine without guidance from a qualified healthcare professional."
            )

            for ln in lines_next:
                lines.append(f"- {ln}")
            lines.append("")

            # --- Subsection: Important limits ---
            lines.append("### Important limits")
            lines.append(
                "- This report is generated by an informational research prototype, not a medical device. "
                "It does not provide medical diagnoses, treatment instructions, or clinical recommendations."
            )
            lines.append(
                "- Absence of a flagged interaction does not mean that a medicine combination is completely safe "
                "or that all possible interactions have been ruled out."
            )
            lines.append(
                "- This review evaluated only the specific items and measurements submitted in this request. "
                "Other medications, over-the-counter products, dietary supplements, and historical health "
                "conditions were not assessed."
            )

            return "\n".join(lines)

        except Exception as err:
            logger.warning("Error generating patient-friendly summary: %s", err)
            return (
                "## 📋 Patient-Friendly Summary\n\n"
                "> ℹ️ **Important Notice:** This is an informational research tool, not a diagnosis or treatment recommendation. Do not change your medicine based on this report.\n\n"
                "### Your prescription\n"
                "The uploaded prescription could not be completely summarized due to an unexpected data issue.\n\n"
                "### What this review found\n"
                "This check could not be completed.\n\n"
                "### What could not be checked\n"
                "The requested evaluation review could not be completed from the supplied information.\n\n"
                "### What you can do next\n"
                "- Consult your prescribing doctor or a licensed pharmacist to review your prescription and test results.\n"
                "- Do not stop, start, or change your medication without professional medical advice.\n\n"
                "### Important limits\n"
                "- This tool is an informational research prototype and does not provide clinical care or diagnosis."
            )

    @classmethod
    def build_technical_details_block(
        cls,
        verified_meds,
        unverified_meds,
        overall_status,
        med_lab_checks=None,
        ddi: Optional[dict] = None,
        dlti: Optional[dict] = None,
        hard_stop: bool = False,
    ) -> str:
        """
        Builds Section B: Technical details and evidence.
        Preserves all existing DDI and DLTI coverage tables, input provenance,
        rule identifiers, and clinical evidence sources.
        """
        try:
            lines = [
                "---",
                "## 🔬 Technical Details and Evidence",
                "",
                f"### Prescription Verification & Extracted Items (Status: `{overall_status}`)",
                "",
            ]

            if hard_stop:
                lines.append(f"> ⚠️ **SAFETY ALERT:** {HARD_STOP_MESSAGE}\n")

            if verified_meds:
                lines.append("#### Verified Medications")
                for med in verified_meds:
                    name = _clean_patient_text(med.get("verified_name") or med.get("name") or "Medication")
                    strength = _clean_patient_text(med.get("strength") or "Strength not specified")
                    freq = _clean_patient_text(med.get("frequency") or "Schedule not specified")
                    timing = _clean_patient_text(med.get("timing") or "")
                    dur = _clean_patient_text(med.get("duration") or "")

                    line = f"- **{name}** ({strength}): {freq}"
                    if timing:
                        line += f" — *{timing}*"
                    if dur:
                        line += f" (Duration: {dur})"
                    lines.append(line)
                lines.append("")

            if unverified_meds:
                lines.append("#### Review Required / Unverified Items")
                for med in unverified_meds:
                    raw = _clean_patient_text(med.get("raw_name") or med.get("name") or "Uncertain item")
                    status = _clean_patient_text(med.get("verification_status", "manual_review"))
                    lines.append(
                        f"- **{raw}** [Status: `{status}`] — Requires professional verification."
                    )
                lines.append("")

            if med_lab_checks:
                lines.append("#### Medication-Lab Safety Alerts")
                for alert in med_lab_checks:
                    lines.append(
                        f"- **{alert.get('title', 'Safety Alert')}**: {alert.get('explanation', '')}"
                    )
                lines.append("")

            # Always append the structured DDI block (from data, not LLM)
            ddi_block = _build_ddi_deterministic_block(ddi)
            if ddi_block:
                lines.append(ddi_block)
                lines.append("")

            # Always append the structured DLTI block (from data, not LLM)
            dlti_block = _build_dlti_deterministic_block(dlti)
            if dlti_block:
                lines.append(dlti_block)
                lines.append("")

            lines.append(f"_{PRESCRIPTION_DISCLAIMER}_")
            return "\n".join(lines)

        except Exception as err:
            logger.warning("Error generating technical details block: %s", err)
            return (
                "---\n## 🔬 Technical Details and Evidence\n\n"
                "### Prescription Verification & Extracted Items\n"
                "Technical evidence could not be generated due to an incomplete or conflicting state.\n\n"
                f"_{PRESCRIPTION_DISCLAIMER}_"
            )

    @classmethod
    def generate_deterministic_summary(
        cls,
        verified_meds,
        unverified_meds,
        overall_status,
        med_lab_checks=None,
        ddi: Optional[dict] = None,
        dlti: Optional[dict] = None,
    ):
        """
        Generates safe deterministic markdown summary.
        Used when LLM is unavailable, halted, or fails output validation.
        Always presents Section A (Patient-Friendly Summary) followed by
        Section B (Technical Details and Evidence).
        """
        try:
            patient_summary = cls.build_patient_friendly_summary(
                verified_meds=verified_meds,
                unverified_meds=unverified_meds,
                ddi=ddi,
                dlti=dlti,
                med_lab_checks=med_lab_checks,
                overall_status=overall_status,
                ai_note=None,
            )
            tech_block = cls.build_technical_details_block(
                verified_meds=verified_meds,
                unverified_meds=unverified_meds,
                overall_status=overall_status,
                med_lab_checks=med_lab_checks,
                ddi=ddi,
                dlti=dlti,
                hard_stop=(overall_status == "hard_stop"),
            )
            return f"{patient_summary}\n\n{tech_block}"
        except Exception as err:
            logger.warning("Error generating deterministic summary: %s", err)
            return (
                "## 📋 Patient-Friendly Summary\n\n"
                "> ℹ️ **Important Notice:** This is an informational research tool, not a diagnosis or treatment recommendation. Do not change your medicine based on this report.\n\n"
                "### Your prescription\n"
                "The uploaded prescription could not be completely summarized due to an unexpected data issue.\n\n"
                "### What this review found\n"
                "This check could not be completed.\n\n"
                "### What could not be checked\n"
                "The requested evaluation review could not be completed from the supplied information.\n\n"
                "### What you can do next\n"
                "- Consult your prescribing doctor or a licensed pharmacist to review your prescription and test results.\n"
                "- Do not stop, start, or change your medication without professional medical advice.\n\n"
                "### Important limits\n"
                "- This tool is an informational research prototype and does not provide clinical care or diagnosis.\n\n"
                "---\n## 🔬 Technical Details and Evidence\n\n"
                "### Prescription Verification & Extracted Items\n"
                "Technical evidence could not be generated due to an incomplete or conflicting state.\n\n"
                f"_{PRESCRIPTION_DISCLAIMER}_"
            )

    @classmethod
    def build_system_prompt(cls, ddi: Optional[dict] = None, dlti: Optional[dict] = None) -> str:
        base = (
            "You are an expert patient-friendly prescription explainer AI.\n"
            "Your role is to explain verified prescription instructions in simple, clear, reassuring language "
            "based STRICTLY on verified data.\n\n"
            "STRICT MANDATORY SAFETY RULES:\n"
            "1. ABSOLUTE PROHIBITION OF DIAGNOSES: You MUST NEVER declare or infer a disease diagnosis from "
            "medications.\n"
            "   (e.g., Metformin -> 'commonly used to help manage blood sugar', NEVER 'the patient has "
            "diabetes').\n"
            "2. ABSOLUTE PROHIBITION OF DOSAGE MODIFICATION: Never tell the patient to increase, decrease, "
            "start, or stop taking medication.\n"
            "3. NO FABRICATED INTERACTIONS: Mention ONLY explicit medication-lab safety alerts or DDI records "
            "supplied in the prompt. Do NOT invent any interaction not listed.\n"
            "4. NO OVERRIDING STATUS: Never present unverified, ambiguous, or unknown items as confirmed.\n"
            "5. KEEP DOSAGE INSTRUCTIONS ACCURATE: Explain exact verified schedules in plain language.\n"
            "6. DDI RULES:\n"
            "   a. Use ONLY the interaction records supplied below — do NOT invent severity labels or "
            "mechanism descriptions.\n"
            "   b. Preserve the dataset Level label verbatim (e.g. 'Major', 'Moderate', 'Minor').\n"
            "   c. Do NOT advise stopping, replacing, or switching any medicine.\n"
            "   d. If coverage is partial or the dataset is unavailable, say so explicitly.\n"
            "   e. NEVER describe NO_RECORD_FOUND as 'safe' or 'no interaction'.\n"
            "   f. If zero medication pairs were evaluated (no_pairs), you MUST NOT state or imply 'no interactions with other medications' or 'no drug interactions'.\n"
            "7. DLTI & LABORATORY RULES:\n"
            "   a. If no DLTI pairs were evaluated, DLTI is disabled, or clinical context is missing, you MUST NOT state 'no safety alerts or warnings' or 'no laboratory interactions'.\n"
        )

        # Inject DDI context facts for the LLM to reference
        if ddi:
            overall = ddi.get("overall_status", "unknown")
            interactions = ddi.get("interactions_found", [])
            coverage = ddi.get("coverage", {})

            base += "\n\nDDI CHECK RESULTS (facts supplied — do not modify or invent):\n"
            base += f"Dataset available: {coverage.get('dataset_available', False)}\n"
            base += f"Overall DDI coverage status: {overall}\n"
            base += f"Total pairs checked: {coverage.get('total_pairs_checked', 0)}\n"
            unresolved = coverage.get("unresolved_ingredients", [])
            if unresolved:
                base += f"Unresolved ingredients (DDI unknown): {', '.join(unresolved)}\n"

            if interactions:
                base += f"\nINTERACTION RECORDS FOUND ({len(interactions)} pair(s)):\n"
                for pair in interactions:
                    base += (
                        f"  - {pair['drug_a']} + {pair['drug_b']}: "
                        f"Level = {pair.get('level', '?')} "
                        f"(source: DDInter dataset)\n"
                    )
            elif overall == "no_pairs":
                base += (
                    "\nZero medication pairs were checked because only a single medication was submitted. "
                    "You MUST NOT claim 'no interactions with other medications'. Explicitly note that interaction "
                    "checking requires multiple medications and was not performed.\n"
                )
            elif overall == "checked":
                base += "\nNo interaction records were found for any checked pair.\n"
            elif overall == "partial":
                base += "\nSome pairs could not be checked due to unresolved drug identities.\n"
            elif overall == "resource_unavailable":
                base += "\nDDI dataset not configured — no pairs were checked.\n"

        if dlti:
            dlti_status = dlti.get("status", "DLTI_DISABLED")
            dlti_cov = dlti.get("coverage", {})
            dlti_pairs = dlti_cov.get("pairs_evaluated", 0)

            base += "\n\nDLTI CHECK RESULTS (facts supplied — do not modify or invent):\n"
            base += f"DLTI status: {dlti_status}\n"
            base += f"DLTI pairs evaluated: {dlti_pairs}\n"
            if dlti_status in ("DLTI_DISABLED", "DLTI_KB_UNAVAILABLE") or dlti_pairs == 0:
                base += (
                    "No medication-laboratory pairs were evaluated. "
                    "You MUST NOT state 'no safety alerts or warnings' or 'no laboratory interactions'.\n"
                )
            else:
                base += f"DLTI rules triggered: {dlti_cov.get('rules_triggered', 0)}\n"

        return base

    @classmethod
    def process(cls, pipeline_context, ai_generator_func=None):
        """
        Executes Prescription Reasoning Agent on pipeline_context.

        Populates context["reasoning"]:
        {
            "summary":                    str,   -- final explanation (LLM or deterministic)
            "ddi_block":                  str,   -- structured DDI block (always from data)
            "medications":                list,
            "unverified_medications":     list,
            "warnings":                   list,
            "review_required":            bool,
            "disclaimer":                 str,
            "generated_by":               str,
            "verification_status_used":   str,
            "ddi_validation_violations":  list,  -- LLM output validation failures
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        verification = pipeline_context.get("verification", {})
        overall_status = verification.get("overall_status", "manual_review")
        all_warnings = list(verification.get("warnings", []))

        # Pull DDI and DLTI data (Step 4b & Step 4c output)
        ddi = pipeline_context.get("ddi", {})
        ddi_warnings = ddi.get("warnings", []) if ddi else []
        all_warnings.extend(ddi_warnings)

        dlti = pipeline_context.get("dlti", {})

        # Build the structured DDI and DLTI blocks BEFORE any LLM call (always from data)
        ddi_block = _build_ddi_deterministic_block(ddi)
        dlti_block = _build_dlti_deterministic_block(dlti)

        # Helper to attach deterministic blocks
        def _attach_deterministic_blocks(text: str) -> str:
            res = (text or "").rstrip()
            if ddi_block:
                res = res + ("\n\n" if res else "") + ddi_block
            if dlti_block:
                res = res + ("\n\n" if res else "") + dlti_block
            return res

        # Filter Verified vs Unverified Medications
        medications = verification.get("medications", [])
        verified_meds = [
            m for m in medications
            if m.get("identity_verified")
            and m.get("verification_status") in ["verified", "verified_proposed"]
        ]
        unverified_meds = [
            m for m in medications
            if not m.get("identity_verified")
            or m.get("verification_status") in ["manual_review", "unknown", "unverified"]
        ]
        med_lab_checks = verification.get("medication_lab_checks", [])

        # 1. HARD STOP PRECEDENCE (CRITICAL SAFETY RULE)
        if overall_status == "hard_stop":
            logger.info(
                "PrescriptionReasoningAgent: hard_stop triggered. "
                "Returning safe review-required response (0 LLM calls)."
            )
            patient_summary = cls.build_patient_friendly_summary(
                verified_meds=[],
                unverified_meds=unverified_meds,
                ddi=ddi,
                dlti=dlti,
                med_lab_checks=med_lab_checks,
                overall_status="hard_stop",
                ai_note=None,
            )
            tech_block = cls.build_technical_details_block(
                verified_meds=[],
                unverified_meds=unverified_meds,
                overall_status="hard_stop",
                med_lab_checks=med_lab_checks,
                ddi=ddi,
                dlti=dlti,
                hard_stop=True,
            )
            full_summary = f"{patient_summary}\n\n{tech_block}"
            pipeline_context["reasoning"] = {
                "status":                   "completed",
                "summary":                  full_summary,
                "patient_summary":          patient_summary,
                "technical_details":        tech_block,
                "ddi_block":                ddi_block,
                "dlti_block":               dlti_block,
                "medications":              [],
                "unverified_medications":   [],
                "warnings":                 all_warnings,
                "review_required":          True,
                "disclaimer":               PRESCRIPTION_DISCLAIMER,
                "generated_by":             "hard_stop_policy",
                "verification_status_used": "hard_stop",
                "ddi_validation_violations": [],
            }
            return pipeline_context

        # Build structured reasoning medication entries for verified items
        reasoning_meds = []
        for vmed in verified_meds:
            name = vmed.get("verified_name") or vmed.get("name") or "Medication"
            strength = vmed.get("strength")
            freq = vmed.get("frequency")
            timing = vmed.get("timing")
            dur = vmed.get("duration")

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
                "name":                name,
                "strength":            strength,
                "frequency":           freq,
                "timing":              timing,
                "duration":            dur,
                "explanation":         " ".join(expl_parts) + ".",
                "verification_status": vmed.get("verification_status"),
            })

        review_req = overall_status == "manual_review" or len(unverified_meds) > 0

        # 3. AI Explanation Generation
        ai_summary = None
        generated_by = "deterministic_fallback"
        ddi_validation_violations: List[str] = []

        if ai_generator_func and verified_meds:
            try:
                user_prompt = (
                    f"Verified Prescription Items:\n{verified_meds}\n\n"
                    f"Unverified Items:\n{unverified_meds}\n\n"
                    f"Safety Alerts:\n{med_lab_checks}\n\n"
                    f"DDI Check Data:\n{ddi}"
                )
                sys_prompt = cls.build_system_prompt(ddi=ddi, dlti=dlti)

                logger.info("PrescriptionReasoningAgent: Executing AI Generator function...")
                ai_summary = ai_generator_func(user_prompt, sys_prompt)

                if ai_summary and isinstance(ai_summary, str) and ai_summary.strip():
                    # 4. Validate LLM output against structured DDI findings
                    is_valid, violations = _validate_llm_output_against_ddi(ai_summary, ddi, dlti=dlti)
                    if not is_valid:
                        ddi_validation_violations = violations
                        logger.warning(
                            "PrescriptionReasoningAgent: LLM output failed DDI validation "
                            "(%d violation(s)). Using deterministic fallback.",
                            len(violations)
                        )
                        all_warnings.extend(
                            [f"DDI output validation: {v}" for v in violations]
                        )
                        ai_summary = None  # Reject and fall through to deterministic
                    else:
                        generated_by = "ai_generator"
                        patient_summary = cls.build_patient_friendly_summary(
                            verified_meds=verified_meds,
                            unverified_meds=unverified_meds,
                            ddi=ddi,
                            dlti=dlti,
                            med_lab_checks=med_lab_checks,
                            overall_status=overall_status,
                            ai_note=ai_summary,
                        )
                        tech_block = cls.build_technical_details_block(
                            verified_meds=verified_meds,
                            unverified_meds=unverified_meds,
                            overall_status=overall_status,
                            med_lab_checks=med_lab_checks,
                            ddi=ddi,
                            dlti=dlti,
                        )
                        ai_summary = f"{patient_summary}\n\n{tech_block}"
                else:
                    ai_summary = None

            except Exception as ai_err:
                logger.warning(
                    "PrescriptionReasoningAgent: AI generation exception: %s. "
                    "Using deterministic fallback.", ai_err
                )
                all_warnings.append(f"AI generation exception: {ai_err}")
                ai_summary = None

        # 5. Deterministic fallback (always includes structured DDI and DLTI blocks from data)
        if not ai_summary:
            ai_summary = cls.generate_deterministic_summary(
                verified_meds,
                unverified_meds,
                overall_status,
                med_lab_checks=med_lab_checks,
                ddi=ddi,
                dlti=dlti,
            )
            if generated_by != "hard_stop_policy":
                generated_by = "deterministic_fallback"

        patient_summary_saved = cls.build_patient_friendly_summary(
            verified_meds=verified_meds,
            unverified_meds=unverified_meds,
            ddi=ddi,
            dlti=dlti,
            med_lab_checks=med_lab_checks,
            overall_status=overall_status,
        )
        tech_block_saved = cls.build_technical_details_block(
            verified_meds=verified_meds,
            unverified_meds=unverified_meds,
            overall_status=overall_status,
            med_lab_checks=med_lab_checks,
            ddi=ddi,
            dlti=dlti,
        )

        pipeline_context["reasoning"] = {
            "summary":                    ai_summary,
            "patient_summary":            patient_summary_saved,
            "technical_details":          tech_block_saved,
            "ddi_block":                  ddi_block,
            "dlti_block":                 dlti_block,
            "medications":                reasoning_meds,
            "unverified_medications":     unverified_meds,
            "warnings":                   all_warnings,
            "review_required":            review_req,
            "disclaimer":                 PRESCRIPTION_DISCLAIMER,
            "generated_by":               generated_by,
            "verification_status_used":   overall_status,
            "ddi_validation_violations":  ddi_validation_violations,
        }

        return pipeline_context
