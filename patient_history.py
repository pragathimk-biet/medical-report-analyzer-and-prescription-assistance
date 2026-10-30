import os
import json
import logging
import re
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import bcrypt
    def hash_password(password: str) -> str:
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    def verify_password(password: str, hashed: str) -> bool:
        if not hashed:
            return False
        if hashed.startswith('$2b$') or hashed.startswith('$2a$') or hashed.startswith('$2y$'):
            try:
                return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
            except Exception:
                return False
        return check_password_hash(hashed, password)
except ImportError:
    def hash_password(password: str) -> str:
        return generate_password_hash(password)
    def verify_password(password: str, hashed: str) -> bool:
        return check_password_hash(hashed, password)

def validate_registration_inputs(email, password, confirm_password=None, full_name=""):
    """Validates registration input fields per security and clinical data governance."""
    if not full_name or len(full_name.strip()) < 2:
        return False, "Full name must be at least 2 characters long."
    if not email or not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email.strip()):
        return False, "Please enter a valid email address."
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not (re.search(r'[A-Za-z]', password) and re.search(r'[\d\W_]', password)):
        return False, "Password must contain at least one letter and one number or special character."
    if confirm_password is not None and password != confirm_password:
        return False, "Passwords do not match."
    return True, ""

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
    },
    "glimepiride": {
        "primary_name": "Glimepiride",
        "class": "Sulfonylurea Antidiabetic",
        "target_lab_keys": ["glucose_fasting", "hba1c"],
        "rule_id": "MED_DB_GLIMEPIRIDE_001"
    },
    "augmentin": {
        "primary_name": "Augmentin (Amoxicillin/Clavulanate)",
        "class": "Beta-Lactamase Inhibitor Antibiotic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_AUGMENTIN_001"
    },
    "cetirizine": {
        "primary_name": "Cetirizine",
        "class": "Antihistamine",
        "target_lab_keys": [],
        "rule_id": "MED_DB_CETIRIZINE_001"
    },
    "doxycycline": {
        "primary_name": "Doxycycline",
        "class": "Tetracycline Antibiotic",
        "target_lab_keys": ["alt", "ast", "creatinine"],
        "rule_id": "MED_DB_DOXYCYCLINE_001"
    },
    "azithromycin": {
        "primary_name": "Azithromycin",
        "class": "Macrolide Antibiotic",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_AZITHROMYCIN_001"
    },
    "ciprofloxacin": {
        "primary_name": "Ciprofloxacin",
        "class": "Fluoroquinolone Antibiotic",
        "target_lab_keys": ["creatinine"],
        "rule_id": "MED_DB_CIPROFLOXACIN_001"
    },
    "mgso4": {
        "primary_name": "Magnesium Sulfate",
        "class": "Anticonvulsant / Mineral",
        "target_lab_keys": ["magnesium", "calcium", "potassium"],
        "rule_id": "MED_DB_MGSO4_001"
    },
    "magnesium sulfate": {
        "primary_name": "Magnesium Sulfate",
        "class": "Anticonvulsant / Mineral",
        "target_lab_keys": ["magnesium", "calcium", "potassium"],
        "rule_id": "MED_DB_MAGNESIUM_SULFATE_001"
    },
    "magnesium sulphate": {
        "primary_name": "Magnesium Sulfate",
        "class": "Anticonvulsant / Mineral",
        "target_lab_keys": ["magnesium", "calcium", "potassium"],
        "rule_id": "MED_DB_MAGNESIUM_SULPHATE_001"
    },
    "dolo": {
        "primary_name": "Paracetamol (Dolo)",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_DOLO_001"
    },
    "crocin": {
        "primary_name": "Paracetamol (Crocin)",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_CROCIN_001"
    },
    "calpol": {
        "primary_name": "Paracetamol (Calpol)",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_CALPOL_001"
    },
    "glycomet": {
        "primary_name": "Metformin (Glycomet)",
        "class": "Biguanide Antidiabetic",
        "target_lab_keys": ["glucose_fasting", "hba1c", "creatinine"],
        "rule_id": "MED_DB_GLYCOMET_001"
    },
    "pan": {
        "primary_name": "Pantoprazole (Pan)",
        "class": "Proton Pump Inhibitor (PPI)",
        "target_lab_keys": ["magnesium", "sodium"],
        "rule_id": "MED_DB_PAN_001"
    },
    "pantocid": {
        "primary_name": "Pantoprazole (Pantocid)",
        "class": "Proton Pump Inhibitor (PPI)",
        "target_lab_keys": ["magnesium", "sodium"],
        "rule_id": "MED_DB_PANTOCID_001"
    },
    "omez": {
        "primary_name": "Omeprazole (Omez)",
        "class": "Proton Pump Inhibitor (PPI)",
        "target_lab_keys": ["magnesium", "sodium"],
        "rule_id": "MED_DB_OMEZ_001"
    },
    "amlong": {
        "primary_name": "Amlodipine (Amlong)",
        "class": "Calcium Channel Blocker (CCB)",
        "target_lab_keys": ["creatinine"],
        "rule_id": "MED_DB_AMLONG_001"
    },
    "telma": {
        "primary_name": "Telmisartan (Telma)",
        "class": "Angiotensin Receptor Blocker (ARB)",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_TELMA_001"
    },
    "telmisartan": {
        "primary_name": "Telmisartan",
        "class": "Angiotensin Receptor Blocker (ARB)",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_TELMISARTAN_001"
    },
    "ecosprin": {
        "primary_name": "Aspirin (Ecosprin)",
        "class": "Antiplatelet / Salicylate",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_ECOSPRIN_001"
    },
    "disprin": {
        "primary_name": "Aspirin (Disprin)",
        "class": "Antiplatelet / Salicylate",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_DISPRIN_001"
    },
    "atorva": {
        "primary_name": "Atorvastatin (Atorva)",
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_ATORVA_001"
    },
    "rosuvas": {
        "primary_name": "Rosuvastatin (Rosuvas)",
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_ROSUVAS_001"
    },
    "clavam": {
        "primary_name": "Amoxicillin/Clavulanate (Clavam)",
        "class": "Beta-Lactamase Inhibitor Antibiotic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_CLAVAM_001"
    },
    "azithral": {
        "primary_name": "Azithromycin (Azithral)",
        "class": "Macrolide Antibiotic",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_AZITHRAL_001"
    },
    "ciplox": {
        "primary_name": "Ciprofloxacin (Ciplox)",
        "class": "Fluoroquinolone Antibiotic",
        "target_lab_keys": ["creatinine"],
        "rule_id": "MED_DB_CIPLOX_001"
    },
    "lasix": {
        "primary_name": "Furosemide (Lasix)",
        "class": "Loop Diuretic",
        "target_lab_keys": ["sodium", "potassium", "creatinine"],
        "rule_id": "MED_DB_LASIX_001"
    },
    "clopidogrel": {
        "primary_name": "Clopidogrel",
        "class": "Antiplatelet",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_CLOPIDOGREL_001"
    },
    "plavix": {
        "primary_name": "Clopidogrel (Plavix)",
        "class": "Antiplatelet",
        "target_lab_keys": ["hemoglobin", "platelets"],
        "rule_id": "MED_DB_PLAVIX_001"
    },
    "digoxin": {
        "primary_name": "Digoxin",
        "class": "Cardiac Glycoside",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_DIGOXIN_001"
    },
    "lanoxin": {
        "primary_name": "Digoxin (Lanoxin)",
        "class": "Cardiac Glycoside",
        "target_lab_keys": ["potassium", "creatinine"],
        "rule_id": "MED_DB_LANOXIN_001"
    },
    "metoprolol": {
        "primary_name": "Metoprolol",
        "class": "Beta-Blocker",
        "target_lab_keys": ["glucose_fasting"],
        "rule_id": "MED_DB_METOPROLOL_001"
    },
    "atenolol": {
        "primary_name": "Atenolol",
        "class": "Beta-Blocker",
        "target_lab_keys": ["glucose_fasting"],
        "rule_id": "MED_DB_ATENOLOL_001"
    },
    "carvedilol": {
        "primary_name": "Carvedilol",
        "class": "Beta-Blocker",
        "target_lab_keys": ["glucose_fasting"],
        "rule_id": "MED_DB_CARVEDILOL_001"
    },
    "glipizide": {
        "primary_name": "Glipizide",
        "class": "Sulfonylurea Antidiabetic",
        "target_lab_keys": ["glucose_fasting", "hba1c"],
        "rule_id": "MED_DB_GLIPIZIDE_001"
    },
    "sitagliptin": {
        "primary_name": "Sitagliptin",
        "class": "DPP-4 Inhibitor",
        "target_lab_keys": ["glucose_fasting", "hba1c"],
        "rule_id": "MED_DB_SITAGLIPTIN_001"
    },
    "januvia": {
        "primary_name": "Sitagliptin (Januvia)",
        "class": "DPP-4 Inhibitor",
        "target_lab_keys": ["glucose_fasting", "hba1c"],
        "rule_id": "MED_DB_JANUVIA_001"
    },
    "allopurinol": {
        "primary_name": "Allopurinol",
        "class": "Xanthine Oxidase Inhibitor",
        "target_lab_keys": ["creatinine", "alt", "ast"],
        "rule_id": "MED_DB_ALLOPURINOL_001"
    },
    "potassium chloride": {
        "primary_name": "Potassium Chloride",
        "class": "Electrolyte Supplement",
        "target_lab_keys": ["potassium"],
        "rule_id": "MED_DB_KCL_001"
    },
    "kcl": {
        "primary_name": "Potassium Chloride (KCl)",
        "class": "Electrolyte Supplement",
        "target_lab_keys": ["potassium"],
        "rule_id": "MED_DB_KCL_002"
    },
    "perinorm": {
        "primary_name": "Metoclopramide (Perinorm)",
        "generic_name": "Metoclopramide",
        "brand_name": "Perinorm",
        "class": "Dopamine D2 Antagonist / Antiemetic / Prokinetic",
        "target_lab_keys": ["alt", "ast", "creatinine"],
        "rule_id": "MED_DB_PERINORM_001",
        "ddinter_id": "DDInter1197",
        "standard_strengths": ["10mg", "5mg/5ml", "10mg/2ml"],
        "dosage_form": "Tablet / Syrup / Injection",
        "schedule": "Schedule H",
        "otc": False,
        "high_risk": False
    },
    "metoclopramide": {
        "primary_name": "Metoclopramide",
        "generic_name": "Metoclopramide",
        "class": "Dopamine D2 Antagonist / Antiemetic / Prokinetic",
        "target_lab_keys": ["alt", "ast", "creatinine"],
        "rule_id": "MED_DB_METOCLOPRAMIDE_001",
        "ddinter_id": "DDInter1197",
        "standard_strengths": ["10mg", "5mg", "5mg/5ml"],
        "dosage_form": "Tablet / Injection / Syrup",
        "schedule": "Schedule H",
        "otc": False,
        "high_risk": False
    },
    "parajely": {
        "primary_name": "Paracetamol (Parajely)",
        "generic_name": "Paracetamol",
        "brand_name": "Parajely",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_PARAJELY_001",
        "ddinter_id": "DDInter14",
        "standard_strengths": ["100mg/ml", "100mg", "125mg/5ml"],
        "dosage_form": "Drops / Oral Suspension",
        "schedule": "OTC / General",
        "otc": True,
        "high_risk": False
    },
    "parajel": {
        "primary_name": "Paracetamol (Parajel)",
        "generic_name": "Paracetamol",
        "brand_name": "Parajel",
        "class": "Analgesic / Antipyretic",
        "target_lab_keys": ["alt", "ast", "bilirubin_total"],
        "rule_id": "MED_DB_PARAJEL_001",
        "ddinter_id": "DDInter14",
        "standard_strengths": ["100mg/ml", "100mg"],
        "dosage_form": "Drops",
        "schedule": "OTC / General",
        "otc": True,
        "high_risk": False
    },
    "ondansetron": {
        "primary_name": "Ondansetron",
        "generic_name": "Ondansetron",
        "class": "5-HT3 Receptor Antagonist / Antiemetic",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_ONDANSETRON_001",
        "ddinter_id": "DDInter1342",
        "schedule": "Schedule H",
        "otc": False
    },
    "emset": {
        "primary_name": "Ondansetron (Emset)",
        "generic_name": "Ondansetron",
        "brand_name": "Emset",
        "class": "5-HT3 Receptor Antagonist / Antiemetic",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_EMSET_001",
        "ddinter_id": "DDInter1342",
        "schedule": "Schedule H",
        "otc": False
    },
    "domperidone": {
        "primary_name": "Domperidone",
        "generic_name": "Domperidone",
        "class": "Dopamine Antagonist / Prokinetic",
        "target_lab_keys": ["alt", "ast"],
        "rule_id": "MED_DB_DOMPERIDONE_001",
        "ddinter_id": "DDInter577",
        "schedule": "Schedule H",
        "otc": False
    },
    "combiflam": {
        "primary_name": "Ibuprofen + Paracetamol (Combiflam)",
        "generic_name": "Ibuprofen + Paracetamol",
        "brand_name": "Combiflam",
        "class": "NSAID + Analgesic Combination",
        "target_lab_keys": ["creatinine", "urea", "alt", "ast"],
        "rule_id": "MED_DB_COMBIFLAM_001",
        "schedule": "Schedule H",
        "otc": False
    },
    "dexolac": {
        "primary_name": "Dexolac Special Care Infant Formula",
        "generic_name": "Nutritional Formula for Premature / Low Birth Weight Infants",
        "brand_name": "Dexolac",
        "class": "Nutritional Product / Infant Formula",
        "target_lab_keys": [],
        "rule_id": "NUT_DB_DEXOLAC_001",
        "item_type": "NUTRITIONAL_PRODUCT",
        "is_medicine": False,
        "is_nutritional": True
    },
    "lactare": {
        "primary_name": "Lactare Herbal Galactagogue Granules",
        "generic_name": "Asparagus racemosus (Shatavari) Dietary Supplement",
        "brand_name": "Lactare",
        "class": "Dietary Supplement / Herbal Galactagogue",
        "target_lab_keys": [],
        "rule_id": "SUPP_DB_LACTARE_001",
        "item_type": "DIETARY_SUPPLEMENT",
        "is_medicine": False,
        "is_supplement": True
    }
}

