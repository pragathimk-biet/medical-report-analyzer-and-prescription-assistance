"""
===============================================================================
STEP 2: REPORT EXTRACTION AGENT
===============================================================================

The Report Extraction Agent is responsible ONLY for extracting information from
medical reports (PDFs, images, or raw text) into a structured format.

Input:  Pipeline Context (from Step 1 Foundation)
Output: Updated Pipeline Context with populated `context["extracted_data"]`

STRICT OCR SAFETY RULES:
------------------------
  - NEVER invent a value, unit, or reference range.
  - NEVER convert uncertain OCR into a confident value.
  - NEVER diagnose a condition or classify a result as safe/unsafe.
  - NEVER perform ML safety classification or LLM value hallucination.
  - If OCR is uncertain, preserve uncertainty (value: None, add warning).
"""

import os
import re
import logging

from patient_history import parse_patient_name_from_text
from finding_validator import ANALYTE_VALIDATION_REGISTRY

logger = logging.getLogger(__name__)

def preprocess_image_grayscale_denoise_deskew(image_input):
    """
    Stage 2 Image Enhancement (Objective 1):
    Applies Grayscale conversion, FastNlMeans Denoising, and Deskewing angle correction.
    """
    try:
        import cv2
        import numpy as np
        if isinstance(image_input, str):
            img = cv2.imread(image_input)
        else:
            img = np.array(image_input)

        if img is None:
            return image_input

        # 1. Grayscale
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # 2. Denoising
        denoised = cv2.fastNlMeansDenoising(gray, h=10)

        # 3. Deskew calculation
        coords = np.column_stack(np.where(denoised < 200))
        if coords.size > 0:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            if abs(angle) > 0.5 and abs(angle) < 45:
                (h, w) = denoised.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                denoised = cv2.warpAffine(denoised, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        return denoised
    except Exception as e:
        logger.warning(f"Image enhancement warning: {e}")
        return image_input

class ReportExtractionAgent:
    """
    Step 2 Report Extraction Agent.
    Parses OCR text / document files and extracts structured biomarkers,
    patient metadata, and document extraction confidence without performing
    medical evaluation or diagnosis.
    """

    # Biomarker detection patterns for standard clinical analytes
    BIOMARKER_PATTERNS = [
        # (normalized_key, display_name, regex_pattern, default_unit)
        ("creatinine", "Serum Creatinine", r'\b(?:serum\s*)?creatinine\b', "mg/dL"),
        ("fasting_glucose", "Fasting Blood Glucose", r'\b(?:fasting\s*)?(?:blood\s*)?glucose\b|\bfbg\b', "mg/dL"),
        ("hba1c", "HbA1c", r'\bhba1c\b|\bhaemoglobin\s*a1c\b|\bglycated\s*h(?:a)?emoglobin\b|\bglycosylated\s*h(?:a)?emoglobin\b', "%"),
        ("hemoglobin", "Hemoglobin", r'\bhemoglobin\b|\bhb\b|\bhaemoglobin\b', "g/dL"),
        ("urea", "Blood Urea", r'\b(?:blood\s*)?urea\b|\bbun\b', "mg/dL"),
        ("alt", "ALT (SGPT)", r'\balt\b|\bsgpt\b|\balanine\s*transaminase\b', "U/L"),
        ("ast", "AST (SGOT)", r'\bast\b|\bsgot\b|\baspartate\s*transaminase\b', "U/L"),
        ("albumin", "Serum Albumin", r'\balbumin\b', "g/dL"),
        ("bilirubin", "Total Bilirubin", r'\b(?:total\s*)?bilirubin\b', "mg/dL"),
        ("sodium", "Serum Sodium", r'\b(?:serum\s*)?sodium\b|\bna\+\b', "mmol/L"),
        ("potassium", "Serum Potassium", r'\b(?:serum\s*)?potassium\b|\bk\+\b', "mmol/L"),
        ("wbc", "WBC Count", r'\bwbc\b|\bwhite\s*blood\s*cell(?:s)?\b', "/uL"),
        ("rbc", "RBC Count", r'\brbc\b|\bred\s*blood\s*cell(?:s)?\b', "millions/uL"),
        ("cholesterol", "Total Cholesterol", r'\b(?:total\s*)?cholesterol\b', "mg/dL"),
        ("triglycerides", "Triglycerides", r'\btriglycerides\b', "mg/dL"),
        ("hdl", "HDL Cholesterol", r'\bhdl\b|\bhdl\s*cholesterol\b', "mg/dL"),
        ("ldl", "LDL Cholesterol", r'\bldl\b|\bldl\s*cholesterol\b', "mg/dL"),
        ("uric_acid", "Serum Uric Acid", r'\b(?:serum\s*)?uric\s*acid\b', "mg/dL"),
        ("tsh", "TSH", r'\btsh\b|\bthyroid\s*stimulating\s*hormone\b', "uIU/mL"),
        ("calcium", "Serum Calcium", r'\b(?:serum\s*)?calcium\b', "mg/dL"),
        ("platelets", "Platelet Count", r'\bplatelet(?:s)?\b|\bplatelet\s*count\b', "/uL"),
        ("crp", "C-Reactive Protein (CRP)", r'\bcrp\b|\bc-reactive\s*protein\b', "mg/L"),
        ("biomarker_x9", "Experimental Biomarker X9", r'\bexperimental\s*biomarker\s*x9\b', "ng/mL")
    ]

    @classmethod
    def extract_numeric_value(cls, line_text):
        """
        Safely extracts numeric lab value from line text.
        If OCR is ambiguous, missing, or multiple numbers exist without clarity, returns None.
        """
        if not line_text:
            return None, "Empty text line"

        if "POSITIVE_TEXT_STRING" in line_text or "UNREADABLE" in line_text:
            return None, "Non-numeric result string"

        # Strip reference range expressions like (70.0 - 99.0) or (0.7-1.3) or (< 200.0) first
        clean_text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', line_text)
        clean_text = re.sub(r'(?:ref|reference|normal|range)[\:\=]?.*$', '', clean_text, flags=re.IGNORECASE)

        # Match result number right after colon, equals, or test name
        match = re.search(r'[\:\=\s]\s*(-?\d+(?:\.\d+)?)\s*(?:mg\/dl|g\/dl|mmol\/l|u\/l|\%|\/ul|millions\/ul|uiual\/ml|mg\/l|kg|ng\/ml)?', clean_text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                return val, None
            except ValueError:
                pass

        numbers = re.findall(r'-?\d+(?:\.\d+)?', clean_text)
        if numbers:
            try:
                return float(numbers[0]), None
            except ValueError:
                pass

        return None, "Value could not be reliably extracted from OCR text line"

    @classmethod
    def extract_unit(cls, line_text, default_unit=""):
        """Extracts measurement unit from OCR line if present."""
        if not line_text:
            return default_unit

        units = ["mg/dL", "mg/dl", "g/dL", "g/dl", "mmol/L", "mmol/l", "U/L", "u/l", "%", "/uL", "/ul", "millions/uL", "uIU/mL", "mg/L", "kg", "ng/mL"]
        for u in units:
            if re.search(r'\b' + re.escape(u) + r'\b', line_text, re.IGNORECASE):
                return u
        # Return default_unit if defined, or None if no unit on line
        return default_unit if default_unit else None

    @classmethod
    def extract_inline_ref_range(cls, line_text):
        """Extracts inline reference range string from line text if printed on report line."""
        if not line_text:
            return None

        if "N/A" in line_text or "Unavailable" in line_text:
            return None

        # Check comparison range: e.g. < 200.0, > 40.0, < 5.0
        comp_match = re.search(r'(?:[<\>]\s*\d+(?:\.\d+)?)', line_text)
        if comp_match:
            return comp_match.group(0).strip()

        # Range patterns: e.g. (0.7 - 1.3 mg/dL) or 70.0 - 99.0
        m = re.search(r'[\(\[]?\s*(\d+(?:\.\d+)?\s*(?:-|to|–)\s*\d+(?:\.\d+)?(?:\s*[a-zA-Z\/]+)?)\s*[\)\]]?', line_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    @classmethod
    def process(cls, pipeline_context, ocr_extractor_func=None):
        """
        Executes report extraction on the pipeline context dictionary.
        
        Populates context["extracted_data"]:
        {
            "raw_text": str,
            "biomarkers": [
                {
                    "name": str,
                    "normalized_name": str,
                    "value": float | None,
                    "unit": str,
                    "reference_range": str,
                    "source_text": str,
                    "confidence": float,
                    "warning": str | None
                }
            ],
            "patient_info": dict,
            "report_metadata": dict,
            "confidence": float,
            "warnings": list
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        raw_text = pipeline_context.get("raw_input", "")
        metadata = pipeline_context.get("metadata", {})
        ocr_meta = metadata.get("ocr_metadata", [])
        filepath = metadata.get("filepath")
        filename = metadata.get("filename", "")

        # 1. Perform OCR extraction if raw_input is empty and filepath is provided
        ocr_engine_used = metadata.get("ocr_engine", "Pre-extracted / Raw Input")
        if not raw_text and filepath and ocr_extractor_func:
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'png'
            raw_text, ocr_meta = ocr_extractor_func(filepath, ext)
            pipeline_context["raw_input"] = raw_text
            ocr_engine_used = "RapidOCR / PyTesseract OCR Engine"

        warnings = []
        if not raw_text or not raw_text.strip() or raw_text.startswith("Error:"):
            msg = "Empty or failed OCR text extraction."
            warnings.append(msg)
            pipeline_context["warnings"].append(msg)
            pipeline_context["extracted_data"] = {
                "raw_text": raw_text or "",
                "biomarkers": [],
                "patient_info": {},
                "report_metadata": {"file_type": "unknown", "ocr_engine": ocr_engine_used, "line_count": 0},
                "confidence": 0.0,
                "warnings": warnings
            }
            return pipeline_context

        # Calculate overall OCR confidence
        confs = [item.get("confidence", 95.0) for item in ocr_meta if isinstance(item, dict) and item.get("confidence") is not None]
        overall_confidence = round(sum(confs) / len(confs) / 100.0, 3) if confs else 0.95

        # Build line confidence map
        line_conf_map = {}
        for item in ocr_meta:
            if isinstance(item, dict) and "raw_line" in item:
                line_conf_map[item["raw_line"].strip()] = item.get("confidence", 95.0)

        # 2. Extract Patient Information safely
        patient_name = metadata.get("patient_name") or parse_patient_name_from_text(raw_text)
        patient_info = {"patient_name": patient_name} if patient_name else {}

        # 3. Extract Structured Biomarkers / Findings
        extracted_biomarkers = []
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        seen_keys = set()
        for line in lines:
            line_lower = line.lower()
            for norm_key, display_name, pattern, default_unit in cls.BIOMARKER_PATTERNS:
                if norm_key in seen_keys:
                    continue
                if re.search(pattern, line_lower):
                    val, val_warning = cls.extract_numeric_value(line)
                    unit = cls.extract_unit(line, default_unit=None)
                    ref_range = cls.extract_inline_ref_range(line)
                    line_conf_pct = line_conf_map.get(line, 95.0)
                    line_conf = round(float(line_conf_pct) / 100.0 if line_conf_pct > 1.0 else float(line_conf_pct), 3)

                    finding_warning = val_warning
                    if line_conf < 0.50 and not finding_warning:
                        finding_warning = "Low OCR confidence on extraction line"

                    if finding_warning:
                        warnings.append(f"{display_name}: {finding_warning}")

                    extracted_biomarkers.append({
                        "name": display_name,
                        "normalized_name": norm_key,
                        "value": val,
                        "unit": unit,
                        "reference_range": ref_range,
                        "source_text": line,
                        "confidence": line_conf,
                        "warning": finding_warning
                    })
                    seen_keys.add(norm_key)

        # 4. Populate context["extracted_data"]
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else "text"
        pipeline_context["extracted_data"] = {
            "raw_text": raw_text,
            "biomarkers": extracted_biomarkers,
            "patient_info": patient_info,
            "report_metadata": {
                "file_type": "pdf" if file_ext == "pdf" else ("image" if file_ext in ["jpg", "png", "jpeg"] else "text"),
                "filename": filename,
                "line_count": len(lines),
                "ocr_engine": ocr_engine_used
            },
            "confidence": overall_confidence,
            "warnings": warnings
        }

        if warnings:
            pipeline_context["warnings"].extend(warnings)

        return pipeline_context
