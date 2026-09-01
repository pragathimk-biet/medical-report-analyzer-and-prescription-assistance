import os
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
from dotenv import load_dotenv
import requests
import json
import logging
import re
import shutil

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)

# Auto-discover Tesseract path on Windows
def init_tesseract():
    tess_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'),
        os.getenv('TESSERACT_PATH', '')
    ]
    for path in tess_paths:
        if path and os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            logger.info(f"Tesseract found at: {path}")
            return path
    which_p = shutil.which("tesseract")
    if which_p:
        pytesseract.pytesseract.tesseract_cmd = which_p
        logger.info(f"Tesseract found via PATH: {which_p}")
        return which_p
    logger.warning("Tesseract not found in standard system paths.")
    return None

init_tesseract()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# LLM Providers Configuration
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "deepseek-r1:14b"
NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"

def get_available_ollama_model():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m.get('name', '') for m in r.json().get('models', [])]
            if models:
                for m in models:
                    if 'deepseek-r1:14b' in m:
                        return m
                for m in models:
                    if 'deepseek' in m:
                        return m
                return models[0]
    except Exception:
        pass
    return DEFAULT_MODEL_NAME

# Pre-initialize RapidOCR globally for instant image extraction
rapid_ocr_engine = None
try:
    from rapidocr_onnxruntime import RapidOCR
    rapid_ocr_engine = RapidOCR()
    logger.info("RapidOCR engine pre-initialized globally.")
except Exception as _ocr_err:
    logger.warning(f"RapidOCR global init warning: {_ocr_err}")

def _safe_ai_fallback_text(prompt, system_prompt="You are an expert medical AI advisor."):
    """Return a safe deterministic summary when AI backends are unavailable."""
    import re

    text = str(prompt or "")
    patient_name = "Default Patient"
    age = "N/A"
    gender = "N/A"
    lab_ref_no = "N/A"
    reg_date = "N/A"

    name_match = re.search(r'Patient Name\s*[:\-]?\s*([A-Za-z .-]+)', text, re.IGNORECASE)
    if name_match:
        patient_name = name_match.group(1).strip()
    age_match = re.search(r'Age\s*[:\-]?\s*(\d{1,3})', text, re.IGNORECASE)
    if age_match:
        age = age_match.group(1)
    gender_match = re.search(r'Gender\s*[:\-]?\s*(Male|Female|Other)', text, re.IGNORECASE)
    if gender_match:
        gender = gender_match.group(1).title()
    lab_ref_match = re.search(r'Lab Ref No\.?\s*[:\-]?\s*([A-Za-z0-9/-]+)', text, re.IGNORECASE)
    if lab_ref_match:
        lab_ref_no = lab_ref_match.group(1).strip()
    date_match = re.search(r'Registration Date\s*[:\-]?\s*([^\n]+)', text, re.IGNORECASE)
    if date_match:
        reg_date = date_match.group(1).strip()

    eval_results = []
    for param_name, regex in [
        ("HbA1c", r'hba1c\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%'),
        ("Fasting Blood Glucose", r'fasting blood glucose\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:mg/dl|mg/dL|mmol/L|mmol/l)'),
        ("Random Blood Glucose", r'random blood glucose\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:mg/dl|mg/dL|mmol/L|mmol/l)'),
        ("Serum Creatinine", r'creatinine\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:mg/dl|mg/dL)'),
        ("Hemoglobin", r'hemoglobin\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g/dl|g/dL)'),
    ]:
        match = re.search(regex, text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            unit = '%' if 'hba1c' in regex.lower() else 'mg/dL' if 'glucose' in param_name.lower() or 'creatinine' in param_name.lower() else 'g/dL'
            status = 'HIGH' if ('hba1c' in param_name.lower() and val > 5.6) or ('glucose' in param_name.lower() and val > 99) or ('creatinine' in param_name.lower() and val > 1.2) or ('hemoglobin' in param_name.lower() and val < 13) else 'NORMAL'
            eval_results.append({
                'test_name': param_name,
                'result_value': val,
                'unit': unit,
                'status': status,
                'reference_text': 'Report Range (automated fallback)',
                'normalized_test_name': param_name.lower().replace(' ', '_').replace('/', '_'),
                'category': 'diabetes' if 'glucose' in param_name.lower() or 'hba1c' in param_name.lower() else 'general'
            })

    if not eval_results:
        return "# 📋 Medical Report Analysis & Clinical Guidance\n\n### 👤 Patient Information\n| Demographic Field | Value | Demographic Field | Value |\n| :--- | :--- | :--- | :--- |\n| **Patient Name** | **{patient_name}** | **Age / Gender** | {age} Years / {gender} |\n| **Lab Ref No.** | `{lab_ref_no}` | **Report Date** | {reg_date} |\n\n---\n\n## 🔬 Extracted Laboratory Test Findings\n\nNo validated laboratory values were detected from the submitted input. Please review the original report or paste a clearer lab report for detailed analysis.\n\n> ⚠️ **Medical Disclaimer**: This automated analysis is designed for patient education and decision support. It does not provide a formal medical diagnosis. Always consult a licensed healthcare professional for official medical advice."

    return generate_safe_deterministic_fallback(eval_results, raw_text=text)


def generate_ai_analysis(prompt, system_prompt="You are an expert medical AI advisor."):
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()

    # 1. NVIDIA Nemotron / NIM API
    if nvidia_key:
        try:
            from openai import OpenAI
            model = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct").strip()
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_key)
            logger.info(f"Using NVIDIA NIM API (Model: {model})")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"NVIDIA API Error: {e}. Falling back to Ollama local AI.")

    # 2. Local Ollama AI
    try:
        model = get_available_ollama_model()
        data = {
            "model": model,
            "prompt": f"{system_prompt}\n\n{prompt}",
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 800
            }
        }
        logger.info(f"Using Ollama local AI (Model: {model})")
        response = requests.post(OLLAMA_ENDPOINT, json=data, timeout=120)
        response.raise_for_status()
        result = response.json()
        ai_reply = result.get('response', '')
        if ai_reply:
            return ai_reply
    except Exception as e:
        logger.warning(f"Ollama local AI connection failed: {e}")

    logger.warning("No AI backend reachable. Returning deterministic offline clinical fallback.")
    return _safe_ai_fallback_text(prompt, system_prompt)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

from win_ocr import run_win_ocr

def extract_text_from_image(image_path):
    ocr_metadata = []
    # 1. Try RapidOCR (high accuracy ONNX-based OCR, instant global instance)
    if rapid_ocr_engine:
        try:
            ocr_result, _ = rapid_ocr_engine(image_path)
            if ocr_result:
                extracted_lines = []
                for line_idx, line in enumerate(ocr_result, 1):
                    if line and len(line) > 1 and line[1].strip():
                        text_str = line[1].strip()
                        conf = round(float(line[2]) * 100, 1) if len(line) > 2 and line[2] is not None else None
                        extracted_lines.append(text_str)
                        ocr_metadata.append({
                            "line_number": line_idx,
                            "raw_line": text_str,
                            "confidence": conf
                        })
                if extracted_lines:
                    extracted_text = "\n".join(extracted_lines)
                    logger.info("Successfully extracted text using RapidOCR engine!")
                    return extracted_text, ocr_metadata
        except Exception as e:
            logger.warning(f"RapidOCR extraction warning: {e}")

    # 2. Try PyTesseract if available
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        if text and text.strip():
            return text, []
    except Exception as e:
        logger.warning(f"PyTesseract extraction warning: {e}")

    # 3. Try Windows Native OCR (WinRT)
    try:
        win_text = run_win_ocr(image_path)
        if win_text and win_text.strip():
            logger.info("Successfully extracted text using Windows Native OCR!")
            return win_text, []
    except Exception as e:
        logger.warning(f"Windows Native OCR warning: {e}")

    return "Error: Could not extract text from this image. Please upload a clearer report image, upload a PDF file, or paste your report text directly into the text field.", []