# Nutritional Products Knowledge Base (Infant Formulas & Medical Feeds)
NUTRITIONAL_KEYWORDS = {
    "dexolac", "similac", "nan pro", "lactogen", "enfamil", "farex", "cerelac",
    "pediasure", "ensure", "protinex", "resource high protein", "infant formula",
    "milk powder", "special care powder", "special care", "nutricia", "danone",
    "infant food", "baby cereal", "nestle nan"
}

# Dietary and Herbal Supplements Knowledge Base
SUPPLEMENT_KEYWORDS = {
    "lactare", "galakol", "shatavari", "calcimax", "ostocalcium", "becozinc",
    "supradyn", "zincovit", "revital", "neurobion", "evion", "choco granules",
    "lactare granules", "lactation supplement", "cod liver oil", "omega 3",
    "fish oil", "multivitamin", "protein powder", "calcium supplement"
}

# Medical Devices and Medical Supplies Distinction Knowledge Base
DEVICE_KEYWORDS = {
    "cannula", "iv cannula", "catheter", "foley catheter", "syringe", "needle",
    "iv set", "infusion set", "scalp vein", "endotracheal tube", "nebulizer mask",
    "stent", "surgical drain", "buretrol", "spinal needle", "oxygen mask",
    "glucometer", "lancet", "thermometer", "bp cuff", "vaporizer"
}

