from app import generate_safe_deterministic_fallback


def test_report_output_matches_requested_patient_format():
    eval_results = [{
        "test_name": "HbA1c",
        "result_value": 6.8,
        "unit": "%",
        "status": "HIGH",
        "reference_text": "Report Range (4.0 - 5.6)",
        "normalized_test_name": "hba1c",
        "category": "diabetes",
    }]

    output = generate_safe_deterministic_fallback(
        eval_results,
        raw_text="Patient Name: Irani Gangadharappa\nAge: 69 years\nGender: Male\nLab Ref No.: 0208578\nRegistration Date: 30/10/2023 15:20"
    )

    assert "# Medical Report Analysis" in output
    assert "### 👤 Patient Demographic Information" in output
    assert "## 🩺 Glycosylated Haemoglobin (HbA1c)" in output
    assert "### Your Result" in output
    assert "### Status" in output
    assert "### What does this mean?" in output
    assert "### Does this suggest a health condition?" in output
    assert "### What should you do?" in output
    assert "### Which doctor should I consult?" in output
    assert "## 📋 Overall Patient-Friendly Health Summary" in output
    assert "## Important Findings" in output
    assert "## Recommended Next Step" in output
    assert "<details>" in output
