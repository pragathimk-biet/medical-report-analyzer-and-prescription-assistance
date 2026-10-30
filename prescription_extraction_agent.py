"""
===============================================================================
STEP 2: PRESCRIPTION EXTRACTION AGENT
===============================================================================

This module provides the Prescription Extraction Agent for the modular pipeline:

  Patient Upload / OCR Text
        │
        ▼
   Input Router
        │
        ▼
[ Prescription Extraction Agent ] ◄── THIS AGENT
        │
        ▼
  pipeline_context["extracted_data"] & pipeline_context["handwriting"]

STRICT EXTRACTION BOUNDARIES:
-----------------------------
  1. Extracts patient info, medications, strength, dosage form, frequency schedules,
     timing (before/after food), duration, and instructions.
  2. Preserves raw OCR text separately from structured data.
  3. Low confidence / ambiguous drug names (confidence < 0.50 or truncated text)
     are preserved as raw text with name=None and recorded in context["handwriting"]["candidates"].
  4. NEVER invents or guesses missing medication names, strengths, or frequency schedules.
  5. Performs ZERO safety checks, verification, or LLM reasoning (reserved for future steps).
"""

import os
import re
import logging
from patient_history import classify_medical_item, normalize_medicine_name, TRUSTED_MEDICATION_DATABASE

logger = logging.getLogger(__name__)

# Common dosage forms (expanded for hospital prescriptions and pharmacy invoices)
DOSAGE_FORMS = [
    "tablet", "tab", "tabs", "capsule", "cap", "caps", "injection", "inj",
    "syrup", "syr", "drops", "drop", "powder", "pwd", "granules", "gran",
    "cream", "crm", "ointment", "oint", "gel", "lotion", "solution", "sol",
    "suspension", "susp", "inhaler", "spray", "sachet", "sachets"
]

# Frequency schedule patterns
FREQUENCY_PATTERNS = {
    r'\b1\-0\-1\b|\btwice\s*daily\b|\bbid\b|\bbd\b': {
        "frequency": "Twice Daily (BD/1-0-1)", "morning": True, "afternoon": False, "evening": True
    },
    r'\b1\-1\-1\b|\bthree\s*times\s*daily\b|\btid\b|\btds\b': {
        "frequency": "Three Times Daily (TDS/1-1-1)", "morning": True, "afternoon": True, "evening": True
    },
    r'\b1\-0\-0\b|\bonce\s*daily\s*morning\b': {
        "frequency": "Once Daily Morning (1-0-0)", "morning": True, "afternoon": False, "evening": False
    },
    r'\b0\-0\-1\b|\bonce\s*daily\s*night\b|\bhs\b|\bat\s*bedtime\b': {
        "frequency": "Once Daily Night (0-0-1)", "morning": False, "afternoon": False, "evening": True
    },
    r'\b1\-0\-1\-0\b|\b1\-1\-1\-1\b|\bfour\s*times\s*daily\b|\bqid\b': {
        "frequency": "Four Times Daily (QID)", "morning": True, "afternoon": True, "evening": True
    },
    r'\bonce\s*daily\b|\bod\b': {
        "frequency": "Once Daily (OD)", "morning": True, "afternoon": False, "evening": False
    },
    r'\bas\s*needed\b|\bprn\b': {
        "frequency": "As Needed (PRN)", "morning": False, "afternoon": False, "evening": False
    }
}