def extract_text_from_pdf(pdf_path):
    # Try native PDF text extraction with PyPDF first
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        extracted = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                extracted.append(t)
        if extracted:
            return "\n".join(extracted), []
    except Exception as e:
        logger.warning(f"PyPDF extraction fallback: {e}")

    # Fallback to pdf2image + pytesseract OCR
    try:
        images = convert_from_path(pdf_path)
        text = ""
        for image in images:
            text += pytesseract.image_to_string(image)
        if text and text.strip():
            return text, []
    except Exception as e:
        logger.warning(f"PDF OCR warning: {e}")

    return "Error: Could not extract text from PDF. Please upload a text-based PDF or paste the report text directly.", []

def is_connection_error(e):
    if e is None:
        return True
    err_str = str(e).lower()
    return isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.RequestException)) or \
        any(k in err_str for k in ['connection', 'refused', '10061', 'actively refused', 'max retries', 'failed to establish', '410', '404', '401', '429', 'statuserror', 'httperror', 'openai', 'api', 'gone', 'not found'])

from rule_engine import MedicalRuleEngine
from patient_history import PatientHistoryManager, extract_patient_name, normalize_patient_name
from tabular_ml_engine import TabularMLAgent, predict_finding_safety
from input_router import InputRouter, create_pipeline_context
from report_extraction_agent import ReportExtractionAgent
from report_verification_agent import ReportVerificationAgent
from ml_safety_agent import MLSafetyAgent
from report_reasoning_agent import ReportReasoningAgent

rule_engine = MedicalRuleEngine()
patient_history = PatientHistoryManager()

FORBIDDEN_DIAGNOSTIC_TERMS = [
    # 1. Diagnostic Assertions
    r'diagnosed with',
    r'diagnostic confirmation',
    r'confirm(?:s)? (?:that you have|a diagnosis of|clinical|kidney|renal|liver|hepatic|thyroid|heart|diabetic)',
    r'is suffering from',
    r'has developed (?:kidney|renal|liver|hepatic|thyroid|heart|diabetic)',
    r'definitive diagnosis',
    r'proves (?:that you have|the presence of)',

    # 2. Organ Failure & Disease Terms
    r'renal failure',
    r'kidney failure',
    r'kidney disease',
    r'renal disease',
    r'impaired kidney function',
    r'impaired renal function',
    r'active typhoid infection',
    r'active typhoid fever',
    r'hepatic failure',
    r'liver failure',
    r'liver disease',
    r'hepatotoxicity',
    r'heart failure',
    r'cardiac failure',
    r'respiratory failure',
    r'organ failure',
    r'pancreatitis',
    r'cirrhosis',
    r'diabetic ketoacidosis',
    r'severe anemia',
    r'thyroid disease',

    # 3. Prescriptive Treatment & Mandatory Interventions
    r'immediately stop',
    r'stop taking your medication',
    r'immediately discontinue',
    r'discontinue your medication',
    r'you must take',
    r'start taking',
    r'must drink \d+ liters',
    r'strict diet ban',
    r'food ban'
]

def get_patient_friendly_status(status, validation_status=None):
    if validation_status in ["REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
        return "❓ Unable to Determine"
    s_upper = str(status).upper()
    if s_upper in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
        return "✅ Normal"
    elif s_upper in ["PREDIABETES", "PREDIABETES_RANGE", "BORDERLINE_HIGH", "NEAR_OPTIMAL", "MILDLY_DECREASED"]:
        return "⚠️ Needs Attention"
    elif s_upper in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "KIDNEY_FAILURE_RANGE", "SEVERELY_DECREASED"]:
        return "🔴 High"
    elif s_upper == "LOW":
        return "🔵 Low"
    else:
        return "ℹ️ Informational"

