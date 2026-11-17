"""
app.py — Medical Report Analyzer & Prescription Assistant
Enhanced Agentic AI v3.0 — Full Integration Build
Preserves all original functionality + adds DDI, biomarker extraction, patient history, RAG chatbot
"""

import os
import io
import cv2
import uuid
import numpy as np
import threading
import concurrent.futures
from flask import Flask, request, render_template, jsonify, session
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
from dotenv import load_dotenv
import requests
import json
import logging
import shutil

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Tesseract auto-discovery
# ---------------------------------------------------------------------------
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
    logger.warning("Tesseract not found. Will rely on RapidOCR and Windows OCR.")
    return None

TESSERACT_AVAILABLE = init_tesseract() is not None

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "medical-analyzer-secret-2026")
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {
    'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp',
    'pdf', 'docx', 'doc', 'txt'
}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp'}

# ---------------------------------------------------------------------------
# LLM Configuration (preserved from original)
# ---------------------------------------------------------------------------
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "deepseek-r1:14b"
NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"

NVIDIA_PREFERRED_MODELS = [
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "mistralai/mistral-large-4-1t-a52b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "poolside/laguna-xs-2.1",
]
_working_nvidia_model = None

# ---------------------------------------------------------------------------
# RapidOCR — global singleton
# ---------------------------------------------------------------------------
rapid_ocr_engine = None
rapid_ocr_lock = threading.Lock()
try:
    from rapidocr_onnxruntime import RapidOCR
    rapid_ocr_engine = RapidOCR()
    logger.info("RapidOCR pre-initialized.")
except Exception as _ocr_err:
    logger.warning(f"RapidOCR init warning: {_ocr_err}")

# ---------------------------------------------------------------------------
# Windows OCR
# ---------------------------------------------------------------------------
from win_ocr import run_win_ocr

# ---------------------------------------------------------------------------
# Enhanced modules
# ---------------------------------------------------------------------------
from rule_engine import extract_biomarkers_from_text, format_findings_for_display, classify_finding, validate_finding_7_layers
from ddi_engine import (
    normalize_medicine_name, run_full_ddi_check,
    get_ingredients, get_category, TRUSTED_MEDICATION_DATABASE,
    check_prescription_vs_labs, check_labs_vs_active_medicines
)
from database import (
    init_db, save_analysis, get_analysis_history, save_active_medicines,
    get_active_medicines, save_lab_results, get_lab_history, get_session_context,
    get_patient_profile, save_patient_profile, set_medicine_status
)

# Initialize database
init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_session_id():
    """Get or create a session ID."""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


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


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------
def preprocess_image_for_ocr(image_path):
    try:
        img_cv = cv2.imread(image_path)
        if img_cv is None:
            pil_img = Image.open(image_path).convert('RGB')
            img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        if max(h, w) < 1500:
            scale = 2.0
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        binary = cv2.adaptiveThreshold(
            denoised, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10
        )
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(binary, -1, kernel)
        return Image.fromarray(sharpened)
    except Exception as e:
        logger.warning(f"Image preprocessing failed: {e}. Using original.")
        try:
            return Image.open(image_path).convert('L')
        except Exception:
            return Image.open(image_path)


def ocr_single_image_pil(pil_image):
    """Run OCR on a PIL Image using all available engines."""
    texts = []
    if rapid_ocr_engine:
        try:
            img_array = np.array(pil_image.convert('RGB'))
            with rapid_ocr_lock:
                ocr_result, _ = rapid_ocr_engine(img_array)
            if ocr_result:
                lines = [line[1] for line in ocr_result if line and len(line) > 1 and line[1].strip()]
                if lines:
                    texts.append(("rapidocr", "\n".join(lines)))
        except Exception as e:
            logger.warning(f"RapidOCR: {e}")

    if TESSERACT_AVAILABLE:
        try:
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(pil_image, config=custom_config)
            if text and text.strip():
                texts.append(("tesseract", text.strip()))
        except Exception as e:
            logger.warning(f"Tesseract: {e}")

    if texts:
        best = max(texts, key=lambda x: len(x[1]))
        logger.info(f"Best OCR engine: {best[0]} ({len(best[1])} chars)")
        return best[1]
    return ""


def extract_text_from_image(image_path):
    preprocessed = preprocess_image_for_ocr(image_path)
    text = ocr_single_image_pil(preprocessed)
    if text and len(text.strip()) > 10:
        return text
    try:
        orig = Image.open(image_path)
        text = ocr_single_image_pil(orig)
        if text and text.strip():
            return text
    except Exception as e:
        logger.warning(f"Original image OCR fallback: {e}")
    try:
        win_text = run_win_ocr(image_path)
        if win_text and win_text.strip():
            logger.info("Windows Native OCR succeeded.")
            return win_text
    except Exception as e:
        logger.warning(f"Windows Native OCR: {e}")
    return "Error: Could not extract text from this image."


def _process_pdf_page(args):
    page_index, pil_image = args
    try:
        text = ocr_single_image_pil(pil_image)
        return (page_index, text)
    except Exception:
        return (page_index, "")


def extract_text_from_pdf(pdf_path):
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        native_texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t and t.strip():
                native_texts.append(t.strip())
        if native_texts:
            combined = "\n\n".join(native_texts)
            if len(combined.strip()) > 50:
                return combined
    except Exception as e:
        logger.warning(f"PyPDF extraction: {e}")

    try:
        from pdf2image import convert_from_path
        poppler_paths = [
            r'C:\Program Files\poppler\Library\bin',
            r'C:\Program Files\poppler\bin',
            r'C:\Program Files (x86)\poppler\bin',
            os.path.expanduser(r'~\AppData\Local\Programs\poppler\Library\bin'),
        ]
        poppler_path = None
        for p in poppler_paths:
            if os.path.isdir(p):
                poppler_path = p
                break

        kwargs = {'dpi': 200, 'fmt': 'PNG'}
        if poppler_path:
            kwargs['poppler_path'] = poppler_path

        images = convert_from_path(pdf_path, **kwargs)
        if not images:
            return "Error: Could not render PDF pages."

        page_args = [(i, img) for i, img in enumerate(images)]
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(images))) as executor:
            futures = {executor.submit(_process_pdf_page, arg): arg[0] for arg in page_args}
            for future in concurrent.futures.as_completed(futures):
                try:
                    page_idx, text = future.result()
                    results[page_idx] = text
                except Exception as e:
                    logger.warning(f"PDF page OCR error: {e}")

        sorted_texts = [results.get(i, "") for i in range(len(images))]
        combined = "\n\n".join(t for t in sorted_texts if t.strip())
        if combined.strip():
            return combined
    except Exception as e:
        logger.warning(f"PDF to image: {e}")

    return "Error: Could not extract text from this PDF."