class PrescriptionExtractionAgent:
    """
    Step 2 Prescription Extraction Agent.
    Parses OCR text or document files to extract structured prescription metadata,
    medications, schedules, and low-confidence handwriting candidates.
    """

    @classmethod
    def extract_patient_info(cls, text, metadata):
        """Extracts patient demographic header information."""
        info = {
            "patient_name": metadata.get("patient_name"),
            "age": metadata.get("age"),
            "sex": metadata.get("gender"),
            "date": None,
            "prescriber": None
        }

        if not text:
            return info

        # Extract patient name if not provided
        if not info["patient_name"]:
            name_match = re.search(r'(?:patient\s*name|pt\s*name|name|patient)\s*[\:\=]\s*([a-zA-Z\s\.]+)', text, re.IGNORECASE)
            if name_match:
                candidate_name = name_match.group(1).strip().split('\n')[0]
                if len(candidate_name) > 2 and not any(kw in candidate_name.lower() for kw in ["date", "age", "rx", "tab"]):
                    info["patient_name"] = candidate_name

        # Extract Age
        if not info["age"]:
            age_match = re.search(r'(?:age|yrs|years)\s*[\:\=]?\s*(\d{1,3})\s*(?:yrs|years|y)?', text, re.IGNORECASE)
            if age_match:
                try:
                    info["age"] = int(age_match.group(1))
                except ValueError:
                    pass

        # Extract Sex / Gender
        if not info["sex"]:
            sex_match = re.search(r'(?:sex|gender)\s*[\:\=]\s*(male|female|m|f|other)', text, re.IGNORECASE)
            if sex_match:
                raw_sex = sex_match.group(1).lower()
                if raw_sex in ['m', 'male']:
                    info["sex"] = "Male"
                elif raw_sex in ['f', 'female']:
                    info["sex"] = "Female"
                else:
                    info["sex"] = raw_sex.capitalize()

        # Extract Date
        date_match = re.search(r'(?:date)\s*[\:\=]\s*(\d{1,4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,4})', text, re.IGNORECASE)
        if date_match:
            info["date"] = date_match.group(1)

        # Extract Prescriber
        presc_match = re.search(r'(?:dr\.|doctor|physician)\s*([a-zA-Z\s\.]+)', text, re.IGNORECASE)
        if presc_match:
            doc_name = presc_match.group(1).strip().split('\n')[0]
            if len(doc_name) > 2:
                info["prescriber"] = f"Dr. {doc_name}".replace("Dr. Dr.", "Dr.")

        return info

    @classmethod
    def extract_medications(cls, text, ocr_metadata=None):
        """
        Parses text lines to extract structured medications, dosages, timing,
        and flags low-confidence handwriting candidates.
        """
        medications = []
        handwriting_candidates = []
        warnings = []

        if not text:
            return medications, handwriting_candidates, warnings

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        # Map line numbers to confidence if available
        conf_map = {}
        if ocr_metadata and isinstance(ocr_metadata, list):
            for item in ocr_metadata:
                if isinstance(item, dict):
                    line_num = item.get("line_number")
                    conf = item.get("confidence", 95.0)
                    if line_num is not None:
                        conf_map[line_num] = float(conf) / 100.0 if float(conf) > 1.0 else float(conf)

        logger.info("PrescriptionExtractionAgent: Beginning extraction on text (%d characters, %d lines)", len(text), len(lines))

        # Common invoice table header patterns to skip
        INVOICE_HEADER_PATTERNS = [
            r'\b(?:sl\s*no|sl\.no|item\s*no|particulars|product\s*description|description|batch\s*no|batch|mfg|exp\s*date|expiry|rate|amount|mrp|tax\s*invoice|retail\s*invoice|cash\s*memo|total\s*amount|grand\s*total|sub\s*total|subtotal|gstin|cgst|sgst|discount|terms\s*and\s*conditions|signature|pharmacist)\b'
        ]

        for idx, line in enumerate(lines, 1):
            line_lower = line.lower().strip()
            
            # Skip standalone headers or instruction-only lines
            if line_lower in ["rx", "prescription", "rx:", "medications:"] or line_lower.startswith("take ") or line_lower.startswith("sig "):
                continue

            # Skip invoice table headers and administrative lines unless line explicitly contains medication/dosage forms
            if any(re.search(pat, line_lower) for pat in INVOICE_HEADER_PATTERNS) and not any(d in line_lower for d in ["tab", "cap", "inj", "drops", "syrup", "powder", "granules"]):
                continue

            if any(h in line_lower for h in ["laboratory", "diagnosis", "report", "clinic", "hospital"]) and not any(d in line_lower for d in ["tab", "cap", "mg", "drops", "powder"]):
                continue

            # Classify medical item: medicine vs nutritional product vs dietary supplement vs medical device vs medical supply
            item_info = classify_medical_item(line)

            # Detect item line: covers prescriptions, handwritten notes, and invoice table rows
            is_item_line = (
                item_info["is_device_or_supply"] or
                item_info.get("is_nutritional") or
                item_info.get("is_supplement") or
                any(re.search(r'\b' + f + r'\b', line_lower) for f in DOSAGE_FORMS) or
                re.search(r'\b\d+\s*(?:mg|g|mcg|ml|iu)\b', line_lower) is not None or
                any(p in line_lower for p in ["1-0-1", "1-1-1", "0-0-1", "twice daily", "once daily", "bid", "tid", "od", "prn"]) or
                re.match(r'^\s*\d+[\.\s\-]+[a-zA-Z]', line) is not None or  # Itemized invoice row (e.g. "1. Dexolac...", "1 Parajely...")
                line_lower.startswith("rx ") or
                any(dbk in line_lower for dbk in TRUSTED_MEDICATION_DATABASE if len(dbk) >= 4)
            )

            if not is_item_line:
                continue

            line_conf = conf_map.get(idx, 0.95)

            # 1. Clean line from invoice trailing columns (rates, quantities, amounts, batch, exp date)
            line_cleaned_for_name = re.sub(r'(\s+\d{1,2}[\/\-\.]\d{2,4})', '', line)
            line_cleaned_for_name = re.sub(r'(\s+\d+(?:\.\d+)?)+\s*$', '', line_cleaned_for_name).strip()
            line_cleaned_for_name = re.sub(r'\s+(?:b(?:atch)?\.?\s*(?:no\.?)?[:\s]*)?[A-Z0-9]{4,10}\s*$', '', line_cleaned_for_name, flags=re.I).strip()

            # 2. Extract dosage form using normalizer and standalone words
            norm_res = normalize_medicine_name(line_cleaned_for_name)
            dosage_form = norm_res.get("dosage_form")
            if not dosage_form:
                for form in DOSAGE_FORMS:
                    if re.search(r'\b' + form + r'\b', line_lower):
                        dosage_form = form.capitalize()
                        break

            # 3. Check strength
            strength = norm_res.get("strength")
            if not strength:
                str_match = re.search(r'(-?\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu|units))\b', line, re.IGNORECASE)
                if str_match:
                    strength = str_match.group(1)

            # 4. Check frequency schedule
            freq_dict = {
                "frequency": None, "morning": False, "afternoon": False, "evening": False
            }
            for pat, f_info in FREQUENCY_PATTERNS.items():
                if re.search(pat, line_lower):
                    freq_dict = f_info
                    break

            # 5. Check timing (before/after food)
            timing = None
            if re.search(r'\bafter\s*(?:food|meals)\b|\bpc\b', line_lower):
                timing = "After Food"
            elif re.search(r'\bbefore\s*(?:food|meals)\b|\bac\b', line_lower):
                timing = "Before Food"

            # 6. Check duration
            duration = None
            dur_match = re.search(r'(?:for\s*)?(\d+\s*(?:days|weeks|months|day|week|month))', line_lower)
            if dur_match:
                duration = dur_match.group(1)

            raw_name = line
            # If the normalizer stripped a concatenated dosage form (e.g. PERINORMTAB -> Perinorm), use its clean_name
            if norm_res.get("dosage_form") and norm_res.get("clean_name"):
                clean_name = norm_res.get("clean_name")
            else:
                clean_name = line_cleaned_for_name

            # Strip leading prefixes
            clean_name = re.sub(r'^(?:rx|\d+[\.\s\-]+|[\-\*\•])\s*', '', clean_name, flags=re.IGNORECASE).strip()
            for form in ["tablet", "tab", "capsule", "cap", "injection", "inj", "syrup", "syr", "drops"]:
                clean_name = re.sub(r'^\b' + form + r'\b\s*', '', clean_name, flags=re.IGNORECASE).strip()

            # Stop at dosage units or frequency/SIG instructions (e.g. "Prednisone 10mg once daily" -> "Prednisone")
            name_tokens = []
            for token in clean_name.split():
                token_l = token.lower().strip(":,.-")
                if token in ["-", "–", "—", "/", "|"]:
                    break
                if token_l in ["1-0-1", "1-1-1", "0-0-1", "1-0-0", "0-1-0", "after", "before", "once", "twice", "daily", "bid", "tid", "qid", "od", "prn", "take", "sig", "dispense", "pc", "ac", "stat", "sos"]:
                    break
                if token_l in ["mg", "mcg", "g", "gm", "ml", "iu", "units"]:
                    break
                if re.match(r'^\d', token_l) and not any(k in clean_name.lower() for k in ["dexolac", "lactare"]):
                    break
                name_tokens.append(token)

            extracted_name = " ".join(name_tokens).strip(" -–—,.:;/") if name_tokens else clean_name.strip(" -–—,.:;/")

            # Resolve item type and flags
            if item_info.get("is_nutritional"):
                item_type = "NUTRITIONAL_PRODUCT"
                is_medicine = False
                is_device_or_supply = False
            elif item_info.get("is_supplement"):
                item_type = "DIETARY_SUPPLEMENT"
                is_medicine = False
                is_device_or_supply = False
            elif item_info.get("is_device_or_supply"):
                item_type = item_info.get("item_type", "MEDICAL_DEVICE")
                is_medicine = False
                is_device_or_supply = True
            else:
                item_type = "MEDICINE"
                is_medicine = True
                is_device_or_supply = False

            # Low confidence or truncated drug name handling
            is_ambiguous = (
                line_conf < 0.50 or
                extracted_name.endswith("...") or
                (len(extracted_name) <= 2 and extracted_name.lower() not in ["k+", "fe"]) or
                re.search(r'[^a-zA-Z0-9\s\-\+\/]', extracted_name) is not None
            )

            logger.info("PrescriptionExtractionAgent: Extracted item '%s' (raw='%s', type=%s, form=%s, strength=%s, conf=%.2f)",
                        extracted_name, raw_name, item_type, dosage_form, strength, line_conf)

            if is_ambiguous:
                med_entry = {
                    "raw_name": raw_name,
                    "name": None,
                    "strength": strength,
                    "dosage_form": dosage_form,
                    "frequency": freq_dict.get("frequency"),
                    "morning": freq_dict.get("morning", False),
                    "afternoon": freq_dict.get("afternoon", False),
                    "evening": freq_dict.get("evening", False),
                    "timing": timing,
                    "duration": duration,
                    "instructions": line,
                    "source_text": line,
                    "confidence": round(line_conf, 2),
                    "item_type": item_info["item_type"],
                    "is_device_or_supply": item_info["is_device_or_supply"],
                    "is_medicine": item_info["is_medicine"],
                    "warning": "Medication name ambiguous or low OCR confidence"
                }
                handwriting_candidates.append({
                    "raw_text": raw_name,
                    "confidence": round(line_conf, 2),
                    "source_text": line
                })
                warnings.append(f"Ambiguous or low confidence medication line: '{line}'")
            else:
                med_entry = {
                    "raw_name": raw_name,
                    "name": extracted_name,
                    "strength": strength,
                    "dosage_form": dosage_form,
                    "frequency": freq_dict.get("frequency"),
                    "morning": freq_dict.get("morning", False),
                    "afternoon": freq_dict.get("afternoon", False),
                    "evening": freq_dict.get("evening", False),
                    "timing": timing,
                    "duration": duration,
                    "instructions": line,
                    "source_text": line,
                    "confidence": round(line_conf, 2),
                    "item_type": item_info["item_type"],
                    "is_device_or_supply": item_info["is_device_or_supply"],
                    "is_medicine": item_info["is_medicine"],
                }

            medications.append(med_entry)

        return medications, handwriting_candidates, warnings

    @classmethod
    def process(cls, pipeline_context, ocr_extractor_func=None):
        """
        Executes Prescription Extraction Agent on pipeline_context.
        
        Populates context["extracted_data"] & context["handwriting"]:
        {
            "raw_text": str,
            "patient_info": dict,
            "medications": list,
            "prescription_metadata": dict,
            "warnings": list
        }
        """
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dictionary.")

        raw_input = pipeline_context.get("raw_input", "")
        metadata = pipeline_context.get("metadata", {})
        ocr_meta = metadata.get("ocr_metadata")

        raw_text = ""
        # 1. OCR Extraction if file path is provided or ocr_extractor_func exists
        if ocr_extractor_func and isinstance(raw_input, str):
            ext = raw_input.rsplit('.', 1)[1].lower() if '.' in raw_input else 'png'
            try:
                raw_text, ocr_meta = ocr_extractor_func(raw_input, ext)
                metadata["ocr_metadata"] = ocr_meta
            except Exception as ocr_err:
                logger.warning(f"PrescriptionExtractionAgent OCR error: {ocr_err}")
                pipeline_context["warnings"].append(f"OCR extraction error: {ocr_err}")
        elif isinstance(raw_input, str) and (raw_input.endswith('.pdf') or raw_input.endswith('.png') or raw_input.endswith('.jpg') or raw_input.endswith('.jpeg')):
            if os.path.exists(raw_input):
                from app import PerceptionExtractionAgent
                ext = raw_input.rsplit('.', 1)[1].lower()
                try:
                    raw_text, ocr_meta = PerceptionExtractionAgent.extract(raw_input, ext)
                    metadata["ocr_metadata"] = ocr_meta
                except Exception as ocr_err:
                    logger.warning(f"PrescriptionExtractionAgent default OCR error: {ocr_err}")
                    pipeline_context["warnings"].append(f"OCR extraction error: {ocr_err}")
            else:
                pipeline_context["warnings"].append(f"Prescription document file not found: {raw_input}")
        elif isinstance(raw_input, str):
            raw_text = raw_input

        if isinstance(raw_text, str) and raw_text.startswith("Error:"):
            pipeline_context.setdefault("errors", []).append(raw_text)

        # 2. Extract Patient Info
        patient_info = cls.extract_patient_info(raw_text, metadata)

        # 3. Extract Medications & Handwriting Candidates
        medications, hw_candidates, warnings = cls.extract_medications(raw_text, ocr_metadata=ocr_meta)

        # 4. Populate extracted_data
        pipeline_context["extracted_data"] = {
            "raw_text": raw_text,
            "patient_info": patient_info,
            "medications": medications,
            "prescription_metadata": {
                "date": patient_info.get("date"),
                "prescriber": patient_info.get("prescriber")
            },
            "warnings": warnings
        }

        # 5. Populate handwriting dict
        pipeline_context["handwriting"] = {
            "candidates": hw_candidates
        }

        if warnings:
            pipeline_context["warnings"].extend(warnings)

        return pipeline_context
