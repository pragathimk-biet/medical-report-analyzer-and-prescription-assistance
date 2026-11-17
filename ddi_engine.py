"""
ddi_engine.py — Drug-Drug Interaction (DDI) Safety Engine
Uses a built-in verified knowledge base. No external API calls needed.
Checks: New vs New, New vs Historical, Duplicate Ingredients.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TRUSTED MEDICATION DATABASE
# Format: {canonical_name: {ingredients: [...], category: str, brand_names: [...]}}
# ---------------------------------------------------------------------------
TRUSTED_MEDICATION_DATABASE = {
    # Antidiabetics
    "metformin": {
        "ingredients": ["metformin"],
        "category": "medicine",
        "brand_names": ["glucophage", "glycomet", "obimet", "formet", "gluconorm"],
        "class": "biguanide antidiabetic"
    },
    "glibenclamide": {
        "ingredients": ["glibenclamide"],
        "category": "medicine",
        "brand_names": ["daonil", "euglucon", "semi-daonil"],
        "class": "sulfonylurea antidiabetic"
    },
    "glipizide": {
        "ingredients": ["glipizide"],
        "category": "medicine",
        "brand_names": ["glucotrol", "glypride"],
        "class": "sulfonylurea antidiabetic"
    },
    "glimepiride": {
        "ingredients": ["glimepiride"],
        "category": "medicine",
        "brand_names": ["amaryl", "glimer", "glimpid"],
        "class": "sulfonylurea antidiabetic"
    },
    "sitagliptin": {
        "ingredients": ["sitagliptin"],
        "category": "medicine",
        "brand_names": ["januvia", "istavel"],
        "class": "dpp-4 inhibitor"
    },
    "empagliflozin": {
        "ingredients": ["empagliflozin"],
        "category": "medicine",
        "brand_names": ["jardiance", "empagard"],
        "class": "sglt2 inhibitor"
    },
    "insulin": {
        "ingredients": ["insulin"],
        "category": "medicine",
        "brand_names": ["humulin", "novolin", "lantus", "levemir", "novorapid", "humalog"],
        "class": "insulin"
    },
    # Antihypertensives
    "amlodipine": {
        "ingredients": ["amlodipine"],
        "category": "medicine",
        "brand_names": ["norvasc", "amlip", "amlopress", "stamlo", "amcard"],
        "class": "calcium channel blocker"
    },
    "lisinopril": {
        "ingredients": ["lisinopril"],
        "category": "medicine",
        "brand_names": ["prinivil", "zestril", "lisoril", "hipril"],
        "class": "ace inhibitor"
    },
    "enalapril": {
        "ingredients": ["enalapril"],
        "category": "medicine",
        "brand_names": ["vasotec", "envas", "enam"],
        "class": "ace inhibitor"
    },
    "losartan": {
        "ingredients": ["losartan"],
        "category": "medicine",
        "brand_names": ["cozaar", "losar", "losacar", "tozaar"],
        "class": "arb"
    },
    "telmisartan": {
        "ingredients": ["telmisartan"],
        "category": "medicine",
        "brand_names": ["micardis", "telma", "telmikind", "telpres"],
        "class": "arb"
    },
    "valsartan": {
        "ingredients": ["valsartan"],
        "category": "medicine",
        "brand_names": ["diovan", "valtan", "valsafe"],
        "class": "arb"
    },
    "atenolol": {
        "ingredients": ["atenolol"],
        "category": "medicine",
        "brand_names": ["tenormin", "aten", "betacard"],
        "class": "beta blocker"
    },
    "metoprolol": {
        "ingredients": ["metoprolol"],
        "category": "medicine",
        "brand_names": ["lopressor", "toprol", "metolar", "betaloc"],
        "class": "beta blocker"
    },
    "carvedilol": {
        "ingredients": ["carvedilol"],
        "category": "medicine",
        "brand_names": ["coreg", "carloc", "carca"],
        "class": "alpha-beta blocker"
    },
    "hydrochlorothiazide": {
        "ingredients": ["hydrochlorothiazide"],
        "category": "medicine",
        "brand_names": ["hydrodiuril", "hctz"],
        "class": "thiazide diuretic"
    },
    "furosemide": {
        "ingredients": ["furosemide"],
        "category": "medicine",
        "brand_names": ["lasix", "frusenex", "frusemide"],
        "class": "loop diuretic"
    },
    # Statins (Lipid-lowering)
    "atorvastatin": {
        "ingredients": ["atorvastatin"],
        "category": "medicine",
        "brand_names": ["lipitor", "atorva", "aztor", "storvas", "lipvas"],
        "class": "statin"
    },
    "rosuvastatin": {
        "ingredients": ["rosuvastatin"],
        "category": "medicine",
        "brand_names": ["crestor", "rozat", "rosuvas", "rozucor"],
        "class": "statin"
    },
    "simvastatin": {
        "ingredients": ["simvastatin"],
        "category": "medicine",
        "brand_names": ["zocor", "simvas", "simcard"],
        "class": "statin"
    },
    # Analgesics / Anti-inflammatories
    "paracetamol": {
        "ingredients": ["paracetamol", "acetaminophen"],
        "category": "medicine",
        "brand_names": ["crocin", "calpol", "dolo", "tylenol", "panadol", "fepanil"],
        "class": "analgesic antipyretic"
    },
    "ibuprofen": {
        "ingredients": ["ibuprofen"],
        "category": "medicine",
        "brand_names": ["brufen", "advil", "nurofen", "combiflam"],
        "class": "nsaid"
    },
    "diclofenac": {
        "ingredients": ["diclofenac"],
        "category": "medicine",
        "brand_names": ["voveran", "voltaren", "diclomax", "reactine"],
        "class": "nsaid"
    },
    "naproxen": {
        "ingredients": ["naproxen"],
        "category": "medicine",
        "brand_names": ["naprosyn", "aleve", "naprelan"],
        "class": "nsaid"
    },
    "aspirin": {
        "ingredients": ["aspirin", "acetylsalicylic acid"],
        "category": "medicine",
        "brand_names": ["disprin", "ecosprin", "micropirin", "cardioprin"],
        "class": "nsaid antiplatelet"
    },
    # Antibiotics
    "amoxicillin": {
        "ingredients": ["amoxicillin"],
        "category": "medicine",
        "brand_names": ["amoxil", "trimox", "moxikind", "novamox"],
        "class": "penicillin antibiotic"
    },
    "azithromycin": {
        "ingredients": ["azithromycin"],
        "category": "medicine",
        "brand_names": ["zithromax", "azee", "azithral", "zady"],
        "class": "macrolide antibiotic"
    },
    "ciprofloxacin": {
        "ingredients": ["ciprofloxacin"],
        "category": "medicine",
        "brand_names": ["cipro", "cifran", "ciplox", "ciprobid"],
        "class": "fluoroquinolone antibiotic"
    },
    "metronidazole": {
        "ingredients": ["metronidazole"],
        "category": "medicine",
        "brand_names": ["flagyl", "metrogyl", "metronidazole"],
        "class": "antibiotic antiprotozoal"
    },
    "doxycycline": {
        "ingredients": ["doxycycline"],
        "category": "medicine",
        "brand_names": ["vibramycin", "doxt", "doxrid"],
        "class": "tetracycline antibiotic"
    },
    # Thyroid
    "levothyroxine": {
        "ingredients": ["levothyroxine"],
        "category": "medicine",
        "brand_names": ["synthroid", "eltroxin", "thyronorm", "levothroid"],
        "class": "thyroid hormone"
    },
    # Antacids / GI
    "omeprazole": {
        "ingredients": ["omeprazole"],
        "category": "medicine",
        "brand_names": ["prilosec", "omez", "ocid", "omesec"],
        "class": "proton pump inhibitor"
    },
    "pantoprazole": {
        "ingredients": ["pantoprazole"],
        "category": "medicine",
        "brand_names": ["protonix", "pantop", "pan", "pantodac"],
        "class": "proton pump inhibitor"
    },
    "ranitidine": {
        "ingredients": ["ranitidine"],
        "category": "medicine",
        "brand_names": ["zantac", "rantac", "aciloc"],
        "class": "h2 blocker"
    },
    # Blood thinners
    "warfarin": {
        "ingredients": ["warfarin"],
        "category": "medicine",
        "brand_names": ["coumadin", "warfin", "sofarin"],
        "class": "anticoagulant"
    },
    "clopidogrel": {
        "ingredients": ["clopidogrel"],
        "category": "medicine",
        "brand_names": ["plavix", "clopivas", "deplatt"],
        "class": "antiplatelet"
    },
    # Supplements / Non-drugs
    "vitamin_c": {
        "ingredients": ["ascorbic acid", "vitamin c"],
        "category": "supplement",
        "brand_names": ["celin", "limcee", "redoxon"],
        "class": "vitamin supplement"
    },
    "vitamin_d_supplement": {
        "ingredients": ["cholecalciferol", "vitamin d3"],
        "category": "supplement",
        "brand_names": ["calcirol", "cholecalciferol", "dstol"],
        "class": "vitamin supplement"
    },
    "calcium_carbonate": {
        "ingredients": ["calcium carbonate"],
        "category": "supplement",
        "brand_names": ["shelcal", "calcimax", "calcium sandoz"],
        "class": "mineral supplement"
    },
    "iron_supplement": {
        "ingredients": ["ferrous sulfate", "ferrous fumarate", "iron"],
        "category": "supplement",
        "brand_names": ["fersolate", "orofer", "dexorange"],
        "class": "mineral supplement"
    },
    "folic_acid": {
        "ingredients": ["folic acid", "folate"],
        "category": "supplement",
        "brand_names": ["folvite", "folic acid"],
        "class": "vitamin supplement"
    },
}

# ---------------------------------------------------------------------------
# DDI Knowledge Base
# Format: {(drug_a, drug_b): {severity, mechanism, clinical_effect, management}}
# Keys are SORTED tuples of canonical ingredient names
# ---------------------------------------------------------------------------
DDI_KNOWLEDGE_BASE = {
    # Warfarin interactions (high risk)
    ("aspirin", "warfarin"): {
        "severity": "MAJOR",
        "mechanism": "Additive anticoagulant/antiplatelet effect",
        "clinical_effect": "Significantly increased bleeding risk including GI and intracranial bleeding",
        "management": "Avoid unless benefit clearly outweighs risk; monitor INR closely"
    },
    ("ibuprofen", "warfarin"): {
        "severity": "MAJOR",
        "mechanism": "NSAIDs displace warfarin from protein binding and inhibit platelet function",
        "clinical_effect": "Increased INR and serious bleeding risk",
        "management": "Avoid NSAIDs; use paracetamol for pain if anticoagulated"
    },
    ("diclofenac", "warfarin"): {
        "severity": "MAJOR",
        "mechanism": "NSAID potentiates anticoagulant effect",
        "clinical_effect": "Increased bleeding risk",
        "management": "Avoid combination; use alternative analgesic"
    },
    ("ciprofloxacin", "warfarin"): {
        "severity": "MAJOR",
        "mechanism": "Fluoroquinolones inhibit warfarin metabolism (CYP1A2)",
        "clinical_effect": "INR elevation, increased bleeding risk",
        "management": "Monitor INR closely; consider dose adjustment"
    },
    # Statin interactions
    ("atorvastatin", "clarithromycin"): {
        "severity": "MAJOR",
        "mechanism": "CYP3A4 inhibition increases statin levels",
        "clinical_effect": "Risk of myopathy and rhabdomyolysis",
        "management": "Temporarily suspend statin during antibiotic course"
    },
    # ACE inhibitor + ARB (double blockade)
    ("lisinopril", "losartan"): {
        "severity": "MAJOR",
        "mechanism": "Dual RAAS blockade",
        "clinical_effect": "Hypotension, hyperkalemia, acute kidney injury",
        "management": "Avoid combination; use single RAAS agent"
    },
    ("enalapril", "telmisartan"): {
        "severity": "MAJOR",
        "mechanism": "Dual RAAS blockade",
        "clinical_effect": "Hypotension, hyperkalemia, acute kidney injury",
        "management": "Avoid combination"
    },
    # ACE inhibitor + potassium
    ("lisinopril", "potassium"): {
        "severity": "MODERATE",
        "mechanism": "ACE inhibitors reduce potassium excretion",
        "clinical_effect": "Hyperkalemia risk",
        "management": "Monitor serum potassium regularly"
    },
    # NSAIDs + antihypertensives
    ("ibuprofen", "lisinopril"): {
        "severity": "MODERATE",
        "mechanism": "NSAIDs reduce prostaglandin synthesis, blunting antihypertensive effect",
        "clinical_effect": "Reduced blood pressure control; risk of acute kidney injury",
        "management": "Use paracetamol instead; monitor BP and renal function"
    },
    ("ibuprofen", "atenolol"): {
        "severity": "MODERATE",
        "mechanism": "NSAID reduces antihypertensive efficacy",
        "clinical_effect": "Reduced blood pressure control",
        "management": "Use alternative analgesic; monitor blood pressure"
    },
    ("diclofenac", "amlodipine"): {
        "severity": "MODERATE",
        "mechanism": "NSAIDs may antagonize antihypertensive effect",
        "clinical_effect": "Reduced blood pressure control",
        "management": "Monitor blood pressure; use shorter NSAID courses"
    },
    # Metformin interactions
    ("ciprofloxacin", "metformin"): {
        "severity": "MODERATE",
        "mechanism": "Fluoroquinolones may cause glucose dysregulation",
        "clinical_effect": "Hypoglycemia or hyperglycemia risk",
        "management": "Monitor blood glucose closely"
    },
    # Sulfonylurea + other antidiabetics
    ("glibenclamide", "metformin"): {
        "severity": "MINOR",
        "mechanism": "Additive glucose-lowering effect",
        "clinical_effect": "Hypoglycemia risk (usually managed)",
        "management": "Monitor blood glucose; adjust doses as needed"
    },
    ("glimepiride", "metformin"): {
        "severity": "MINOR",
        "mechanism": "Additive glucose-lowering effect",
        "clinical_effect": "Hypoglycemia risk",
        "management": "Monitor blood glucose"
    },
    # Aspirin + NSAIDs
    ("aspirin", "ibuprofen"): {
        "severity": "MODERATE",
        "mechanism": "Ibuprofen blocks aspirin's antiplatelet binding site",
        "clinical_effect": "Reduced cardioprotective effect of low-dose aspirin",
        "management": "Take aspirin at least 2 hours before ibuprofen"
    },
    ("aspirin", "diclofenac"): {
        "severity": "MODERATE",
        "mechanism": "Additive GI risk; potential antiplatelet interference",
        "clinical_effect": "Increased GI bleeding risk",
        "management": "Use gastroprotection (PPI); avoid unless necessary"
    },
    # Thyroid + calcium/iron
    ("calcium_carbonate", "levothyroxine"): {
        "severity": "MODERATE",
        "mechanism": "Calcium binds levothyroxine in GI tract, reducing absorption",
        "clinical_effect": "Reduced thyroid hormone absorption, hypothyroidism",
        "management": "Separate doses by at least 4 hours"
    },
    ("iron_supplement", "levothyroxine"): {
        "severity": "MODERATE",
        "mechanism": "Iron binds levothyroxine reducing absorption",
        "clinical_effect": "Reduced thyroid hormone levels",
        "management": "Separate doses by at least 4 hours"
    },
    # PPI + methotrexate
    ("omeprazole", "methotrexate"): {
        "severity": "MODERATE",
        "mechanism": "PPIs reduce renal clearance of methotrexate",
        "clinical_effect": "Methotrexate toxicity",
        "management": "Monitor methotrexate levels; consider dose adjustment"
    },
    # Ciprofloxacin + antacids
    ("calcium_carbonate", "ciprofloxacin"): {
        "severity": "MODERATE",
        "mechanism": "Calcium chelates fluoroquinolone, reducing absorption",
        "clinical_effect": "Reduced antibiotic efficacy",
        "management": "Separate doses by at least 2 hours"
    },
    # Beta blocker + insulin
    ("atenolol", "insulin"): {
        "severity": "MODERATE",
        "mechanism": "Beta blockers mask hypoglycemic symptoms (tachycardia)",
        "clinical_effect": "Prolonged hypoglycemia may go unrecognized",
        "management": "Monitor blood glucose closely; educate on non-adrenergic hypoglycemia signs"
    },
    ("metoprolol", "insulin"): {
        "severity": "MODERATE",
        "mechanism": "Beta blockers mask tachycardia sign of hypoglycemia",
        "clinical_effect": "Hypoglycemia may be prolonged and masked",
        "management": "Monitor blood glucose; watch for sweating as hypoglycemia sign"
    },
    # Duplicate statin warning
    ("atorvastatin", "rosuvastatin"): {
        "severity": "MAJOR",
        "mechanism": "Duplicate statin therapy",
        "clinical_effect": "Significantly increased risk of myopathy and rhabdomyolysis",
        "management": "Use only one statin; never combine statins"
    },
    ("atorvastatin", "simvastatin"): {
        "severity": "MAJOR",
        "mechanism": "Duplicate statin therapy",
        "clinical_effect": "Myopathy and rhabdomyolysis risk",
        "management": "Use only one statin"
    },
    # ACE + diuretic
    ("furosemide", "lisinopril"): {
        "severity": "MODERATE",
        "mechanism": "Excessive diuresis combined with RAAS inhibition",
        "clinical_effect": "First-dose hypotension, electrolyte imbalance",
        "management": "Start with low doses; monitor BP and electrolytes"
    },
}


# ---------------------------------------------------------------------------
# Normalize medicine name → canonical key
# ---------------------------------------------------------------------------
def normalize_medicine_name(name: str) -> Optional[str]:
    """Resolve brand or generic name to canonical database key."""
    name_lower = name.strip().lower()
    name_lower = re.sub(r'\b(tab|cap|tablet|capsule|syrup|injection|inj|sr|xl|er|mr|od|bd|tds|qid|mg|ml)\b', '', name_lower)
    name_lower = re.sub(r'[^a-z\s]', '', name_lower).strip()

    # Direct match
    if name_lower in TRUSTED_MEDICATION_DATABASE:
        return name_lower

    # Brand name search
    for canon, data in TRUSTED_MEDICATION_DATABASE.items():
        for brand in data.get("brand_names", []):
            if brand in name_lower or name_lower in brand:
                return canon

    # Partial match on canonical name
    for canon in TRUSTED_MEDICATION_DATABASE:
        if name_lower in canon or canon in name_lower:
            return canon

    return None


def get_ingredients(canonical_name: str) -> list[str]:
    """Get active ingredients for a canonical drug name."""
    if canonical_name in TRUSTED_MEDICATION_DATABASE:
        return TRUSTED_MEDICATION_DATABASE[canonical_name].get("ingredients", [canonical_name])
    return [canonical_name]


def get_category(canonical_name: str) -> str:
    """Get drug category: medicine, supplement, device, nutrition."""
    if canonical_name in TRUSTED_MEDICATION_DATABASE:
        return TRUSTED_MEDICATION_DATABASE[canonical_name].get("category", "medicine")
    return "medicine"


# ---------------------------------------------------------------------------
# DDI Lookup
# ---------------------------------------------------------------------------
def _lookup_ddi(ingredient_a: str, ingredient_b: str) -> Optional[dict]:
    """Look up DDI between two ingredients."""
    key = tuple(sorted([ingredient_a.lower(), ingredient_b.lower()]))
    return DDI_KNOWLEDGE_BASE.get(key)


def check_ddi(drug_list_a: list[str], drug_list_b: list[str] = None,
              label_a: str = "New Prescription", label_b: str = "Historical Medicines") -> list[dict]:
    """
    Check DDI between drugs.
    If drug_list_b is None, checks within drug_list_a (New vs New).
    Returns list of interaction findings.
    """
    interactions = []
    if drug_list_b is None:
        # New vs New — check all pairs within list_a
        pairs = []
        for i in range(len(drug_list_a)):
            for j in range(i + 1, len(drug_list_a)):
                pairs.append((drug_list_a[i], drug_list_a[j], label_a, label_a))
    else:
        # New vs Historical
        pairs = [(a, b, label_a, label_b) for a in drug_list_a for b in drug_list_b]

    for drug_a, drug_b, src_a, src_b in pairs:
        canon_a = normalize_medicine_name(drug_a)
        canon_b = normalize_medicine_name(drug_b)
        if not canon_a or not canon_b or canon_a == canon_b:
            continue

        # Only check medicines (not supplements)
        cat_a = get_category(canon_a)
        cat_b = get_category(canon_b)
        if cat_a != "medicine" or cat_b != "medicine":
            continue

        ingredients_a = get_ingredients(canon_a)
        ingredients_b = get_ingredients(canon_b)

        for ing_a in ingredients_a:
            for ing_b in ingredients_b:
                ddi = _lookup_ddi(ing_a, ing_b)
                if ddi:
                    interactions.append({
                        "drug_a": drug_a,
                        "drug_b": drug_b,
                        "canonical_a": canon_a,
                        "canonical_b": canon_b,
                        "ingredient_a": ing_a,
                        "ingredient_b": ing_b,
                        "source_a": src_a,
                        "source_b": src_b,
                        "severity": ddi["severity"],
                        "mechanism": ddi["mechanism"],
                        "clinical_effect": ddi["clinical_effect"],
                        "management": ddi["management"]
                    })

    return interactions


def check_duplicate_ingredients(drug_list: list[str]) -> list[dict]:
    """Detect duplicate active ingredients in a drug list."""
    ingredient_to_drugs = {}
    duplicates = []

    for drug in drug_list:
        canon = normalize_medicine_name(drug)
        if not canon:
            continue
        ingredients = get_ingredients(canon)
        for ing in ingredients:
            if ing not in ingredient_to_drugs:
                ingredient_to_drugs[ing] = []
            ingredient_to_drugs[ing].append(drug)

    for ing, drugs in ingredient_to_drugs.items():
        if len(drugs) > 1:
            duplicates.append({
                "ingredient": ing,
                "drugs": drugs,
                "severity": "WARNING",
                "note": f"Duplicate ingredient '{ing}' found in: {', '.join(drugs)}"
            })

    return duplicates


# ---------------------------------------------------------------------------
# STAGE 4E: Prescription vs Previous Labs Check
# ---------------------------------------------------------------------------
def check_prescription_vs_labs(medicines: list[str], lab_history: list[dict] = None) -> list[dict]:
    """
    Cross-checks newly prescribed medicines against historical lab results.
    E.g., Metformin + elevated Creatinine -> Lactic acidosis warning
          NSAIDs + elevated Creatinine -> Acute kidney injury warning
          ACEi/ARB + elevated Potassium -> Severe hyperkalemia warning
          Statins + elevated ALT/AST -> Hepatotoxicity / transaminitis warning
          Warfarin / Aspirin + low Platelets -> Major hemorrhage warning
    """
    alerts = []
    if not medicines or not lab_history:
        return alerts

    latest_labs = {}
    for lab in lab_history:
        test = str(lab.get("test_name", "")).lower()
        if test not in latest_labs:
            try:
                latest_labs[test] = {
                    "value": float(lab.get("value", 0)),
                    "status": str(lab.get("status", "")).upper(),
                    "unit": str(lab.get("unit", ""))
                }
            except Exception:
                latest_labs[test] = {
                    "value": str(lab.get("value", "")),
                    "status": str(lab.get("status", "")).upper(),
                    "unit": str(lab.get("unit", ""))
                }

    for med in medicines:
        canon = normalize_medicine_name(med)
        if not canon:
            continue

        # 1. Metformin + Elevated Creatinine
        if canon == "metformin":
            creat = latest_labs.get("creatinine")
            if creat and (creat["status"] in ("HIGH", "CRITICAL") or (isinstance(creat["value"], (int, float)) and creat["value"] >= 1.4)):
                alerts.append({
                    "medicine": med,
                    "canonical": canon,
                    "lab_test": "Creatinine",
                    "lab_value": f"{creat['value']} {creat['unit']}",
                    "severity": "MAJOR",
                    "mechanism": "Reduced renal clearance of metformin",
                    "clinical_effect": "Elevated risk of metformin-associated lactic acidosis (MALA)",
                    "management": "Evaluate renal function (eGFR). Metformin contraindicated if eGFR < 30 mL/min; adjust dose if eGFR 30–45 mL/min."
                })

        # 2. NSAIDs + Elevated Creatinine
        if canon in ("ibuprofen", "diclofenac", "naproxen", "aspirin"):
            creat = latest_labs.get("creatinine")
            if creat and (creat["status"] in ("HIGH", "CRITICAL") or (isinstance(creat["value"], (int, float)) and creat["value"] >= 1.3)):
                alerts.append({
                    "medicine": med,
                    "canonical": canon,
                    "lab_test": "Creatinine",
                    "lab_value": f"{creat['value']} {creat['unit']}",
                    "severity": "MAJOR",
                    "mechanism": "Inhibition of vasodilatory renal prostaglandins impairs glomerular perfusion",
                    "clinical_effect": "Acute kidney injury (AKI), fluid retention, worsening hypertension",
                    "management": "Avoid NSAIDs in renal impairment; use alternative non-nephrotoxic analgesics (e.g. Paracetamol)."
                })

        # 3. ACE inhibitors / ARBs + Elevated Potassium
        if canon in ("lisinopril", "enalapril", "losartan", "telmisartan", "valsartan"):
            pot = latest_labs.get("potassium")
            if pot and (pot["status"] in ("HIGH", "CRITICAL") or (isinstance(pot["value"], (int, float)) and pot["value"] >= 5.1)):
                alerts.append({
                    "medicine": med,
                    "canonical": canon,
                    "lab_test": "Potassium",
                    "lab_value": f"{pot['value']} {pot['unit']}",
                    "severity": "MAJOR",
                    "mechanism": "Suppression of aldosterone synthesis reduces renal potassium clearance",
                    "clinical_effect": "Severe hyperkalemia, cardiac conduction abnormalities, arrhythmias",
                    "management": "Recheck serum potassium; lower dose or temporarily hold; avoid concurrent potassium supplements."
                })

        # 4. Statins + Elevated Liver Enzymes (ALT / AST)
        if canon in ("atorvastatin", "rosuvastatin", "simvastatin"):
            alt = latest_labs.get("alt")
            ast = latest_labs.get("ast")
            if (alt and alt["status"] in ("HIGH", "CRITICAL")) or (ast and ast["status"] in ("HIGH", "CRITICAL")):
                elev_val = f"ALT: {alt['value']} {alt['unit']}" if alt else f"AST: {ast['value']} {ast['unit']}"
                alerts.append({
                    "medicine": med,
                    "canonical": canon,
                    "lab_test": "Liver Enzymes (ALT/AST)",
                    "lab_value": elev_val,
                    "severity": "MODERATE",
                    "mechanism": "Hepatic enzyme elevation and potential statin-induced transaminitis",
                    "clinical_effect": "Elevated transaminases; potential drug-induced liver injury",
                    "management": "Monitor hepatic panel; if transaminases exceed 3x upper limit of normal, hold statin until normalized."
                })

        # 5. Anticoagulants / Antiplatelets + Low Platelets
        if canon in ("warfarin", "clopidogrel", "aspirin"):
            plt = latest_labs.get("platelets")
            if plt and (plt["status"] in ("LOW", "CRITICAL") or (isinstance(plt["value"], (int, float)) and plt["value"] < 100)):
                alerts.append({
                    "medicine": med,
                    "canonical": canon,
                    "lab_test": "Platelet Count",
                    "lab_value": f"{plt['value']} {plt['unit']}",
                    "severity": "MAJOR",
                    "mechanism": "Impaired hemostasis due to combined antithrombotic therapy and thrombocytopenia",
                    "clinical_effect": "Significantly elevated hemorrhage risk, GI bleeding, hematoma",
                    "management": "Monitor CBC and coagulation profile; urgent clinical review of bleeding risk."
                })

    return alerts


# ---------------------------------------------------------------------------
# STAGE 4F: New Labs vs Active Medicines Check
# ---------------------------------------------------------------------------
def check_labs_vs_active_medicines(findings: list[dict], active_medicines: list[str]) -> list[dict]:
    """
    Checks if newly extracted abnormal laboratory findings may be adverse reactions
    to or relevant to previously confirmed active medications.
    """
    alerts = []
    if not findings or not active_medicines:
        return alerts

    active_canons = {}
    for m in active_medicines:
        c = normalize_medicine_name(m)
        if c:
            active_canons[c] = m

    for f in findings:
        test = str(f.get("test", "")).lower()
        status = str(f.get("status", "")).upper()
        if status in ("NORMAL", "UNKNOWN"):
            continue

        # Creatinine elevated + active NSAID or ACEi
        if test == "creatinine" and status in ("HIGH", "CRITICAL"):
            for med_canon, original_name in active_canons.items():
                if med_canon in ("ibuprofen", "diclofenac", "naproxen"):
                    alerts.append({
                        "finding": f"Creatinine elevated ({f.get('value')} {f.get('unit')})",
                        "active_medicine": original_name,
                        "severity": "MODERATE",
                        "note": "Elevated creatinine may reflect NSAID-induced renal impairment or decreased renal blood flow."
                    })
                elif med_canon in ("lisinopril", "enalapril", "losartan", "telmisartan"):
                    alerts.append({
                        "finding": f"Creatinine elevated ({f.get('value')} {f.get('unit')})",
                        "active_medicine": original_name,
                        "severity": "MODERATE",
                        "note": "Moderate rise in creatinine (<30%) can occur with ACEi/ARB therapy; monitor closely."
                    })

        # Potassium elevated + active ACEi/ARB
        if test == "potassium" and status in ("HIGH", "CRITICAL"):
            for med_canon, original_name in active_canons.items():
                if med_canon in ("lisinopril", "enalapril", "losartan", "telmisartan"):
                    alerts.append({
                        "finding": f"Potassium elevated ({f.get('value')} {f.get('unit')})",
                        "active_medicine": original_name,
                        "severity": "MAJOR",
                        "note": "Hyperkalemia may be drug-induced by active ACE inhibitor/ARB therapy."
                    })

        # Liver enzymes (ALT / AST) elevated + active Statin
        if test in ("alt", "ast") and status in ("HIGH", "CRITICAL"):
            for med_canon, original_name in active_canons.items():
                if med_canon in ("atorvastatin", "rosuvastatin", "simvastatin"):
                    alerts.append({
                        "finding": f"{f.get('test', '').upper()} elevated ({f.get('value')} {f.get('unit')})",
                        "active_medicine": original_name,
                        "severity": "MODERATE",
                        "note": "Transaminase elevation may be related to active statin therapy."
                    })

    return alerts


def run_full_ddi_check(new_medicines: list[str], historical_medicines: list[str] = None, lab_history: list[dict] = None) -> dict:
    """Run all DDI checks and return a structured report."""
    report = {
        "new_vs_new": [],
        "new_vs_historical": [],
        "duplicate_ingredients": [],
        "prescription_vs_labs": [],
        "total_interactions": 0,
        "severity_summary": {"MAJOR": 0, "MODERATE": 0, "MINOR": 0, "WARNING": 0}
    }

    # New vs New
    if len(new_medicines) > 1:
        report["new_vs_new"] = check_ddi(new_medicines, label_a="New Prescription")

    # New vs Historical
    if historical_medicines and len(historical_medicines) > 0:
        report["new_vs_historical"] = check_ddi(
            new_medicines, historical_medicines,
            label_a="New Prescription", label_b="Historical Medicines"
        )

    # Duplicate Ingredients (across new + historical)
    all_meds = new_medicines + (historical_medicines or [])
    report["duplicate_ingredients"] = check_duplicate_ingredients(all_meds)

    # Prescription vs Previous Labs
    if lab_history:
        report["prescription_vs_labs"] = check_prescription_vs_labs(new_medicines, lab_history)

    # Tally
    for interaction in report["new_vs_new"] + report["new_vs_historical"]:
        sev = interaction.get("severity", "MINOR")
        report["severity_summary"][sev] = report["severity_summary"].get(sev, 0) + 1
        report["total_interactions"] += 1

    for alert in report["prescription_vs_labs"]:
        sev = alert.get("severity", "MODERATE")
        report["severity_summary"][sev] = report["severity_summary"].get(sev, 0) + 1
        report["total_interactions"] += 1

    for dup in report["duplicate_ingredients"]:
        report["severity_summary"]["WARNING"] = report["severity_summary"].get("WARNING", 0) + 1

    report["has_ddi"] = (report["total_interactions"] > 0 or len(report["duplicate_ingredients"]) > 0)
    report["interactions"] = [
        {
            "drug1": i.get("drug_a", ""),
            "drug2": i.get("drug_b", ""),
            "severity": i.get("severity", "MINOR"),
            "effect": i.get("clinical_effect", ""),
            "management": i.get("management", "")
        }
        for i in report["new_vs_new"] + report["new_vs_historical"]
    ]

    return report
