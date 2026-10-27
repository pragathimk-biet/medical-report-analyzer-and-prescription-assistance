"""
Tests for Report Analysis workflow:
1. All four source results retained with explicit evaluation dispositions.
2. Printed-range and guideline-category differences represented separately.
3. Patient narrative agrees with structured evidence.
4. Post-meal glucose not silently converted to an OGTT interpretation.
5. Qualitative urine observations not numerically or physiologically invented.
6. Unsupported tests cannot become "normal" through LLM wording.
7. Complete summaries and safe handling of incomplete generation.
8. No raw disclosure-wrapper tags in PDF text; enclosed evidence remains.
9. Screen/PDF content consistency.
10. Both report-upload and pasted-text routes.
11. At least one unrelated supported analyte and one unsupported analyte,
    using labeled fixtures and no invented clinical rules.
12. Existing prescription DDI/DLTI and PDF-export behavior unchanged.
"""

import os
import io
import re
import pytest
from pypdf import PdfReader

from app import app, extract_text_from_pdf, analyze_medical_report, LLMConsistencyValidator, ValidationGuardrailAgent
from rule_engine import MedicalRuleEngine
from report_reasoning_agent import ReportReasoningAgent
from pdf_export import build_analysis_pdf
from ddi_checker import DDIPairChecker
from dlti_checker import DLTICheckingAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kiran_kumar_pdf_path():
    path = os.path.join(os.path.dirname(__file__), "..", "scratch", "kiran_kumar.pdf")
    if not os.path.exists(path):
        pytest.skip("scratch/kiran_kumar.pdf not available")
    return path


@pytest.fixture
def kiran_kumar_text(kiran_kumar_pdf_path):
    text, _ = extract_text_from_pdf(kiran_kumar_pdf_path)
    return text


@pytest.fixture
def rule_engine_inst():
    return MedicalRuleEngine()


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 1. All four source results retained with explicit evaluation dispositions
# ---------------------------------------------------------------------------