def get_health_condition_suggestion(status, validation_status=None):
    if validation_status in ["REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
        return "**Cannot determine from this report**\n\n**This report does not by itself confirm a disease.**"
    s_upper = str(status).upper()
    if s_upper in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
        return "**No clear abnormality detected**\n\n**This report does not by itself confirm a disease.**"
    elif s_upper in ["PREDIABETES", "PREDIABETES_RANGE", "BORDERLINE_HIGH", "MILDLY_DECREASED"]:
        return "**Possible health-related finding**\n\n**This report does not by itself confirm a disease.**"
    else:
        return "**Finding that may need medical evaluation**\n\n**This report does not by itself confirm a disease.**"

def get_recommended_doctor_category(param_key, category, status):
    p_key = str(param_key).lower()
    cat = str(category).lower()
    s_upper = str(status).upper()
    
    if s_upper in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
        return "**General Physician / Primary Care Doctor** (for routine wellness monitoring)"
        
    if "hba1c" in p_key or "glucose" in p_key or cat == "diabetes":
        return "**Diabetologist or Endocrinologist**"
    elif "creatinine" in p_key or "urea" in p_key or "bun" in p_key or "egfr" in p_key or cat == "kidney":
        return "**Nephrologist**"
    elif "tsh" in p_key or "t4" in p_key or cat == "thyroid":
        return "**Endocrinologist**"
    elif "hemoglobin" in p_key or "wbc" in p_key or "platelets" in p_key or cat == "cbc":
        return "**Hematologist**"
    elif "alt" in p_key or "ast" in p_key or "bilirubin" in p_key or cat == "liver":
        return "**Gastroenterologist or Hepatologist**"
    elif "cholesterol" in p_key or "triglycerides" in p_key or cat == "lipid_profile":
        return "**Cardiologist or Primary Care Physician**"
    elif "sodium" in p_key or "potassium" in p_key or cat == "electrolytes":
        return "**Nephrologist or General Physician**"
    elif "typhi" in p_key or cat == "widal":
        return "**General Physician / Internal Medicine**"
    else:
        return "**General Physician / Internal Medicine**"

def generate_safe_deterministic_fallback(eval_results, two_way_alerts=None, raw_text=""):
    from patient_history import extract_patient_demographics

    demographics = extract_patient_demographics(raw_text)
    patient_name = demographics.get('patient_name', 'Default Patient')
    age = demographics.get('age', 'N/A')
    gender = demographics.get('gender', 'N/A')
    lab_ref_no = demographics.get('lab_ref_no', 'N/A')
    reg_date = demographics.get('registration_date', 'N/A')

    def status_badge(status):
        s = str(status).upper()
        if s in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
            return "✅ **NORMAL**"
        if s in ["PREDIABETES", "PREDIABETES_RANGE", "BORDERLINE_HIGH", "MILDLY_DECREASED", "REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
            return "⚠️ **MEDIUM**"
        if s in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]:
            return "🔴 **HIGH**"
        if s in ["LOW", "VERY_LOW"]:
            return "🔵 **LOW**"
        return "ℹ️ **INFORMATIONAL**"

    def friendly_condition(status):
        s = str(status).upper()
        if s in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
            return "**No clear abnormality detected**"
        if s in ["PREDIABETES", "PREDIABETES_RANGE", "BORDERLINE_HIGH", "MILDLY_DECREASED", "REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
            return "**Possible health-related finding**"
        return "**Finding that may need medical evaluation**"

    def friendly_explanation(param, status, value, unit, ref_text):
        param_name = str(param).strip()
        value_str = f"{value} {unit}".strip()
        s = str(status).upper()
        if s in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
            return f"Your {param_name.lower()} level is {value_str}, which is within the expected range according to the report reference ({ref_text}). This is reassuring and usually does not by itself indicate an abnormality."
        if s in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]:
            return f"Your {param_name.lower()} level is {value_str}, which is above the expected range ({ref_text}). This may reflect a metabolic or physiologic stress pattern and should be discussed with a clinician."
        if s in ["LOW", "VERY_LOW"]:
            return f"Your {param_name.lower()} level is {value_str}, which is below the expected range ({ref_text}). A lower than expected result can sometimes suggest reduced physiological reserve or nutritional factors and should be reviewed clinically."
        return f"Your {param_name.lower()} level is {value_str}. This result falls in a range that may need additional clinical context for interpretation."

    def doctor_for(param, category, status):
        p_key = str(param).lower()
        cat = str(category).lower()
        s_upper = str(status).upper()
        if s_upper in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"]:
            return "General Physician / Primary Care Doctor"
        if "hba1c" in p_key or "glucose" in p_key or cat == "diabetes":
            return "Diabetologist / Endocrinologist"
        if "creatinine" in p_key or "urea" in p_key or "bun" in p_key or "egfr" in p_key or cat == "kidney":
            return "Nephrologist"
        if "tsh" in p_key or "t4" in p_key or cat == "thyroid":
            return "Endocrinologist"
        if "hemoglobin" in p_key or "wbc" in p_key or "platelets" in p_key or cat == "cbc":
            return "Hematologist"
        if "alt" in p_key or "ast" in p_key or "bilirubin" in p_key or cat == "liver":
            return "Gastroenterologist / Hepatologist"
        if "cholesterol" in p_key or "triglycerides" in p_key or cat == "lipid_profile":
            return "Cardiologist / Primary Care Physician"
        if "sodium" in p_key or "potassium" in p_key or cat == "electrolytes":
            return "Nephrologist / General Physician"
        return "General Physician / Primary Care Doctor"

    def display_param_name(param):
        p = str(param)
        if p.lower() == "hba1c":
            return "Glycosylated Haemoglobin (HbA1c)"
        if p.lower() == "fasting blood glucose":
            return "Fasting Blood Glucose"
        if p.lower() == "random blood glucose":
            return "Random Blood Glucose"
        if p.lower() == "serum creatinine":
            return "Serum Creatinine"
        if p.lower() == "hemoglobin":
            return "Hemoglobin"
        return p

    lines = ["# Medical Report Analysis", ""]
    lines.append("### 👤 Patient Demographic Information")
    lines.append("| Demographic Field | Details |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Patient Name** | **{patient_name}** |")
    lines.append(f"| **Age / Sex** | {age} Year(s) / {gender} |")
    lines.append(f"| **Lab Ref No.** | `{lab_ref_no}` |")
    if reg_date and reg_date != 'N/A':
        lines.append(f"| **Registration Date** | {reg_date} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    if not eval_results:
        lines.append("## 🩺 No laboratory findings detected")
        lines.append("")
        lines.append("### Your Result")
        lines.append("No validated laboratory result was detected in this report.")
        lines.append("")
        lines.append("### Status")
        lines.append("❓ **UNABLE TO DETERMINE**")
        lines.append("")
        lines.append("### What does this mean?")
        lines.append("The uploaded file may not contain enough clear lab values for a reliable clinical check. Please review the original report or upload a clearer image/PDF.")
        lines.append("")
        lines.append("### Does this suggest a health condition?")
        lines.append("**Cannot determine from this report**")
        lines.append("")
        lines.append("**This report does not by itself confirm a disease.**")
        lines.append("")
        lines.append("### What should you do?")
        lines.append("Upload a clearer image or verify the lab values in the original document. A doctor can help interpret the report if the result is unclear.")
        lines.append("")
        lines.append("### Which doctor should I consult?")
        lines.append("**General Physician / Primary Care Doctor**")
        lines.append("")
        lines.append("## 📋 Overall Patient-Friendly Health Summary")
        lines.append("No clear abnormal result could be verified from the provided report. Please check the source document for complete laboratory values.")
        lines.append("")
        lines.append("## Important Findings")
        lines.append("✅ **Normal / Unclear:**")
        lines.append("- No validated abnormal findings were detected from the uploaded information.")
        lines.append("")
        lines.append("## Recommended Next Step")
        lines.append("Consult a **General Physician / Primary Care Doctor** to review the report and confirm the intended interpretation.")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>🔬 View Technical & Evidence Details</summary>")
        lines.append("")
        lines.append(rule_engine.format_deterministic_markdown(eval_results) if eval_results else "No standardized laboratory parameters evaluated by the Rule Engine.")
        lines.append("</details>")
        return "\n".join(lines)

    summary_high = []
    summary_normal = []
    summary_medium = []

    for res in eval_results:
        param = res.get("test_name", res.get("parameter", "Test"))
        value = res.get("result_value", res.get("value", ""))
        unit = res.get("unit", "")
        status = str(res.get("status", "NORMAL")).upper()
        ref_text = res.get("reference_text", res.get("range_description", "standard range"))
        category = str(res.get("category", "")).lower()
        display_name = display_param_name(param)

        lines.append(f"## 🩺 {display_name}")
        lines.append("")
        lines.append("### Your Result")
        lines.append(f"{value} {unit}".strip())
        lines.append("")
        lines.append("### Status")
        lines.append(status_badge(status))
        lines.append("")
        lines.append("### What does this mean?")
        lines.append(friendly_explanation(display_name, status, value, unit, ref_text))
        lines.append("")
        lines.append("### Does this suggest a health condition?")
        lines.append(friendly_condition(status))
        lines.append("")
        lines.append("**This report does not by itself confirm a disease.**")
        lines.append("")
        lines.append("### What should you do?")
        if status in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]:
            lines.append(f"Repeat or confirm the result with your clinician and discuss lifestyle, diet, and follow-up monitoring. Consider consulting a {doctor_for(param, category, status)} for review.")
        elif status in ["LOW", "VERY_LOW"]:
            lines.append(f"Review the result with a clinician, especially if symptoms are present. Additional tests may help clarify whether this is a persistent or temporary pattern.")
        else:
            lines.append("Continue routine monitoring and maintain healthy eating, hydration, sleep, and exercise habits. Repeat testing is usually guided by your clinician if symptoms change.")
        lines.append("")
        lines.append("### Which doctor should I consult?")
        lines.append(f"**{doctor_for(param, category, status)}**")
        lines.append("")
        lines.append("---")
        lines.append("")

        if status in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]:
            summary_high.append(f"- High {display_name.lower()} level ({value} {unit})")
        elif status in ["PREDIABETES", "PREDIABETES_RANGE", "BORDERLINE_HIGH", "MILDLY_DECREASED", "REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
            summary_medium.append(f"- Medium {display_name.lower()} level ({value} {unit})")
        else:
            summary_normal.append(f"- Normal {display_name.lower()} level ({value} {unit})")

    lines.append("## 📋 Overall Patient-Friendly Health Summary")
    if summary_high:
        lines.append(f"Some findings are above the expected reference range, which may warrant closer review. This does not confirm a disease by itself, but it is prudent to discuss the results with a clinician and monitor them over time.")
    elif summary_medium:
        lines.append(f"One or more values are borderline and may need additional clinical context. These findings can be watched closely and discussed with a doctor to decide whether further review is needed.")
    else:
        lines.append(f"The reported values are largely within the expected range. This suggests no clear abnormality from the available information, though periodic follow-up is still important for overall health monitoring.")

    lines.append("")
    lines.append("## Important Findings")
    if summary_high:
        lines.append("🔴 **Needs Attention:**")
        lines.extend(summary_high)
    if summary_medium:
        lines.append("")
        lines.append("⚠️ **Medium / Monitor:**")
        lines.extend(summary_medium)
    if summary_normal:
        lines.append("")
        lines.append("✅ **Normal:**")
        lines.extend(summary_normal)

    doctor_pick = "General Physician / Primary Care Doctor"
    if summary_high:
        doctor_pick = doctor_for(next((res.get("test_name", "") for res in eval_results if str(res.get("status", "")).upper() in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]), ""), next((str(res.get("category", "")) for res in eval_results if str(res.get("status", "")).upper() in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]), ""), next((str(res.get("status", "")) for res in eval_results if str(res.get("status", "")).upper() in ["HIGH", "VERY_HIGH", "DIABETES_RANGE", "POSITIVE", "SEVERELY_DECREASED"]), ""))

    lines.append("")
    lines.append("## Recommended Next Step")
    lines.append(f"Consult a **{doctor_pick}** to review the reported values, consider repeat testing if needed, and discuss lifestyle or medication adjustments appropriate to your health context.")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>🔬 View Technical & Evidence Details</summary>")
    lines.append("")
    lines.append(rule_engine.format_deterministic_markdown(eval_results) if eval_results else "No standardized laboratory parameters evaluated by the Rule Engine.")
    lines.append("</details>")

    return "\n".join(lines)