def extract_text_from_docx(file_path):
    try:
        import docx
        doc = docx.Document(file_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        if paragraphs:
            return "\n".join(paragraphs)
    except Exception as e:
        logger.warning(f"DOCX extraction: {e}")
    return "Error: Could not extract text from Word document."


def extract_text_from_txt(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        logger.warning(f"TXT extraction: {e}")
    return "Error: Could not read text file."


def extract_text(file_path, ext):
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return extract_text_from_image(file_path)
    elif ext == 'pdf':
        return extract_text_from_pdf(file_path)
    elif ext in ('docx', 'doc'):
        return extract_text_from_docx(file_path)
    elif ext == 'txt':
        return extract_text_from_txt(file_path)
    return "Error: Unsupported file format."


# ---------------------------------------------------------------------------
# LLM AI Analysis (preserved + enhanced)
# ---------------------------------------------------------------------------
def generate_ai_analysis(prompt, system_prompt="You are an expert medical AI advisor."):
    global _working_nvidia_model
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()

    if nvidia_key:
        try:
            from openai import OpenAI
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_key)
            env_model = os.getenv("NVIDIA_MODEL", "").strip()
            candidates = []
            if _working_nvidia_model:
                candidates.append(_working_nvidia_model)
            if env_model and env_model not in candidates:
                candidates.append(env_model)
            for m in NVIDIA_PREFERRED_MODELS:
                if m not in candidates:
                    candidates.append(m)

            last_error = None
            for model in candidates:
                try:
                    logger.info(f"Trying NVIDIA NIM model: {model}")
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        max_tokens=1500,
                        timeout=60
                    )
                    _working_nvidia_model = model
                    logger.info(f"NVIDIA NIM success: {model}")
                    return response.choices[0].message.content
                except Exception as model_err:
                    err_str = str(model_err)
                    if any(code in err_str for code in ['410', '404', '403', 'end of life', 'Not found', 'not subscribed']):
                        logger.warning(f"Model {model} unavailable, trying next...")
                        if _working_nvidia_model == model:
                            _working_nvidia_model = None
                        last_error = model_err
                        continue
                    logger.warning(f"Model {model} error ({err_str[:60]}), trying next...")
                    last_error = model_err
                    continue

            logger.error(f"All NVIDIA models failed. Last error: {last_error}")
        except ImportError:
            logger.warning("openai package not installed.")
        except Exception as e:
            logger.error(f"NVIDIA client init error: {e}")

    # Ollama fallback
    try:
        model = get_available_ollama_model()
        data = {
            "model": model,
            "prompt": f"{system_prompt}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1500}
        }
        logger.info(f"Trying Ollama local AI: {model}")
        response = requests.post(OLLAMA_ENDPOINT, json=data, timeout=180)
        response.raise_for_status()
        result = response.json()
        text = result.get('response', '')
        if text.strip():
            return text
    except Exception as e:
        logger.warning(f"Ollama unavailable: {e}")

    raise requests.exceptions.ConnectionError(
        "No AI backend available. Set a valid NVIDIA_API_KEY or start Ollama."
    )


def is_connection_error(e):
    err_str = str(e).lower()
    return isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)) or \
        'connection refused' in err_str or '10061' in err_str or 'actively refused' in err_str or \
        'max retries exceeded' in err_str or 'no ai backend' in err_str


# ---------------------------------------------------------------------------
# Medicine Extractor from prescription text
# ---------------------------------------------------------------------------
import re

def extract_medicines_from_text(text: str) -> list[dict]:
    """Extract medicine names from prescription text."""
    medicines = []
    seen = set()

    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Try to match medicine patterns
        # Pattern: Tab./Cap./Syp. MedicineName Strength Dosage
        med_match = re.search(
            r'(?:tab|cap|tablet|capsule|syrup|inj|injection|drops|cream|gel|oint|patch)\.?\s+([a-zA-Z][a-zA-Z\s\-]+?)(?:\s+\d|\s*\(|\s*$)',
            line, re.IGNORECASE
        )
        if med_match:
            med_name = med_match.group(1).strip()
            if len(med_name) > 2 and med_name.lower() not in seen:
                canon = normalize_medicine_name(med_name)
                seen.add(med_name.lower())
                dosage_match = re.search(r'(\d+(?:\.\d+)?\s*mg|\d+\s*ml|\d+\s*mcg|\d+\s*iu)', line, re.IGNORECASE)
                freq_match = re.search(r'(\d-\d-\d|\d\s*times|\bbd\b|\btds\b|\bod\b|\bqid\b)', line, re.IGNORECASE)
                dur_match = re.search(r'(\d+\s*(?:days?|weeks?|months?))', line, re.IGNORECASE)
                medicines.append({
                    "name": med_name,
                    "canonical_name": canon or med_name.lower(),
                    "category": TRUSTED_MEDICATION_DATABASE.get(canon, {}).get("category", "medicine") if canon else "medicine",
                    "dosage": dosage_match.group(0) if dosage_match else "",
                    "frequency": freq_match.group(0) if freq_match else "",
                    "duration": dur_match.group(0) if dur_match else "",
                    "raw_line": line,
                    "verified": canon is not None
                })
            continue

        # Fallback: check if any word in the line matches a known medicine
        words = re.findall(r'[a-zA-Z]{4,}', line)
        for word in words:
            if word.lower() in seen:
                continue
            canon = normalize_medicine_name(word)
            if canon:
                seen.add(word.lower())
                seen.add(canon)
                dosage_match = re.search(r'(\d+(?:\.\d+)?\s*mg|\d+\s*ml)', line, re.IGNORECASE)
                medicines.append({
                    "name": word,
                    "canonical_name": canon,
                    "category": TRUSTED_MEDICATION_DATABASE.get(canon, {}).get("category", "medicine"),
                    "dosage": dosage_match.group(0) if dosage_match else "",
                    "frequency": "",
                    "duration": "",
                    "raw_line": line,
                    "verified": True
                })

    return medicines