SUPPLY_KEYWORDS = {
    "easy fix", "micropore", "plaster", "adhesive plaster", "bandage", "crepe bandage",
    "gauze", "gauze swab", "cotton", "cotton roll", "surgical tape", "dynaplast",
    "sterile gloves", "surgical gloves", "alcohol swab", "spirit swab", "antiseptic wipe",
    "surgical spirit", "dettol", "savlon", "adhesive tape"
}

def classify_medical_item(text):
    """
    Distinguishes medicines, nutritional products, dietary supplements, medical devices,
    and medical supplies from prescriptions and pharmacy bills.
    Ensures non-pharmaceutical items are never falsely submitted to drug-drug interaction databases.
    """
    if not text or not isinstance(text, str):
        return {
            "item_type": "UNKNOWN",
            "is_medicine": False,
            "is_nutritional": False,
            "is_supplement": False,
            "is_device_or_supply": False,
            "label": "Unknown Item"
        }
    
    clean_text = text.lower().strip()
    
    # 1. Nutritional Product Matching (Infant formulas, clinical nutritional powders)
    for nut in NUTRITIONAL_KEYWORDS:
        if nut in clean_text or re.search(r'\b' + re.escape(nut) + r'\b', clean_text):
            return {
                "item_type": "NUTRITIONAL_PRODUCT",
                "is_medicine": False,
                "is_nutritional": True,
                "is_supplement": False,
                "is_device_or_supply": False,
                "label": "Nutritional Product (Infant Formula / Nutritional Feed)",
                "matched_keyword": nut
            }

    # 2. Dietary & Herbal Supplement Matching (Galactagogues, multivitamins, granules)
    for supp in SUPPLEMENT_KEYWORDS:
        if supp in clean_text or re.search(r'\b' + re.escape(supp) + r'\b', clean_text):
            return {
                "item_type": "DIETARY_SUPPLEMENT",
                "is_medicine": False,
                "is_nutritional": False,
                "is_supplement": True,
                "is_device_or_supply": False,
                "label": "Dietary / Herbal Supplement",
                "matched_keyword": supp
            }

    # 3. Medical Device Matching
    for dev in DEVICE_KEYWORDS:
        if dev in clean_text or re.search(r'\b' + re.escape(dev) + r'\b', clean_text):
            return {
                "item_type": "MEDICAL_DEVICE",
                "is_medicine": False,
                "is_nutritional": False,
                "is_supplement": False,
                "is_device_or_supply": True,
                "label": "Medical Device",
                "matched_keyword": dev
            }
            
    # 4. Medical Supply Matching
    for sup in SUPPLY_KEYWORDS:
        if sup in clean_text or re.search(r'\b' + re.escape(sup) + r'\b', clean_text):
            return {
                "item_type": "MEDICAL_SUPPLY",
                "is_medicine": False,
                "is_nutritional": False,
                "is_supplement": False,
                "is_device_or_supply": True,
                "label": "Medical Supply",
                "matched_keyword": sup
            }
            
    # 5. Default to Medication
    return {
        "item_type": "MEDICINE",
        "is_medicine": True,
        "is_nutritional": False,
        "is_supplement": False,
        "is_device_or_supply": False,
        "label": "Medication"
    }

