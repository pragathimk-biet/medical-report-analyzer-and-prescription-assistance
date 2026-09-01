import os
import json
import logging
import re
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

# Trusted Medication Database (Tier 1 Exact Match Layer)
TRUSTED_MEDICATION_DATABASE = {
    "spironolactone": {
        "primary_name": "Spironolactone",
        "class": "Potassium-Sparing Diuretic",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_SPIRONOLACTONE_001"
    },
    "aldactone": {
        "primary_name": "Spironolactone (Aldactone)",
        "class": "Potassium-Sparing Diuretic",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_ALDACTONE_001"
    },
    "lisinopril": {
        "primary_name": "Lisinopril",
        "class": "ACE Inhibitor",
        "target_lab_keys": ["potassium", "creatinine", "urea"],
        "rule_id": "MED_DB_LISINOPRIL_001"
    },
    "enalapril": {
        "primary_name": "Enalapril",
        "class": "ACE Inhibitor",
        "target_lab_keys": ["potassium", "creatinine", "urea"],
        "rule_id": "MED_DB_ENALAPRIL_001"
    },
    "losartan": {
        "primary_name": "Losartan",
        "class": "Angiotensin Receptor Blocker (ARB)",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_LOSARTAN_001"
    },
    "valsartan": {
        "primary_name": "Valsartan",
        "class": "Angiotensin Receptor Blocker (ARB)",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_VALSARTAN_001"
    },
    "ramipril": {
        "primary_name": "Ramipril",
        "class": "ACE Inhibitor",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_RAMIPRIL_001"
    },
    "ibuprofen": {
        "primary_name": "Ibuprofen",
        "class": "Non-Steroidal Anti-Inflammatory Drug (NSAID)",
        "target_lab_keys": ["creatinine", "urea", "alt", "ast"],
        "rule_id": "MED_DB_IBUPROFEN_001"
    },
    "naproxen": {
        "primary_name": "Naproxen",
        "class": "Non-Steroidal Anti-Inflammatory Drug (NSAID)",
        "target_lab_keys": ["creatinine", "urea"],
        "rule_id": "MED_DB_NAPROXEN_001"
    },
    "diclofenac": {
        "primary_name": "Diclofenac",
        "class": "Non-Steroidal Anti-Inflammatory Drug (NSAID)",
        "target_lab_keys": ["creatinine", "urea", "alt", "ast"],
        "rule_id": "MED_DB_DICLOFENAC_001"
    },
    "prednisone": {
        "primary_name": "Prednisone",
        "class": "Corticosteroid",
        "target_lab_keys": ["glucose_fasting", "hba1c", "sodium", "wbc"],
        "rule_id": "MED_DB_PREDNISONE_001"
    },
    "dexamethasone": {
        "primary_name": "Dexamethasone",
        "class": "Corticosteroid",
        "target_lab_keys": ["glucose_fasting", "hba1c", "wbc"],
        "rule_id": "MED_DB_DEXAMETHASONE_001"
    },
    "paracetamol": {
        "primary_name": "Paracetamol (Acetaminophen)",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_PARACETAMOL_001"
    },
    "acetaminophen": {
        "primary_name": "Acetaminophen",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_ACETAMINOPHEN_001"
    },
    "atorvastatin": {
        "primary_name": "Atorvastatin",
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_ATORVASTATIN_001"
    },
    "rosuvastatin": {
        "primary_name": "Rosuvastatin",
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_ROSUVASTATIN_001"
    },
    "levothyroxine": {
        "primary_name": "Levothyroxine",
        "class": "Thyroid Hormone Derivative",
        "target_lab_keys": ["tsh", "free_t4"],
        "rule_id": "MED_DB_LEVOTHYROXINE_001"
    },
    "furosemide": {
        "primary_name": "Furosemide (Lasix)",
        "class": "Loop Diuretic",
        "target_lab_keys": ["sodium", "potassium", "creatinine"],
        "rule_id": "MED_DB_FUROSEMIDE_001"
    },
    "hydrochlorothiazide": {
        "primary_name": "Hydrochlorothiazide (HCTZ)",
        "class": "Thiazide Diuretic",
        "target_lab_keys": ["sodium", "potassium", "glucose_fasting"],
        "rule_id": "MED_DB_HCTZ_001"
    },
    "metformin": {
        "primary_name": "Metformin",
        "class": "Biguanide Antidiabetic",
        "target_lab_keys": ["glucose_fasting", "hba1c", "creatinine"],
        "rule_id": "MED_DB_METFORMIN_001"
    },
    "dapagliflozin": {
        "primary_name": "Dapagliflozin",
        "class": "SGLT2 Inhibitor",
        "target_lab_keys": ["glucose_fasting", "hba1c", "creatinine"],
        "rule_id": "MED_DB_DAPAGLIFLOZIN_001"
    },
    "empagliflozin": {
        "primary_name": "Empagliflozin",
        "class": "SGLT2 Inhibitor",
        "target_lab_keys": ["glucose_fasting", "hba1c", "creatinine"],
        "rule_id": "MED_DB_EMPAGLIFLOZIN_001"
    },
    "warfarin": {
        "primary_name": "Warfarin",
        "class": "Vitamin K Antagonist Anticoagulant",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_WARFARIN_001"
    },
    "aspirin": {
        "primary_name": "Aspirin",
        "class": "Antiplatelet / Salicylate",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_ASPIRIN_001"
    },
    "amoxicillin": {
        "primary_name": "Amoxicillin",
        "class": "Penicillin Antibiotic",
        "target_lab_keys": ["alt", "ast", "creatinine"],
        "rule_id": "MED_DB_AMOXICILLIN_001"
    },
    "amoxil": {
        "primary_name": "Amoxil (Amoxicillin)",
        "class": "Penicillin Antibiotic",
        "target_lab_keys": ["alt", "ast", "creatinine"],
        "rule_id": "MED_DB_AMOXIL_001"
    },
    "amoxiclav": {
        "primary_name": "Amoxiclav (Amoxicillin/Clavulanate)",
        "class": "Beta-Lactamase Inhibitor Antibiotic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_AMOXICLAV_001"
    },
    "pantoprazole": {
        "primary_name": "Pantoprazole",
        "class": "Proton Pump Inhibitor (PPI)",
        "target_lab_keys": ["magnesium", "sodium"],
        "rule_id": "MED_DB_PANTOPRAZOLE_001"
    },
    "omeprazole": {
        "primary_name": "Omeprazole",
        "class": "Proton Pump Inhibitor (PPI)",
        "target_lab_keys": ["magnesium", "sodium"],
        "rule_id": "MED_DB_OMEPRAZOLE_001"
    },
    "amlodipine": {
        "primary_name": "Amlodipine",
        "class": "Calcium Channel Blocker (CCB)",
        "target_lab_keys": ["creatinine"],
        "rule_id": "MED_DB_AMLODIPINE_001"
    },
    "spironolactone": {
        "primary_name": "Spironolactone",
        "class": "Potassium-Sparing Diuretic",
        "target_lab_keys": ["potassium"],
        "rule_id": "MED_DB_SPIRONOLACTONE_001"
    }
}