# ---------------------------------------------------------------------------
# Analyze Medical Report — Enhanced with biomarker extraction
# ---------------------------------------------------------------------------
def analyze_medical_report(text: str, session_id: str = None, gender: str = "unknown") -> dict:
    # Step 1: Deterministic biomarker extraction & 7-layer validation
    findings = extract_biomarkers_from_text(text, gender)
    findings_table = format_findings_for_display(findings)

    # Step 2: Save lab results to profile history
    if session_id and findings:
        save_lab_results(session_id, findings)

    # Step 2b: Stage 4F — Check new lab findings vs active medicines in patient profile
    active_med_alerts = []
    if session_id and findings:
        active = get_active_medicines(session_id)
        active_med_names = [m.get("canonical_name", "") for m in active if m.get("canonical_name")]
        if active_med_names:
            active_med_alerts = check_labs_vs_active_medicines(findings, active_med_names)

    # Step 3: Build enhanced findings summary for LLM
    if findings:
        abnormal = [f for f in findings if f["status"] not in ("NORMAL", "UNKNOWN")]
        normal = [f for f in findings if f["status"] == "NORMAL"]

        findings_context = "\n\n## Deterministically Extracted Biomarker Values:\n"
        for f in findings:
            val = f.get("value", "")
            unit = f.get("unit", "")
            status = f.get("status", "")
            flag = f.get("flag", "")
            ref = f.get("reference", "")
            test = f.get("test", "").replace("_", " ").title()
            findings_context += f"- {test}: **{val} {unit}** {flag} {status} (Ref: {ref})\n"
    else:
        findings_context = ""
        abnormal = []
        normal = []

    # Format active medicine cross-check alerts section
    med_alert_section = ""
    if active_med_alerts:
        alert_lines = ["\n\n## ⚠️ Active Medications Cross-Check (from Patient Profile)\n"]
        for al in active_med_alerts:
            alert_lines.append(f"- 🔴 **{al['finding']}** correlates with active medicine **{al['active_medicine'].title()}**")
            alert_lines.append(f"  - *Note:* {al['note']}")
        med_alert_section = "\n".join(alert_lines)

    # Step 4: AI Analysis
    try:
        system_prompt = """You are an expert medical report analyzer AI. Analyze the provided medical test report.
Format your response strictly using these sections:

# Medical Report Analysis

## 1. Test Result Analysis
For each test, clearly state:
- **Test Name — Value (Status)**: e.g., Hemoglobin — 11.2 g/dL (LOW)
- Reference range and what the status means

## 2. AI Clinical Summary
Concise 2-3 sentence summary in plain language.

## 3. Abnormal Findings Explained
Explain what each abnormal value means and why it matters.

## 4. What to Reduce / Avoid
Specific dietary and lifestyle items to reduce.

## 5. Recommended Health Actions
Clear, actionable dietary, exercise, and medical guidance.

## 6. When to See a Doctor
Urgency level (Routine / Soon / Urgent) and specific warning signs.

IMPORTANT: Always display actual extracted values (e.g., "Hemoglobin: 11.2 g/dL — LOW"). Never invent values."""

        prompt = f"Medical report text:\n\n{text}"
        if findings_context:
            prompt += f"\n{findings_context}"
        if med_alert_section:
            prompt += f"\n{med_alert_section}"

        english_analysis = generate_ai_analysis(prompt, system_prompt)

        # Prepend deterministic findings table and active medication alerts if available
        prefix_parts = []
        if findings_table:
            prefix_parts.append(f"## 📊 Extracted Biomarker Values\n\n{findings_table}")
        if med_alert_section:
            prefix_parts.append(med_alert_section)
        if prefix_parts:
            english_analysis = "\n\n".join(prefix_parts) + "\n\n---\n\n" + english_analysis

    except Exception as e:
        if is_connection_error(e):
            fallback_parts = ["### ⚠️ AI Server Connection Warning\n\n**Notice:** AI backend unavailable. Showing deterministic analysis only.\n\n---"]
            if findings_table:
                fallback_parts.append(f"## 📊 Extracted Biomarker Values\n\n{findings_table}")
            if med_alert_section:
                fallback_parts.append(med_alert_section)
            if abnormal:
                fallback_parts.append("## ⚠️ Abnormal Findings")
                for f in abnormal:
                    test = f.get("test", "").replace("_", " ").title()
                    val = f.get("value", "")
                    unit = f.get("unit", "")
                    status = f.get("status", "")
                    flag = f.get("flag", "")
                    ref = f.get("reference", "")
                    fallback_parts.append(f"- **{test}**: {val} {unit} {flag} **{status}** (Ref: {ref})")
            fallback_parts.append("\n> Please consult a healthcare professional to evaluate your results.")
            english_analysis = "\n\n".join(fallback_parts)
        else:
            english_analysis = f"Error analyzing report: {str(e)}"

    return {
        'english': english_analysis,
        'bangla': None,
        'findings': findings,
        'active_med_alerts': active_med_alerts,
        'abnormal_count': len(abnormal) if 'abnormal' in dir() else 0
    }