def normalize_medicine_name(raw_name: str) -> dict:
    """
    Normalizes a medicine or pharmacy product string.
    Separates concatenated dosage forms (e.g. 'PERINORMTAB' -> 'Perinorm', form: 'Tablet'),
    extracts strengths ('100mg', '10mg', '1g'), and strips bill packaging codes ('10's', '1X10', '250G').
    """
    if not raw_name or not isinstance(raw_name, str):
        return {
            "raw_name": "",
            "clean_name": "",
            "normalized_lower": "",
            "dosage_form": None,
            "extracted_strength": None,
            "canonical_key": ""
        }

    clean = raw_name.strip()
    # 1. Strip leading line numbering / bullets / prefix forms
    clean = re.sub(r'^(?:\d+[\.\s\-\)]+|rx[:\.\s]*|tab[\.\s]+|cap[\.\s]+|inj[\.\s]+|syp[\.\s]+)', '', clean, flags=re.I).strip()

    # 2. Extract dosage strength if embedded
    extracted_strength = None
    str_match = re.search(r'\b(\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu|units))\b', clean, re.I)
    if str_match:
        extracted_strength = str_match.group(1).strip()
        clean = re.sub(r'\b' + re.escape(str_match.group(0)) + r'\b', '', clean, flags=re.I).strip()
    else:
        # Check concatenated numbers at end of token, e.g. "PERINORM10", "AZITHRAL500"
        concat_num = re.search(r'([a-zA-Z]{3,})(\d+(?:\.\d+)?)\s*$', clean)
        if concat_num and concat_num.group(1).lower() not in ["20g", "18g", "22g", "24g"]:
            clean = concat_num.group(1).strip()
            extracted_strength = f"{concat_num.group(2)}mg"

    # 3. Detect and separate dosage forms (standalone or concatenated)
    detected_form = None
    forms_map = {
        "tablet": "Tablet", "tablets": "Tablet", "tab": "Tablet", "tabs": "Tablet",
        "capsule": "Capsule", "capsules": "Capsule", "cap": "Capsule", "caps": "Capsule",
        "injection": "Injection", "inj": "Injection", "injections": "Injection",
        "syrup": "Syrup", "syp": "Syrup", "drops": "Drops", "drop": "Drops",
        "powder": "Powder", "pwd": "Powder", "granules": "Granules", "gran": "Granules",
        "ointment": "Ointment", "oint": "Ointment", "cream": "Cream", "crm": "Cream",
        "gel": "Gel", "lotion": "Lotion", "solution": "Solution", "sol": "Solution",
        "suspension": "Suspension", "susp": "Suspension", "inhaler": "Inhaler",
        "spray": "Spray", "sachet": "Sachet", "sachets": "Sachet"
    }

    # Check concatenated dosage form at end of token (e.g. "PERINORMTAB", "PARAJELYDROPS")
    concat_form_pattern = r'^(.*?)(tabs?|tablets?|caps?|capsules?|inj(?:ection)?|syps?|syrups?|drops?|pwds?|powders?|grans?|granules?|oints?|ointments?|gels?|crms?|creams?|soln?|solutions?|susps?|suspensions?)$'
    m_concat = re.match(concat_form_pattern, clean, re.I)
    if m_concat and len(m_concat.group(1).strip()) >= 3:
        clean = m_concat.group(1).strip()
        matched_suffix = m_concat.group(2).lower()
        detected_form = forms_map.get(matched_suffix, matched_suffix.capitalize())
    else:
        # Check standalone dosage form words
        clean_tokens = []
        for tok in clean.split():
            tok_l = tok.lower().strip(":,.-")
            if tok_l in forms_map:
                detected_form = forms_map[tok_l]
            elif tok_l in ["10's", "15's", "10s", "15s", "1x10", "1x15", "strip", "bottle", "vial", "ampoule"]:
                continue
            else:
                clean_tokens.append(tok)
        clean = " ".join(clean_tokens).strip()

    # 4. Strip commercial package size (e.g. '250G', '400G', '100ML')
    clean = re.sub(r'\b\d+\s*(?:g|gm|gms|ml|ltr)\b', '', clean, flags=re.I).strip()
    clean = re.sub(r'[\(\)\[\]\{\}\:\,\.]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    canonical_key = clean.lower()
    return {
        "raw_name": raw_name,
        "clean_name": clean.title() if clean.isupper() else clean,
        "dosage_form": detected_form,
        "strength": extracted_strength,
        "canonical_key": canonical_key
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

    email = None
    m_email = re.search(r'(?i)\b(?:e-?mail|email)\s*[\:\=\-]\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', text)
    if m_email:
        email = m_email.group(1).strip()

    phone = None
    m_phone = re.search(r'(?i)\b(?:tel(?:ephone)?|phone|mobile|contact)\s*[\:\=\-]\s*([\+\d\s\-\(\)]{6,20})', text)
    if m_phone:
        phone = m_phone.group(1).strip()

    fax = None
    m_fax = re.search(r'(?i)\b(?:fax)\s*[\:\=\-]\s*([\+\d\s\-\(\)]{6,20})', text)
    if m_fax:
        fax = m_fax.group(1).strip()

    subranges = []
    for line in text.splitlines():
        line_s = line.strip()
        m_sub = re.match(r'(?i)^\s*(adults?|children|child|newborns?|neonates?|infants?|males?|females?|men|women)\s*[\:\=]\s*(.+)$', line_s)
        if m_sub:
            subranges.append({"group": m_sub.group(1).capitalize(), "range": m_sub.group(2).strip()})

    return {
        "patient_name": name,
        "age": age,
        "gender": gender,
        "lab_ref_no": lab_ref_no,
        "registration_date": registration_date,
        "email": email,
        "phone": phone,
        "fax": fax,
        "subranges": subranges
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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                patient_slug TEXT NOT NULL,
                contact_phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                patient_name TEXT NOT NULL,
                age TEXT,
                gender TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS active_medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                medicine_name TEXT NOT NULL,
                generic_name TEXT,
                strength TEXT,
                dosage TEXT,
                med_class TEXT,
                status TEXT DEFAULT 'active',
                start_date TEXT,
                end_date TEXT,
                source_prescription_id INTEGER,
                confidence_status TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS prescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                visit_id TEXT,
                medicine_name TEXT NOT NULL,
                extracted_snippet TEXT,
                original_file_path TEXT,
                extraction_status TEXT DEFAULT 'COMPLETED',
                prescription_date TEXT,
                raw_text TEXT,
                verification_status TEXT DEFAULT 'VERIFIED',
                safety_status TEXT DEFAULT 'SAFE',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS prescribed_medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prescription_id INTEGER NOT NULL,
                patient_slug TEXT NOT NULL,
                medicine_name TEXT NOT NULL,
                generic_name TEXT,
                brand_name TEXT,
                strength TEXT,
                dose TEXT,
                route TEXT,
                frequency TEXT,
                duration TEXT,
                confidence_score REAL DEFAULT 1.0,
                verification_status TEXT DEFAULT 'VERIFIED',
                item_type TEXT DEFAULT 'MEDICINE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prescription_id) REFERENCES prescriptions (id) ON DELETE CASCADE,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ddi_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                prescription_id INTEGER,
                medicine_a TEXT NOT NULL,
                medicine_b TEXT NOT NULL,
                source_a TEXT,
                source_b TEXT,
                severity TEXT NOT NULL,
                interaction_description TEXT,
                clinical_consequences TEXT,
                recommendation TEXT,
                evidence_source TEXT DEFAULT 'DDInter / BioThings',
                verification_status TEXT DEFAULT 'VERIFIED',
                analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_slug) REFERENCES patients (slug) ON DELETE CASCADE,
                FOREIGN KEY (prescription_id) REFERENCES prescriptions (id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS safety_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_slug TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                details TEXT,
                source_module TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

    def record_complete_prescription(self, patient_slug, visit_id, file_path=None, raw_text=None,
                                     verification_status="VERIFIED", safety_status="SAFE",
                                     prescription_date=None, extracted_meds=None, ddi_results=None):
        """
        Records a prescription with all prescribed medicines and DDI results inside a database transaction.
        Preserves data consistency and relational foreign keys across tables.
        """
        extracted_meds = extracted_meds or []
        ddi_results = ddi_results or []
        rx_date = prescription_date or datetime.now().strftime("%Y-%m-%d")

        med_names_summary = ", ".join([
            m.get("medicine_name") or m.get("name") or "Medicine"
            for m in extracted_meds[:3]
        ]) or "Prescription"

        with self._get_connection() as conn:
            cur = conn.cursor()
            # 1. Insert into prescriptions table
            cur.execute("""
                INSERT INTO prescriptions (
                    patient_slug, visit_id, medicine_name, extracted_snippet,
                    original_file_path, extraction_status, prescription_date,
                    raw_text, verification_status, safety_status, timestamp
                )
                VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                patient_slug,
                visit_id,
                med_names_summary,
                (raw_text[:200] if raw_text else None),
                file_path,
                rx_date,
                raw_text,
                verification_status,
                safety_status
            ))
            prescription_id = cur.lastrowid

            # 2. Insert prescribed medicines
            for med in extracted_meds:
                m_name = med.get("medicine_name") or med.get("name") or med.get("verified_name") or "Unknown"
                cur.execute("""
                    INSERT INTO prescribed_medicines (
                        prescription_id, patient_slug, medicine_name, generic_name,
                        brand_name, strength, dose, route, frequency, duration,
                        confidence_score, verification_status, item_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prescription_id,
                    patient_slug,
                    m_name,
                    med.get("generic_name"),
                    med.get("brand_name"),
                    med.get("strength"),
                    med.get("dose") or med.get("dosage"),
                    med.get("route"),
                    med.get("frequency"),
                    med.get("duration"),
                    float(med.get("confidence_score", med.get("confidence", 1.0)) or 1.0),
                    med.get("verification_status", "VERIFIED"),
                    med.get("item_type", "MEDICINE")
                ))

            # 3. Insert DDI results
            for ddi in ddi_results:
                cur.execute("""
                    INSERT INTO ddi_results (
                        patient_slug, prescription_id, medicine_a, medicine_b,
                        source_a, source_b, severity, interaction_description,
                        clinical_consequences, recommendation, evidence_source,
                        verification_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VERIFIED')
                """, (
                    patient_slug,
                    prescription_id,
                    ddi.get("drug_a") or ddi.get("medicine_a") or "Drug A",
                    ddi.get("drug_b") or ddi.get("medicine_b") or "Drug B",
                    ddi.get("source_a") or ddi.get("source_product_a") or "NEW",
                    ddi.get("source_b") or ddi.get("source_product_b") or "NEW",
                    ddi.get("severity") or ddi.get("level") or "MODERATE",
                    ddi.get("interaction_description") or ddi.get("note") or ddi.get("description"),
                    ddi.get("clinical_consequences"),
                    ddi.get("recommendation"),
                    ddi.get("evidence_source", "DDInter / BioThings")
                ))

            # 4. Insert or update visit log
            cur.execute("""
                INSERT INTO visits (patient_slug, visit_id, visit_type, details, findings_count)
                VALUES (?, ?, 'PRESCRIPTION', ?, ?)
            """, (patient_slug, visit_id, f"Prescription uploaded with {len(extracted_meds)} items", len(extracted_meds)))

            conn.commit()
            return prescription_id

    def get_patient_prescriptions(self, patient_slug):
        """Retrieves all prescriptions recorded for a patient."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM prescriptions
                WHERE patient_slug = ?
                ORDER BY timestamp DESC
            """, (patient_slug,))
            return [dict(r) for r in cur.fetchall()]

    def get_patient_prescribed_medicines(self, patient_slug, prescription_id=None):
        """Retrieves prescribed medicines, optionally filtered by prescription_id."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            if prescription_id:
                cur.execute("""
                    SELECT * FROM prescribed_medicines
                    WHERE patient_slug = ? AND prescription_id = ?
                    ORDER BY id ASC
                """, (patient_slug, prescription_id))
            else:
                cur.execute("""
                    SELECT * FROM prescribed_medicines
                    WHERE patient_slug = ?
                    ORDER BY id DESC
                """, (patient_slug,))
            return [dict(r) for r in cur.fetchall()]

    def get_patient_medications(self, patient_slug, status=None):
        """Retrieves active or discontinued medications for a patient."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            if status:
                cur.execute("""
                    SELECT * FROM active_medications
                    WHERE patient_slug = ? AND LOWER(status) = LOWER(?)
                    ORDER BY added_at DESC
                """, (patient_slug, status))
            else:
                cur.execute("""
                    SELECT * FROM active_medications
                    WHERE patient_slug = ?
                    ORDER BY added_at DESC
                """, (patient_slug,))
            return [dict(r) for r in cur.fetchall()]

    def update_medication_status(self, med_name_or_id, patient_slug, status):
        """Updates medication status (e.g. 'active' <-> 'discontinued')."""
        clean_status = status.lower().strip()
        with self._get_connection() as conn:
            cur = conn.cursor()
            if isinstance(med_name_or_id, int) or (isinstance(med_name_or_id, str) and med_name_or_id.isdigit()):
                cur.execute("""
                    UPDATE active_medications
                    SET status = ?
                    WHERE id = ? AND patient_slug = ?
                """, (clean_status, int(med_name_or_id), patient_slug))
            else:
                cur.execute("""
                    UPDATE active_medications
                    SET status = ?
                    WHERE LOWER(medicine_name) = LOWER(?) AND patient_slug = ?
                """, (clean_status, str(med_name_or_id).strip(), patient_slug))
            conn.commit()
            return cur.rowcount > 0

    def add_to_active_medications(self, patient_slug, medicine_name, generic_name=None,
                                 strength=None, dosage=None, med_class=None, source_rx_id=None):
        """Adds or updates an active medication for a patient."""
        dos_str = json.dumps(dosage) if isinstance(dosage, dict) else (str(dosage) if dosage else None)
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO active_medications (
                    patient_slug, medicine_name, generic_name, strength,
                    dosage, med_class, status, source_prescription_id, confidence_status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 'VERIFIED')
            """, (patient_slug, medicine_name, generic_name, strength, dos_str, med_class, source_rx_id))
            conn.commit()
            return cur.lastrowid

    def record_ddi_results(self, patient_slug, prescription_id, ddi_list):
        """Records DDI analysis results into relational table."""
        if not ddi_list:
            return
        with self._get_connection() as conn:
            cur = conn.cursor()
            for ddi in ddi_list:
                cur.execute("""
                    INSERT INTO ddi_results (
                        patient_slug, prescription_id, medicine_a, medicine_b,
                        source_a, source_b, severity, interaction_description,
                        clinical_consequences, recommendation, evidence_source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    patient_slug,
                    prescription_id,
                    dddi_a := ddi.get("drug_a") or ddi.get("medicine_a") or "Drug A",
                    dddi_b := ddi.get("drug_b") or ddi.get("medicine_b") or "Drug B",
                    ddi.get("source_a") or ddi.get("source_product_a") or "NEW",
                    ddi.get("source_b") or ddi.get("source_product_b") or "NEW",
                    ddi.get("severity") or ddi.get("level") or "MODERATE",
                    ddi.get("interaction_description") or ddi.get("note") or ddi.get("description"),
                    ddi.get("clinical_consequences"),
                    ddi.get("recommendation"),
                    ddi.get("evidence_source", "DDInter / BioThings")
                ))
            conn.commit()

    def get_patient_ddi_history(self, patient_slug):
        """Retrieves past DDI analysis records for a patient."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ddi_results
                WHERE patient_slug = ?
                ORDER BY analysis_date DESC
            """, (patient_slug,))
            return [dict(r) for r in cur.fetchall()]

    def record_safety_alert(self, patient_slug, alert_type, title, severity, details=None, source_module=None):
        """Records safety alert in relational audit table."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO safety_alerts (patient_slug, alert_type, title, severity, details, source_module)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (patient_slug, alert_type, title, severity, details, source_module))
            conn.commit()

    def get_patient_safety_alerts(self, patient_slug):
        """Retrieves safety alerts for a patient."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM safety_alerts
                WHERE patient_slug = ?
                ORDER BY created_at DESC
            """, (patient_slug,))
            return [dict(r) for r in cur.fetchall()]

    def get_complete_patient_history(self, patient_slug):
        """Returns consolidated relational patient history dictionary."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            # Patient profile
            cur.execute("SELECT * FROM patients WHERE slug = ?", (patient_slug,))
            p_row = cur.fetchone()
            patient_profile = dict(p_row) if p_row else {"slug": patient_slug, "patient_name": patient_slug}

            # Medications
            cur.execute("SELECT * FROM active_medications WHERE patient_slug = ? ORDER BY added_at DESC", (patient_slug,))
            all_meds = [dict(r) for r in cur.fetchall()]
            active_meds = [m for m in all_meds if str(m.get("status", "")).lower() == "active"]
            discontinued_meds = [m for m in all_meds if str(m.get("status", "")).lower() == "discontinued"]

            # Prescriptions with prescribed medicines
            cur.execute("SELECT * FROM prescriptions WHERE patient_slug = ? ORDER BY timestamp DESC", (patient_slug,))
            prescriptions = [dict(r) for r in cur.fetchall()]
            for rx in prescriptions:
                rx_id = rx["id"]
                cur.execute("SELECT * FROM prescribed_medicines WHERE prescription_id = ? ORDER BY id ASC", (rx_id,))
                rx["medicines"] = [dict(m) for m in cur.fetchall()]

            # Lab results
            cur.execute("SELECT * FROM lab_results WHERE patient_slug = ? ORDER BY evaluated_at DESC", (patient_slug,))
            lab_results = [dict(r) for r in cur.fetchall()]

            # DDI history
            cur.execute("SELECT * FROM ddi_results WHERE patient_slug = ? ORDER BY analysis_date DESC", (patient_slug,))
            ddi_history = [dict(r) for r in cur.fetchall()]

            # Safety alerts
            cur.execute("SELECT * FROM safety_alerts WHERE patient_slug = ? ORDER BY created_at DESC", (patient_slug,))
            alerts = [dict(r) for r in cur.fetchall()]

            # Visits and Reports
            cur.execute("SELECT * FROM reports WHERE patient_slug = ? ORDER BY timestamp DESC", (patient_slug,))
            reports = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM visits WHERE patient_slug = ? ORDER BY timestamp DESC", (patient_slug,))
            visits = [dict(r) for r in cur.fetchall()]

            return {
                "profile": patient_profile,
                "active_medications": active_meds,
                "discontinued_medications": discontinued_meds,
                "all_medications": all_meds,
                "prescriptions": prescriptions,
                "lab_results": lab_results,
                "ddi_history": ddi_history,
                "safety_alerts": alerts,
                "reports": reports,
                "visits": visits
            }

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

                # Sync records without destroying relational integrity
                cursor.execute("DELETE FROM active_medications WHERE patient_slug=?", (slug,))
                cursor.execute("DELETE FROM lab_results WHERE patient_slug=?", (slug,))

                # Active Medications
                for med in pdata.get("active_medications", []):
                    dos_str = json.dumps(med.get("dosage")) if isinstance(med.get("dosage"), dict) else (str(med.get("dosage")) if med.get("dosage") else None)
                    m_status = med.get("status", "active")
                    cursor.execute("""
                        INSERT INTO active_medications (patient_slug, medicine_name, dosage, med_class, confidence_status, status, added_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (slug, med.get("name") or med.get("medicine_name", ""), dos_str, med.get("class", ""), med.get("confidence_status", ""), m_status, med.get("added_at", datetime.now().isoformat())))

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

                # Prescriptions (preserve existing relational rows to maintain foreign key integrity)
                for rx in pdata.get("prescriptions", []):
                    rx_id = rx.get("id")
                    v_id = rx.get("visit_id")
                    if rx_id:
                        cursor.execute("SELECT id FROM prescriptions WHERE id=?", (rx_id,))
                        if cursor.fetchone():
                            continue
                    if v_id:
                        cursor.execute("SELECT id FROM prescriptions WHERE patient_slug=? AND visit_id=?", (slug, v_id))
                        if cursor.fetchone():
                            continue
                    cursor.execute("""
                        INSERT INTO prescriptions (patient_slug, visit_id, medicine_name, extracted_snippet, original_file_path, verification_status, safety_status, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (slug, rx.get("visit_id"), rx.get("medicine_name", ""), rx.get("extracted_snippet"), rx.get("original_file_path"), rx.get("verification_status", "VERIFIED"), rx.get("safety_status", "SAFE"), rx.get("timestamp", datetime.now().isoformat())))

                # Reports
                for rpt in pdata.get("reports", []):
                    v_id = rpt.get("visit_id")
                    if v_id:
                        cursor.execute("SELECT id FROM reports WHERE patient_slug=? AND visit_id=?", (slug, v_id))
                        if cursor.fetchone():
                            continue
                    cursor.execute("""
                        INSERT INTO reports (patient_slug, visit_id, report_type, findings_count, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    """, (slug, rpt.get("visit_id", ""), rpt.get("type", "LAB_REPORT"), rpt.get("findings_count", 0), rpt.get("timestamp", datetime.now().isoformat())))

                # Visits
                for v in pdata.get("visits", []):
                    v_id = v.get("visit_id")
                    if v_id:
                        cursor.execute("SELECT id FROM visits WHERE patient_slug=? AND visit_id=?", (slug, v_id))
                        if cursor.fetchone():
                            continue
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

    @staticmethod
    def normalize_patient_name(patient_name):
        return normalize_patient_name(patient_name)

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

    def _save(self, target_slug=None):
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=2)
            # Sync to SQLite relational tables (rows and columns)
            self.sqlite_db.sync_from_dict(self.db)
            # Sync to Neon Serverless PostgreSQL Cloud
            self.sync_to_neon(target_slug=target_slug)
        except Exception as e:
            logger.warning(f"Failed to save patient history: {e}")

    def sync_to_neon(self, target_slug=None):
        """Syncs patient store data into Neon Serverless PostgreSQL Cloud tables."""
        neon_url = os.getenv('NEON_DATABASE_URL', '')
        if not neon_url:
            return
        try:
            import psycopg2
            conn = psycopg2.connect(neon_url, connect_timeout=2)
            cur = conn.cursor()

            if target_slug:
                if target_slug in self.db.get("patients", {}):
                    items = [(target_slug, self.db["patients"][target_slug])]
                else:
                    items = []
            else:
                items = list(self.db.get("patients", {}).items())

            for slug, pdata in items:
                p_name = pdata.get("patient_name", slug)
                cur.execute("""
                    INSERT INTO patients (slug, patient_name)
                    VALUES (%s, %s)
                    ON CONFLICT(slug) DO UPDATE SET patient_name=EXCLUDED.patient_name, updated_at=CURRENT_TIMESTAMP
                """, (slug, p_name))

                cur.execute("DELETE FROM active_medications WHERE patient_slug=%s;", (slug,))
                cur.execute("DELETE FROM lab_results WHERE patient_slug=%s;", (slug,))
                cur.execute("DELETE FROM prescriptions WHERE patient_slug=%s;", (slug,))
                cur.execute("DELETE FROM visits WHERE patient_slug=%s;", (slug,))

                for med in pdata.get("active_medications", []):
                    dos_str = json.dumps(med.get("dosage")) if isinstance(med.get("dosage"), dict) else (str(med.get("dosage")) if med.get("dosage") else None)
                    cur.execute("""
                        INSERT INTO active_medications (patient_slug, medicine_name, dosage, med_class, confidence_status)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (slug, med.get("name", ""), dos_str, med.get("class", ""), med.get("confidence_status", "")))

                for res in pdata.get("past_lab_results", []):
                    cur.execute("""
                        INSERT INTO lab_results (patient_slug, visit_id, parameter, key, value, unit, status, validation_status, rule_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        slug,
                        res.get("visit_id"),
                        res.get("parameter", res.get("test_name", "")),
                        res.get("key", res.get("normalized_test_name", "")),
                        float(res.get("value", res.get("result_value", 0))),
                        res.get("unit", ""),
                        res.get("status", "NORMAL"),
                        res.get("validation_status", "VALIDATED"),
                        res.get("rule_id", "")
                    ))

                for visit in pdata.get("visits", []):
                    cur.execute("""
                        INSERT INTO visits (patient_slug, visit_id, visit_type, details, findings_count)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (slug, visit.get("visit_id", ""), visit.get("visit_type", "REPORT_ANALYSIS"), json.dumps(visit.get("details", {})), visit.get("findings_count", 0)))

            conn.commit()
            cur.close()
            conn.close()
            logger.info("Successfully synced patient history to Neon Serverless Postgres Cloud!")
        except Exception as e:
            logger.warning(f"Failed to sync patient history to Neon Postgres: {e}")

    def create_user_account(self, email, password, full_name, age=None, gender=None, contact_phone=None, confirm_password=None):
        """Creates a registered user account and links it to a patient profile in DB."""
        # 1. Input Validation
        valid, err = validate_registration_inputs(email, password, confirm_password=confirm_password, full_name=full_name)
        if not valid:
            return False, err

        slug, display_name = normalize_patient_name(full_name)
        pw_hash = hash_password(password)
        clean_email = email.strip().lower()

        # 2. Store in Neon Cloud Postgres if configured
        neon_url = os.getenv('NEON_DATABASE_URL', '')
        if neon_url:
            try:
                import psycopg2
                conn = psycopg2.connect(neon_url, connect_timeout=2)
                cur = conn.cursor()
                cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s);", (clean_email,))
                if cur.fetchone():
                    cur.close()
                    conn.close()
                    return False, "An account with this email address already exists."

                cur.execute("""
                    INSERT INTO patients (slug, patient_name, age, gender)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(slug) DO UPDATE SET patient_name=EXCLUDED.patient_name, age=EXCLUDED.age, gender=EXCLUDED.gender, updated_at=CURRENT_TIMESTAMP
                """, (slug, display_name, str(age) if age else None, gender))

                cur.execute("""
                    INSERT INTO users (email, password_hash, full_name, patient_slug, contact_phone)
                    VALUES (%s, %s, %s, %s, %s)
                """, (clean_email, pw_hash, display_name, slug, contact_phone))

                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.warning(f"Error registering user in Neon Cloud DB: {e}")

        # 3. Store in local SQLite DB
        user_id = None
        try:
            with self.sqlite_db._get_connection() as conn_sq:
                cur_sq = conn_sq.cursor()
                cur_sq.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?);", (clean_email,))
                if cur_sq.fetchone():
                    return False, "An account with this email address already exists."

                cur_sq.execute("""
                    INSERT INTO users (email, password_hash, full_name, patient_slug, contact_phone)
                    VALUES (?, ?, ?, ?, ?)
                """, (clean_email, pw_hash, display_name, slug, contact_phone))
                user_id = cur_sq.lastrowid

                cur_sq.execute("""
                    INSERT INTO patients (slug, patient_name, age, gender, user_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET patient_name=excluded.patient_name,
                        age=COALESCE(excluded.age, patients.age),
                        gender=COALESCE(excluded.gender, patients.gender),
                        user_id=COALESCE(excluded.user_id, patients.user_id),
                        updated_at=CURRENT_TIMESTAMP
                """, (slug, display_name, str(age) if age else None, gender, user_id))
                conn_sq.commit()
        except Exception as e:
            logger.warning(f"Error registering user in local SQLite DB: {e}")
            return False, f"Database error during registration: {str(e)}"

        # 4. Initialize patient profile in history store
        self._get_patient_store(display_name)
        self._save(target_slug=slug)

        user_data = {
            "user_id": user_id,
            "email": clean_email,
            "full_name": display_name,
            "patient_slug": slug
        }
        return True, user_data

    def authenticate_user(self, email, password):
        """Authenticates user against Neon Postgres or SQLite DB credentials."""
        clean_email = email.strip().lower()

        # Try Neon Cloud DB first
        neon_url = os.getenv('NEON_DATABASE_URL', '')
        if neon_url:
            try:
                import psycopg2
                conn = psycopg2.connect(neon_url, connect_timeout=2)
                cur = conn.cursor()
                cur.execute("SELECT id, email, password_hash, full_name, patient_slug FROM users WHERE LOWER(email)=LOWER(%s);", (clean_email,))
                row = cur.fetchone()
                cur.close()
                conn.close()

                if row and verify_password(password, row[2]):
                    return {
                        "user_id": row[0],
                        "email": row[1],
                        "full_name": row[3],
                        "patient_slug": row[4]
                    }
                elif row:
                    return None  # Invalid password
            except Exception as e:
                logger.warning(f"Error authenticating user in Neon Cloud DB: {e}")

        # Fallback to local SQLite DB
        try:
            with self.sqlite_db._get_connection() as conn_sq:
                cur_sq = conn_sq.cursor()
                cur_sq.execute("SELECT id, email, password_hash, full_name, patient_slug FROM users WHERE LOWER(email)=LOWER(?);", (clean_email,))
                row = cur_sq.fetchone()
                if row and verify_password(password, row["password_hash"]):
                    return {
                        "user_id": row["id"],
                        "email": row["email"],
                        "full_name": row["full_name"],
                        "patient_slug": row["patient_slug"]
                    }
        except Exception as e:
            logger.warning(f"Error authenticating user in local SQLite DB: {e}")

        return None

    def toggle_medication_status(self, patient_name, med_name_or_id, new_status):
        """Toggles a patient's medication status between 'active' and 'discontinued'."""
        slug, _ = normalize_patient_name(patient_name)
        clean_status = new_status.lower().strip()
        # 1. Update in SQLite
        db_updated = self.sqlite_db.update_medication_status(med_name_or_id, slug, clean_status)
        # 2. Update in JSON store
        pstore = self._get_patient_store(patient_name)
        for med in pstore.get("active_medications", []):
            m_name = (med.get("name") or med.get("medicine_name") or "").lower()
            if m_name == str(med_name_or_id).lower() or str(med.get("id")) == str(med_name_or_id):
                med["status"] = clean_status
        self._save(target_slug=slug)
        return db_updated

    def save_complete_prescription(self, patient_name, visit_id=None, file_path=None, raw_text=None,
                                  verification_status="VERIFIED", safety_status="SAFE",
                                  prescription_date=None, extracted_meds=None, ddi_results=None):
        """Persists a complete prescription with its medications and DDI results to DB and store."""
        slug, display_name = normalize_patient_name(patient_name)
        pstore = self._get_patient_store(patient_name)
        v_id = visit_id or f"VISIT-{len(pstore.get('visits', [])) + 1:03d}"
        extracted_meds = extracted_meds or []
        ddi_results = ddi_results or []
        timestamp = datetime.now().isoformat()

        # 1. Persist to SQLite relational database
        rx_id = self.sqlite_db.record_complete_prescription(
            patient_slug=slug,
            visit_id=v_id,
            file_path=file_path,
            raw_text=raw_text,
            verification_status=verification_status,
            safety_status=safety_status,
            prescription_date=prescription_date,
            extracted_meds=extracted_meds,
            ddi_results=ddi_results
        )

        # 2. Persist to memory and JSON store
        rx_entry = {
            "id": rx_id,
            "visit_id": v_id,
            "medicine_name": ", ".join([m.get("medicine_name") or m.get("name") or "Medicine" for m in extracted_meds[:3]]),
            "extracted_snippet": raw_text[:200] if raw_text else None,
            "original_file_path": file_path,
            "timestamp": timestamp,
            "verification_status": verification_status,
            "safety_status": safety_status,
            "medicines": extracted_meds,
            "ddi_results": ddi_results
        }
        pstore.setdefault("prescriptions", []).append(rx_entry)
        
        visit_entry = {
            "visit_id": v_id,
            "timestamp": timestamp,
            "type": "PRESCRIPTION",
            "details": f"Prescription uploaded with {len(extracted_meds)} items"
        }
        pstore.setdefault("visits", []).append(visit_entry)
        self._save(target_slug=slug)
        return rx_id

    def get_dashboard_data(self, patient_name):
        """Returns consolidated dashboard payload for a patient."""
        slug, display_name = normalize_patient_name(patient_name)
        db_data = self.sqlite_db.get_complete_patient_history(slug)
        # Ensure display name fallback
        if not db_data.get("profile", {}).get("patient_name"):
            db_data["profile"]["patient_name"] = display_name
        return db_data

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

    def add_active_medication(self, medicine_name, dosage=None, patient_name="Default Patient", status="active", generic_name=None, strength=None):
        """Register active medication under a specific patient name."""
        if not medicine_name or not isinstance(medicine_name, str):
            return
        
        med_clean = medicine_name.strip()
        classification = self.classify_medication(med_clean)

        med_entry = {
            "name": med_clean,
            "generic_name": generic_name,
            "strength": strength,
            "dosage": dosage,
            "class": classification.get("class", "Unclassified"),
            "confidence_status": classification.get("status", "UNCLASSIFIED"),
            "status": status,
            "added_at": datetime.now().isoformat()
        }
        
        pstore = self._get_patient_store(patient_name)
        existing_names = [m["name"].lower() for m in pstore.get("active_medications", [])]
        if med_clean.lower() not in existing_names:
            pstore.setdefault("active_medications", []).append(med_entry)
            slug, _ = normalize_patient_name(patient_name)
            self.sqlite_db.add_to_active_medications(
                slug, med_clean, generic_name=generic_name, strength=strength,
                dosage=dosage, med_class=classification.get("class")
            )
            self._save(target_slug=slug)

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
        slug, _ = normalize_patient_name(patient_name)
        self._save(target_slug=slug)

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
        
        slug, _ = normalize_patient_name(patient_name)
        self._save(target_slug=slug)

    # --- REQUIREMENT 3: Trusted Medication Knowledge Layer ---
    def classify_medication(self, medicine_name):
        """
        Multi-tier medication classification:
        Tier 0: Non-pharmaceutical classification (Nutritional Product / Dietary Supplement)
        Tier 1: Exact / Normalized / Trusted DB Match
        Tier 2: High-confidence strict fuzzy match (threshold >= 0.88)
        Tier 3: Pharmacological Suffix Match
        Tier 4: Unclassified (Strict zero-guessing policy)
        """
        if not medicine_name or not isinstance(medicine_name, str):
            return {"status": "UNCLASSIFIED", "message": "Medication could not be confidently classified."}

        # Check non-pharmaceutical items first (Nutritional formulas, dietary supplements)
        item_cat = classify_medical_item(medicine_name)
        if item_cat["is_nutritional"]:
            return {
                "status": "NUTRITIONAL_PRODUCT_MATCH",
                "medication": medicine_name,
                "generic_name": "Nutritional Formula / Dietary Feed",
                "class": "Nutritional Product / Infant Formula",
                "target_lab_keys": [],
                "item_type": "NUTRITIONAL_PRODUCT",
                "is_medicine": False,
                "is_nutritional": True,
                "rule_id": "NUT_ITEM_MATCH_001"
            }
        if item_cat["is_supplement"]:
            return {
                "status": "DIETARY_SUPPLEMENT_MATCH",
                "medication": medicine_name,
                "generic_name": "Dietary / Herbal Supplement",
                "class": "Dietary Supplement / Herbal Formulation",
                "target_lab_keys": [],
                "item_type": "DIETARY_SUPPLEMENT",
                "is_medicine": False,
                "is_supplement": True,
                "rule_id": "SUPP_ITEM_MATCH_001"
            }

        norm_info = normalize_medicine_name(medicine_name)
        clean_key = norm_info["canonical_key"]
        med_lower = medicine_name.lower().strip()
        first_word = clean_key.split()[0].strip(":,.-") if clean_key else med_lower.split()[0].strip(":,.-")

        # Tier 1: Exact / Normalized / Substring Database Match
        for db_key, db_info in TRUSTED_MEDICATION_DATABASE.items():
            if db_key == clean_key or db_key == med_lower or db_key == first_word or db_key in med_lower or (len(clean_key) >= 4 and clean_key in db_key):
                return {
                    "status": "TRUSTED_DB_MATCH",
                    "medication": db_info["primary_name"],
                    "generic_name": db_info.get("generic_name"),
                    "brand_name": db_info.get("brand_name"),
                    "class": db_info["class"],
                    "target_lab_keys": db_info["target_lab_keys"],
                    "ddinter_id": db_info.get("ddinter_id"),
                    "rule_id": db_info["rule_id"],
                    "dosage_form": norm_info.get("dosage_form") or db_info.get("dosage_form"),
                    "extracted_strength": norm_info.get("strength"),
                    "match_method": "EXACT_OR_NORMALIZED_MATCH",
                    "confidence": 1.0
                }

        # Tier 2: Strict High-Confidence Fuzzy Matching (threshold >= 0.88)
        best_match_key = None
        best_ratio = 0.0
        from difflib import SequenceMatcher
        for db_key in TRUSTED_MEDICATION_DATABASE.keys():
            ratio = SequenceMatcher(None, clean_key, db_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_key = db_key

        if best_ratio >= 0.88 and best_match_key:
            db_info = TRUSTED_MEDICATION_DATABASE[best_match_key]
            logger.info("Fuzzy matched '%s' to '%s' (similarity: %.2f)", medicine_name, best_match_key, best_ratio)
            return {
                "status": "TRUSTED_DB_MATCH",
                "medication": db_info["primary_name"],
                "generic_name": db_info.get("generic_name"),
                "brand_name": db_info.get("brand_name"),
                "class": db_info["class"],
                "target_lab_keys": db_info["target_lab_keys"],
                "ddinter_id": db_info.get("ddinter_id"),
                "rule_id": db_info["rule_id"],
                "dosage_form": norm_info.get("dosage_form") or db_info.get("dosage_form"),
                "extracted_strength": norm_info.get("strength"),
                "match_method": "STRICT_FUZZY_MATCH",
                "confidence": round(best_ratio, 2)
            }

        # Tier 3: Suffix Fallback Matcher
        for suffix_rule in PHARMACOLOGICAL_SUFFIX_MAP:
            for sfx in suffix_rule["suffixes"]:
                if med_lower.endswith(sfx) or first_word.endswith(sfx) or clean_key.endswith(sfx):
                    return {
                        "status": "SUFFIX_FALLBACK_MATCH",
                        "medication": medicine_name,
                        "class": suffix_rule["class"],
                        "target_lab_keys": [suffix_rule["lab_key"]],
                        "rule_id": suffix_rule["rule_id"],
                        "suffix": sfx,
                        "confidence": 0.85
                    }

        # Tier 4: Unknown Medication -> Do NOT Guess
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