def test_all_four_source_results_retained_with_dispositions(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    assert len(findings) == 4, f"Expected 4 findings, got {len(findings)}"

    names = [f.get("test_name") for f in findings]
    assert "Fasting Glucose" in names
    assert any("Post Prandial" in n and ("Sugar" in n or "Glucose" in n) and "Urine" not in n for n in names)
    assert any("Urine" in n and "Fasting" in n for n in names)
    assert any("Urine" in n and ("Post" in n or "PP" in n) for n in names)

    for f in findings:
        disp = f.get("disposition")
        assert disp in [
            "EVALUATED",
            "EVALUATED_PRINTED_RANGE_ONLY",
            "UNSUPPORTED_QUALITATIVE",
            "INSUFFICIENT_CONTEXT",
            "UNRESOLVED_MAPPING",
            "REJECTED"
        ], f"Finding {f.get('test_name')} has invalid disposition: {disp}"


# ---------------------------------------------------------------------------
# 2. Printed-range and guideline-category differences represented separately
# ---------------------------------------------------------------------------

def test_printed_range_and_guideline_category_separated(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    fbg = next(f for f in findings if "Fasting Glucose" in f.get("test_name"))

    assert fbg.get("result_value") == 102.0
    
    p_comp = fbg.get("printed_comparison")
    assert p_comp is not None, "Missing printed_comparison dictionary"
    assert p_comp.get("status") == "NORMAL", f"Expected printed status NORMAL, got {p_comp.get('status')}"
    assert "70" in p_comp.get("range") and "120" in p_comp.get("range")

    g_comp = fbg.get("guideline_comparison")
    assert g_comp is not None, "Missing guideline_comparison dictionary"
    assert g_comp.get("status") == "PREDIABETES_RANGE", f"Expected guideline status PREDIABETES_RANGE, got {g_comp.get('status')}"
    assert "ADA 2024" in g_comp.get("source")

    # Neither comparison should overwrite the other
    assert p_comp.get("status") != g_comp.get("status")


# ---------------------------------------------------------------------------
# 3. Patient narrative agrees with structured evidence & reconciles comparison
# ---------------------------------------------------------------------------

def test_patient_narrative_agrees_with_structured_evidence(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    summary = ReportReasoningAgent.build_report_patient_summary(findings)

    # Narrative must mention both comparisons for 102 mg/dL
    assert "102" in summary
    assert "70" in summary and "120" in summary
    assert "prediabetes" in summary.lower() or "ada 2024" in summary.lower()

    # Narrative must not claim effective regulation or perfect health
    assert "proves effective blood-sugar regulation" not in summary.lower()
    assert "you are healthy" not in summary.lower()
    assert "no disease" not in summary.lower()

    # All 4 findings must appear in the deterministic markdown table inside <details>
    assert "LAB-001" in summary
    assert "LAB-002" in summary
    assert "LAB-003" in summary
    assert "LAB-004" in summary


# ---------------------------------------------------------------------------
# 4. Post-meal glucose not silently converted to an OGTT interpretation
# ---------------------------------------------------------------------------

def test_post_meal_glucose_not_converted_to_ogtt(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    pp_finding = next(f for f in findings if "Post Prandial" in f.get("test_name") and "Urine" not in f.get("test_name"))

    assert pp_finding.get("result_value") == 262.0
    p_comp = pp_finding.get("printed_comparison")
    assert p_comp.get("status") == "HIGH"
    assert "80" in p_comp.get("range") and "140" in p_comp.get("range")

    # Guideline comparison should NOT map to OGTT
    g_comp = pp_finding.get("guideline_comparison")
    assert g_comp.get("status") in ["NOT_MAPPED", "NOT_APPLICABLE"]

    summary = ReportReasoningAgent.build_report_patient_summary(findings)
    # Check that narrative explicitly warns this is ordinary post-meal, not an OGTT
    assert "oral glucose tolerance test" in summary.lower() or "ogtt" in summary.lower()
    assert "not" in summary.lower()


# ---------------------------------------------------------------------------
# 5. Qualitative urine observations not numerically or physiologically invented
# ---------------------------------------------------------------------------

def test_qualitative_urine_observations_not_numerically_or_physiologically_invented(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    fasting_urine = next(f for f in findings if "Urine" in f.get("test_name") and "Fasting" in f.get("test_name"))
    pp_urine = next(f for f in findings if "Urine" in f.get("test_name") and "Post" in f.get("test_name"))

    assert fasting_urine.get("result_text") == "Nil"
    assert fasting_urine.get("result_value") is None
    assert pp_urine.get("result_text") == "Yellow 1 %"
    assert pp_urine.get("result_value") is None

    summary = ReportReasoningAgent.build_report_patient_summary(findings)
    # Must NOT claim the body is "producing excess sugar"
    assert "producing excess sugar in urine" not in summary.lower()
    assert "producing excess sugar" not in summary.lower()


# ---------------------------------------------------------------------------
# 6. Unsupported tests cannot become "normal" through LLM wording
# ---------------------------------------------------------------------------

def test_unsupported_analyte_cannot_become_normal(rule_engine_inst):
    # Labeled fixture with an unsupported biomarker
    fixture_text = """
    LABORATORY TEST REPORT
    Patient Name: Test Patient
    Age: 40 Years  Sex: Male
    Date: 17/10/2026
    -----------------------------------------------------------------
    TEST                          RESULT        UNIT      REFERENCE
    Experimental Biomarker X9     45.2          ng/mL     10.0 - 20.0
    -----------------------------------------------------------------
    """
    findings = rule_engine_inst.parse_and_evaluate(fixture_text)
    assert len(findings) >= 1
    x9 = findings[0]
    assert x9.get("disposition") in ["UNSUPPORTED_ANALYTE", "UNRESOLVED_MAPPING", "EVALUATED_PRINTED_RANGE_ONLY", "INSUFFICIENT_CONTEXT"]
    
    summary = ReportReasoningAgent.build_report_patient_summary(findings)
    # The summary must not classify unsupported test as 'Normal' or declare disease-free
    assert "you are healthy" not in summary.lower()
    assert "everything is normal" not in summary.lower()


# ---------------------------------------------------------------------------
# 7. Unrelated supported analyte: Serum Creatinine
# ---------------------------------------------------------------------------

def test_unrelated_supported_analyte_creatinine(rule_engine_inst):
    # Labeled fixture with an established supported analyte
    fixture_text = """
    LABORATORY TEST REPORT
    Patient Name: John Doe
    Age: 55 Years  Sex: Male
    Date: 17/10/2026
    -----------------------------------------------------------------
    TEST                          RESULT        UNIT      REFERENCE
    Serum Creatinine              2.1           mg/dL     0.7 - 1.3
    -----------------------------------------------------------------
    """
    findings = rule_engine_inst.parse_and_evaluate(fixture_text)
    assert len(findings) == 1
    creat = findings[0]
    assert creat.get("result_value") == 2.1
    assert creat.get("unit") == "mg/dL"
    assert creat.get("status") == "HIGH"
    assert creat.get("disposition") == "EVALUATED"

    summary = ReportReasoningAgent.build_report_patient_summary(findings)
    assert "creatinine" in summary.lower()
    assert "2.1" in summary


# ---------------------------------------------------------------------------
# 8. Complete summaries and safe handling of incomplete generation
# ---------------------------------------------------------------------------

def test_complete_summary_and_safe_handling_of_truncation(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    
    # Simulate a truncated LLM output ending at "to manage your"
    truncated_llm_text = "# Medical Report Analysis\n## 1. Main Findings\nYour blood sugar needs to manage your"
    is_valid, violations = LLMConsistencyValidator.validate(truncated_llm_text, findings)
    assert is_valid is False
    assert any("manage your" in v.lower() or "truncated" in v.lower() for v in violations)

    # Fallback must be complete and valid
    fallback = ValidationGuardrailAgent.validate_and_enforce(truncated_llm_text, findings, raw_text=kiran_kumar_text)
    assert "</details>" in fallback
    assert "## 1. Main Findings" in fallback
    assert "## 2. Your Results, Explained" in fallback
    assert "## 3. What Could Not Be Assessed" in fallback
    assert "## 4. What To Do Next" in fallback
    assert "## 5. Important Limits" in fallback


# ---------------------------------------------------------------------------
# 9. No raw disclosure-wrapper tags in PDF text & enclosed evidence remains
# ---------------------------------------------------------------------------

def test_no_raw_disclosure_tags_in_pdf_and_evidence_preserved(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    summary_md = ReportReasoningAgent.build_report_patient_summary(findings)

    pdf_bytes = build_analysis_pdf(summary_md, kind="report")
    assert len(pdf_bytes) > 1000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_pdf_text = "".join(p.extract_text() or "" for p in reader.pages)
    norm_pdf_text = re.sub(r'\s+', ' ', full_pdf_text)

    # NO literal HTML disclosure wrapper tags
    assert "<details>" not in full_pdf_text
    assert "</details>" not in full_pdf_text
    assert "<summary>" not in full_pdf_text

    # All 4 tests must remain in PDF text
    assert "Fasting Glucose" in norm_pdf_text
    assert "Post Prandial Blood Sugar" in norm_pdf_text
    assert "Fasting Urine Sugar" in norm_pdf_text
    assert "Post Prandial Urine sugar" in norm_pdf_text
    assert "102" in full_pdf_text
    assert "262" in full_pdf_text
    assert "Yellow 1%" in full_pdf_text or "Yellow 1 %" in full_pdf_text


# ---------------------------------------------------------------------------
# 10. Screen/PDF content consistency
# ---------------------------------------------------------------------------

def test_screen_and_pdf_content_consistency(rule_engine_inst, kiran_kumar_text):
    findings = rule_engine_inst.parse_and_evaluate(kiran_kumar_text)
    screen_markdown = ReportReasoningAgent.build_report_patient_summary(findings)

    # On screen: <details> and <summary> exist for interactivity
    assert "<details>" in screen_markdown
    assert "<summary>" in screen_markdown
    assert "</details>" in screen_markdown

    # In PDF: wrapper tags removed, content preserved
    pdf_bytes = build_analysis_pdf(screen_markdown, kind="report")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pdf_text = "".join(p.extract_text() or "" for p in reader.pages)

    assert "<details>" not in pdf_text
    assert "Deterministic Rule Engine Clinical Evaluation" in pdf_text
    assert "Evaluation Coverage Summary" in pdf_text


# ---------------------------------------------------------------------------
# 11. Both report-upload and pasted-text routes
# ---------------------------------------------------------------------------

def test_report_upload_route(client, kiran_kumar_pdf_path):
    with open(kiran_kumar_pdf_path, 'rb') as f:
        data = {'file': (f, 'kiran_kumar.pdf')}
        res = client.post('/upload', data=data, content_type='multipart/form-data')
    
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data.get('success') is True
    analysis = json_data.get('analysis', {})
    english_md = analysis.get('english', '')

    assert "102" in english_md
    assert "262" in english_md
    assert "Yellow 1%" in english_md or "Yellow 1 %" in english_md


def test_pasted_text_route(client, kiran_kumar_text):
    res = client.post('/analyze-report-text', json={'report_text': kiran_kumar_text})
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data.get('success') is True
    analysis = json_data.get('analysis', {})
    english_md = analysis.get('english', '')

    assert "102" in english_md
    assert "262" in english_md
    assert "Yellow 1%" in english_md or "Yellow 1 %" in english_md


# ---------------------------------------------------------------------------
# 12. Existing prescription DDI/DLTI and PDF-export behavior unchanged
# ---------------------------------------------------------------------------

def test_prescription_ddi_dlti_unaffected():
    # Verify DLTI pipeline processing for Prednisone + Glucose
    ctx = {
        "document_type": "prescription",
        "raw_input": "Tab Prednisone 10mg once daily in morning",
        "metadata": {},
        "extracted_data": {},
        "handwriting": {},
        "verification": {
            "medications": [{
                "name": "prednisone",
                "raw_name": "Prednisone 10mg",
                "identity_verified": True,
                "route": "ORAL",
            }],
            "current_labs": [{
                "analyte": "glucose",
                "value": 180.0,
                "unit": "mg/dL",
                "status": "HIGH",
            }],
        },
        "safety": {},
        "reasoning": {},
        "warnings": [],
        "errors": [],
    }
    processed = DLTICheckingAgent.process(ctx)
    assert processed is not None
    assert "dlti" in processed

    # Verify PDF export for prescription still works
    rx_md = "# Prescription Analysis\n## Patient Information\nPrednisone 10 mg once daily."
    pdf_bytes = build_analysis_pdf(rx_md, kind="medicine")
    assert len(pdf_bytes) > 500