# ---------------------------------------------------------------------------
# Analyze Prescription — Enhanced with DDI checking, Previous Labs & Symptoms
# ---------------------------------------------------------------------------
def analyze_prescription(text: str, session_id: str = None, symptoms: str = "", patient_info: dict = None) -> dict:
    # Step 1: Extract medicines from text
    medicines = extract_medicines_from_text(text)

    # Also handle manually added medicine if provided (combining Medicine Info into Prescription)
    manual_med = (patient_info.get("medicine") or patient_info.get("additional_medicine") or "").strip() if patient_info else ""
    if manual_med:
        canon_manual = normalize_medicine_name(manual_med)
        ds = []
        if patient_info.get("dosage"):
            d = patient_info["dosage"]
            if d.get("morning"): ds.append(f"{d['morning']} morning")
            if d.get("evening"): ds.append(f"{d['evening']} evening")
            if d.get("night"): ds.append(f"{d['night']} night")
        dosage_str = ", ".join(ds) if ds else "As directed"

        if not any(m.get("canonical_name") == canon_manual for m in medicines):
            medicines.append({
                "name": manual_med,
                "canonical_name": canon_manual or manual_med.lower(),
                "category": TRUSTED_MEDICATION_DATABASE.get(canon_manual, {}).get("category", "medicine") if canon_manual else "medicine",
                "dosage": dosage_str,
                "frequency": "Daily",
                "duration": "Ongoing",
                "raw_line": f"{manual_med} - {dosage_str}",
                "verified": canon_manual is not None
            })

    # Step 2: Get historical active medicines AND previous lab records
    historical_meds = []
    lab_history = []
    if session_id:
        active = get_active_medicines(session_id)
        historical_meds = [m.get("canonical_name", "") for m in active if m.get("canonical_name")]
        lab_history = get_lab_history(session_id, limit=30)

    # Step 3: Multi-Vector DDI Check (New vs New, New vs Historical, Duplicates, Rx vs Labs)
    new_med_names = [m.get("name", "") for m in medicines if m.get("category") == "medicine"]
    ddi_report = {}
    if new_med_names:
        ddi_report = run_full_ddi_check(new_med_names, historical_meds if historical_meds else None, lab_history)

    # Step 4: Save medicines to profile history
    if session_id and medicines:
        save_active_medicines(session_id, medicines)

    # Step 5: Format DDI section
    ddi_section = ""
    if ddi_report:
        total = ddi_report.get("total_interactions", 0)
        sev = ddi_report.get("severity_summary", {})
        new_vs_new = ddi_report.get("new_vs_new", [])
        new_vs_hist = ddi_report.get("new_vs_historical", [])
        duplicates = ddi_report.get("duplicate_ingredients", [])
        rx_labs = ddi_report.get("prescription_vs_labs", [])

        if total > 0 or duplicates:
            ddi_parts = [f"\n\n## ⚠️ Drug Safety & Interaction Report\n"]
            ddi_parts.append(f"**Found:** {sev.get('MAJOR', 0)} Major | {sev.get('MODERATE', 0)} Moderate | {sev.get('MINOR', 0)} Minor | {len(duplicates)} Duplicate Ingredient(s)\n")

            if new_vs_new:
                ddi_parts.append("### 🔴 New Prescription Interactions")
                for i in new_vs_new:
                    icon = "🔴" if i['severity'] == "MAJOR" else "🟡" if i['severity'] == "MODERATE" else "🟢"
                    ddi_parts.append(f"- {icon} **{i['drug_a']} + {i['drug_b']}** [{i['severity']}]")
                    ddi_parts.append(f"  - **Effect:** {i['clinical_effect']}")
                    ddi_parts.append(f"  - **Management:** {i['management']}")

            if new_vs_hist:
                ddi_parts.append("\n### 🟡 New vs Historical Medicine Interactions (from Profile)")
                for i in new_vs_hist:
                    icon = "🔴" if i['severity'] == "MAJOR" else "🟡" if i['severity'] == "MODERATE" else "🟢"
                    ddi_parts.append(f"- {icon} **{i['drug_a']}** (new) + **{i['drug_b']}** (historical profile) [{i['severity']}]")
                    ddi_parts.append(f"  - **Effect:** {i['clinical_effect']}")
                    ddi_parts.append(f"  - **Management:** {i['management']}")

            if rx_labs:
                ddi_parts.append("\n### 🔬 Prescription vs Previous Labs Alerts (from Profile)")
                for al in rx_labs:
                    icon = "🔴" if al['severity'] == "MAJOR" else "🟡"
                    ddi_parts.append(f"- {icon} **{al['medicine']}** vs Previous **{al['lab_test']} ({al['lab_value']})** [{al['severity']}]")
                    ddi_parts.append(f"  - **Risk:** {al['clinical_effect']}")
                    ddi_parts.append(f"  - **Management:** {al['management']}")

            if duplicates:
                ddi_parts.append("\n### ⚠️ Duplicate Ingredients Detected")
                for d in duplicates:
                    ddi_parts.append(f"- **{d['ingredient']}** appears in: {', '.join(d['drugs'])}")

            ddi_section = "\n".join(ddi_parts)
        else:
            ddi_section = "\n\n## ✅ Drug Interaction Safety Check\n\nNo known interactions detected between the extracted medicines or with previous lab records."

    # Step 6: AI Analysis with optional Symptom Correlation
    try:
        med_list_str = ""
        if medicines:
            med_list_str = "\n\nExtracted Medicines:\n"
            for m in medicines:
                cat = m.get("category", "medicine")
                cat_icon = "💊" if cat == "medicine" else "🧪" if cat == "supplement" else "📦"
                med_list_str += f"- {cat_icon} **{m['name']}** ({cat})"
                if m.get("dosage"):
                    med_list_str += f" | Dose: {m['dosage']}"
                if m.get("frequency"):
                    med_list_str += f" | Freq: {m['frequency']}"
                if m.get("duration"):
                    med_list_str += f" | Duration: {m['duration']}"
                if m.get("verified"):
                    med_list_str += " ✓"
                med_list_str += "\n"

        symptom_prompt_clause = ""
        if symptoms.strip():
            symptom_prompt_clause = """
## 5. Symptom & Medication Correlation Analysis
- **Therapeutic Alignment**: Assess whether the prescribed medicines appropriately address the reported symptoms.
- **Potential Adverse Drug Reactions (ADR)**: Could any reported symptom be a known side effect or adverse reaction of the prescribed medications?
- **Interaction Risk Correlation**: Highlight if any symptom could be a warning sign of the identified drug interactions (e.g., bleeding, hypoglycemia, electrolyte disturbance).
- **Urgency & Consultation Guidance**: State if symptoms warrant urgent medical review or medication adjustment."""

        system_prompt = f"""You are an expert medical pharmacist and clinical AI advisor. Analyze the provided prescription.
Format your response strictly using these sections:

# Prescription Analysis

## 1. Prescribed Medicines
List each medicine with:
- **Medicine Name**: (generic + brand if mentioned)
- **Dosage**: Strength and form
- **Schedule**: Morning/Afternoon/Evening/Night dosing
- **Duration**: Number of days

## 2. Medicine Information
For each medicine, briefly explain:
- Primary use / condition it treats
- Common side effects to be aware of
- Key precautions

## 3. General Instructions
- Special instructions noted (with food, before bed, etc.)
- Lifestyle or dietary advice

## 4. Important Safety Notes
- Drug interaction warnings (from the DDI section below if present)
- When to contact the doctor immediately{symptom_prompt_clause}

Note: This is for informational purposes only. Always follow your doctor's instructions."""

        prompt = f"Prescription text:\n\n{text}"
        if med_list_str:
            prompt += med_list_str
        if symptoms.strip():
            prompt += f"\n\nReported Patient Symptoms to Correlate:\n{symptoms.strip()}"

        english_analysis = generate_ai_analysis(prompt, system_prompt)
        english_analysis += ddi_section

    except Exception as e:
        if is_connection_error(e):
            fallback_parts = ["### ⚠️ AI Server Connection Warning\n\nAI backend unavailable. Showing extracted information only.\n\n---"]
            if medicines:
                fallback_parts.append("## 💊 Extracted Medicines\n")
                for m in medicines:
                    fallback_parts.append(f"- **{m['name']}** ({m.get('category', 'medicine')})")
                    if m.get("dosage"):
                        fallback_parts.append(f"  - Dosage: {m['dosage']}")
                    if m.get("frequency"):
                        fallback_parts.append(f"  - Frequency: {m['frequency']}")

            if symptoms.strip():
                fallback_parts.append(f"\n## 🔍 Reported Symptoms Check\n**Symptoms:** {symptoms.strip()}")
                fallback_parts.append("- Please ensure your doctor is aware of these symptoms so they can monitor for medication side effects or adjust treatment.")

            fallback_parts.append("\n> Always follow your doctor's exact prescription instructions.")
            english_analysis = "\n\n".join(fallback_parts) + ddi_section
        else:
            english_analysis = f"Error analyzing prescription: {str(e)}" + ddi_section

    return {
        'english': english_analysis,
        'bangla': None,
        'medicines': medicines,
        'ddi': ddi_report
    }


