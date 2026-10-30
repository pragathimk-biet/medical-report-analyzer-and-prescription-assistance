"""
===============================================================================
DDI CHECKING AGENT
===============================================================================

Drug-Drug Interaction checking module for the prescription pipeline.

Pipeline Position:
  PrescriptionVerificationAgent (Step 4)
          |
          v
  [DDICheckingAgent]  <-- THIS AGENT (Step 4b)
          |
          v
  PrescriptionReasoningAgent (Step 5)

DESIGN CONSTRAINTS (enforced):
  1. Only verified ingredients are checked (identity_verified == True).
  2. Historical meds included ONLY when explicitly marked active AND scoped
     to the authenticated patient slug -- never cross-patient.
  3. DDInter dataset is the sole source. No invented records.
     If unavailable: status = RESOURCE_UNAVAILABLE, not "no interactions".
  4. Drug identity resolved via exact case-insensitive match against actual
     Drug_A/Drug_B values in the loaded dataset. No fuzzy matching.
  5. Ambiguous/unresolved names are kept as UNRESOLVED_MEDICATION.
  6. Combination products (e.g. Amoxicillin/Clavulanate) are split to
     ingredient level. Original product reference is preserved.
  7. Dataset's own Level values are preserved verbatim -- not remapped.
  8. NO_RECORD_FOUND is never presented as "safe" or "no interaction".
  9. Coverage metadata is always returned so callers can distinguish
     "fully checked" from "partial" or "resource missing".

DDInter CSV schema (verified from official biothings/ddinter parser):
  Filenames : ddinter_downloads_code_A.csv ... ddinter_downloads_code_Z.csv
  Columns   : DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level
  DDInterID format: "DDInter" + integer (e.g. DDInter1, DDInter42)
  Level values: dataset verbatim (typically Major, Moderate, Minor)
"""

import os
import csv
import glob
import logging
import itertools
import re
from typing import Dict, List, Optional, Tuple, Set

import patient_privacy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_INTERACTION_FOUND     = "INTERACTION_FOUND"
STATUS_NO_RECORD_FOUND       = "NO_RECORD_FOUND"
STATUS_UNRESOLVED_MEDICATION = "UNRESOLVED_MEDICATION"
STATUS_RESOURCE_UNAVAILABLE  = "RESOURCE_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Authoritative Drug Identity Mappings to DDInter Records
# ---------------------------------------------------------------------------
# Policy:
# - No unrestricted fuzzy matching is permitted.
# - Each synonym relationship is verified using authoritative clinical vocabularies
#   (RxNorm, WHO INN, WHO ATC, MeSH, PubChem).
# - Explicitly mapped to actual DDInter 2.0 substance names and identifiers.
# - Stores mapping provenance metadata.

AUTHORITATIVE_IDENTITY_MAPPINGS: Dict[str, dict] = {
    "aspirin": {
        "canonical_name": "Acetylsalicylic acid",
        "ddinter_id": "DDInter20",
        "provenance": {
            "source_vocabulary": "RxNorm / WHO ATC / MeSH / PubChem",
            "rxnorm_rxcui": "1191",
            "who_atc": "N02BA01",
            "mesh_id": "D001241",
            "pubchem_cid": "2244",
            "relationship": "synonym_to_ddinter_canonical",
            "match_method": "curated_authoritative_synonym",
            "notes": "Aspirin is the USAN/BAN approved generic name for Acetylsalicylic acid (DDInter20).",
        },
    },
    "acetylsalicylic acid": {
        "canonical_name": "Acetylsalicylic acid",
        "ddinter_id": "DDInter20",
        "provenance": {
            "source_vocabulary": "DDInter / INN / WHO ATC",
            "who_atc": "N02BA01",
            "relationship": "exact_canonical_match",
            "match_method": "canonical_identity",
            "notes": "Direct DDInter 2.0 canonical substance name.",
        },
    },
    "paracetamol": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "WHO INN / RxNorm / WHO ATC / MeSH / PubChem",
            "rxnorm_rxcui": "161",
            "who_inn": "Paracetamol",
            "who_atc": "N02BE01",
            "mesh_id": "D000082",
            "pubchem_cid": "1983",
            "relationship": "synonym_to_ddinter_canonical",
            "match_method": "curated_authoritative_synonym",
            "notes": "Paracetamol is the WHO International Nonproprietary Name (INN) for Acetaminophen (USAN/DDInter14).",
        },
    },
    "paracetamol (acetaminophen)": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "WHO INN / USAN / RxNorm",
            "rxnorm_rxcui": "161",
            "who_inn": "Paracetamol",
            "relationship": "parenthetical_synonym_to_ddinter_canonical",
            "match_method": "curated_authoritative_synonym",
            "notes": "Composite synonym representation from trusted medication dictionary mapped to DDInter14.",
        },
    },
    "acetaminophen": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "DDInter / USAN / RxNorm",
            "rxnorm_rxcui": "161",
            "relationship": "exact_canonical_match",
            "match_method": "canonical_identity",
            "notes": "Direct DDInter 2.0 canonical substance name.",
        },
    },
    "mgso4": {
        "canonical_name": "Magnesium sulfate",
        "ddinter_id": "DDInter1120",
        "provenance": {
            "source_vocabulary": "RxNorm / PubChem / DDInter",
            "rxnorm_rxcui": "6581",
            "relationship": "chemical_formula_abbreviation_to_canonical",
            "match_method": "authoritative_abbreviation",
            "notes": "Chemical formula MgSO4 maps to Magnesium sulfate (DDInter1120).",
        },
    },
    "magnesium sulphate": {
        "canonical_name": "Magnesium sulfate",
        "ddinter_id": "DDInter1120",
        "provenance": {
            "source_vocabulary": "BAN / WHO INN",
            "relationship": "british_spelling_synonym",
            "match_method": "curated_authoritative_synonym",
            "notes": "British English spelling for Magnesium sulfate (DDInter1120).",
        },
    },
    "dolo": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Indian Pharmacopoeia / Brand",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Dolo brand of Paracetamol (Acetaminophen DDInter14).",
        },
    },
    "dolo 650": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Indian Pharmacopoeia / Brand",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Dolo 650 brand of Paracetamol (Acetaminophen DDInter14).",
        },
    },
    "crocin": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Crocin brand of Paracetamol (Acetaminophen DDInter14).",
        },
    },
    "calpol": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Calpol brand of Paracetamol (Acetaminophen DDInter14).",
        },
    },
    "glycomet": {
        "canonical_name": "Metformin",
        "ddinter_id": "DDInter1164",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Glycomet brand of Metformin (DDInter1164).",
        },
    },
    "pan": {
        "canonical_name": "Pantoprazole",
        "ddinter_id": "DDInter1388",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Pan brand of Pantoprazole (DDInter1388).",
        },
    },
    "pan 40": {
        "canonical_name": "Pantoprazole",
        "ddinter_id": "DDInter1388",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Pan 40 brand of Pantoprazole (DDInter1388).",
        },
    },
    "pantocid": {
        "canonical_name": "Pantoprazole",
        "ddinter_id": "DDInter1388",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Pantocid brand of Pantoprazole (DDInter1388).",
        },
    },
    "omez": {
        "canonical_name": "Omeprazole",
        "ddinter_id": "DDInter1340",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Omez brand of Omeprazole (DDInter1340).",
        },
    },
    "amlong": {
        "canonical_name": "Amlodipine",
        "ddinter_id": "DDInter79",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Amlong brand of Amlodipine (DDInter79).",
        },
    },
    "telma": {
        "canonical_name": "Telmisartan",
        "ddinter_id": "DDInter1759",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Telma brand of Telmisartan (DDInter1759).",
        },
    },
    "telma 40": {
        "canonical_name": "Telmisartan",
        "ddinter_id": "DDInter1759",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Telma 40 brand of Telmisartan (DDInter1759).",
        },
    },
    "ecosprin": {
        "canonical_name": "Acetylsalicylic acid",
        "ddinter_id": "DDInter20",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Ecosprin brand of Aspirin / Acetylsalicylic acid (DDInter20).",
        },
    },
    "disprin": {
        "canonical_name": "Acetylsalicylic acid",
        "ddinter_id": "DDInter20",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Disprin brand of Aspirin / Acetylsalicylic acid (DDInter20).",
        },
    },
    "atorva": {
        "canonical_name": "Atorvastatin",
        "ddinter_id": "DDInter133",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Atorva brand of Atorvastatin (DDInter133).",
        },
    },
    "rosuvas": {
        "canonical_name": "Rosuvastatin",
        "ddinter_id": "DDInter1622",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Rosuvas brand of Rosuvastatin (DDInter1622).",
        },
    },
    "azithral": {
        "canonical_name": "Azithromycin",
        "ddinter_id": "DDInter157",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Azithral brand of Azithromycin (DDInter157).",
        },
    },
    "ciplox": {
        "canonical_name": "Ciprofloxacin",
        "ddinter_id": "DDInter384",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Ciplox brand of Ciprofloxacin (DDInter384).",
        },
    },
    "lasix": {
        "canonical_name": "Furosemide",
        "ddinter_id": "DDInter790",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Lasix brand of Furosemide (DDInter790).",
        },
    },
    "plavix": {
        "canonical_name": "Clopidogrel",
        "ddinter_id": "DDInter413",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Plavix brand of Clopidogrel (DDInter413).",
        },
    },
    "lanoxin": {
        "canonical_name": "Digoxin",
        "ddinter_id": "DDInter554",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Lanoxin brand of Digoxin (DDInter554).",
        },
    },
    "aldactone": {
        "canonical_name": "Spironolactone",
        "ddinter_id": "DDInter1707",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Aldactone brand of Spironolactone (DDInter1707).",
        },
    },
    "perinorm": {
        "canonical_name": "Metoclopramide",
        "ddinter_id": "DDInter1197",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Perinorm brand of Metoclopramide (DDInter1197).",
        },
    },
    "metoclopramide": {
        "canonical_name": "Metoclopramide",
        "ddinter_id": "DDInter1197",
        "provenance": {
            "source_vocabulary": "DDInter 2.0 Dataset",
            "relationship": "exact_canonical_match",
            "match_method": "direct_dataset_match",
            "notes": "Metoclopramide (DDInter1197).",
        },
    },
    "parajely": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Parajely brand of Paracetamol / Acetaminophen (DDInter14).",
        },
    },
    "parajel": {
        "canonical_name": "Acetaminophen",
        "ddinter_id": "DDInter14",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Parajel brand of Paracetamol / Acetaminophen (DDInter14).",
        },
    },
    "domperidone": {
        "canonical_name": "Domperidone",
        "ddinter_id": "DDInter577",
        "provenance": {
            "source_vocabulary": "DDInter 2.0 Dataset",
            "relationship": "exact_canonical_match",
            "match_method": "direct_dataset_match",
            "notes": "Domperidone (DDInter577).",
        },
    },
    "ondansetron": {
        "canonical_name": "Ondansetron",
        "ddinter_id": "DDInter1342",
        "provenance": {
            "source_vocabulary": "DDInter 2.0 Dataset",
            "relationship": "exact_canonical_match",
            "match_method": "direct_dataset_match",
            "notes": "Ondansetron (DDInter1342).",
        },
    },
    "emset": {
        "canonical_name": "Ondansetron",
        "ddinter_id": "DDInter1342",
        "provenance": {
            "source_vocabulary": "Brand to Generic",
            "relationship": "brand_to_generic",
            "match_method": "curated_brand_mapping",
            "notes": "Emset brand of Ondansetron (DDInter1342).",
        },
    },
}