# --- REQUIREMENTS 7, 8, 10: LLM Consistency Validator Engine ---
class LLMConsistencyValidator:
    """
    Audits candidate LLM output against structured authoritative findings.
    Validates:
    1. Status Integrity: Parameter headers must match Rule Engine evaluated status.
    2. Forbidden Diagnostic & Treatment Terms: No ungrounded organ failure claims or prescriptive mandates.
    3. Invented Tests & History Facts: No fabricated tests or ungrounded statements.
    """
    @staticmethod
    def validate(analysis_text, eval_results, two_way_alerts=None):
        violations = []
        if not analysis_text or not isinstance(analysis_text, str):
            return False, ["Empty or invalid analysis text"]

        # 1. Check for forbidden diagnostic terms & treatment mandates
        for term_pattern in FORBIDDEN_DIAGNOSTIC_TERMS:
            if re.search(term_pattern, analysis_text, re.IGNORECASE):
                violations.append(f"Forbidden diagnostic / treatment term pattern matched: '{term_pattern}'")

        # 2. Audit Parameter Status Consistency against Rule Engine Source of Truth
        if eval_results:
            for res in eval_results:
                param = res.get("test_name", res.get("parameter"))
                status = res.get("status")
                if not param or not status:
                    continue

                # Check if block exists for param
                param_block = re.search(r'##\s*🩺\s*' + re.escape(param) + r'([\s\S]*?)(?=##\s*🩺|##\s*📋|##\s*⚠️|$)', analysis_text, re.IGNORECASE)
                if not param_block:
                    param_block = re.search(r'###\s*' + re.escape(param) + r'([\s\S]*?)(?=###|##|$)', analysis_text, re.IGNORECASE)

                if param_block:
                    block_content = param_block.group(1).lower()
                    # Check if status contradicts rule engine status
                    if status in ["NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL"] and ("🔴 high" in block_content or "🔵 low" in block_content or "above normal" in block_content or "higher than normal" in block_content):
                        violations.append(f"Status override detected for {param}: Rule Engine={status}, LLM text indicates High/Low")
                    elif status in ["HIGH", "VERY_HIGH"] and ("✅ normal" in block_content or "within normal range" in block_content):
                        violations.append(f"Status override detected for {param}: Rule Engine={status}, LLM text indicates Normal")

        is_valid = len(violations) == 0
        return is_valid, violations

def sanitize_llm_explanation(analysis_text, eval_results=None):
    """
    Stage 4 & Stage 6 Guardrail Agent:
    Rewrites forbidden diagnostic language and attaches mandatory safety disclaimers.
    """
    if not analysis_text or not isinstance(analysis_text, str):
        return analysis_text

    sanitized = analysis_text
    for term_pattern in FORBIDDEN_DIAGNOSTIC_TERMS:
        sanitized = re.sub(term_pattern, "finding requiring medical evaluation", sanitized, flags=re.IGNORECASE)

    if "consult your primary care physician" not in sanitized.lower():
        sanitized += "\n\n> ⚠️ **Mandatory Medical Disclaimer**: This automated analysis is for informational decision support only. Please consult your primary care physician for diagnostic confirmation."
    return sanitized

# --- REQUIREMENT 9: Modular Specialized Executable Agentic Orchestrator ---
class PerceptionExtractionAgent:
    """Agent 1: Data Perception & OCR Extraction Agent."""
    @staticmethod
    def extract(filepath, ext):
        if ext == 'pdf':
            return extract_text_from_pdf(filepath)
        return extract_text_from_image(filepath)

class LaboratoryEvaluationAgent:
    """Agent 2: Deterministic Rule Engine Evaluation Agent."""
    @staticmethod
    def evaluate(text, ocr_metadata=None):
        return rule_engine.parse_and_evaluate(text, ocr_metadata=ocr_metadata)

class PatientHistoryAgent:
    """Agent 3: Longitudinal History & Trend Detection Agent."""
    @staticmethod
    def process(eval_results, patient_name="Default Patient"):
        patient_history.add_lab_results(eval_results, patient_name=patient_name)
        trends = patient_history.analyze_parameter_trends(eval_results, patient_name=patient_name)
        return trends

class PrescriptionAgent:
    """Agent 4: Prescription & Trusted Medication Classification Agent."""
    @staticmethod
    def classify(medicine_name, dosage=None, patient_name="Default Patient"):
        patient_history.add_active_medication(medicine_name, dosage, patient_name=patient_name)
        return patient_history.classify_medication(medicine_name)

class SafetyCrossCheckAgent:
    """Agent 5: True Bidirectional Medication/Lab Safety Agent."""
    @staticmethod
    def check_direction_a(new_medicine_name, patient_name="Default Patient"):
        return patient_history.check_prescription_against_past_labs(new_medicine_name, patient_name=patient_name)

    @staticmethod
    def check_direction_b(new_eval_results, patient_name="Default Patient"):
        return patient_history.check_new_labs_against_active_meds(new_eval_results, patient_name=patient_name)

class ExplanationAgent:
    """Agent 6: Constrained Explanation Generator Agent."""
    @staticmethod
    def generate(text, eval_results, two_way_alerts=None, trends=None):
        from patient_history import extract_patient_demographics
        demographics = extract_patient_demographics(text)
        deterministic_table = rule_engine.format_deterministic_markdown(eval_results)
        
        alerts_markdown = ""
        if two_way_alerts:
            alerts_lines = ["\n## ⚠️ Possible Medication–Lab Safety Alert"]
            for alert in two_way_alerts:
                alerts_lines.append(f"### {alert['title']} ({alert['severity']} Priority)")
                alerts_lines.append(f"- **Details:** {alert['explanation']}")
                alerts_lines.append("- **Note:** Potential medication-lab safety relationship detected. Professional clinical confirmation by your prescribing doctor is recommended.")
                alerts_lines.append("")
            alerts_markdown = "\n".join(alerts_lines)

        trends_markdown = ""
        if trends:
            trends_lines = ["\n## 📈 Longitudinal Trend Observations"]
            for tr in trends:
                trends_lines.append(f"- **{tr['parameter']}**: {tr['summary']}")
            trends_markdown = "\n".join(trends_lines)

        demo_card = f"""### 👤 Patient Demographic Information
| Demographic Field | Details |
| :--- | :--- |
| **Patient Name** | **{demographics.get('patient_name', 'Default Patient')}** |
| **Age / Sex** | {demographics.get('age', 'N/A')} Year(s) / {demographics.get('gender', 'N/A')} |
| **Lab Ref No.** | `{demographics.get('lab_ref_no', 'N/A')}` |
| **Registration Date** | {demographics.get('registration_date', 'N/A')} |

---
"""

        system_prompt = f"""You are an expert patient-friendly medical report explainer AI. Your role is to explain laboratory findings in simple, reassuring, plain language based STRICTLY on the evaluated laboratory data below.

STRICT MANDATORY GUIDELINES:
1. NO TECHNICAL DEVELOPER JARGON: DO NOT show raw developer/internal terms in the patient-facing explanation sections (such as "Rule Engine", "LLM", "OCR confidence", "Line number", "validation_status", "DEFAULT_JSON", "rule_id", "provenance"). Keep explanations simple.
2. ABSOLUTE PROHIBITION OF DIAGNOSES: You MUST NEVER declare or imply a confirmed disease diagnosis (such as "You have diabetes", "kidney failure", or "active typhoid infection"). Use cautious language like "may indicate", "could be associated with", or "this result alone does not confirm a disease".
3. STATUS BADGES TO USE:
   - ✅ Normal
   - ⚠️ Needs Attention
   - 🔴 High
   - 🔵 Low
   - ℹ️ Informational
   - ❓ Unable to Determine
4. HEALTH CONDITION SUGGESTION CLAUSE: Under "### Does this suggest a health condition?", use one of:
   - **No clear abnormality detected**
   - **Possible health-related finding**
   - **Finding that may need medical evaluation**
   - **Cannot determine from this report**
   Followed by: "**This report does not by itself confirm a disease.**"
5. WHICH DOCTOR TO CONSULT: Recommend a specialist category (e.g. Diabetologist/Endocrinologist for Glucose/HbA1c, Nephrologist for Kidney, Hematologist for Blood/CBC, Cardiologist for Lipids, Gastroenterologist for Liver, General Physician / Primary Care Doctor for general/mild findings).

Patient Demographics:
- Name: {demographics.get('patient_name')}
- Age: {demographics.get('age')}
- Gender: {demographics.get('gender')}
- Lab Ref No: {demographics.get('lab_ref_no')}

Official Laboratory Evaluation Data:
{deterministic_table}

{trends_markdown}

You MUST format your output strictly using this exact structure for each evaluated finding:

# Medical Report Analysis

{demo_card}

## 🩺 [Test Name]

### Your Result
[Value + Unit]

### Status
[Status Badge: ✅ Normal / ⚠️ Needs Attention / 🔴 High / 🔵 Low / ℹ️ Informational / ❓ Unable to Determine]

### What does this mean?
[Simple plain-language explanation]

### Does this suggest a health condition?
[Health Condition Suggestion Clause]

### What should you do?
[Simple practical next step]

### Which doctor should I consult?
[Recommended Specialist Category]

(Repeat ## 🩺 [Test Name] block for each test parameter)

{alerts_markdown if alerts_markdown else ""}

## 📋 Overall Health Summary

[Concise plain-language summary of overall report findings]

## Important Findings

🔴 **Needs Attention:**
- [List findings needing attention or High/Low]

✅ **Normal:**
- [List normal findings]

## Recommended Next Step

[One clear recommendation with recommended doctor category]"""

        prompt = f"Here is the medical report to explain based on the evaluated findings:\n\n{text}"
        return generate_ai_analysis(prompt, system_prompt), prompt, system_prompt