# ---------------------------------------------------------------------------
# Symptoms Analysis (preserved from original)
# ---------------------------------------------------------------------------
def analyze_symptoms(symptoms: str) -> dict:
    try:
        system_prompt = """You are a medical advisor AI. Based on the symptoms described, provide:

# Symptom Analysis

## 1. Possible Conditions
List the most likely conditions (from most to least probable) based on the symptoms.

## 2. Urgency Level
State clearly: 🟢 Low / 🟡 Medium / 🔴 High urgency — with justification.

## 3. Immediate Steps
Actionable things the person can do right now.

## 4. When to Seek Medical Help
Specific warning signs that require immediate medical attention.

**Disclaimer:** This is for informational purposes only and not a substitute for professional medical advice."""

        prompt = f"Symptoms:\n{symptoms}"
        english_analysis = generate_ai_analysis(prompt, system_prompt)
        medline_info = "\n\n---\n*For more information, visit: https://medlineplus.gov/*"
        return {'english': english_analysis + medline_info, 'bangla': None}

    except Exception as e:
        if is_connection_error(e):
            fallback_text = f"""### ⚠️ AI Server Connection Warning

**Notice:** Could not connect to AI endpoint.

---

### 🔍 Symptoms Assessment (Fallback)
**Entered Symptoms:** "{symptoms}"

1. **Urgency Assessment:** 🟡 **Medium** (Monitor closely)
2. **General Precautions:** Rest adequately and maintain proper hydration.
3. **Medical Disclaimer:** Seek emergency care if symptoms worsen or severe pain/fever occurs.

For more information, visit: https://medlineplus.gov/"""
            return {'english': fallback_text, 'bangla': None}
        return {'success': False, 'error': f"Error analyzing symptoms: {str(e)}"}


# ---------------------------------------------------------------------------
# Medicine Analysis (preserved from original)
# ---------------------------------------------------------------------------
def analyze_medicine(medicine_name: str, dosage: dict, patient: dict) -> dict:
    try:
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
- Age: {patient['age']} years old
- Gender: {patient['gender']}

Medicine Name: {medicine_name}
Current Dosage: {formatted_dosage}

Provide:
1. Primary uses and conditions treated
2. Side effects (common to severe)
3. Recommended dosage comparison with standard guidelines
4. Warnings & drug interactions
5. When to seek medical attention immediately"""

        english_analysis = generate_ai_analysis(prompt, system_prompt)
        english_analysis += "\n\n---\n*For more information: https://medlineplus.gov/druginformation.html*"
        return {'english': english_analysis, 'bangla': None}

    except Exception as e:
        if is_connection_error(e):
            fallback_text = f"""### ⚠️ AI Server Connection Warning

---

### 💊 Medicine Information (Fallback)
**Medicine:** {medicine_name}
**Patient Profile:** {patient.get('age')} yrs, {patient.get('gender')}
**Dosage:** {formatted_dosage if 'formatted_dosage' in dir() else 'As directed'}

Consult your pharmacist or prescribing doctor regarding `{medicine_name}`.