# Pharmacological Suffix Map (Tier 2 Dynamic Fallback Matcher)
PHARMACOLOGICAL_SUFFIX_MAP = [
    {
        "suffixes": ["spironolactone", "lactone"],
        "class": "Potassium-Sparing Diuretic",
        "lab_key": "potassium",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "CRITICAL",
        "rule_id": "SUFFIX_SPIRONOLACTONE_HYPERKALEMIA_001",
        "title": "Severe Medication-Lab Contraindication: Potassium-Sparing Diuretic Hyperkalemia Risk",
        "explanation": "Potassium-sparing diuretics block sodium-potassium exchange, causing severe life-threatening hyperkalemia when prescribed to patients with elevated serum potassium."
    },
    {
        "suffixes": ["pril"],
        "class": "ACE Inhibitor",
        "lab_key": "potassium",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "HIGH",
        "rule_id": "SUFFIX_PRIL_HYPERKALEMIA_001",
        "title": "Potential Medication-Lab Safety Relationship: ACE Inhibitor Hyperkalemia Risk",
        "explanation": "ACE inhibitor medications reduce aldosterone secretion, which can elevate or worsen serum potassium levels."
    },
    {
        "suffixes": ["sartan"],
        "class": "Angiotensin Receptor Blocker (ARB)",
        "lab_key": "potassium",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "HIGH",
        "rule_id": "SUFFIX_SARTAN_HYPERKALEMIA_001",
        "title": "Potential Medication-Lab Safety Relationship: ARB Hyperkalemia Risk",
        "explanation": "Angiotensin receptor blockers can decrease urinary potassium excretion and elevate serum potassium."
    },
    {
        "suffixes": ["statin"],
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "lab_key": "alt",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_STATIN_ALT_001",
        "title": "Potential Medication-Lab Safety Relationship: Statin Hepatic Enzyme Elevation",
        "explanation": "Statin medications are processed in the liver and can be correlated with hepatic ALT enzyme elevation."
    },
    {
        "suffixes": ["statin"],
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "lab_key": "ast",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_STATIN_AST_001",
        "title": "Potential Medication-Lab Safety Relationship: Statin Liver Function Monitoring",
        "explanation": "Statin therapy warrants monitoring when AST liver transaminase enzymes are elevated."
    },
    {
        "suffixes": ["flozin"],
        "class": "SGLT2 Inhibitor",
        "lab_key": "glucose_fasting",
        "abnormal_statuses": ["HIGH", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_FLOZIN_GLUCOSE_001",
        "title": "Potential Medication-Lab Safety Relationship: SGLT2 Glycemic Regulation",
        "explanation": "SGLT2 inhibitors promote urinary glucose excretion to regulate elevated blood glucose."
    },
    {
        "suffixes": ["glutide"],
        "class": "GLP-1 Receptor Agonist",
        "lab_key": "glucose_fasting",
        "abnormal_statuses": ["HIGH", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_GLUTIDE_GLUCOSE_001",
        "title": "Potential Medication-Lab Safety Relationship: GLP-1 Glycemic Regulation",
        "explanation": "GLP-1 receptor agonists enhance glucose-dependent insulin secretion to lower elevated blood glucose."
    },
    {
        "suffixes": ["oxacin"],
        "class": "Fluoroquinolone Antibiotic",
        "lab_key": "creatinine",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_OXACIN_CREATININE_001",
        "title": "Potential Medication-Lab Safety Relationship: Fluoroquinolone Renal Excretion",
        "explanation": "Fluoroquinolone antimicrobials undergo renal clearance and warrant monitoring when creatinine is high."
    },
    {
        "suffixes": ["mycin", "micin"],
        "class": "Aminoglycoside / Macrolide Antibiotic",
        "lab_key": "creatinine",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "HIGH",
        "rule_id": "SUFFIX_MYCIN_CREATININE_001",
        "title": "Potential Medication-Lab Safety Relationship: Antimicrobial Nephrotoxicity Consideration",
        "explanation": "Certain antimicrobial drug classes undergo renal excretion and require dosage adjustments when creatinine is elevated."
    },
    {
        "suffixes": ["olol"],
        "class": "Beta-Blocker",
        "lab_key": "glucose_fasting",
        "abnormal_statuses": ["HIGH", "LOW"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_OLOL_GLUCOSE_001",
        "title": "Potential Medication-Lab Safety Relationship: Beta-Blocker Metabolic Monitoring",
        "explanation": "Beta-blockers can affect carbohydrate metabolism and mask hypoglycemic awareness."
    },
    {
        "suffixes": ["dipine"],
        "class": "Dihydropyridine Calcium Channel Blocker",
        "lab_key": "alt",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_DIPINE_ALT_001",
        "title": "Potential Medication-Lab Safety Relationship: Calcium Channel Blocker Metabolism",
        "explanation": "Calcium channel blockers undergo hepatic metabolism and warrant clinical monitoring when ALT is high."
    },
    {
        "suffixes": ["parin"],
        "class": "Anticoagulant / Heparin Derivative",
        "lab_key": "hemoglobin",
        "abnormal_statuses": ["LOW"],
        "severity": "HIGH",
        "rule_id": "SUFFIX_PARIN_HEMOGLOBIN_001",
        "title": "Potential Medication-Lab Safety Relationship: Anticoagulant Bleeding Precaution",
        "explanation": "Anticoagulant therapy increases bleeding risk and warrants close monitoring when hemoglobin is low."
    },
    {
        "suffixes": ["zone"],
        "class": "Corticosteroid / Thiazolidinedione",
        "lab_key": "glucose_fasting",
        "abnormal_statuses": ["HIGH", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE"],
        "severity": "MODERATE",
        "rule_id": "SUFFIX_ZONE_GLUCOSE_001",
        "title": "Potential Medication-Lab Safety Relationship: Steroid Glycemic Effect",
        "explanation": "Steroid therapy promotes gluconeogenesis and insulin resistance, leading to higher fasting blood glucose."
    }
]

# Explicit Rules Database for Known Aliases
MEDICATION_LAB_SAFETY_RULES = [
    {
        "rule_id": "MED_SAFETY_DIR_A_K_SPIRONOLACTONE_001",
        "medication_aliases": ["spironolactone", "aldactone", "lisinopril", "enalapril", "losartan", "valsartan", "ramipril", "perindopril", "benazepril", "candesartan", "irbesartan", "telmisartan", "eplerenone"],
        "lab_key": "potassium",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "HIGH",
        "title": "Potential Medication-Lab Safety Relationship: Hyperkalemia Risk",
        "explanation": "Active medication (ACE inhibitor, ARB, or potassium-sparing diuretic) can reduce renal potassium excretion and elevate serum potassium levels."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_NA_DIURETIC_001",
        "medication_aliases": ["furosemide", "lasix", "hydrochlorothiazide", "hctz", "indapamide", "torsemide", "chlorthalidone", "bumetanide"],
        "lab_key": "sodium",
        "abnormal_statuses": ["LOW"],
        "severity": "HIGH",
        "title": "Potential Medication-Lab Safety Relationship: Hyponatremia Risk",
        "explanation": "Diuretic therapy enhances urinary sodium excretion and can contribute to low serum sodium levels."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_CREATININE_NSAID_001",
        "medication_aliases": ["ibuprofen", "naproxen", "diclofenac", "ketorolac", "meloxicam", "indomethacin", "celecoxib", "piroxicam", "etoricoxib", "nsaid"],
        "lab_key": "creatinine",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Renal Clearance Consideration",
        "explanation": "NSAIDs inhibit renal prostaglandin synthesis, which can reduce renal blood flow and elevate serum creatinine."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_UREA_NSAID_001",
        "medication_aliases": ["ibuprofen", "naproxen", "diclofenac", "ketorolac", "meloxicam", "indomethacin", "celecoxib", "nsaid"],
        "lab_key": "urea",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Nitrogenous Waste Clearance",
        "explanation": "Active NSAID therapy alters renal perfusion and can contribute to elevated blood urea nitrogen."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_ALT_PARACETAMOL_001",
        "medication_aliases": ["paracetamol", "acetaminophen", "tylenol", "panadol", "nimesulide"],
        "lab_key": "alt",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Hepatic Enzyme Monitoring",
        "explanation": "Analgesics like acetaminophen are metabolized by hepatic cytochrome enzymes and warrant monitoring when ALT is high."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_GLUCOSE_STEROID_001",
        "medication_aliases": ["prednisone", "dexamethasone", "hydrocortisone", "methylprednisolone", "triamcinolone", "budesonide", "steroid"],
        "lab_key": "glucose_fasting",
        "abnormal_statuses": ["HIGH", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Glycemic Elevation",
        "explanation": "Corticosteroids stimulate hepatic gluconeogenesis and reduce peripheral glucose uptake, raising blood glucose levels."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_ALT_STATIN_001",
        "medication_aliases": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin", "pitavastatin", "fenofibrate", "gemfibrozil"],
        "lab_key": "alt",
        "abnormal_statuses": ["HIGH", "VERY_HIGH"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Statin Hepatic Transaminase Monitoring",
        "explanation": "Lipid-lowering statin therapy undergoes hepatic clearance and can be associated with transaminase (ALT) elevation."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_TSH_LEVOTHYROXINE_001",
        "medication_aliases": ["levothyroxine", "synthroid", "thyronorm", "eltroxin", "methimazole", "carbimazole", "propylthiouracil"],
        "lab_key": "tsh",
        "abnormal_statuses": ["HIGH", "LOW"],
        "severity": "MODERATE",
        "title": "Potential Medication-Lab Safety Relationship: Thyroid Hormone Axis",
        "explanation": "Exogenous thyroid hormone or antithyroid therapy directly regulates pituitary TSH secretion."
    },
    {
        "rule_id": "MED_SAFETY_DIR_A_HEMOGLOBIN_ANTICOAGULANT_001",
        "medication_aliases": ["warfarin", "coumadin", "heparin", "enoxaparin", "clexane", "apixaban", "rivaroxaban", "dabigatran", "aspirin", "clopidogrel", "plavix"],
        "lab_key": "hemoglobin",
        "abnormal_statuses": ["LOW"],
        "severity": "HIGH",
        "title": "Potential Medication-Lab Safety Relationship: Anticoagulation & Anemia Monitoring",
        "explanation": "Active anticoagulant or antiplatelet therapy increases systemic bleeding risk when hemoglobin is low."
    }
]

def normalize_patient_name(name):
    """Normalizes patient name to a slug key and clean display string."""
    if not name or not isinstance(name, str) or not name.strip():
        return "default_patient", "Default Patient"
    clean_display = name.strip()
    slug = re.sub(r'[^a-zA-Z0-9_]', '_', clean_display.lower())
    slug = re.sub(r'_+', '_', slug).strip('_')
    if not slug:
        slug = "default_patient"
    return slug, clean_display

def parse_patient_name_from_text(text):
    """Auto-extracts patient name from medical report/prescription OCR text if present."""
    if not text or not isinstance(text, str):
        return None
    patterns = [
        r'(?:patient\'?s?\s*name|name\s*of\s*patient|pt\.?\s*name|client\s*name)\s*[\:\=\-]\s*(?:MR|MRS|MS|DR|MASTER)?\.?\s*([A-Za-z\s]+?)(?=\s+(?:lab|ref|age|sex|gender|date|reg|ward|ip|op|no|status|unit|doctor|dr|\d)|$)',
        r'(?:name)\s*[\:\=\-]\s*(?:MR|MRS|MS|DR|MASTER)?\.?\s*([A-Za-z\s]+?)(?=\s+(?:lab|ref|age|sex|gender|date|reg|ward|ip|op|no|status|unit|doctor|dr|\d)|$)',
        r'(?:patient)\s*[\:\=\-]\s*(?:MR|MRS|MS|DR|MASTER)?\.?\s*([A-Za-z\s]+?)(?=\s+(?:lab|ref|age|sex|gender|date|reg|ward|ip|op|no|status|unit|doctor|dr|\d)|$)'
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw_val = m.group(1).strip().split('\n')[0]
            raw_name = re.split(r'[\/\|\(\)\;\,\:]|\b(?:age|sex|gender|date|dob|id|mrn|pid|bill|ref|dr|doctor|lab|ward|unit|ip|op|status|no)\b', raw_val, flags=re.IGNORECASE)[0].strip()
            if raw_name and len(raw_name) >= 2 and raw_name.lower() not in ["dummy", "mr dummy", "mrdummy", "null", "undefined", "self", "test", "demo", "male", "female", "n/a"]:
                clean = re.sub(r'^(mr|mrs|ms|dr|master|baby|shri|smt)\.?\s*', '', raw_name, flags=re.IGNORECASE).strip()
                if len(clean) >= 2:
                    words = [w.capitalize() for w in clean.split() if w]
                    extracted = " ".join(words)
                    if len(extracted) >= 2:
                        return extracted
    return None

def extract_patient_name(text):
    return parse_patient_name_from_text(text)

def extract_patient_demographics(text):
    """
    Auto-extracts patient demographic information from medical report / prescription text:
    - patient_name
    - age
    - gender
    - lab_ref_no
    - registration_date
    """
    if not text or not isinstance(text, str):
        return {
            "patient_name": "Default Patient",
            "age": None,
            "gender": None,
            "lab_ref_no": None,
            "registration_date": None
        }

    name = parse_patient_name_from_text(text) or "Default Patient"

    age = None
    m_age = re.search(r'(\d+)\s*(?:years?|yrs?|year\(s\))', text, re.IGNORECASE)
    if m_age:
        try:
            age = int(m_age.group(1))
        except ValueError:
            pass

    gender = None
    m_gender = re.search(r'\b(male|female|m|f)\b', text, re.IGNORECASE)
    if m_gender:
        g_raw = m_gender.group(1).lower()
        if g_raw in ['male', 'm']:
            gender = 'Male'
        elif g_raw in ['female', 'f']:
            gender = 'Female'

    lab_ref_no = None
    m_ref = re.search(r'(?:lab\s*ref\s*no\.?|ref\s*no\.?|lab\s*no\.?|patient\s*id|mrn|ip\s*no\.?|op\s*no\.?)\s*[\:\=\-]\s*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
    if m_ref:
        lab_ref_no = m_ref.group(1).strip()

    registration_date = None
    m_date = re.search(r'(?:registration\s*date|reg\s*date|collection\s*date|date)\s*[\:\=\-]\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}(?:\s*\d{2}\:\d{2})?)', text, re.IGNORECASE)
    if m_date:
        registration_date = m_date.group(1).strip()

    return {
        "patient_name": name,
        "age": age,
        "gender": gender,
        "lab_ref_no": lab_ref_no,
        "registration_date": registration_date
    }

class PatientDatabase:
    """
    Relational SQLite Database Manager (`patient_database.db`)
    Stores patient data in structured SQL rows and columns across relational tables:
      - patients (id, slug, patient_name, created_at, updated_at)
      - active_medications (id, patient_slug, medicine_name, dosage, med_class, confidence_status, added_at)
      - lab_results (id, patient_slug, visit_id, parameter, key, value, unit, status, validation_status, rule_id, evaluated_at)
      - prescriptions (id, patient_slug, visit_id, medicine_name, extracted_snippet, timestamp)
      - reports (id, patient_slug, visit_id, report_type, findings_count, timestamp)
      - visits (id, patient_slug, visit_id, visit_type, details, findings_count, timestamp)
    """
    def __init__(self, db_path="patient_database.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                patient_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS active_medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                medicine_name TEXT NOT NULL,
                dosage TEXT,
                med_class TEXT,
                confidence_status TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lab_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                visit_id TEXT,
                parameter TEXT NOT NULL,
                key TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                status TEXT NOT NULL,
                validation_status TEXT,
                rule_id TEXT,
                evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS prescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                visit_id TEXT,
                medicine_name TEXT NOT NULL,
                extracted_snippet TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                visit_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                findings_count INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                visit_id TEXT NOT NULL,
                visit_type TEXT DEFAULT 'LAB_REPORT',
                details TEXT,
                findings_count INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );
            """)
            conn.commit()

    def sync_from_dict(self, db_dict):
        """Syncs patient store data into relational SQLite rows and columns."""
        if not db_dict or not isinstance(db_dict, dict) or "patients" not in db_dict:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for slug, pdata in db_dict.get("patients", {}).items():
                p_name = pdata.get("patient_name", slug)
                cursor.execute("""
                    INSERT INTO patients (slug, patient_name)
                    VALUES (?, ?)
                    ON CONFLICT(slug) DO UPDATE SET patient_name=excluded.patient_name, updated_at=CURRENT_TIMESTAMP
                """, (slug, p_name))

                # Clear old records for clean sync
                cursor.execute("DELETE FROM active_medications WHERE patient_slug=?", (slug,))
                cursor.execute("DELETE FROM lab_results WHERE patient_slug=?", (slug,))
                cursor.execute("DELETE FROM prescriptions WHERE patient_slug=?", (slug,))
                cursor.execute("DELETE FROM reports WHERE patient_slug=?", (slug,))
                cursor.execute("DELETE FROM visits WHERE patient_slug=?", (slug,))

                # Active Medications
                for med in pdata.get("active_medications", []):
                    dos_str = json.dumps(med.get("dosage")) if isinstance(med.get("dosage"), dict) else (str(med.get("dosage")) if med.get("dosage") else None)
                    cursor.execute("""
                        INSERT INTO active_medications (patient_slug, medicine_name, dosage, med_class, confidence_status, added_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (slug, med.get("name", ""), dos_str, med.get("class", ""), med.get("confidence_status", ""), med.get("added_at", datetime.now().isoformat())))

                # Lab Results
                for lab in pdata.get("past_lab_results", []):
                    try:
                        val_num = float(lab.get("value", 0.0))
                    except Exception:
                        val_num = 0.0
                    cursor.execute("""
                        INSERT INTO lab_results (patient_slug, visit_id, parameter, key, value, unit, status, validation_status, rule_id, evaluated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        slug,
                        lab.get("visit_id"),
                        lab.get("parameter", ""),
                        lab.get("key", ""),
                        val_num,
                        lab.get("unit", ""),
                        lab.get("status", ""),
                        lab.get("validation_status", ""),
                        lab.get("rule_id", ""),
                        lab.get("evaluated_at", datetime.now().isoformat())
                    ))

                # Prescriptions
                for rx in pdata.get("prescriptions", []):
                    cursor.execute("""
                        INSERT INTO prescriptions (patient_slug, visit_id, medicine_name, extracted_snippet, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    """, (slug, rx.get("visit_id"), rx.get("medicine_name", ""), rx.get("extracted_snippet"), rx.get("timestamp", datetime.now().isoformat())))

                # Reports
                for rpt in pdata.get("reports", []):
                    cursor.execute("""
                        INSERT INTO reports (patient_slug, visit_id, report_type, findings_count, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    """, (slug, rpt.get("visit_id", ""), rpt.get("type", "LAB_REPORT"), rpt.get("findings_count", 0), rpt.get("timestamp", datetime.now().isoformat())))

                # Visits
                for v in pdata.get("visits", []):
                    cursor.execute("""
                        INSERT INTO visits (patient_slug, visit_id, visit_type, details, findings_count, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (slug, v.get("visit_id", ""), v.get("type", "LAB_REPORT"), v.get("details"), v.get("findings_count", 0), v.get("timestamp", datetime.now().isoformat())))

            conn.commit()

    def get_patient_summary(self):
        """Executes SQL query returning patient summary rows across tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    p.slug,
                    p.patient_name,
                    COUNT(DISTINCT m.id) as medications_count,
                    COUNT(DISTINCT l.id) as lab_results_count,
                    COUNT(DISTINCT rx.id) as prescriptions_count,
                    COUNT(DISTINCT r.id) as reports_count,
                    COUNT(DISTINCT v.id) as visits_count,
                    MAX(v.timestamp) as last_visit
                FROM patients p
                LEFT JOIN active_medications m ON p.slug = m.patient_slug
                LEFT JOIN lab_results l ON p.slug = l.patient_slug
                LEFT JOIN prescriptions rx ON p.slug = rx.patient_slug
                LEFT JOIN reports r ON p.slug = r.patient_slug
                LEFT JOIN visits v ON p.slug = v.patient_slug
                GROUP BY p.slug, p.patient_name
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

class PatientHistoryManager:
    """
    Manages a multi-patient database storing history by patient name across visits,
    longitudinal trend analytics, trusted medication knowledge layer, and
    true two-way medication/lab safety checking.
    Persists data in SQLite relational database (`patient_database.db`) with rows and columns.
    """
    @staticmethod
    def extract_patient_name(text):
        return parse_patient_name_from_text(text)

    def __init__(self, storage_file="patient_history_store.json", sqlite_db_path="patient_database.db"):
        self.storage_file = storage_file
        self.sqlite_db_path = sqlite_db_path
        self.sqlite_db = PatientDatabase(db_path=self.sqlite_db_path)
        self.db = self._load()
        # Initial sync to populate relational SQLite database
        self.sqlite_db.sync_from_dict(self.db)

    def get_patient_record(self, patient_name="Default Patient"):
        """Returns structured patient state store record for a patient."""
        slug, display_name = normalize_patient_name(patient_name)
        patient_data = self.db.get("patients", {}).get(slug, {})
        return {
            "patient_name": patient_data.get("patient_name", display_name),
            "slug": slug,
            "active_medications": patient_data.get("active_medications", []),
            "past_lab_history": patient_data.get("past_lab_results", []),
            "prescriptions": patient_data.get("prescriptions", []),
            "reports": patient_data.get("reports", []),
            "visits": patient_data.get("visits", [])
        }

    def _load(self):
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        if "patients" in data:
                            return data
                        # Legacy single-patient migration
                        return {
                            "patients": {
                                "default_patient": {
                                    "patient_name": "Default Patient",
                                    "active_medications": data.get("active_medications", []),
                                    "past_lab_results": data.get("past_lab_results", []),
                                    "prescriptions": data.get("prescriptions", []),
                                    "reports": data.get("reports", []),
                                    "visits": data.get("visits", [])
                                }
                            }
                        }
            except Exception as e:
                logger.warning(f"Failed to load patient history: {e}")
        return {"patients": {}}

    def _save(self):
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=2)
            # Sync to SQLite relational tables (rows and columns)
            self.sqlite_db.sync_from_dict(self.db)
        except Exception as e:
            logger.warning(f"Failed to save patient history: {e}")

    def _get_patient_store(self, patient_name="Default Patient"):
        slug, display_name = normalize_patient_name(patient_name)
        patients = self.db.setdefault("patients", {})
        if slug not in patients:
            patients[slug] = {
                "patient_name": display_name,
                "active_medications": [],
                "past_lab_results": [],
                "prescriptions": [],
                "reports": [],
                "visits": []
            }
        return patients[slug]

    @property
    def history(self):
        """Backward compatibility property returning default patient store."""
        return self._get_patient_store("Default Patient")

    def clear(self, patient_name=None):
        """Reset patient history for testing purposes."""
        if patient_name:
            slug, _ = normalize_patient_name(patient_name)
            if "patients" in self.db and slug in self.db["patients"]:
                del self.db["patients"][slug]
        else:
            self.db = {"patients": {}}
        self._save()

    def list_all_patients(self):
        """Returns a list of all stored patient profiles."""
        summary = []
        for slug, pdata in self.db.get("patients", {}).items():
            summary.append({
                "slug": slug,
                "patient_name": pdata.get("patient_name", slug),
                "medications_count": len(pdata.get("active_medications", [])),
                "lab_results_count": len(pdata.get("past_lab_results", [])),
                "prescriptions_count": len(pdata.get("prescriptions", [])),
                "reports_count": len(pdata.get("reports", [])),
                "visits_count": len(pdata.get("visits", [])),
                "last_visit": pdata["visits"][-1]["timestamp"] if pdata.get("visits") else None
            })
        return summary

    def get_patient_history(self, patient_name="Default Patient"):
        """Retrieves history object for a specific patient."""
        return self._get_patient_store(patient_name)

    def add_active_medication(self, medicine_name, dosage=None, patient_name="Default Patient"):
        """Register active medication under a specific patient name."""
        if not medicine_name or not isinstance(medicine_name, str):
            return
        
        med_clean = medicine_name.strip()
        classification = self.classify_medication(med_clean)

        med_entry = {
            "name": med_clean,
            "dosage": dosage,
            "class": classification.get("class", "Unclassified"),
            "confidence_status": classification.get("status", "UNCLASSIFIED"),
            "added_at": datetime.now().isoformat()
        }
        
        pstore = self._get_patient_store(patient_name)
        existing_names = [m["name"].lower() for m in pstore.get("active_medications", [])]
        if med_clean.lower() not in existing_names:
            pstore.setdefault("active_medications", []).append(med_entry)
            self._save()

    def add_prescription_record(self, medicine_name, extracted_text=None, patient_name="Default Patient"):
        """Record an uploaded prescription under a specific patient name."""
        pstore = self._get_patient_store(patient_name)
        v_id = f"VISIT-{len(pstore.get('visits', [])) + 1:03d}"
        timestamp = datetime.now().isoformat()

        rx_entry = {
            "visit_id": v_id,
            "medicine_name": medicine_name,
            "extracted_snippet": extracted_text[:200] if extracted_text else None,
            "timestamp": timestamp
        }
        pstore.setdefault("prescriptions", []).append(rx_entry)
        
        visit_entry = {
            "visit_id": v_id,
            "timestamp": timestamp,
            "type": "PRESCRIPTION",
            "details": f"Prescription uploaded: {medicine_name}"
        }
        pstore.setdefault("visits", []).append(visit_entry)
        self._save()

    def add_lab_results(self, evaluation_results, visit_id=None, patient_name="Default Patient"):
        """Store historical lab evaluation results with visit timestamp (only validated findings)."""
        if not evaluation_results:
            return
        
        pstore = self._get_patient_store(patient_name)
        pstore.setdefault("past_lab_results", [])
        timestamp = datetime.now().isoformat()
        v_id = visit_id or f"VISIT-{len(pstore.get('visits', [])) + 1:03d}"

        # Filter out ambiguous/unverified/review-required findings from long-term history
        validated_findings = [
            res for res in evaluation_results 
            if res.get("validation_status") in ["VALIDATED", "PARTIALLY_VALIDATED", None]
        ]
        if not validated_findings:
            return

        visit_entry = {
            "visit_id": v_id,
            "timestamp": timestamp,
            "type": "LAB_REPORT",
            "findings_count": len(validated_findings)
        }
        pstore.setdefault("visits", []).append(visit_entry)
        pstore.setdefault("reports", []).append(visit_entry)

        for res in validated_findings:
            res_entry = {
                "visit_id": v_id,
                "parameter": res.get("test_name", res.get("parameter")),
                "key": res.get("normalized_test_name", res.get("key")),
                "value": res.get("result_value", res.get("value")),
                "unit": res.get("unit", ""),
                "status": res["status"],
                "validation_status": res.get("validation_status", "VALIDATED"),
                "rule_id": res.get("rule_id", "RULE_001"),
                "evaluated_at": timestamp
            }
            pstore["past_lab_results"].append(res_entry)
        
        self._save()

    # --- REQUIREMENT 3: Trusted Medication Knowledge Layer ---
    def classify_medication(self, medicine_name):
        """
        Multi-tier medication classification:
        Tier 1: Exact / Trusted DB Match
        Tier 2: Pharmacological Suffix Match
        Tier 3: Unclassified (Returns 'Medication could not be confidently classified.')
        """
        if not medicine_name or not isinstance(medicine_name, str):
            return {"status": "UNCLASSIFIED", "message": "Medication could not be confidently classified."}

        med_lower = medicine_name.lower().strip()
        first_word = med_lower.split()[0].strip(":,.-")

        # Tier 1: Exact Trusted Database Match
        for db_key, db_info in TRUSTED_MEDICATION_DATABASE.items():
            if db_key == med_lower or db_key == first_word or db_key in med_lower:
                return {
                    "status": "TRUSTED_DB_MATCH",
                    "medication": db_info["primary_name"],
                    "class": db_info["class"],
                    "target_lab_keys": db_info["target_lab_keys"],
                    "rule_id": db_info["rule_id"]
                }

        # Tier 2: Suffix Fallback Matcher
        for suffix_rule in PHARMACOLOGICAL_SUFFIX_MAP:
            for sfx in suffix_rule["suffixes"]:
                if med_lower.endswith(sfx) or first_word.endswith(sfx):
                    return {
                        "status": "SUFFIX_FALLBACK_MATCH",
                        "medication": medicine_name,
                        "class": suffix_rule["class"],
                        "target_lab_keys": [suffix_rule["lab_key"]],
                        "rule_id": suffix_rule["rule_id"],
                        "suffix": sfx
                    }

        # Tier 3: Unknown Medication -> Do NOT Guess
        return {
            "status": "UNCLASSIFIED",
            "medication": medicine_name,
            "class": "Unclassified",
            "message": "Medication could not be confidently classified."
        }

    # --- REQUIREMENT 1: Longitudinal Trend & Abnormality Pattern Detection ---
    def analyze_parameter_trends(self, current_eval_results, patient_name="Default Patient"):
        """
        Computes trend metrics across historical visits for each evaluated parameter:
        - increasing_trend / decreasing_trend / stable_trend
        - newly_abnormal / persistently_abnormal / resolved_abnormality / newly_normal
        """
        trends = []
        pstore = self._get_patient_store(patient_name)
        past_results = pstore.get("past_lab_results", [])
        if not past_results or not current_eval_results:
            return trends

        for current_res in current_eval_results:
            key = current_res.get("key")
            param_name = current_res.get("parameter")
            curr_val = current_res.get("value")
            curr_status = current_res.get("status")

            if key is None or not isinstance(curr_val, (int, float)):
                continue

            # Retrieve historical numerical values for this parameter in chronological order
            history_entries = [p for p in past_results if p.get("key") == key and isinstance(p.get("value"), (int, float))]
            if not history_entries:
                continue

            historical_vals = [p["value"] for p in history_entries]
            historical_statuses = [p["status"] for p in history_entries]
            all_vals = historical_vals + [curr_val]

            # 1. Compute Directional Trend (increasing, decreasing, stable)
            trend_type = "STABLE_TREND"
            if len(all_vals) >= 2:
                prev_val = historical_vals[-1]
                diff_pct = ((curr_val - prev_val) / prev_val) * 100 if prev_val != 0 else 0
                if diff_pct >= 3.0:
                    trend_type = "INCREASING_TREND"
                elif diff_pct <= -3.0:
                    trend_type = "DECREASING_TREND"
                else:
                    trend_type = "STABLE_TREND"

            # 2. Compute Abnormality Transition Pattern
            last_past_status = historical_statuses[-1]
            abnormal_set = {"HIGH", "VERY_HIGH", "LOW", "POSITIVE", "PREDIABETES", "PREDIABETES_RANGE", "DIABETES_RANGE", "KIDNEY_FAILURE_RANGE", "SEVERELY_DECREASED"}
            normal_set = {"NORMAL", "NEGATIVE", "DESIRABLE", "OPTIMAL", "ACCEPTABLE"}

            pattern = "STABLE"
            if last_past_status in normal_set and curr_status in abnormal_set:
                pattern = "NEWLY_ABNORMAL"
            elif last_past_status in abnormal_set and curr_status in abnormal_set:
                pattern = "PERSISTENTLY_ABNORMAL"
            elif last_past_status in abnormal_set and curr_status in normal_set:
                pattern = "RESOLVED_ABNORMALITY"
            elif last_past_status in normal_set and curr_status in normal_set:
                pattern = "STABLE_NORMAL"

            trend_item = {
                "parameter": param_name,
                "key": key,
                "current_value": curr_val,
                "current_status": curr_status,
                "history_values": all_vals,
                "visit_count": len(all_vals),
                "directional_trend": trend_type,
                "abnormality_pattern": pattern,
                "summary": f"{param_name}: {trend_type.lower().replace('_', ' ')} across {len(all_vals)} visits ({' -> '.join(map(str, all_vals))} {current_res.get('unit', '')}). Pattern: {pattern.lower().replace('_', ' ')}."
            }
            trends.append(trend_item)

        return trends

    # --- REQUIREMENT 2: True Bidirectional Medication/Lab Safety ---
    def check_prescription_against_past_labs(self, new_medicine_name, patient_name="Default Patient"):
        """
        Direction A: New Prescription -> Past Lab Results
        Input: New Medicine -> Checks against Patient's Historical Lab Results -> Returns Safety Warning.
        Does NOT call Direction B.
        """
        alerts = []
        if not new_medicine_name or not isinstance(new_medicine_name, str):
            return alerts

        classification = self.classify_medication(new_medicine_name)
        pstore = self._get_patient_store(patient_name)
        past_labs = pstore.get("past_lab_results", [])
        if not past_labs:
            return alerts

        med_lower = new_medicine_name.lower().strip()
        triggered_keys = set()

        # 1. Search Explicit Rule Database
        for rule in MEDICATION_LAB_SAFETY_RULES:
            med_match = any(alias in med_lower for alias in rule["medication_aliases"])
            if not med_match:
                continue
            
            for lab in past_labs:
                if lab.get("key") == rule["lab_key"] and lab.get("status") in rule["abnormal_statuses"]:
                    alerts.append({
                        "direction": "New Prescription -> Past Labs (Direction A)",
                        "rule_id": rule["rule_id"],
                        "title": rule["title"],
                        "severity": rule["severity"],
                        "trigger_drug": new_medicine_name,
                        "matched_lab": lab["parameter"],
                        "matched_status": lab["status"],
                        "matched_value": f"{lab['value']} {lab.get('unit', '')}".strip(),
                        "explanation": f"Potential medication-lab safety relationship detected (Direction A): Prescribing {new_medicine_name} for patient '{pstore.get('patient_name')}' when past {lab['parameter']} result was {lab['status']} ({lab['value']} {lab.get('unit', '')}). {rule['explanation']}"
                    })
                    triggered_keys.add((rule["lab_key"], new_medicine_name.lower()))
                    break

        # 2. Dynamic Fallback Search via Suffix Map
        if classification.get("status") == "SUFFIX_FALLBACK_MATCH":
            lab_key = classification["target_lab_keys"][0]
            if (lab_key, new_medicine_name.lower()) not in triggered_keys:
                for lab in past_labs:
                    for suffix_rule in PHARMACOLOGICAL_SUFFIX_MAP:
                        if suffix_rule["lab_key"] == lab_key and lab.get("status") in suffix_rule["abnormal_statuses"]:
                            alerts.append({
                                "direction": "New Prescription -> Past Labs (Direction A)",
                                "rule_id": suffix_rule["rule_id"],
                                "title": suffix_rule["title"],
                                "severity": suffix_rule["severity"],
                                "trigger_drug": new_medicine_name,
                                "matched_lab": lab["parameter"],
                                "matched_status": lab["status"],
                                "matched_value": f"{lab['value']} {lab.get('unit', '')}".strip(),
                                "explanation": f"Potential medication-lab safety relationship detected (Direction A): Prescribing {new_medicine_name} ({classification['class']}) for patient '{pstore.get('patient_name')}' when past {lab['parameter']} result was {lab['status']} ({lab['value']} {lab.get('unit', '')}). {suffix_rule['explanation']}"
                            })
                            break

        return alerts

    def check_new_labs_against_active_meds(self, new_evaluation_results, patient_name="Default Patient"):
        """
        Direction B: New Lab Result -> Active Medications
        Input: Abnormal New Lab Results -> Checks against Patient's Active Medications -> Returns Safety Warning.
        Does NOT call Direction A.
        """
        alerts = []
        pstore = self._get_patient_store(patient_name)
        active_meds = pstore.get("active_medications", [])
        if not active_meds or not new_evaluation_results:
            return alerts

        triggered_pairs = set()

        # 1. Search Explicit Rule Database
        for res in new_evaluation_results:
            # Exclude unvalidated / ambiguous / review required findings from triggering high-confidence warnings
            val_status = res.get("validation_status")
            if val_status in ["REVIEW_REQUIRED", "AMBIGUOUS", "UNVERIFIED"]:
                continue

            lab_key = res.get("normalized_test_name", res.get("key"))
            status = res.get("status")
            param_name = res.get("test_name", res.get("parameter"))
            val_display = res.get("result_text", f"{res.get('value', '')} {res.get('unit', '')}".strip())

            for rule in MEDICATION_LAB_SAFETY_RULES:
                if rule["lab_key"] == lab_key and status in rule["abnormal_statuses"]:
                    matching_meds = [
                        m["name"] for m in active_meds 
                        if any(alias in m["name"].lower() for alias in rule["medication_aliases"])
                    ]
                    for med_name in matching_meds:
                        alerts.append({
                            "direction": "New Labs -> Active Medications (Direction B)",
                            "rule_id": rule["rule_id"],
                            "title": rule["title"],
                            "severity": rule["severity"],
                            "trigger_lab": param_name,
                            "lab_status": status,
                            "lab_value": val_display,
                            "matched_drug": med_name,
                            "explanation": f"Potential medication-lab safety relationship detected (Direction B): New lab finding {param_name} is {status} ({val_display}) for patient '{pstore.get('patient_name')}' while active medication '{med_name}' is being taken. {rule['explanation']}"
                        })
                        triggered_pairs.add((lab_key, med_name.lower()))

        # 2. Dynamic Fallback Search via Suffix Map
        for res in new_evaluation_results:
            lab_key = res.get("key")
            status = res.get("status")

            for med_obj in active_meds:
                med_name = med_obj["name"]
                if (lab_key, med_name.lower()) in triggered_pairs:
                    continue

                classification = self.classify_medication(med_name)
                if classification.get("status") == "SUFFIX_FALLBACK_MATCH":
                    for suffix_rule in PHARMACOLOGICAL_SUFFIX_MAP:
                        if suffix_rule["lab_key"] == lab_key and status in suffix_rule["abnormal_statuses"]:
                            alerts.append({
                                "direction": "New Labs -> Active Medications (Direction B)",
                                "rule_id": suffix_rule["rule_id"],
                                "title": suffix_rule["title"],
                                "severity": suffix_rule["severity"],
                                "trigger_lab": res.get("parameter", res.get("test_name")),
                                "lab_status": status,
                                "lab_value": f"{res.get('value', '')} {res.get('unit', '')}".strip(),
                                "matched_drug": med_name,
                                "explanation": f"Potential medication-lab safety relationship detected (Direction B): New lab finding {res.get('parameter', res.get('test_name'))} is {status} ({res.get('value', '')} {res.get('unit', '')}) for patient '{pstore.get('patient_name')}' while active medication '{med_name}' ({classification['class']}) is being taken. {suffix_rule['explanation']}"
                            })
                            triggered_pairs.add((lab_key, med_name.lower()))
                            break

        return alerts