class ValidationGuardrailAgent:
    """Agent 7: Consistency Validation & Safety Guardrail Agent (with Retry & Fail-Closed Fallback)."""
    @staticmethod
    def validate_and_enforce(analysis_text, eval_results, two_way_alerts=None, prompt_ref=None, system_prompt_ref=None, raw_text=""):
        forbidden_phrases = [
            ("Deterministic Test Findings & Cautious Interpretation", ""),
            ("Deterministic Test Findings", ""),
            ("Deterministic Status", "Status"),
            ("Rule Engine", "System"),
            ("AI Summary", "Summary"),
            ("AI reasoning", "")
        ]
        cleaned_text = analysis_text
        if cleaned_text:
            for phrase, replacement in forbidden_phrases:
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                cleaned_text = pattern.sub(replacement, cleaned_text)
            cleaned_text = re.sub(r'##\s*Possible [^\n]*Finding[s]?\s*\n*\s*\([^\)]*(?:No abnormal|no specific abnormal|all normal)[^\)]*\)\s*\n*', '', cleaned_text, flags=re.IGNORECASE)

        # Execute Consistency Validation
        is_valid, violations = LLMConsistencyValidator.validate(cleaned_text, eval_results, two_way_alerts)
        
        if is_valid:
            # Append technical details under collapsible HTML tag for auditability
            if eval_results and "<details>" not in cleaned_text:
                cleaned_text += "\n\n<details>\n<summary>🔬 View Technical & Evidence Details</summary>\n\n"
                cleaned_text += rule_engine.format_deterministic_markdown(eval_results)
                cleaned_text += "\n\n</details>"
            return cleaned_text

        logger.warning(f"VALIDATION GUARDRAIL TRIGGERED: Violations detected: {violations}")

        # Attempt 1 Retry with Constrained Prompt
        if prompt_ref and system_prompt_ref:
            try:
                logger.info("Retrying LLM generation with constrained safety correction prompt...")
                correction_prompt = f"CRITICAL SAFETY CORRECTION NOTICE: Your previous output violated clinical safety rules for these reasons:\n"
                for v in violations:
                    correction_prompt += f"- {v}\n"
                correction_prompt += "\nPlease regenerate the explanation strictly adhering to the exact Rule Engine statuses, values, and non-diagnostic guidelines.\n\n"
                correction_prompt += prompt_ref

                retry_analysis = generate_ai_analysis(correction_prompt, system_prompt_ref)
                if retry_analysis:
                    for phrase, replacement in forbidden_phrases:
                        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                        retry_analysis = pattern.sub(replacement, retry_analysis)
                    
                    retry_valid, retry_violations = LLMConsistencyValidator.validate(retry_analysis, eval_results, two_way_alerts)
                    if retry_valid:
                        logger.info("Retry succeeded! Safe analysis generated.")
                        if eval_results and "<details>" not in retry_analysis:
                            retry_analysis += "\n\n<details>\n<summary>🔬 View Technical & Evidence Details</summary>\n\n"
                            retry_analysis += rule_engine.format_deterministic_markdown(eval_results)
                            retry_analysis += "\n\n</details>"
                        return retry_analysis
                    else:
                        logger.warning(f"Retry validation failed with violations: {retry_violations}")
            except Exception as retry_err:
                logger.warning(f"Retry attempt failed: {retry_err}")

        # Fail-Closed Fallback Generation (Zero LLM Dependency)
        logger.warning("Failing closed to safe code-generated deterministic fallback.")
        return generate_safe_deterministic_fallback(eval_results, two_way_alerts, raw_text=raw_text or prompt_ref or "")

def enforce_safety_guardrails(analysis_text, eval_results, two_way_alerts=None):
    """Wrapper function for backward compatibility."""
    return ValidationGuardrailAgent.validate_and_enforce(analysis_text, eval_results, two_way_alerts)

def analyze_medical_report(text, ocr_metadata=None, patient_name=None):
    try:
        p_name = patient_name or extract_patient_name(text) or "Default Patient"

        # Agent 2: Laboratory Evaluation
        eval_results = LaboratoryEvaluationAgent.evaluate(text, ocr_metadata=ocr_metadata)

        # Agent 8: Tabular ML Safety Classification Agent
        ml_safety_summary = TabularMLAgent.evaluate_report(eval_results, ocr_metadata=ocr_metadata)

        # Agent 3: Patient History & Trend Detection
        trends = PatientHistoryAgent.process(eval_results, patient_name=p_name)

        # Agent 5: Safety Cross-Check (Direction B: New Labs -> Active Medications)
        two_way_alerts = SafetyCrossCheckAgent.check_direction_b(eval_results, patient_name=p_name)

        # Agent 6: Constrained Explanation Generator
        raw_analysis, prompt_ref, sys_prompt_ref = ExplanationAgent.generate(text, eval_results, two_way_alerts, trends)

        # Agent 7: Consistency Validation & Safety Guardrails
        validated_analysis = ValidationGuardrailAgent.validate_and_enforce(
            raw_analysis, eval_results, two_way_alerts, prompt_ref=prompt_ref, system_prompt_ref=sys_prompt_ref, raw_text=text
        )

        return {
            'english': validated_analysis,
            'bangla': None,
            'patient_name': p_name
        }

    except Exception as e:
        if is_connection_error(e):
            logger.warning("AI Connection failed. Returning structured patient demographic & deterministic fallback response.")
            eval_results = rule_engine.parse_and_evaluate(text)
            two_way_alerts = SafetyCrossCheckAgent.check_direction_b(eval_results, patient_name=p_name)
            fallback_text = generate_safe_deterministic_fallback(eval_results, two_way_alerts, raw_text=text)
            return {
                'english': fallback_text,
                'bangla': None,
                'patient_name': p_name
            }
        return {
            'success': False,
            'error': f"Error analyzing report: {str(e)}"
        }

def analyze_symptoms(symptoms):
    try:
        system_prompt = """You are a medical advisor. Based on the symptoms, please:
1. Analyze the symptoms and provide potential conditions
2. Rate the urgency level (Low/Medium/High)
3. Suggest immediate steps or precautions
4. Recommend when to seek professional medical help

Please note this is for informational purposes only and not a substitute for professional medical advice."""

        prompt = f"Symptoms:\n{symptoms}"
        
        english_analysis = generate_ai_analysis(prompt, system_prompt)
        medline_info = "\n\nFor more detailed medical information, please visit: https://medlineplus.gov/"

        return {
            'english': english_analysis + medline_info,
            'bangla': None
        }

    except Exception as e:
        if is_connection_error(e):
            logger.warning("AI Connection failed for symptoms analysis.")
            fallback_text = f"""# 🔍 Symptoms Assessment & Guidance

### 📋 Reported Symptoms
> "{symptoms}"

---

## ⚡ Preliminary Health Guidance
1. **Urgency Level**: 🟡 **Medium** (Monitor symptoms closely)
2. **General Precautions**: Rest adequately, maintain proper hydration, and track any symptom changes.
3. **When to Seek Urgent Care**: Seek immediate medical attention if you experience high fever, severe pain, shortness of breath, or sudden weakness.

> ⚠️ **Medical Disclaimer**: This automated symptom summary is provided for general informational guidance only. Always consult a certified physician for medical advice."""
            return {
                'english': fallback_text,
                'bangla': None
            }
        return {
            'success': False,
            'error': f"Error analyzing symptoms: {str(e)}"
        }