For more information: https://medlineplus.gov/druginformation.html"""
            return {'english': fallback_text, 'bangla': None}
        return {'success': False, 'error': f"Error analyzing medicine: {str(e)}"}


# ---------------------------------------------------------------------------
# RAG Chatbot
# ---------------------------------------------------------------------------
def rag_chatbot_response(question: str, session_id: str, conversation_history: list = None, current_analysis: dict = None) -> str:
    """Answer questions using patient-specific context, current analysis, and profile history."""
    context = get_session_context(session_id)
    profile = context.get("profile", {})
    active_medicines = context.get("active_medicines", [])
    lab_history = context.get("lab_history", [])
    analysis_history = context.get("analysis_history", [])

    context_parts = []

    # Patient profile
    if profile and profile.get("name"):
        prof_line = f"Patient: {profile.get('name', 'Patient')}"
        if profile.get("age"): prof_line += f", Age: {profile['age']}"
        if profile.get("gender") and profile['gender'] != "unknown": prof_line += f", Gender: {profile['gender'].capitalize()}"
        if profile.get("known_conditions"): prof_line += f", Conditions: {profile['known_conditions']}"
        context_parts.append(f"## Patient Profile:\n{prof_line}")

    # Currently active analyzed content
    if current_analysis and isinstance(current_analysis, dict):
        curr_text = current_analysis.get('english', '')
        if curr_text:
            context_parts.append(f"## Current Analyzed Report / Prescription Context:\n{curr_text[:2500]}")

    if lab_history:
        context_parts.append("## Recent Lab Results (Patient History):")
        for lab in lab_history[:12]:
            test = lab.get("test_name", "").replace("_", " ").title()
            val = lab.get("value", "")
            unit = lab.get("unit", "")
            status = lab.get("status", "")
            ref = lab.get("reference_range", "")
            context_parts.append(f"- {test}: {val} {unit} [{status}] (Ref: {ref})")

    if active_medicines:
        context_parts.append("\n## Confirmed Active Medicines (Patient History):")
        for med in active_medicines[:10]:
            name = med.get("canonical_name", "").replace("_", " ").title()
            dosage = med.get("dosage", "")
            freq = med.get("frequency", "")
            context_parts.append(f"- {name}" + (f" | {dosage}" if dosage else "") + (f" | {freq}" if freq else ""))

    patient_context = "\n".join(context_parts) if context_parts else "No patient records available yet."

    messages_context = ""
    if conversation_history:
        for msg in conversation_history[-4:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role and content:
                messages_context += f"\n{role.upper()}: {content}"

    system_prompt = """You are a trusted medical clinical AI assistant for the Medical Report Analyzer system.
Answer questions based strictly on the patient's verified laboratory values, prescriptions, and medical history provided in the context.
Rules:
1. Base answers on the patient's verified data in the context. Never invent unverified results.
2. If data is unavailable, clearly state: "This information is not present in your current records."
3. Explain abnormal findings clearly in accessible language, and detail dietary/lifestyle and clinical follow-ups.
4. For medication interactions or flagged medicines, detail the interacting pairs, clinical mechanism, and risk mitigation.
5. Provide actionable questions for the patient to discuss with their physician.
6. Maintain strict data safety and clinical caution."""

    prompt = f"""Patient Context:
{patient_context}

{f"Previous conversation:{messages_context}" if messages_context else ""}

Patient Question: {question}

Please provide a helpful, clinically accurate response based on the patient's actual data above."""

    try:
        response = generate_ai_analysis(prompt, system_prompt)
        return response
    except Exception as e:
        if is_connection_error(e):
            q_lower = question.lower()

            # 1. Hemoglobin question
            if any(w in q_lower for w in ["hemoglobin", "hgb", "hb"]):
                hgb_labs = [l for l in lab_history if "hemoglobin" in str(l.get("test_name", "")).lower()]
                if hgb_labs:
                    l = hgb_labs[0]
                    return (
                        f"**Hemoglobin Status:** Your recorded hemoglobin is **{l['value']} {l['unit']}** ({l['status']}). "
                        f"Normal reference range is **{l['reference_range']}**.\n\n"
                        f"- **What it means:** A low hemoglobin level indicates reduced oxygen-carrying capacity of red blood cells (anemia).\n"
                        f"- **Common causes:** Iron deficiency, vitamin B12/folate deficiency, blood loss, or chronic inflammation.\n"
                        f"- **Next steps:** Consult your doctor to investigate the root cause, check serum ferritin, and discuss iron supplementation or dietary changes."
                    )
                return "No hemoglobin record found in your uploaded documents. Please upload a Complete Blood Count (CBC) report."

            # 2. HbA1c question
            if any(w in q_lower for w in ["hba1c", "a1c", "glycated"]):
                a1c_labs = [l for l in lab_history if "hba1c" in str(l.get("test_name", "")).lower()]
                if a1c_labs:
                    l = a1c_labs[0]
                    return (
                        f"**HbA1c Status:** Your HbA1c is **{l['value']}%** ({l['status']}).\n\n"
                        f"- **What it means:** HbA1c reflects your average blood sugar levels over the past 2–3 months.\n"
                        f"- **Benchmarks:** Normal is **< 5.7%**, Prediabetes is **5.7%–6.4%**, and Diabetes is **≥ 6.5%**.\n"
                        f"- **Recommendation:** Discuss with your doctor regarding lifestyle, dietary adjustments, and appropriate glycemic management."
                    )
                return "No HbA1c measurement found in your current records. Upload a diabetes or glycemic panel report."

            # 3. Abnormal test values question
            if any(w in q_lower for w in ["abnormal", "out of range", "flagged", "high", "low"]):
                abnormal = [l for l in lab_history if str(l.get("status", "")).upper() not in ("NORMAL", "UNKNOWN", "")]
                if abnormal:
                    res_lines = ["### ⚠️ Your Abnormal Lab Values:\n"]
                    for l in abnormal:
                        t = str(l.get('test_name', '')).replace('_', ' ').title()
                        res_lines.append(f"- **{t}**: {l.get('value')} {l.get('unit', '')} — **{l.get('status')}** (Ref: {l.get('reference_range', 'N/A')})")
                    res_lines.append("\n*Please schedule a clinical review with your doctor to evaluate these parameters together.*")
                    return "\n".join(res_lines)
                return "All your recorded laboratory values are currently within standard reference ranges!"

            # 4. Medication interaction question
            if any(w in q_lower for w in ["interact", "interaction", "ddi", "contraindication"]):
                if active_medicines:
                    med_names = [m.get("canonical_name", "") for m in active_medicines if m.get("canonical_name")]
                    ddi = run_full_ddi_check(med_names)
                    if ddi.get("total_interactions", 0) > 0:
                        lines = ["### ⚠️ Identified Drug Interactions in Your Records:\n"]
                        for i in ddi.get("new_vs_new", []):
                            lines.append(f"- **{i['drug_a'].title()} + {i['drug_b'].title()}** [{i['severity']}]: {i['clinical_effect']}\n  *Action:* {i['management']}")
                        return "\n".join(lines)
                    return "No adverse drug-drug interactions detected among your recorded active medications."
                return "No active medicines currently recorded. Please upload a prescription or enter your medications."

            # 5. Doctor precautions question
            if any(w in q_lower for w in ["precaution", "doctor", "questions to ask", "discuss"]):
                return (
                    "### 📋 Recommended Discussion Points for Your Doctor:\n"
                    "1. **Abnormal Values**: Review any out-of-range lab markers and ask if repeat testing or imaging is warranted.\n"
                    "2. **Medication Regimen**: Confirm dosages, timing (with/without food), and ask about alternative options for flagged interactions.\n"
                    "3. **Lifestyle & Nutrition**: Inquire about tailored nutritional goals (e.g., low-glycemic, sodium-controlled, iron-rich diet).\n"
                    "4. **Warning Signs**: Ask what acute symptoms (dizziness, palpitations, bruising) require urgent contact."
                )

            # 6. Normal reference range question
            if any(w in q_lower for w in ["reference", "normal range", "benchmark"]):
                if lab_history:
                    lines = ["### 📊 Your Recorded Test Reference Ranges:\n"]
                    for l in lab_history[:8]:
                        t = str(l.get('test_name', '')).replace('_', ' ').title()
                        lines.append(f"- **{t}**: Normal is {l.get('reference_range', 'Standard laboratory range')}")
                    return "\n".join(lines)
                return "Please upload your medical report to view reference ranges for your specific tests."

            # 7. General medicine question
            if any(w in q_lower for w in ["medicine", "drug", "tablet", "prescription"]):
                if active_medicines:
                    lines = ["### 💊 Your Recorded Medications:\n"]
                    for m in active_medicines:
                        name = m.get('canonical_name', '').replace('_', ' ').title()
                        dosage = m.get('dosage', 'Standard dose')
                        lines.append(f"- **{name}**: {dosage}")
                    return "\n".join(lines)
                return "No medications recorded in your profile yet. Upload a prescription to track them."

            return (
                "I am your medical report assistant. I can answer questions about your lab values (e.g. Hemoglobin, Glucose, HbA1c), "
                "active medications, drug interactions, and discussion points for your doctor. Try asking: *'What are my abnormal test values?'*"
            )

        return f"Error processing your question: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    session_id = get_session_id()
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded.'}), 400

        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected.'}), 400

        if not allowed_file(file.filename):
            exts = ', '.join(sorted(ALLOWED_EXTENSIONS)).upper()
            return jsonify({'error': f'Unsupported file type. Supported: {exts}'}), 400

        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        logger.info(f"File saved: {filepath}")

        analysis_type = request.form.get('analysis_type', 'report')
        gender = request.form.get('gender', 'unknown')
        symptoms = request.form.get('symptoms', '').strip()
        session_id = get_session_id()

        try:
            text = extract_text(filepath, ext)

            if os.path.exists(filepath):
                os.remove(filepath)

            if text and text.startswith("Error:"):
                return jsonify({'error': text}), 400

            if not text or not text.strip():
                return jsonify({'error': 'Could not extract any text from the file.'}), 400

            logger.info(f"Extracted {len(text)} chars. Analyzing as: {analysis_type}")

            if analysis_type == 'prescription':
                patient_info_raw = request.form.get('patient_info')
                patient_info = None
                if patient_info_raw:
                    try:
                        patient_info = json.loads(patient_info_raw)
                    except Exception:
                        pass
                analysis = analyze_prescription(text, session_id, symptoms, patient_info=patient_info)
            else:
                analysis = analyze_medical_report(text, session_id, gender)

            # Save to history
            save_analysis(
                session_id=session_id,
                analysis_type=analysis_type,
                filename=filename,
                extracted_text=text,
                findings=analysis.get('findings', []),
                ddi_data=analysis.get('ddi', {}),
                medicines=analysis.get('medicines', []),
                ai_analysis=analysis.get('english', '')
            )

            if isinstance(analysis, dict) and 'error' in analysis and 'success' in analysis:
                return jsonify(analysis), 500

            return jsonify({
                'success': True,
                'analysis': analysis,
                'extracted_chars': len(text)
            })

        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/analyze-symptoms', methods=['POST'])
def process_symptoms():
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            return jsonify({'error': 'No symptoms provided'}), 400
        symptoms = data['symptoms']
        if not symptoms.strip():
            return jsonify({'error': 'Symptoms cannot be empty'}), 400
        analysis = analyze_symptoms(symptoms)
        if isinstance(analysis, dict) and 'error' in analysis and 'success' in analysis:
            return jsonify(analysis), 500
        return jsonify({'success': True, 'analysis': analysis})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/translate', methods=['POST'])
def translate_text():
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'No text provided'}), 400
        text = data['text']
        target_language = data.get('target_language', 'Kannada').strip()
        if not text.strip():
            return jsonify({'error': 'Text cannot be empty'}), 400

        system_prompt = f"""You are an expert medical translator AI. Translate into {target_language}.
Rules:
1. Preserve all Markdown formatting (#, ##, bullet points, **bold**, blockquotes).
2. Keep numbers, lab values, and units (mg/dL, %, etc.) intact.
3. Provide an accurate, fluent medical translation."""

        prompt = f"Translate this medical analysis into {target_language}:\n\n{text}"
        translated_text = generate_ai_analysis(prompt, system_prompt)
        return jsonify({'success': True, 'translation': translated_text, 'language': target_language})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Translation error: {str(e)}'}), 500