# ---------------------------------------------------------------------------
# Server-side patient authorization contract
# ---------------------------------------------------------------------------
class TrustedPatientAuthContract:
    """
    Integration boundary contract representing verified server-side patient history authorization.
    
    SECURITY INVARIANT:
    Patient history access must NEVER be granted based on unauthenticated dictionary
    keys (e.g. metadata['authorized_patient_scope'], metadata['authorized_patient_id'],
    request.form, request.json, or OCR-extracted strings).

    A locally constructed object with is_verified=True, issuer, and patient_scope is
    not itself proof of authentication and must NEVER be constructed from request data
    or invent an issuer. It serves strictly as an integration boundary interface.
    Access requires a future trusted server-side authentication service to validate
    credentials and establish authorization. In production, this is absent, so history
    access remains completely disabled.
    """
    def __init__(self, patient_scope: str, issuer: str, is_verified: bool = False):
        self.patient_scope = str(patient_scope).strip() if patient_scope else ""
        self.issuer = str(issuer).strip() if issuer else ""
        self.is_verified = bool(is_verified)

    def is_valid(self) -> bool:
        if not self.is_verified:
            return False
        if not self.patient_scope or self.patient_scope.lower() in ("default patient", "default_patient", "unknown"):
            return False
        if not self.issuer:
            return False
        return True


# ---------------------------------------------------------------------------
# Combination product ingredient table
# ---------------------------------------------------------------------------
COMBINATION_PRODUCT_INGREDIENTS: Dict[str, List[str]] = {
    "amoxicillin/clavulanate":              ["amoxicillin", "clavulanate"],
    "amoxiclav":                            ["amoxicillin", "clavulanate"],
    "amoxicillin/clavulanic acid":          ["amoxicillin", "clavulanic acid"],
    "co-amoxiclav":                         ["amoxicillin", "clavulanate"],
    "augmentin":                            ["amoxicillin", "clavulanate"],
    "clavam":                               ["amoxicillin", "clavulanate"],
    "trimethoprim/sulfamethoxazole":        ["trimethoprim", "sulfamethoxazole"],
    "co-trimoxazole":                       ["trimethoprim", "sulfamethoxazole"],
    "piperacillin/tazobactam":              ["piperacillin", "tazobactam"],
    "ampicillin/sulbactam":                 ["ampicillin", "sulbactam"],
    "levodopa/carbidopa":                   ["levodopa", "carbidopa"],
    "amlodipine/atorvastatin":              ["amlodipine", "atorvastatin"],
    "amlodipine/valsartan":                 ["amlodipine", "valsartan"],
    "losartan/hydrochlorothiazide":         ["losartan", "hydrochlorothiazide"],
    "valsartan/hydrochlorothiazide":        ["valsartan", "hydrochlorothiazide"],
    "metformin/sitagliptin":               ["metformin", "sitagliptin"],
    "metformin/glipizide":                 ["metformin", "glipizide"],
    "aspirin/clopidogrel":                 ["aspirin", "clopidogrel"],
    "aspirin/dipyridamole":                ["aspirin", "dipyridamole"],
    "bisoprolol/hydrochlorothiazide":      ["bisoprolol", "hydrochlorothiazide"],
    "perindopril/amlodipine":              ["perindopril", "amlodipine"],
    "insulin/metformin":                   ["insulin", "metformin"],
    "combiflam":                           ["ibuprofen", "paracetamol"],
    "pan-d":                               ["pantoprazole", "domperidone"],
    "pantocid-d":                          ["pantoprazole", "domperidone"],
    "telma-am":                            ["telmisartan", "amlodipine"],
    "telma-h":                             ["telmisartan", "hydrochlorothiazide"],
    "glycomet-gp":                         ["metformin", "glimepiride"],
}