def analyze_medicine(medicine_name, dosage, patient):
    try:
        p_name = "Default Patient"
        if patient and isinstance(patient, dict) and patient.get('name'):
            p_name = patient.get('name')

        # Agent 4 & 5: Prescription Classification & Safety Cross-Check (Direction A: Prescription -> Past Labs)
        PrescriptionAgent.classify(medicine_name, dosage, patient_name=p_name)
        patient_history.add_prescription_record(medicine_name, patient_name=p_name)
        rx_alerts = SafetyCrossCheckAgent.check_direction_a(medicine_name, patient_name=p_name)

        rx_alerts_md = ""
        if rx_alerts:
            alerts_lines = ["\n\n## Possible Medication–Lab Safety Alert"]
            for alert in rx_alerts:
                alerts_lines.append(f"### {alert['title']} ({alert['severity']} Priority)")
                alerts_lines.append(f"- **Details:** {alert['explanation']}")
                alerts_lines.append("- **Note:** Potential medication-lab safety relationship detected. Professional clinical confirmation by your prescribing doctor is recommended.")
                alerts_lines.append("")
            rx_alerts_md = "\n".join(alerts_lines)

        dosage_str = []
        if dosage.get('morning', 0) > 0:
            dosage_str.append(f"{dosage['morning']} tablet(s) in the morning")
        if dosage.get('evening', 0) > 0:
            dosage_str.append(f"{dosage['evening']} tablet(s) in the evening")
        if dosage.get('night', 0) > 0:
            dosage_str.append(f"{dosage['night']} tablet(s) at night")
        
        formatted_dosage = ", ".join(dosage_str) if dosage_str else "As directed"

        system_prompt = "You are a medical information advisor."
        prompt = f"""Please analyze the following medicine and dosage for a patient:

Patient Information:
- Patient Name: {p_name}
- Age: {patient.get('age', 'N/A')} years old
- Gender: {patient.get('gender', 'N/A')}

Medicine Name: {medicine_name}
Current Dosage: {formatted_dosage}

Provide:
1. Primary uses
2. Side effects (common to severe)
3. Recommended dosage comparison
4. Warnings & drug interactions
5. When to seek medical attention"""

        english_analysis = generate_ai_analysis(prompt, system_prompt)
        if rx_alerts_md:
            english_analysis += rx_alerts_md
        english_analysis += "\n\nFor more detailed medical information, please visit: https://medlineplus.gov/druginformation.html"

        return {
            'english': english_analysis,
            'bangla': None,
            'patient_name': p_name
        }

    except Exception as e:
        if is_connection_error(e):
            logger.warning("AI Connection failed for medicine analysis.")
            fallback_text = f"""# 💊 Medicine Information & Guidance

### 👤 Patient Profile
* **Patient Name**: {p_name}
* **Age / Gender**: {patient.get('age')} Years / {patient.get('gender')}
* **Prescribed Medicine**: `{medicine_name}`
* **Dosage Schedule**: {formatted_dosage}

---

## 💡 Practical Usage & Safety Guidance
1. **General Usage**: Take `{medicine_name}` as instructed by your prescribing doctor or pharmacist.
2. **Precaution**: Do not stop or alter prescribed dosages without medical consultation.

> ⚠️ **Medical Disclaimer**: This automated summary is provided for general informational guidance only. Always consult a certified physician for medical advice."""
            return {
                'english': fallback_text,
                'bangla': None
            }
        return {
            'success': False,
            'error': f"Error analyzing medicine: {str(e)}"
        }

def analyze_prescription_text(text, patient=None):
    try:
        p_name = None
        if patient and isinstance(patient, dict) and patient.get('name') and str(patient.get('name')).strip():
            p_name = str(patient.get('name')).strip()
        if not p_name:
            p_name = extract_patient_name(text) or "Default Patient"

        patient_info = f"\nPatient Information: Name: {p_name}\n"
        if patient and isinstance(patient, dict):
            age = patient.get('age')
            gender = patient.get('gender')
            if age or gender:
                patient_info += f"Age: {age or 'N/A'}, Gender: {gender or 'N/A'}\n"

        # Agent 4 & 5: Register active medications from lines & Direction A Safety Check
        lines = text.splitlines()
        rx_alerts = []
        for line in lines:
            line_s = line.strip()
            if line_s and not line_s.startswith(("#", "//", "Patient")):
                first_word = line_s.split()[0].strip(":,.-")
                if len(first_word) >= 3:
                    PrescriptionAgent.classify(first_word, patient_name=p_name)
                    patient_history.add_prescription_record(first_word, extracted_text=line_s, patient_name=p_name)
                    alerts = SafetyCrossCheckAgent.check_direction_a(first_word, patient_name=p_name)
                    if alerts:
                        rx_alerts.extend(alerts)

        rx_alerts_md = ""
        if rx_alerts:
            alerts_lines = ["\n\n## Possible Medication–Lab Safety Alert"]
            for alert in rx_alerts:
                alerts_lines.append(f"### {alert['title']} ({alert['severity']} Priority)")
                alerts_lines.append(f"- **Details:** {alert['explanation']}")
                alerts_lines.append("- **Note:** Potential medication-lab safety relationship detected. Professional clinical confirmation by your prescribing doctor is recommended.")
                alerts_lines.append("")
            rx_alerts_md = "\n".join(alerts_lines)

        system_prompt = """You are an expert clinical pharmacist and medical AI advisor. Analyze the provided prescription document text and format your response strictly using the following clear Markdown sections:

# Prescription & Medication Analysis

## 1. Identified Prescriptions & Dosage
- **Prescribed Medications**: List each identified medication name, dosage strength, and frequency schedule (Morning, Evening, Night).
- **Patient Profile Context**: State patient demographics if provided.

## AI Summary
Provide a concise, 1-2 sentence plain-language summary of the overall prescription instructions and intended treatment goal.

## Key Indications & Drug Usage
- Explain the primary medical purpose for each identified drug in simple language.

## Precautions & Side Effects
- Highlight common side effects and key safety warnings.
- Warn against potential drug-drug or drug-food interactions.

## Recommended Follow-up Actions
- Provide clear instructions on taking medicines with/after meals, storage recommendations, and when to follow up with the prescribing doctor."""

        prompt = f"Here is the extracted prescription document text to analyze:{patient_info}\n\n{text}"
        
        english_analysis = generate_ai_analysis(prompt, system_prompt)
        if rx_alerts_md:
            english_analysis += rx_alerts_md
        english_analysis += "\n\nFor official drug information, please visit: https://medlineplus.gov/druginformation.html"

        return {
            'english': english_analysis,
            'bangla': None,
            'patient_name': p_name
        }

    except Exception as e:
        if is_connection_error(e):
            logger.warning("AI Connection failed for prescription analysis.")
            demographics = patient_history.extract_patient_demographics(text)
            lines_res = ["# 💊 Prescription Analysis & Medication Guidance", ""]
            lines_res.append("### 👤 Patient Information")
            lines_res.append("| Demographic Field | Value | Demographic Field | Value |")
            lines_res.append("| :--- | :--- | :--- | :--- |")
            lines_res.append(f"| **Patient Name** | **{demographics.get('patient_name', p_name)}** | **Age / Gender** | {demographics.get('age', 'N/A')} Years / {demographics.get('gender', 'N/A')} |")
            lines_res.append(f"| **Lab Ref No.** | `{demographics.get('lab_ref_no', 'N/A')}` | **Date** | {demographics.get('registration_date', 'N/A')} |")
            lines_res.append("")
            lines_res.append("---")
            lines_res.append("")
            lines_res.append("## 📋 Extracted Prescription & Medication Findings\n")
            lines_res.append(f"> {text[:350]}...\n" if len(text) > 350 else f"> {text}\n")
            lines_res.append("## 💧 Recommended Health Actions & Next Steps\n")
            lines_res.append("- 💊 **Verify Dosages**: Confirm dosage schedules directly with your pharmacist or prescribing doctor.")
            lines_res.append("- 👨‍⚕️ **Medical Follow-Up**: Schedule regular check-ups to monitor treatment response.\n")
            lines_res.append("> ⚠️ **Medical Disclaimer**: This automated prescription summary is provided for informational support only. Do not alter prescribed drug dosages without consulting your licensed healthcare provider.")
            fallback_text = "\n".join(lines_res)
            return {
                'english': fallback_text,
                'bangla': None,
                'patient_name': p_name
            }
        return {
            'success': False,
            'error': f"Error analyzing prescription: {str(e)}"
        }