@app.route('/analyze-medicine', methods=['POST'])
def process_medicine():
    try:
        data = request.get_json()
        if not data or 'medicine' not in data or 'dosage' not in data or 'patient' not in data:
            return jsonify({'error': 'Missing required information'}), 400

        medicine = data['medicine'].strip()
        dosage = data['dosage']
        patient = data['patient']

        if not medicine:
            return jsonify({'error': 'Medicine name cannot be empty'}), 400

        required_fields = ['morning', 'evening', 'night']
        if not all(field in dosage for field in required_fields):
            return jsonify({'error': 'Invalid dosage format'}), 400

        if not isinstance(patient.get('age'), int) or patient['age'] <= 0:
            return jsonify({'error': 'Invalid patient age'}), 400

        if not patient.get('gender') or patient['gender'] not in ['male', 'female', 'other']:
            return jsonify({'error': 'Invalid patient gender'}), 400

        analysis = analyze_medicine(medicine, dosage, patient)
        if isinstance(analysis, dict) and 'error' in analysis and 'success' in analysis:
            return jsonify(analysis), 500
        return jsonify({'success': True, 'analysis': analysis})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/analyze-report-text', methods=['POST'])
def process_report_text():
    try:
        data = request.get_json()
        if not data or 'report_text' not in data:
            return jsonify({'error': 'No report text provided'}), 400
        report_text = data['report_text'].strip()
        if not report_text:
            return jsonify({'error': 'Report text cannot be empty'}), 400

        analysis_type = data.get('analysis_type', 'report')
        gender = data.get('gender', 'unknown')
        symptoms = data.get('symptoms', '').strip()
        session_id = get_session_id()

        if analysis_type == 'prescription':
            patient_info = data.get('patient_info')
            analysis = analyze_prescription(report_text, session_id, symptoms, patient_info=patient_info)
        else:
            analysis = analyze_medical_report(report_text, session_id, gender)

        # Save to history
        save_analysis(
            session_id=session_id,
            analysis_type=analysis_type,
            filename="[Text Input]",
            extracted_text=report_text,
            findings=analysis.get('findings', []),
            ddi_data=analysis.get('ddi', {}),
            medicines=analysis.get('medicines', []),
            ai_analysis=analysis.get('english', '')
        )

        if isinstance(analysis, dict) and 'error' in analysis and 'success' in analysis:
            return jsonify(analysis), 500
        return jsonify({'success': True, 'analysis': analysis})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/chatbot', methods=['POST'])