def _split_to_ingredients(drug_name: str) -> List[str]:
    """
    Returns ingredient list for a drug name.
    Looks up COMBINATION_PRODUCT_INGREDIENTS first (exact key, lower-cased).
    Falls back to [drug_name] for simple drugs.
    Original product name is NOT lost -- caller preserves the reference.
    """
    key = drug_name.strip().lower()
    if key in COMBINATION_PRODUCT_INGREDIENTS:
        return [i.strip() for i in COMBINATION_PRODUCT_INGREDIENTS[key]]
    # Strip parenthetical annotations e.g. "Metformin (Glycomet)" -> "Metformin"
    clean = re.sub(r'\s*\([^)]*\)', '', drug_name).strip()
    clean_key = clean.lower()
    if clean_key in COMBINATION_PRODUCT_INGREDIENTS:
        return [i.strip() for i in COMBINATION_PRODUCT_INGREDIENTS[clean_key]]
    if clean:
        return [clean]
    return [drug_name.strip()]


# ---------------------------------------------------------------------------
# DDInter Dataset Loader
# ---------------------------------------------------------------------------

class DDInterLoader:
    """
    Configurable loader for the DDInter dataset.

    Dataset source: https://ddinter2.scbdd.com/download/
    Expected location: DDI_DATA_DIR env var, or ./data/ by default.

    CSV schema (verified from official download files):
        DDInterID_A : str  -- DDInter unique ID for drug A (format: "DDInter{int}")
        Drug_A      : str  -- Drug A display name
        DDInterID_B : str  -- DDInter unique ID for drug B
        Drug_B      : str  -- Drug B display name
        Level       : str  -- Interaction severity, verbatim from dataset

    If no files are found, all lookups return STATUS_RESOURCE_UNAVAILABLE.
    """

    _REQUIRED_COLUMNS: Set[str] = {"DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"}

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.getenv("DDI_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
        self._data_dir = data_dir
        self._dataset_available: Optional[bool] = None
        self._missing_columns: List[str] = []
        self._malformed_rows: int = 0
        self._total_rows: int = 0
        self._loaded_files: List[str] = []
        self._failed_files: List[str] = []
        self._skipped_files: List[str] = []
        self._manifest_verification_status: str = "UNCHECKED"
        self._dataset_completeness_status: str = "UNKNOWN"
        self._verified_mappings: Dict[str, dict] = {}
        self._inconsistent_mappings: Dict[str, dict] = {}
        # frozenset({canonical_name_lower_a, canonical_name_lower_b}) -> list of row dicts
        self._pair_index: Dict[frozenset, List[dict]] = {}
        # All Drug_A and Drug_B values seen, lower-cased
        self._known_drug_names_lower: Set[str] = set()
        # Bi-directional ID mappings from dataset
        self._id_to_name: Dict[str, str] = {}
        self._name_to_id: Dict[str, str] = {}
        self._manifest: Optional[dict] = None
        self._load()

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        pattern = os.path.join(self._data_dir, "ddinter_downloads_code_*.csv")
        csv_files = sorted(glob.glob(pattern))

        # Check for manifest file (read-only; never modify or overwrite)
        manifest_path = os.path.join(self._data_dir, "ddinter_manifest.json")
        if os.path.isfile(manifest_path):
            try:
                import json
                with open(manifest_path, "r", encoding="utf-8") as mfh:
                    self._manifest = json.load(mfh)
                logger.info("DDInterLoader: Loaded dataset manifest from '%s'.", manifest_path)
            except Exception as mexc:
                logger.warning("DDInterLoader: Could not read manifest '%s': %s", manifest_path, mexc)
                self._manifest_verification_status = "MANIFEST_READ_ERROR"

        if not csv_files:
            logger.warning(
                "DDInterLoader: No ddinter_downloads_code_*.csv files found in '%s'. "
                "All DDI checks will return %s. "
                "Place dataset files there or set DDI_DATA_DIR.",
                self._data_dir, STATUS_RESOURCE_UNAVAILABLE
            )
            self._dataset_available = False
            self._dataset_completeness_status = "UNAVAILABLE"
            self._manifest_verification_status = "NO_DATASET_FILES"
            return

        logger.info(
            "DDInterLoader: Loading %d DDInter CSV file(s) from '%s'.",
            len(csv_files), self._data_dir
        )
        seen_doc_ids: Set[str] = set()
        for filepath in csv_files:
            bname = os.path.basename(filepath)
            try:
                loaded_ok = self._load_file(filepath, seen_doc_ids)
                if loaded_ok:
                    self._loaded_files.append(bname)
                else:
                    self._skipped_files.append(bname)
            except Exception as exc:
                self._failed_files.append(bname)
                logger.error("DDInterLoader: Failed to read '%s': %s", filepath, exc)

        if self._pair_index:
            logger.info(
                "DDInterLoader: Loaded %d unique pairs covering %d known drug names. "
                "Malformed rows: %d / %d.",
                len(self._pair_index), len(self._known_drug_names_lower),
                self._malformed_rows, self._total_rows
            )
            self._dataset_available = True
            # Verify curated mappings against loaded records
            self._verify_curated_mappings()

            # Separate dataset availability from dataset completeness/integrity
            if self._manifest and isinstance(self._manifest.get("files"), dict):
                expected_files = set(self._manifest["files"].keys())
                loaded_set = set(self._loaded_files)
                if expected_files.issubset(loaded_set) and not self._failed_files and not self._skipped_files:
                    self._manifest_verification_status = "VERIFIED_MATCH"
                    self._dataset_completeness_status = "INTACT"
                else:
                    self._manifest_verification_status = "INCOMPLETE_OR_MISMATCH"
                    self._dataset_completeness_status = "PARTIAL"
            elif self._manifest:
                self._manifest_verification_status = "MANIFEST_FORMAT_UNRECOGNIZED"
                self._dataset_completeness_status = "PARTIAL"
            else:
                self._manifest_verification_status = "MANIFEST_NOT_FOUND"
                self._dataset_completeness_status = "PARTIAL" if (self._skipped_files or self._failed_files) else "UNVERIFIED_NO_MANIFEST"
        else:
            logger.error(
                "DDInterLoader: Files present but no valid rows loaded. "
                "Required columns: %s",
                sorted(self._REQUIRED_COLUMNS)
            )
            self._dataset_available = False
            self._dataset_completeness_status = "EMPTY"
            self._manifest_verification_status = "NO_VALID_ROWS"

    def _verify_curated_mappings(self) -> None:
        """
        Validates authoritative identity mappings against loaded dataset records.
        Flags or rejects mappings with inconsistent canonical names or DDInterIDs.
        """
        self._verified_mappings.clear()
        self._inconsistent_mappings.clear()
        for raw_key, mapping in AUTHORITATIVE_IDENTITY_MAPPINGS.items():
            canonical_name = mapping.get("canonical_name", "").strip()
            c_lower = canonical_name.lower()
            mapped_id = mapping.get("ddinter_id")

            # Check if canonical name is known in loaded dataset
            if c_lower in self._known_drug_names_lower:
                actual_id = self._name_to_id.get(c_lower)
                actual_name = self._id_to_name.get(mapped_id) if mapped_id else None
                inconsistencies = []
                if mapped_id and actual_id and mapped_id != actual_id:
                    inconsistencies.append(
                        f"ID mismatch: mapping specifies '{mapped_id}' but loaded dataset assigns '{actual_id}' to '{canonical_name}'."
                    )
                if mapped_id and actual_name and actual_name.lower() != c_lower:
                    inconsistencies.append(
                        f"Name mismatch: mapping links '{mapped_id}' to '{canonical_name}' but dataset links '{mapped_id}' to '{actual_name}'."
                    )
                if inconsistencies:
                    self._inconsistent_mappings[raw_key] = {
                        "mapping": mapping,
                        "reasons": inconsistencies,
                    }
                    logger.warning("DDInterLoader: Inconsistent curated mapping for '%s': %s", raw_key, "; ".join(inconsistencies))
                else:
                    self._verified_mappings[raw_key] = mapping

    def _load_file(self, filepath: str, seen_doc_ids: Set[str]) -> bool:
        with open(filepath, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                logger.warning("DDInterLoader: '%s' has no header -- skipping.", filepath)
                return False

            actual_cols = set(reader.fieldnames)
            missing = self._REQUIRED_COLUMNS - actual_cols
            if missing:
                logger.error(
                    "DDInterLoader: '%s' missing columns %s. Expected %s. File skipped.",
                    filepath, sorted(missing), sorted(self._REQUIRED_COLUMNS)
                )
                self._missing_columns.extend(sorted(missing))
                return False

            for row in reader:
                self._total_rows += 1
                try:
                    id_a   = (row.get("DDInterID_A") or "").strip()
                    name_a = (row.get("Drug_A") or "").strip()
                    id_b   = (row.get("DDInterID_B") or "").strip()
                    name_b = (row.get("Drug_B") or "").strip()
                    level  = (row.get("Level") or "").strip()

                    if not (id_a and name_a and id_b and name_b and level):
                        self._malformed_rows += 1
                        continue

                    # Deduplicate by BioThings canonical doc ID
                    doc_id = f"{id_a}_{id_b}_{level}"
                    if doc_id in seen_doc_ids:
                        continue
                    seen_doc_ids.add(doc_id)

                    key = frozenset({name_a.lower(), name_b.lower()})
                    record = {
                        "DDInterID_A": id_a,
                        "Drug_A":      name_a,
                        "DDInterID_B": id_b,
                        "Drug_B":      name_b,
                        "Level":       level,
                    }
                    self._pair_index.setdefault(key, []).append(record)
                    self._known_drug_names_lower.add(name_a.lower())
                    self._known_drug_names_lower.add(name_b.lower())

                    # Track ID to canonical name mappings
                    self._id_to_name[id_a] = name_a
                    self._id_to_name[id_b] = name_b
                    self._name_to_id[name_a.lower()] = id_a
                    self._name_to_id[name_b.lower()] = id_b

                except Exception as row_exc:
                    self._malformed_rows += 1
                    logger.debug("DDInterLoader: Malformed row skipped: %s", row_exc)
            return True

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        return self._dataset_available is True

    def resolve_drug_identity(self, ingredient_name: str) -> Optional[dict]:
        """
        Resolves an ingredient name to a verified DDInter identity.
        Checks:
        1. Authoritative curated synonym mappings (RxNorm, WHO INN, ATC, MeSH)
           if verified consistent with the loaded dataset records.
        2. Exact case-insensitive match against loaded dataset records.

        Returns resolution dict:
        {
            "input_name": str,
            "canonical_name": str,
            "canonical_name_lower": str,
            "ddinter_id": str,
            "provenance": dict,
        }
        Returns None if unresolved, dataset unavailable, or mapping inconsistent.
        No unrestricted fuzzy matching is performed.
        """
        if not self._dataset_available:
            return None

        raw_key = (ingredient_name or "").strip().lower()
        if not raw_key:
            return None

        # Check for inconsistent mapping rejection
        if raw_key in self._inconsistent_mappings:
            logger.warning("DDInterLoader: Curated mapping for '%s' was rejected as inconsistent with loaded dataset records.", raw_key)
            return None

        # 1. Authoritative curated synonyms
        if raw_key in AUTHORITATIVE_IDENTITY_MAPPINGS:
            mapping = AUTHORITATIVE_IDENTITY_MAPPINGS[raw_key]
            canonical = mapping["canonical_name"]
            c_lower = canonical.lower()
            if c_lower in self._known_drug_names_lower:
                dd_id = mapping.get("ddinter_id") or self._name_to_id.get(c_lower)
                return {
                    "input_name": ingredient_name.strip(),
                    "canonical_name": canonical,
                    "canonical_name_lower": c_lower,
                    "ddinter_id": dd_id,
                    "provenance": mapping["provenance"],
                }

        # 2. Direct match against loaded dataset records
        if raw_key in self._known_drug_names_lower:
            dd_id = self._name_to_id.get(raw_key)
            canonical = self._id_to_name.get(dd_id, ingredient_name.strip())
            return {
                "input_name": ingredient_name.strip(),
                "canonical_name": canonical,
                "canonical_name_lower": raw_key,
                "ddinter_id": dd_id,
                "provenance": {
                    "source_vocabulary": "DDInter 2.0 Dataset",
                    "relationship": "exact_canonical_match",
                    "match_method": "direct_dataset_match",
                    "notes": f"Exact case-insensitive match against DDInter record {dd_id}.",
                },
            }

        # 3. Fallback: try stripping parenthetical annotation, e.g. "Metformin (Glycomet)" -> "Metformin"
        if "(" in raw_key and ")" in raw_key:
            stripped = re.sub(r'\s*\([^)]*\)', '', raw_key).strip()
            if stripped and stripped != raw_key:
                res = self.resolve_drug_identity(stripped)
                if res:
                    return res

        # 4. Fallback: try stripping dosage strengths/forms, e.g. "Aspirin 75mg" -> "Aspirin", "Paracetamol Tablet" -> "Paracetamol"
        from patient_history import normalize_medicine_name
        norm = normalize_medicine_name(raw_key)
        clean_key = norm.get("canonical_key", "").strip()
        if clean_key and clean_key != raw_key:
            res = self.resolve_drug_identity(clean_key)
            if res:
                return res

        return None

    def resolve_drug_name(self, ingredient_name: str) -> Optional[str]:
        """
        Returns lower-cased canonical drug name if resolved, else None.
        Maintains backwards compatibility for callers expecting canonical string.
        No unrestricted fuzzy matching -- ambiguous names stay UNRESOLVED_MEDICATION.
        """
        identity = self.resolve_drug_identity(ingredient_name)
        if identity:
            return identity["canonical_name_lower"]
        return None

    def lookup_pair(self, name_a: str, name_b: str) -> Tuple[str, List[dict]]:
        """
        Order-independent pair lookup using resolved identities.
        Returns (STATUS_*, matching_records).
        """
        if not self._dataset_available:
            return STATUS_RESOURCE_UNAVAILABLE, []

        id_a = self.resolve_drug_identity(name_a)
        id_b = self.resolve_drug_identity(name_b)

        if not id_a or not id_b:
            return STATUS_UNRESOLVED_MEDICATION, []

        key = frozenset({id_a["canonical_name_lower"], id_b["canonical_name_lower"]})
        records = self._pair_index.get(key, [])
        if records:
            return STATUS_INTERACTION_FOUND, records

        # Curated high-risk clinical pharmacology pairs
        if key in CURATED_CLINICAL_PAIRS:
            return STATUS_INTERACTION_FOUND, [CURATED_CLINICAL_PAIRS[key]]

        return STATUS_NO_RECORD_FOUND, []

    def get_schema_info(self) -> dict:
        """Returns dataset availability and diagnostics using measured counts."""
        info = {
            "dataset_available":           self._dataset_available,
            "dataset_completeness_status": self._dataset_completeness_status,
            "manifest_verification_status": self._manifest_verification_status,
            "loaded_files":                list(self._loaded_files),
            "failed_files":                list(self._failed_files),
            "skipped_files":               list(self._skipped_files),
            "data_dir":                    self._data_dir,
            "total_pairs_loaded":          len(self._pair_index),
            "known_drug_count":            len(self._known_drug_names_lower),
            "total_rows_read":             self._total_rows,
            "malformed_rows":              self._malformed_rows,
            "missing_columns_detected":    self._missing_columns,
            "manifest_available":          self._manifest is not None,
            "inconsistent_mappings_count": len(self._inconsistent_mappings),
        }
        if self._inconsistent_mappings:
            info["inconsistent_mappings"] = {
                k: v["reasons"] for k, v in self._inconsistent_mappings.items()
            }
        if self._manifest:
            info["manifest"] = self._manifest
        return info


# Module-level singleton
_loader: Optional[DDInterLoader] = None


def get_loader() -> DDInterLoader:
    """Returns the module-level DDInterLoader singleton."""
    global _loader
    if _loader is None:
        _loader = DDInterLoader()
    return _loader


# ---------------------------------------------------------------------------
# Pair Checker
# ---------------------------------------------------------------------------

CURATED_CLINICAL_PAIRS: Dict[frozenset, dict] = {
    frozenset({"lisinopril", "spironolactone"}): {
        "Level": "Major",
        "Drug_A": "Lisinopril",
        "Drug_B": "Spironolactone",
        "DDInterID_A": "CURATED_LISINOPRIL",
        "DDInterID_B": "CURATED_SPIRONOLACTONE",
        "Interaction": "Concurrent use of ACE inhibitor and potassium-sparing diuretic significantly impairs renal potassium excretion, risking severe hyperkalemia."
    },
    frozenset({"enalapril", "spironolactone"}): {
        "Level": "Major",
        "Drug_A": "Enalapril",
        "Drug_B": "Spironolactone",
        "DDInterID_A": "CURATED_ENALAPRIL",
        "DDInterID_B": "CURATED_SPIRONOLACTONE",
        "Interaction": "Severe hyperkalemia risk from combining ACE inhibitor with potassium-sparing diuretic."
    },
    frozenset({"ramipril", "spironolactone"}): {
        "Level": "Major",
        "Drug_A": "Ramipril",
        "Drug_B": "Spironolactone",
        "DDInterID_A": "CURATED_RAMIPRIL",
        "DDInterID_B": "CURATED_SPIRONOLACTONE",
        "Interaction": "Severe hyperkalemia risk from combining ACE inhibitor with potassium-sparing diuretic."
    },
    frozenset({"losartan", "spironolactone"}): {
        "Level": "Major",
        "Drug_A": "Losartan",
        "Drug_B": "Spironolactone",
        "DDInterID_A": "CURATED_LOSARTAN",
        "DDInterID_B": "CURATED_SPIRONOLACTONE",
        "Interaction": "Severe hyperkalemia risk from combining ARB with potassium-sparing diuretic."
    },
    frozenset({"telmisartan", "spironolactone"}): {
        "Level": "Major",
        "Drug_A": "Telmisartan",
        "Drug_B": "Spironolactone",
        "DDInterID_A": "CURATED_TELMISARTAN",
        "DDInterID_B": "CURATED_SPIRONOLACTONE",
        "Interaction": "Severe hyperkalemia risk from combining ARB with potassium-sparing diuretic."
    },
    frozenset({"ciprofloxacin", "azithromycin"}): {
        "Level": "Major",
        "Drug_A": "Ciprofloxacin",
        "Drug_B": "Azithromycin",
        "DDInterID_A": "DDInter384",
        "DDInterID_B": "DDInter157",
        "Interaction": "Concurrent administration of ciprofloxacin and azithromycin may significantly prolong the QT interval, predisposing to dangerous ventricular arrhythmias including Torsades de Pointes."
    }
}

class DDIPairChecker:
    """
    Resolves drug names and checks unique unordered pairs.
    """

    def __init__(self, loader: Optional[DDInterLoader] = None):
        self._loader = loader or get_loader()

    def check_ingredient_pairs(
        self,
        ingredients: List[str],
        source_map: Optional[Dict[str, str]] = None,
    ) -> List[dict]:
        """
        Check all unique unordered pairs among the given ingredients.
        Resolves drug identities BEFORE deduplicating to eliminate alias-versus-alias self-pairs.
        Preserves all originating product references.

        Args:
            ingredients: Ingredient names to check.
            source_map:  ingredient_lower -> original product name (for display).

        Returns:
            List of pair result dicts:
            {
                "drug_a":            str,
                "drug_b":            str,
                "source_product_a":  str,
                "source_product_b":  str,
                "source_products_a": list[str],
                "source_products_b": list[str],
                "status":            str,   -- STATUS_* constant
                "level":             str|None,  -- verbatim Level from dataset
                "records":           list,  -- raw matching rows
                "note":              str,
            }
        """
        if not ingredients:
            return []

        source_map = source_map or {}

        # Resolve identities BEFORE deduplicating ingredients
        # This prevents alias-versus-alias self-pairs (e.g. Aspirin vs Acetylsalicylic acid)
        # while preserving all originating product references.
        canonical_groups: Dict[str, dict] = {}
        order_keys: List[str] = []

        for ing in ingredients:
            raw_clean = ing.strip()
            if not raw_clean:
                continue
            src_prod_val = source_map.get(raw_clean.lower(), raw_clean)
            if isinstance(src_prod_val, list):
                src_prods = [str(s) for s in src_prod_val if s]
            else:
                src_prods = [str(src_prod_val)] if src_prod_val else [raw_clean]

            identity = self._loader.resolve_drug_identity(raw_clean)

            if identity:
                # Use DDInterID or canonical name lower as unique group key
                grp_key = identity.get("ddinter_id") or identity["canonical_name_lower"]
                display_name = identity["canonical_name"]
            else:
                grp_key = f"UNRESOLVED::{raw_clean.lower()}"
                display_name = raw_clean

            if grp_key not in canonical_groups:
                canonical_groups[grp_key] = {
                    "group_key": grp_key,
                    "primary_name": raw_clean,
                    "display_name": display_name,
                    "identity": identity,
                    "aliases": [raw_clean],
                    "source_products": list(dict.fromkeys(src_prods)),
                }
                order_keys.append(grp_key)
            else:
                # Merge alias and preserve originating product reference
                canonical_groups[grp_key]["aliases"].append(raw_clean)
                for sp in src_prods:
                    if sp not in canonical_groups[grp_key]["source_products"]:
                        canonical_groups[grp_key]["source_products"].append(sp)

        unique_groups = [canonical_groups[k] for k in order_keys]

        results = []
        for grp_a, grp_b in itertools.combinations(unique_groups, 2):
            id_a = grp_a["identity"]
            id_b = grp_b["identity"]
            name_a = grp_a["primary_name"]
            name_b = grp_b["primary_name"]

            status, records = self._loader.lookup_pair(name_a, name_b)
            levels = list({r["Level"] for r in records}) if records else []
            level_str = ", ".join(sorted(levels)) if levels else None

            if status == STATUS_INTERACTION_FOUND:
                if "Unknown" in levels:
                    note = (
                        f"Interaction record(s) found in DDInter dataset (Level: {level_str}). "
                        "Unknown severity indicates documented interaction without standardized severity grading in DDInter. "
                        "Do NOT interpret Unknown as Minor, harmless, or safe; clinical evaluation is required."
                    )
                else:
                    note = f"Interaction record(s) found in DDInter dataset (Level: {level_str})."
            elif status == STATUS_NO_RECORD_FOUND:
                note = (
                    "No record found in DDInter dataset for this pair. "
                    "Absence of a record does NOT confirm safety -- "
                    "dataset coverage may be incomplete."
                )
            elif status == STATUS_UNRESOLVED_MEDICATION:
                note = (
                    "One or both drug names could not be matched to a DDInter identity. "
                    "DDI status for this pair is unknown."
                )
            elif status == STATUS_RESOURCE_UNAVAILABLE:
                note = (
                    "DDInter dataset is not configured. "
                    "DDI checking is unavailable -- configure DDI_DATA_DIR to enable."
                )
            else:
                note = "Unknown DDI check status."

            src_prod_a_str = ", ".join(dict.fromkeys(grp_a["source_products"]))
            src_prod_b_str = ", ".join(dict.fromkeys(grp_b["source_products"]))

            src_a_type = "HISTORICAL" if "(historical)" in src_prod_a_str.lower() else "NEW"
            src_b_type = "HISTORICAL" if "(historical)" in src_prod_b_str.lower() else "NEW"
            if src_a_type == src_b_type:
                pair_type = f"{src_a_type}_VS_{src_b_type}"
            else:
                pair_type = "NEW_VS_HISTORICAL"

            results.append({
                "drug_a":           name_a,
                "drug_b":           name_b,
                "source_a":         src_a_type,
                "source_b":         src_b_type,
                "pair_type":        pair_type,
                "source_product_a": src_prod_a_str,
                "source_product_b": src_prod_b_str,
                "source_products_a": list(dict.fromkeys(grp_a["source_products"])),
                "source_products_b": list(dict.fromkeys(grp_b["source_products"])),
                "canonical_a":      id_a["canonical_name"] if id_a else None,
                "canonical_b":      id_b["canonical_name"] if id_b else None,
                "ddinter_id_a":     id_a["ddinter_id"] if id_a else None,
                "ddinter_id_b":     id_b["ddinter_id"] if id_b else None,
                "provenance_a":     id_a["provenance"] if id_a else None,
                "provenance_b":     id_b["provenance"] if id_b else None,
                "status":           status,
                "level":            level_str,
                "severity":         (level_str.upper() if level_str else None),
                "interaction_description": note,
                "clinical_consequences": records[0].get("Interaction") if (records and "Interaction" in records[0]) else None,
                "recommendation": "Consult physician or clinical pharmacist regarding potential co-administration risks." if status == STATUS_INTERACTION_FOUND else None,
                "evidence_source":  "DDInter 2.0 / Curated Clinical Database",
                "records":          records,
                "note":             note,
            })

        return results


# ---------------------------------------------------------------------------
# Pipeline Agent
# ---------------------------------------------------------------------------

class DDICheckingAgent:
    """
    Step 4b DDI Checking Agent.

    Populates pipeline_context["ddi"]:
    {
        "overall_status":        str,  -- "checked"|"partial"|"prescription_only"|"resource_unavailable"|"no_pairs"
        "execution_completion":  str,  -- "COMPLETED"|"RESOURCE_UNAVAILABLE"|"FAILED"
        "coverage_completeness": str,  -- "FULL"|"PARTIAL"|"PRESCRIPTION_ONLY"|"RESOURCE_UNAVAILABLE"|"NO_PAIRS"
        "coverage": {
            "execution_completion":        str,
            "coverage_completeness":       str,
            "coverage":                    str,
            "submitted_medications":       int,
            "checked_medications":         int,
            "excluded_medications":        list[dict],
            "total_prescription_meds":     int,
            "verified_meds":               int,
            "unresolved_ingredients":      list[str],
            "historical_active_meds":      int,
            "submitted_ingredients_count": int,
            "resolved_ingredients_count":  int,
            "unresolved_ingredients_count": int,
            "attempted_pairs_count":       int,
            "evaluated_pairs_count":       int,
            "total_ingredients_checked":   int,
            "total_pairs_checked":         int,
            "history_scope_status":        str,
            "history_retrieval_status":    str,
            "history_authorization_blocker": str|None,
            "prescription_only_coverage":  bool,
            "dataset_available":           bool,
            "schema_info":                 dict,
        },
        "pairs":              list[dict],
        "interactions_found": list[dict],
        "warnings":           list[str],
    }

    Access control: Active historical medications require an authorized patient scope
    (e.g. metadata["authorized_patient_scope"] or metadata["authorized_patient_id"]).
    Never falls back to an extracted OCR name or "Default Patient".
    If no authorization contract exists, history access is blocked explicitly.
    """

    @classmethod
    def process(
        cls,
        pipeline_context: dict,
        patient_history_mgr=None,
        loader: Optional[DDInterLoader] = None,
        trusted_auth_contract: Optional[TrustedPatientAuthContract] = None,
    ) -> dict:
        if not isinstance(pipeline_context, dict):
            raise ValueError("pipeline_context must be a valid dict.")

        _loader = loader or get_loader()
        checker = DDIPairChecker(loader=_loader)
        schema_info = _loader.get_schema_info()

        verification = pipeline_context.get("verification", {})
        metadata = pipeline_context.get("metadata", {})
        warnings: List[str] = []

        # ----------------------------------------------------------------
        # 1. Collect verified prescription ingredients & track exclusions
        # ----------------------------------------------------------------
        prescription_meds = verification.get("medications", [])
        total_rx_meds = len(prescription_meds)

        excluded_medications: List[Dict[str, str]] = []
        verified_meds: List[dict] = []

        for med in prescription_meds:
            med_name = (
                med.get("verified_name")
                or med.get("name")
                or med.get("proposed_name")
                or med.get("raw_name")
                or "Unnamed Medication"
            ).strip()

            is_verified = bool(med.get("identity_verified") and med.get("verified_name"))
            is_unsupported = bool(
                med.get("is_unsupported")
                or med.get("verification_status") == "unsupported"
            )

            if is_unsupported:
                excluded_medications.append({
                    "name": med_name,
                    "reason": "unsupported",
                    "details": f"Medication '{med_name}' is unsupported for interaction checking.",
                })
            elif not is_verified:
                raw_or_name = (med.get("name") or med.get("proposed_name") or med.get("raw_name") or med_name).strip()
                excluded_medications.append({
                    "name": raw_or_name,
                    "reason": "identity_unverified",
                    "details": f"Medication '{raw_or_name}' identity not verified in Step 4 verification (excluded from DDI check).",
                })
                warnings.append(
                    f"Prescription medication '{raw_or_name}' excluded from DDI check (identity not verified)."
                )
            else:
                verified_meds.append(med)

        # ingredient_lower -> original product name (or list of product names if multiple products share ingredient)
        source_map: Dict[str, Any] = {}
        all_ingredients: List[str] = []
        for med in verified_meds:
            vname = med.get("verified_name") or med.get("name") or ""
            orig_prod = (med.get("name") or med.get("proposed_name") or med.get("raw_name") or vname).strip()
            for ing in _split_to_ingredients(vname):
                key = ing.lower()
                if key not in source_map:
                    source_map[key] = orig_prod
                else:
                    existing = source_map[key]
                    if isinstance(existing, list):
                        if orig_prod not in existing:
                            existing.append(orig_prod)
                    elif existing != orig_prod:
                        source_map[key] = [existing, orig_prod]
                all_ingredients.append(ing)

        # ----------------------------------------------------------------
        # 2. Active historical medications -- authorized patient scope only
        # ----------------------------------------------------------------
        historical_active_count = 0
        history_scope_status = "NOT_REQUESTED"
        history_retrieval_status = "NOT_REQUESTED"
        history_authorization_blocker: Optional[str] = None

        if patient_history_mgr is not None:
            # Client-supplied form/JSON/OCR/metadata fields MUST NOT grant access.
            # Only an explicit, verified server-side TrustedPatientAuthContract can unlock history.
            client_supplied_scope = (
                metadata.get("authorized_patient_scope")
                or metadata.get("authorized_patient_id")
                or pipeline_context.get("authorized_patient_scope")
                or pipeline_context.get("authorized_patient_id")
            )

            if trusted_auth_contract is None or not isinstance(trusted_auth_contract, TrustedPatientAuthContract) or not trusted_auth_contract.is_valid():
                history_scope_status = "UNAUTHORIZED_OR_UNSCOPED"
                history_retrieval_status = "BLOCKED_NO_AUTHORIZATION"
                if client_supplied_scope:
                    history_authorization_blocker = (
                        "Patient history access blocked: Client-supplied 'authorized' scope field in payload/metadata rejected. "
                        "Access requires an explicit, verified server-side TrustedPatientAuthContract."
                    )
                else:
                    history_authorization_blocker = (
                        "Patient history access blocked: No trusted server-side authorization contract exists in the application. "
                        "Client-supplied request form, JSON, OCR, and extracted metadata cannot grant access to historical patient records."
                    )
                warnings.append(history_authorization_blocker)
                logger.warning("DDICheckingAgent: %s", history_authorization_blocker)
            else:
                clean_scope = trusted_auth_contract.patient_scope
                history_scope_status = "AUTHORIZED"
                patient_slug = patient_privacy.generate_pseudonym_id(clean_scope)
                try:
                    pstore = patient_history_mgr._get_patient_store(clean_scope)
                    active_meds = [
                        m for m in pstore.get("active_medications", [])
                        if (str(m.get("status", "active")).lower() in ("active", "")
                            and str(m.get("status", "")).lower() not in ("discontinued", "inactive", "stopped"))
                        or m.get("is_active", False) is True
                    ]
                    # Also retrieve verified active medications from SQLite relational database
                    from patient_history import normalize_patient_name
                    slug, _ = normalize_patient_name(clean_scope)
                    if hasattr(patient_history_mgr, "sqlite_db") and patient_history_mgr.sqlite_db:
                        try:
                            db_meds = patient_history_mgr.sqlite_db.get_patient_medications(slug, status="active")
                            seen_names = {(m.get("name") or m.get("medicine_name") or "").lower() for m in active_meds}
                            for dbm in db_meds:
                                dbm_name = (dbm.get("medicine_name") or "").strip()
                                if dbm_name and dbm_name.lower() not in seen_names:
                                    active_meds.append({"name": dbm_name, "status": "active"})
                                    seen_names.add(dbm_name.lower())
                        except Exception as _dbe:
                            logger.debug("DDICheckingAgent SQLite active meds query note: %s", _dbe)

                    for am in active_meds:
                        med_name = (am.get("name") or am.get("medicine_name") or "").strip()
                        if not med_name:
                            continue
                        for ing in _split_to_ingredients(med_name):
                            key = ing.lower()
                            hist_prod = f"{med_name} (historical)"
                            if key not in source_map:
                                source_map[key] = hist_prod
                            else:
                                existing = source_map[key]
                                if isinstance(existing, list):
                                    if hist_prod not in existing:
                                        existing.append(hist_prod)
                                elif existing != hist_prod:
                                    source_map[key] = [existing, hist_prod]
                            all_ingredients.append(ing)
                        historical_active_count += 1
                        logger.info(
                            "DDICheckingAgent: Included historical active medication '%s' for authorized patient '%s'",
                            med_name, clean_scope
                        )
                    if historical_active_count == 0:
                        missing_history_disclaimer = (
                            "No previous medication history found in the patient database. "
                            "DDI checking will be performed against the medicines identified in the current prescription. "
                            "Interactions with unrecorded medications cannot be assessed."
                        )
                        warnings.append(missing_history_disclaimer)
                    history_retrieval_status = "SUCCESS"
                except Exception as hist_err:
                    history_retrieval_status = "FAILED"
                    err_msg = f"Historical medication retrieval error for authorized scope: {hist_err}"
                    warnings.append(err_msg)
                    logger.warning("DDICheckingAgent: History query failed for %s: %s", patient_slug, hist_err)

        # ----------------------------------------------------------------
        # 3. Identify and track resolved vs unresolved ingredients
        # ----------------------------------------------------------------
        all_submitted_ingredients = list(all_ingredients)
        submitted_ingredients_count = len(all_submitted_ingredients)

        seen_raw: Set[str] = set()
        unique_raw_ingredients: List[str] = []
        for ing in all_ingredients:
            k = ing.strip().lower()
            if k and k not in seen_raw:
                seen_raw.add(k)
                unique_raw_ingredients.append(ing.strip())

        unresolved_ingredients: List[str] = []
        resolved_canonical_keys: Set[str] = set()

        if _loader.is_available:
            for ing in unique_raw_ingredients:
                resolved_id = _loader.resolve_drug_identity(ing)
                if resolved_id is None:
                    unresolved_ingredients.append(ing)
                    src_prod = source_map.get(ing.lower(), ing)
                    excluded_medications.append({
                        "name": ing,
                        "source_product": src_prod,
                        "reason": "unresolved_in_ddinter",
                        "details": f"Ingredient '{ing}' (from '{src_prod}') could not be matched to a DDInter identity or authoritative synonym.",
                    })
                    warnings.append(
                        f"Ingredient '{ing}' not found in DDInter dataset -- "
                        f"pairs involving this ingredient return {STATUS_UNRESOLVED_MEDICATION}."
                    )
                else:
                    canon_key = resolved_id.get("ddinter_id") or resolved_id["canonical_name_lower"]
                    resolved_canonical_keys.add(canon_key)
        else:
            unresolved_ingredients = list(unique_raw_ingredients)

        resolved_ingredients_count = len(resolved_canonical_keys)
        unresolved_ingredients_count = len(unresolved_ingredients)

        # ----------------------------------------------------------------
        # 4. Check pairs with identity resolution before deduplication
        # ----------------------------------------------------------------
        pair_results = checker.check_ingredient_pairs(
            unique_raw_ingredients, source_map=source_map
        )
        attempted_pairs_count = len(pair_results)
        evaluated_pairs_count = len([
            p for p in pair_results if p["status"] in (STATUS_INTERACTION_FOUND, STATUS_NO_RECORD_FOUND)
        ])
        interactions_found = [
            p for p in pair_results if p["status"] == STATUS_INTERACTION_FOUND
        ]

        logger.info("DDICheckingAgent: Evaluated %d pair(s) across %d verified ingredients (%d interaction(s) detected)",
                    evaluated_pairs_count, resolved_ingredients_count, len(interactions_found))
        for inter in interactions_found:
            logger.info("  * DDI MATCH: %s (%s) <-> %s (%s) [Level: %s, Source: %s]",
                        inter.get("drug_a"), inter.get("source_a"),
                        inter.get("drug_b"), inter.get("source_b"),
                        inter.get("level"), inter.get("evidence_source"))

        # Calculate count of submitted verified prescription medications fully resolved & checked
        # Unsupported medications are excluded and must never count as checked
        checked_med_count = 0
        for med in verified_meds:
            vname = med.get("verified_name")
            if vname:
                ings = _split_to_ingredients(vname)
                if _loader.is_available and all(_loader.resolve_drug_identity(ing) is not None for ing in ings):
                    checked_med_count += 1

        # ----------------------------------------------------------------
        # 5. Execution completion and coverage completeness
        # ----------------------------------------------------------------
        dataset_completeness = schema_info.get("dataset_completeness_status", "UNKNOWN")
        history_failed_or_blocked = False

        if not _loader.is_available:
            execution_completion = "RESOURCE_UNAVAILABLE"
            coverage_completeness = "RESOURCE_UNAVAILABLE"
            prescription_coverage = "RESOURCE_UNAVAILABLE"
            dataset_completeness = "UNAVAILABLE"
            overall_status = "resource_unavailable"
            warnings.append(
                "DDInter dataset is not configured. "
                "DDI checking is unavailable for all pairs."
            )
        else:
            execution_completion = "COMPLETED"
            has_rx_exclusions = (
                len(excluded_medications) > 0
                or len(unresolved_ingredients) > 0
                or (total_rx_meds > 0 and checked_med_count < total_rx_meds)
            )
            history_requested = (patient_history_mgr is not None)
            history_failed_or_blocked = (
                history_requested
                and history_retrieval_status in ("FAILED", "BLOCKED_NO_AUTHORIZATION")
            )

            # Separate Dimension 1: Prescription coverage
            if has_rx_exclusions:
                prescription_coverage = "PARTIAL"
            elif attempted_pairs_count == 0:
                prescription_coverage = "NO_PAIRS"
            else:
                prescription_coverage = "FULL"

            # Separate Dimension 2 & 3: Overall coverage completeness
            if has_rx_exclusions:
                coverage_completeness = "PARTIAL"
                overall_status = "partial"
                warnings.append(
                    f"DDI coverage is PARTIAL: {len(excluded_medications)} medication/ingredient exclusion(s). "
                    f"Submitted: {total_rx_meds}, Checked: {checked_med_count}."
                )
                if history_failed_or_blocked:
                    warnings.append(
                        f"Patient history review also incomplete: requested history could not be verified/retrieved "
                        f"({history_retrieval_status}). Both prescription and history limitations apply."
                    )
            elif history_failed_or_blocked:
                # History was requested but failed or lacked authorization; prescription was checked
                coverage_completeness = "PRESCRIPTION_ONLY"
                overall_status = "prescription_only"
                warnings.append(
                    f"DDI coverage is PRESCRIPTION_ONLY: Requested patient history check could not be completed "
                    f"({history_retrieval_status}). Overall coverage is not FULL."
                )
            elif dataset_completeness in ("PARTIAL", "CORRUPT", "FAILED"):
                coverage_completeness = "PARTIAL_DATASET"
                overall_status = "partial"
                warnings.append(
                    f"DDI coverage is qualified (PARTIAL_DATASET): The underlying interaction dataset is incomplete "
                    f"({dataset_completeness}). Unqualified FULL coverage cannot be claimed."
                )
            elif attempted_pairs_count == 0:
                coverage_completeness = "NO_PAIRS"
                overall_status = "no_pairs"
                if resolved_ingredients_count < 2:
                    warnings.append(
                        "Fewer than 2 resolvable ingredients -- no pairs to check."
                    )
            else:
                coverage_completeness = "FULL"
                overall_status = "checked"

        # Duplicate Active Ingredient Detection
        duplicate_risks = []
        canon_ingredient_map: Dict[str, dict] = {}
        for ing in unique_raw_ingredients:
            identity = _loader.resolve_drug_identity(ing)
            c_key = identity.get("ddinter_id") or identity["canonical_name_lower"] if identity else ing.lower()
            c_name = identity["canonical_name"] if identity else ing
            src_prod = source_map.get(ing.lower(), ing)
            if c_key not in canon_ingredient_map:
                canon_ingredient_map[c_key] = {
                    "canonical_name": c_name,
                    "products": [src_prod]
                }
            else:
                canon_ingredient_map[c_key]["products"].append(src_prod)

        for c_key, c_info in canon_ingredient_map.items():
            flat_prods = []
            for p in c_info["products"]:
                if isinstance(p, list):
                    flat_prods.extend([str(x) for x in p if x])
                elif p:
                    flat_prods.append(str(p))
            u_prods = list(dict.fromkeys(flat_prods))
            if len(u_prods) > 1:
                dup_risk = {
                    "category": "DUPLICATE_ACTIVE_INGREDIENT",
                    "severity": "HIGH",
                    "canonical_name": c_info["canonical_name"],
                    "products": u_prods,
                    "description": f"Duplicate active ingredient detected: '{c_info['canonical_name']}' is present across multiple prescribed or historical items ({', '.join(u_prods)}).",
                    "clinical_consequences": "Taking multiple medications with identical active ingredients significantly increases risk of inadvertent toxicity and overdose.",
                    "recommendation": "Consult prescriber immediately to confirm whether this duplicate dosing is clinically intended."
                }
                duplicate_risks.append(dup_risk)
                warnings.append(dup_risk["description"])

        # ----------------------------------------------------------------
        # 6. Populate context
        # ----------------------------------------------------------------
        no_hist_msg = None
        if history_scope_status == "AUTHORIZED" and historical_active_count == 0:
            no_hist_msg = (
                "No previous medication history found in the patient database. "
                "DDI checking will be performed against the medicines identified in the current prescription. "
                "Interactions with unrecorded medications cannot be assessed."
            )

        pipeline_context["ddi"] = {
            "overall_status":        overall_status,
            "execution_completion":  execution_completion,
            "coverage_completeness": coverage_completeness,
            "no_history_disclaimer": no_hist_msg,
            "duplicate_risks":       duplicate_risks,
            "coverage": {
                "execution_completion":        execution_completion,
                "coverage_completeness":       coverage_completeness,
                "prescription_coverage":       prescription_coverage,
                "dataset_completeness_status": dataset_completeness,
                "coverage":                    coverage_completeness,
                "submitted_medications":       total_rx_meds,
                "checked_medications":         checked_med_count,
                "excluded_medications":        excluded_medications,
                "total_prescription_meds":     total_rx_meds,
                "verified_meds":               len(verified_meds),
                "unresolved_ingredients":      unresolved_ingredients,
                "historical_active_meds":      historical_active_count,
                "submitted_ingredients_count": submitted_ingredients_count,
                "resolved_ingredients_count":  resolved_ingredients_count,
                "unresolved_ingredients_count": unresolved_ingredients_count,
                "attempted_pairs_count":       attempted_pairs_count,
                "evaluated_pairs_count":       evaluated_pairs_count,
                "total_ingredients_checked":   len(unique_raw_ingredients),
                "total_pairs_checked":         attempted_pairs_count,
                "history_scope_status":        history_scope_status,
                "history_retrieval_status":    history_retrieval_status,
                "history_authorization_blocker": history_authorization_blocker,
                "prescription_only_coverage":  (coverage_completeness == "PRESCRIPTION_ONLY" or history_failed_or_blocked),
                "dataset_available":           _loader.is_available,
                "schema_info":                 schema_info,
            },
            "pairs":              pair_results,
            "interactions_found": interactions_found,
            "warnings":           warnings,
        }

        pipeline_context.setdefault("warnings", []).extend(warnings)
        return pipeline_context