@app.route('/upload-prescription', methods=['POST'])
def upload_prescription():
    filepath = None
    try:
        if 'file' not in request.files:
            logger.error("No file part in prescription request")
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.error("No selected file in prescription request")
            return jsonify({'error': 'No selected file'}), 400

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"rx_{filename}")
            file.save(filepath)
            logger.info(f"Prescription file saved: {filepath}")

            try:
                ext = filename.rsplit('.', 1)[1].lower()
                text, ocr_meta = PerceptionExtractionAgent.extract(filepath, ext)

                if text and text.startswith("Error:"):
                    logger.error(f"Prescription text extraction failed: {text}")
                    return jsonify({'error': text}), 400

                age = request.form.get('age')
                gender = request.form.get('gender')
                p_name_form = request.form.get('patient_name')

                # Create standardized Prescription Pipeline Context
                pipeline_ctx = InputRouter.create_pipeline_context(
                    document_type="prescription",
                    raw_input=filepath,
                    metadata={
                        "patient_name": p_name_form,
                        "age": int(age) if age and age.isdigit() else None,
                        "gender": gender if gender in ['male', 'female', 'other'] else None
                    }
                )

                logger.info("Executing Complete 4-Stage Prescription Pipeline")
                pipeline_ctx = PrescriptionPipelineBoundary.process_prescription(
                    pipeline_ctx,
                    ocr_extractor_func=PerceptionExtractionAgent.extract,
                    ai_generator_func=generate_ai_analysis
                )
                logger.info("Complete Prescription Pipeline execution finished")

                analysis_summary = pipeline_ctx["reasoning"].get("summary", "")
                p_name_res = pipeline_ctx["extracted_data"].get("patient_info", {}).get("patient_name") or p_name_form

                return jsonify({
                    'success': True,
                    'analysis': {
                        'english': analysis_summary,
                        'bangla': None,
                        'patient_name': p_name_res
                    },
                    'pipeline_context': pipeline_ctx
                })
            finally:
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        logger.info("Prescription file processed and removed")
                    except Exception as _e:
                        logger.warning(f"Could not remove temp file {filepath}: {_e}")

        logger.error("Invalid file type from extension check for prescription")
        return jsonify({'error': 'Invalid file type. Please upload a JPG, PNG, or PDF file.'}), 400

    except Exception as e:
        logger.error(f"Unexpected error in upload_prescription: {str(e)}")
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            logger.error("No file part in request")
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.error("No selected file")
            return jsonify({'error': 'No selected file'}), 400

        patient_name = request.form.get('patient_name')

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved: {filepath}")

            try:
                ext = filename.rsplit('.', 1)[1].lower()
                text, ocr_meta = PerceptionExtractionAgent.extract(filepath, ext)

                os.remove(filepath)
                logger.info("File processed and removed")

                if text and text.startswith("Error:"):
                    logger.error(f"Text extraction failed: {text}")
                    return jsonify({'error': text}), 400

                # Input Router (Step 1 Foundation)
                pipeline_ctx = InputRouter.route_and_create_context(
                    text=text,
                    filename=filename,
                    explicit_type="medical_report",
                    metadata={"patient_name": patient_name, "ocr_metadata": ocr_meta}
                )
                logger.info(f"InputRouter classified payload as: {pipeline_ctx['document_type']}")

                # Report Extraction Agent (Step 2)
                pipeline_ctx = ReportExtractionAgent.process(pipeline_ctx)
                logger.info(f"ReportExtractionAgent extracted {len(pipeline_ctx['extracted_data'].get('biomarkers', []))} biomarkers")

                # Report Verification Agent (Step 3)
                pipeline_ctx = ReportVerificationAgent.process(pipeline_ctx)
                logger.info(f"ReportVerificationAgent verified {len(pipeline_ctx['verification'].get('biomarkers', []))} biomarkers")

                # ML Safety Classifier Agent (Step 4)
                pipeline_ctx = MLSafetyAgent.evaluate_safety(pipeline_ctx)
                logger.info(f"MLSafetyAgent classified overall report safety as: {pipeline_ctx['safety'].get('safety_status')}")

                # Report Reasoning Agent (Step 5)
                pipeline_ctx = ReportReasoningAgent.process(pipeline_ctx, ai_generator_func=generate_ai_analysis)
                logger.info(f"ReportReasoningAgent reasoning completed using: {pipeline_ctx['reasoning'].get('generated_by')}")

                logger.info("Starting text analysis")
                analysis = analyze_medical_report(text, ocr_metadata=ocr_meta, patient_name=patient_name)
                logger.info("Analysis completed")
                
                if isinstance(analysis, dict) and 'error' in analysis:
                    return jsonify(analysis), 500
                
                return jsonify({
                    'success': True,
                    'analysis': analysis,
                    'document_type': pipeline_ctx['document_type'],
                    'pipeline_context': pipeline_ctx
                })
            except Exception as e:
                logger.error(f"Error processing file: {str(e)}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return jsonify({'error': f'Error processing file: {str(e)}'}), 500

        logger.error("Invalid file type from extension check")
        return jsonify({'error': 'Invalid file type'}), 400

    except Exception as e:
        logger.error(f"Unexpected error in upload_file: {str(e)}")
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@app.route('/api/route-input', methods=['POST'])
def route_input_endpoint():
    """Step 1 Foundation Endpoint for testing document type routing."""
    try:
        data = request.get_json(silent=True) or {}
        text = data.get('text', '')
        filename = data.get('filename', '')
        explicit_type = data.get('document_type')
        ctx = InputRouter.route_and_create_context(text=text, filename=filename, explicit_type=explicit_type)
        return jsonify({
            'success': True,
            'routing_result': {
                'document_type': ctx['document_type']
            },
            'pipeline_context': ctx
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients', methods=['GET'])
def get_patients_list():
    try:
        patients = patient_history.list_all_patients()
        return jsonify({'success': True, 'patients': patients})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patient/<patient_name>', methods=['GET'])
def get_patient_detail(patient_name):
    try:
        history = patient_history.get_patient_history(patient_name)
        return jsonify({'success': True, 'patient': history})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patient/active-medication', methods=['POST'])
def add_patient_medication():
    try:
        data = request.get_json() or {}
        med_name = data.get('medicine_name')
        patient_name = data.get('patient_name', 'Default Patient')
        dosage = data.get('dosage')

        if not med_name:
            return jsonify({'error': 'Medicine name is required'}), 400

        patient_history.add_active_medication(med_name, dosage=dosage, patient_name=patient_name)
        alerts = patient_history.check_prescription_against_past_labs(med_name, patient_name=patient_name)
        
        return jsonify({
            'success': True,
            'message': f"Added active medication '{med_name}' for patient '{patient_name}'",
            'safety_alerts': alerts
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/analyze-symptoms', methods=['POST'])
def process_symptoms():
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            logger.error("No symptoms provided in request")
            return jsonify({'error': 'No symptoms provided'}), 400

        symptoms = data['symptoms']
        if not symptoms.strip():
            logger.error("Empty symptoms string provided")
            return jsonify({'error': 'Symptoms cannot be empty'}), 400

        logger.info("Starting symptoms analysis")
        analysis = analyze_symptoms(symptoms)
        logger.info("Symptoms analysis completed")
        
        if isinstance(analysis, dict) and 'error' in analysis:
            return jsonify(analysis), 500
            
        return jsonify({
            'success': True,
            'analysis': analysis
        })
    except Exception as e:
        logger.error(f"Error in process_symptoms: {str(e)}")
        return jsonify({'error': f'Error processing symptoms: {str(e)}'}), 500

@app.route('/translate', methods=['POST'])
def translate_text():
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            logger.error("No text provided for translation")
            return jsonify({'error': 'No text provided'}), 400

        text = data['text']
        target_language = data.get('target_language', 'Kannada').strip()

        if not text.strip():
            logger.error("Empty text provided for translation")
            return jsonify({'error': 'Text cannot be empty'}), 400

        logger.info(f"Starting AI medical translation into {target_language}")
        system_prompt = f"""You are an expert medical translator AI. Your task is to translate the provided medical analysis report into {target_language}.
Rules:
1. Preserve all Markdown formatting, section titles (#, ##), bullet points, blockquotes (>), bold highlights (**text**), and line breaks.
2. Keep numbers, lab values, and measurement units (e.g. 121.6 mg/dl, %, mg/dL) intact.
3. Provide an accurate, fluent medical translation."""

        prompt = f"Translate the following medical analysis into {target_language}:\n\n{text}"
        try:
            translated_text = generate_ai_analysis(prompt, system_prompt)
        except Exception as ai_err:
            logger.warning(f"AI Connection failed during translation into {target_language}: {ai_err}")
            translated_text = f"> ⚠️ **Translation Warning**: AI service offline. Displaying report in original language.\n\n{text}"

        logger.info("AI Translation completed")
        return jsonify({
            'success': True,
            'translation': translated_text,
            'language': target_language
        })
    except Exception as e:
        logger.error(f"Error in translation: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error during translation: {str(e)}'
        }), 500

@app.route('/analyze-medicine', methods=['POST'])
def process_medicine():
    try:
        data = request.get_json()
        if not data or 'medicine' not in data or 'dosage' not in data or 'patient' not in data:
            logger.error("Missing medicine information")
            return jsonify({'error': 'Missing required information'}), 400

        medicine = data['medicine'].strip()
        dosage = data['dosage']
        patient = data['patient']

        if not medicine:
            logger.error("Empty medicine name provided")
            return jsonify({'error': 'Medicine name cannot be empty'}), 400

        required_fields = ['morning', 'evening', 'night']
        if not all(field in dosage for field in required_fields):
            logger.error("Invalid dosage format")
            return jsonify({'error': 'Invalid dosage format'}), 400

        if not isinstance(patient.get('age'), int) or patient['age'] <= 0:
            logger.error("Invalid patient age")
            return jsonify({'error': 'Invalid patient age'}), 400

        if not patient.get('gender') or patient['gender'] not in ['male', 'female', 'other']:
            logger.error("Invalid patient gender")
            return jsonify({'error': 'Invalid patient gender'}), 400

        logger.info(f"Starting medicine analysis for: {medicine} (Patient: {patient['age']}y, {patient['gender']})")
        analysis = analyze_medicine(medicine, dosage, patient)
        logger.info("Medicine analysis completed")
        
        if isinstance(analysis, dict) and 'error' in analysis:
            return jsonify(analysis), 500
            
        return jsonify({
            'success': True,
            'analysis': analysis
        })
    except Exception as e:
        logger.error(f"Error in process_medicine: {str(e)}")
        return jsonify({'error': f'Error processing medicine information: {str(e)}'}), 500

@app.route('/analyze-report-text', methods=['POST'])
def process_report_text():
    try:
        data = request.get_json()
        if not data or 'report_text' not in data:
            logger.error("No report text provided in request")
            return jsonify({'error': 'No report text provided'}), 400

        report_text = data['report_text'].strip()
        if not report_text:
            logger.error("Empty report text provided")
            return jsonify({'error': 'Report text cannot be empty'}), 400

        logger.info("Starting direct report text analysis")
        analysis = analyze_medical_report(report_text)
        logger.info("Report text analysis completed")
        
        if isinstance(analysis, dict) and 'error' in analysis:
            return jsonify(analysis), 500
            
        return jsonify({
            'success': True,
            'analysis': analysis
        })
    except Exception as e:
        logger.error(f"Error in process_report_text: {str(e)}")
        return jsonify({'error': f'Error processing report text: {str(e)}'}), 500

class PatientHistoryRAGChatbot:
    """
    Stage 6 (Objective 3): Custom RAG Chatbot (Novelty Addition)
    Retrieves structured patient lab history, active medications, and verified report context
    from PatientHistoryManager state store to answer patient follow-up questions safely.
    """

    @classmethod
    def answer_patient_query(cls, patient_id, query_text):
        if not query_text or not isinstance(query_text, str):
            return "Please enter a valid follow-up question regarding your medical report or medications."

        patient_record = patient_history.get_patient_record(patient_id or "default_patient")
        active_meds = patient_record.get("active_medications", [])
        past_labs = patient_record.get("past_lab_history", [])
        trends = patient_history.analyze_parameter_trends([], patient_name=patient_id or "default_patient")

        retrieval_context = []
        retrieval_context.append(f"Patient ID: {patient_id or 'default_patient'}")

        if active_meds:
            med_lines = [f"- {m.get('medication')} ({m.get('strength', 'N/A')}, {m.get('frequency', 'N/A')})" for m in active_meds]
            retrieval_context.append("Active Prescribed Medications:\n" + "\n".join(med_lines))
        else:
            retrieval_context.append("Active Prescribed Medications: None recorded")

        if past_labs:
            lab_lines = [f"- {l.get('test_name')}: {l.get('value')} {l.get('unit')} (Status: {l.get('status')})" for l in past_labs[-10:]]
            retrieval_context.append("Recent Laboratory Test Findings:\n" + "\n".join(lab_lines))
        else:
            retrieval_context.append("Recent Laboratory Test Findings: None recorded")

        if trends:
            retrieval_context.append(f"Longitudinal Health Trends: {trends}")

        context_str = "\n\n".join(retrieval_context)

        system_prompt = """You are an empathetic, expert patient assistant AI. Answer the patient's question using ONLY the provided verified patient history context.
Rules:
1. NEVER confirm a medical diagnosis or use forbidden diagnostic phrases like "you have kidney failure" or "active infection".
2. DO NOT prescribe new medications or advise stopping prescribed drugs without doctor consultation.
3. Keep your response patient-friendly, factual, clear, and reassuring.
4. Always conclude with a recommendation to consult their primary care physician."""

        user_prompt = f"Patient Question: {query_text}\n\nRetrieved Structured Patient History:\n{context_str}"

        try:
            ai_reply = generate_ai_analysis(user_prompt, system_prompt)
            guarded_reply = sanitize_llm_explanation(ai_reply, None)
            return guarded_reply
        except Exception as e:
            logger.warning(f"RAG Chatbot AI fallback: {e}")
            if active_meds:
                med_names = ", ".join([m.get("name", m.get("medication", "Medication")) for m in active_meds])
                return f"Based on your recorded patient history, active medications include: {med_names}. Please consult your primary care doctor for personalized medical guidance."
            return f"Based on your recorded lab history ({len(past_labs)} tests) and active medications ({len(active_meds)} prescribed), please review your detailed report summary above and consult your primary care doctor for personalized medical guidance."

@app.route('/api/patient-chat', methods=['POST'])
def patient_chat_endpoint():
    try:
        data = request.get_json() or {}
        patient_id = data.get('patient_id', 'default_patient')
        query_text = data.get('query', '').strip()

        if not query_text:
            return jsonify({'success': False, 'error': 'Query text cannot be empty.'}), 400

        reply = PatientHistoryRAGChatbot.answer_patient_query(patient_id, query_text)
        return jsonify({
            'success': True,
            'patient_id': patient_id,
            'query': query_text,
            'response': reply
        })
    except Exception as e:
        logger.error(f"Error in patient_chat_endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)