def chatbot():
    """RAG Chatbot endpoint."""
    try:
        data = request.get_json()
        if not data or 'question' not in data:
            return jsonify({'error': 'No question provided'}), 400

        question = data['question'].strip()
        if not question:
            return jsonify({'error': 'Question cannot be empty'}), 400

        session_id = get_session_id()
        conversation_history = data.get('history', [])
        current_analysis = data.get('current_analysis')

        response = rag_chatbot_response(question, session_id, conversation_history, current_analysis=current_analysis)
        return jsonify({'success': True, 'response': response})
    except Exception as e:
        return jsonify({'error': f'Chatbot error: {str(e)}'}), 500


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    """Get or update patient profile."""
    try:
        session_id = get_session_id()
        if request.method == 'POST':
            data = request.get_json() or {}
            name = data.get('name', 'Primary Patient').strip()
            age = data.get('age')
            gender = data.get('gender', 'unknown')
            conditions = data.get('known_conditions', '').strip()
            allergies = data.get('allergies', '').strip()
            if age:
                try: age = int(age)
                except Exception: age = None
            save_patient_profile(session_id, name, age, gender, conditions, allergies)
            return jsonify({'success': True, 'profile': get_patient_profile(session_id)})
        else:
            return jsonify({'success': True, 'profile': get_patient_profile(session_id)})
    except Exception as e:
        return jsonify({'error': f'Profile error: {str(e)}'}), 500


@app.route('/set-medicine-status', methods=['POST'])
def update_medicine_status():
    """Confirm or discontinue active medicine."""
    try:
        session_id = get_session_id()
        data = request.get_json() or {}
        canonical_name = data.get('canonical_name', '').strip()
        confirmed = int(data.get('confirmed', 1))
        discontinued = int(data.get('discontinued', 0))
        if not canonical_name:
            return jsonify({'error': 'Medicine canonical name required'}), 400
        set_medicine_status(session_id, canonical_name, confirmed, discontinued)
        return jsonify({'success': True, 'active_medicines': get_active_medicines(session_id)})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/history', methods=['GET'])
def get_history():
    """Get patient analysis history and profile logs."""
    try:
        session_id = get_session_id()
        history = get_analysis_history(session_id)
        lab_hist = get_lab_history(session_id, limit=20)
        active_meds = get_active_medicines(session_id)
        prof = get_patient_profile(session_id)
        return jsonify({
            'success': True,
            'profile': prof,
            'analyses': history,
            'lab_history': lab_hist,
            'active_medicines': active_meds
        })
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/ddi-check', methods=['POST'])
def ddi_check():
    """Direct DDI check endpoint."""
    try:
        data = request.get_json()
        medicines = data.get('medicines', [])
        if not medicines:
            return jsonify({'error': 'No medicines provided'}), 400

        session_id = get_session_id()
        historical = get_active_medicines(session_id)
        hist_names = [m.get("canonical_name", "") for m in historical]

        report = run_full_ddi_check(medicines, hist_names if hist_names else None)
        return jsonify({'success': True, 'ddi_report': report})
    except Exception as e:
        return jsonify({'error': f'DDI check error: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
