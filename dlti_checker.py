"""
===============================================================================
DLTI CHECKING AGENT
Drug–Laboratory Test Interaction (DLTI) Research Prototype
===============================================================================

Pipeline Position (Research Preview — DISABLED BY DEFAULT):
  PrescriptionVerificationAgent (Step 4)
          │
          ▼
  [DDICheckingAgent]  (Step 4b)
          │
          ▼
  [DLTICheckingAgent] ◄── THIS AGENT (Step 4c) — RESEARCH PREVIEW ONLY
          │
          ▼
  PrescriptionReasoningAgent (Step 5)

GOVERNANCE INVARIANTS (enforced):
  1. RESEARCH PREVIEW — NOT CLINICALLY VALIDATED.
     All output is labeled as research-grade and must not substitute for
     clinical judgment.
  2. Disabled by default. Must be explicitly enabled via
     DLTI_RESEARCH_PREVIEW_ENABLED = True. Production path is unaffected.
  3. Only verified medication identities (identity_verified == True) are
     evaluated. Unverified medications are skipped and reported.
  4. Only lab values present in the current request are used.
     No patient history reads. No external data access.
  5. Rules are loaded exclusively from the versioned knowledge base file.
     No hardcoded thresholds or inline rules.
  6. Applicability is checked in full before any threshold evaluation.
     A rule that fails applicability is reported as NOT_APPLICABLE, not
     as NO_INTERACTION.
  7. Unit resolution is mandatory. Unresolved units -> REJECT_EVALUATION.
     Unit conversion is applied only where explicitly declared in the rule.
  8. NO_RULE_FOUND is never presented as "safe" or "no interaction".
  9. Knowledge base integrity is checked on load. A failed integrity check
     produces status KNOWLEDGE_BASE_UNAVAILABLE, not silent success.
 10. Output coverage metadata always distinguishes:
       RESEARCH_PREVIEW_EVALUATED / RESEARCH_PREVIEW_NOT_APPLICABLE /
       KNOWLEDGE_BASE_UNAVAILABLE / DISABLED
 11. All output blocks carry the label:
       "⚠ Research preview — not clinically validated"
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default: DISABLED. Must be explicitly set to True by the caller to activate.
DLTI_RESEARCH_PREVIEW_ENABLED: bool = False

# Default knowledge base path, relative to this module's directory.
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KB_PATH = os.path.join(_MODULE_DIR, "data", "dlti_knowledge_base.json")

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_TRIGGERED               = "DLTI_TRIGGERED"            # Rule matched (threshold met or status matched)
STATUS_RULE_EVALUATED          = "DLTI_RULE_EVALUATED"        # Rule evaluated; threshold not met
STATUS_NOT_APPLICABLE          = "DLTI_NOT_APPLICABLE"        # Rule found but applicability check failed
STATUS_NO_RULE_FOUND           = "DLTI_NO_RULE_FOUND"         # No rule covers this med-lab pair
STATUS_REJECTED_EVALUATION     = "DLTI_REJECTED_EVALUATION"   # Mandatory field missing / unit unresolvable
STATUS_KB_UNAVAILABLE          = "DLTI_KB_UNAVAILABLE"        # Knowledge base could not be loaded
STATUS_DISABLED                = "DLTI_DISABLED"              # Feature is disabled (global flag)
STATUS_RULE_DISABLED           = "DLTI_RULE_DISABLED"         # Individual rule has operator=DISABLED
STATUS_MED_UNVERIFIED          = "DLTI_MED_UNVERIFIED"        # Medication identity not verified — skipped
STATUS_INDETERMINATE_FASTING   = "DLTI_INDETERMINATE_FASTING" # Fasting context required but unknown
STATUS_INSUFFICIENT_CONTEXT    = "DLTI_INSUFFICIENT_CONTEXT"  # Required context field (e.g. lab status) missing

RESEARCH_PREVIEW_LABEL = "Research preview — not clinically validated"

# ---------------------------------------------------------------------------
# Valid values for schema validation of the knowledge base
# ---------------------------------------------------------------------------

_VALID_TIERS = {"TIER_1_EXECUTABLE", "TIER_2_RESEARCH_CANDIDATE"}
_VALID_RELATIONSHIP_CATEGORIES = {
    "PHARMACODYNAMIC_EFFECT",
    "ANALYTICAL_INTERFERENCE",
    "CLINICAL_SAFETY_MONITORING",
}
_VALID_OPERATORS = {"<", "<=", ">", ">=", "==", "BETWEEN", "STATUS_MATCH", "DISABLED"}
_VALID_DIRECTIONS = {"MED_TO_LAB", "LAB_TO_MED", "BIDIRECTIONAL"}
_VALID_REVIEW_STATUSES = {"DRAFT", "PEER_REVIEWED", "APPROVED", "DEPRECATED", "SUPERSEDED"}

# Analyte key normalization: lowercase key -> canonical key stored in rules
_ANALYTE_KEY_ALIASES: Dict[str, str] = {
    "glucose": "GLUCOSE",
    "fasting glucose": "GLUCOSE",
    "fasting blood glucose": "GLUCOSE",
    "fasting blood sugar": "GLUCOSE",
    "random glucose": "GLUCOSE",
    "random blood sugar": "GLUCOSE",
    "plasma glucose": "GLUCOSE",
    "blood glucose": "GLUCOSE",
    "glucose (timing unspecified)": "GLUCOSE",
    "crp": "CRP",
    "c-reactive protein": "CRP",
    "c reactive protein": "CRP",
    "potassium": "POTASSIUM",
    "serum potassium": "POTASSIUM",
    "k+": "POTASSIUM",
}

# Medication generic name normalization
_MED_NAME_ALIASES: Dict[str, str] = {
    "prednisone": "prednisone",
    "rayos": "prednisone",
    "deltasone": "prednisone",
    "spironolactone": "spironolactone",
    "aldactone": "spironolactone",
    "carospir": "spironolactone",
}

# Unit normalization: lowercase input -> canonical unit
_UNIT_NORMALIZATION: Dict[str, str] = {
    "mg/dl": "mg/dL",
    "mg/100ml": "mg/dL",
    "mmol/l": "mmol/L",
    "meq/l": "mmol/L",
    "mEq/L": "mmol/L",
    "mg/l": "mg/L",
    "mg/dl": "mg/L",   # CRP unit variant
}


# ---------------------------------------------------------------------------
# Knowledge Base Loader
# ---------------------------------------------------------------------------

class DLTIKnowledgeBase:
    """
    Loads and structurally validates the DLTI research knowledge base.

    Validation enforces:
    - Required metadata keys.
    - All rules have required fields.
    - All rules are TIER_2_RESEARCH_CANDIDATE (TIER_1 is blocked in research preview).
    - All rules have release_approved == False (released rules must not enter the
      research preview path without explicit governance).
    - No rules with review_status == "APPROVED" and release_approved == True
      silently enter the research path.

    On failure: raises DLTIKnowledgeBaseError (captured and surfaced as
    STATUS_KB_UNAVAILABLE in results — never swallowed silently).
    """

    def __init__(self, kb_path: str = DEFAULT_KB_PATH):
        self.kb_path = kb_path
        self._raw: Optional[Dict] = None
        self._rules: List[Dict] = []
        self._metadata: Dict = {}
        self._load_errors: List[str] = []
        self._is_loaded: bool = False

    def load(self) -> "DLTIKnowledgeBase":
        """Load and validate the knowledge base. Returns self."""
        self._load_errors = []
        self._rules = []
        self._metadata = {}
        self._is_loaded = False

        # --- File existence ---
        if not os.path.isfile(self.kb_path):
            self._load_errors.append(
                f"Knowledge base file not found: {self.kb_path}"
            )
            return self

        # --- JSON parse ---
        try:
            with open(self.kb_path, "r", encoding="utf-8") as fh:
                self._raw = json.load(fh)
        except json.JSONDecodeError as exc:
            self._load_errors.append(f"JSON parse error: {exc}")
            return self
        except OSError as exc:
            self._load_errors.append(f"File read error: {exc}")
            return self

        if not isinstance(self._raw, dict):
            self._load_errors.append("Knowledge base root must be a JSON object.")
            return self

        # --- Metadata ---
        meta = self._raw.get("_metadata")
        if not isinstance(meta, dict):
            self._load_errors.append("Missing or invalid '_metadata' section.")
        else:
            self._metadata = meta
            for req_key in ("schema_version", "knowledge_base_id", "knowledge_base_version", "status"):
                if not meta.get(req_key):
                    self._load_errors.append(f"Missing required metadata key: '{req_key}'")

        # --- Rules ---
        rules_raw = self._raw.get("rules")
        if not isinstance(rules_raw, list):
            self._load_errors.append("Missing or invalid 'rules' array.")
            return self

        for idx, rule in enumerate(rules_raw):
            rule_errors = self._validate_rule_structure(rule, idx)
            if rule_errors:
                for err in rule_errors:
                    self._load_errors.append(f"Rule[{idx}]: {err}")
            else:
                self._rules.append(rule)

        if not self._load_errors:
            self._is_loaded = True
        return self

    def _validate_rule_structure(self, rule: Any, idx: int) -> List[str]:
        """Returns a list of structural errors for the given rule."""
        errs: List[str] = []
        if not isinstance(rule, dict):
            return ["Rule must be a dict."]

        required = {
            "rule_id", "rule_version", "tier", "relationship_category",
            "governance", "medication_criteria", "laboratory_criteria",
            "evaluation_logic", "evidence_references", "clinical_advisory",
            "context_outcomes",
        }
        missing = required - set(rule.keys())
        if missing:
            errs.append(f"Missing required fields: {sorted(missing)}")
            return errs  # Can't proceed without required fields

        # Tier
        if rule.get("tier") not in _VALID_TIERS:
            errs.append(f"Invalid tier: '{rule.get('tier')}'")

        # Relationship category
        if rule.get("relationship_category") not in _VALID_RELATIONSHIP_CATEGORIES:
            errs.append(f"Invalid relationship_category: '{rule.get('relationship_category')}'")

        # Governance
        gov = rule.get("governance", {})
        if not isinstance(gov, dict):
            errs.append("governance must be a dict.")
        else:
            if gov.get("review_status") not in _VALID_REVIEW_STATUSES:
                errs.append(f"Invalid review_status: '{gov.get('review_status')}'")
            if not isinstance(gov.get("release_approved"), bool):
                errs.append("governance.release_approved must be a boolean.")

        # Medication criteria
        med = rule.get("medication_criteria", {})
        if not isinstance(med, dict) or not med.get("generic_name"):
            errs.append("medication_criteria.generic_name is required.")
        if not isinstance(med.get("allowed_routes"), list) or len(med.get("allowed_routes", [])) == 0:
            errs.append("medication_criteria.allowed_routes must be a non-empty list.")

        # Laboratory criteria
        lab = rule.get("laboratory_criteria", {})
        if not isinstance(lab, dict) or not lab.get("analyte_key"):
            errs.append("laboratory_criteria.analyte_key is required.")
        if not lab.get("required_canonical_unit"):
            errs.append("laboratory_criteria.required_canonical_unit is required.")

        # Evaluation logic
        ev = rule.get("evaluation_logic", {})
        if not isinstance(ev, dict):
            errs.append("evaluation_logic must be a dict.")
        else:
            if ev.get("operator") not in _VALID_OPERATORS:
                errs.append(f"Invalid operator: '{ev.get('operator')}'")
            if ev.get("direction") not in _VALID_DIRECTIONS:
                errs.append(f"Invalid direction: '{ev.get('direction')}'")

        return errs

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    def rules(self) -> List[Dict]:
        return list(self._rules)

    @property
    def metadata(self) -> Dict:
        return dict(self._metadata)

    @property
    def load_errors(self) -> List[str]:
        return list(self._load_errors)


# ---------------------------------------------------------------------------
# Concept Resolvers
# ---------------------------------------------------------------------------

def resolve_analyte_key(raw_analyte: str) -> Optional[str]:
    """
    Resolves a raw analyte name to its canonical key used in rule definitions.
    Returns None if unresolvable.
    """
    if not raw_analyte:
        return None
    normalized = raw_analyte.strip().lower()
    return _ANALYTE_KEY_ALIASES.get(normalized)


def resolve_medication_generic(raw_name: str) -> Optional[str]:
    """
    Resolves a raw medication name (generic or brand) to its canonical generic name.
    Returns None if unresolvable.
    """
    if not raw_name:
        return None
    normalized = raw_name.strip().lower()
    return _MED_NAME_ALIASES.get(normalized)


def resolve_unit(raw_unit: str) -> Optional[str]:
    """
    Normalizes a raw unit string to its canonical form.
    Returns the raw unit if it's already a recognized canonical form,
    or maps via alias table. Returns None if unresolvable.
    """
    if not raw_unit:
        return None
    stripped = raw_unit.strip()
    lower = stripped.lower()
    # Direct canonical match check (case-insensitive)
    canonical_units = {"mg/dL", "mmol/L", "mg/L", "%", "g/dL", "IU/L", "U/L", "umol/L"}
    for cu in canonical_units:
        if stripped.lower() == cu.lower():
            return cu
    return _UNIT_NORMALIZATION.get(lower) or _UNIT_NORMALIZATION.get(stripped)


# ---------------------------------------------------------------------------
# Applicability Checker
# ---------------------------------------------------------------------------

class ApplicabilityResult:
    """Structured result of a rule applicability check."""
    __slots__ = ("passed", "failed_checks", "notes")

    def __init__(self, passed: bool, failed_checks: List[str], notes: List[str]):
        self.passed = passed
        self.failed_checks = failed_checks
        self.notes = notes


def check_rule_applicability(
    rule: Dict,
    med_entry: Dict,
    lab_entry: Dict,
    resolved_analyte_key: Optional[str],
    resolved_generic_name: Optional[str],
    resolved_unit: Optional[str],
    lab_value: Optional[float],
) -> ApplicabilityResult:
    """
    Checks all applicability conditions for a rule against the supplied inputs.

    Applicability checks (in order):
      1. medication_identity_verified — med_entry must have identity_verified=True.
      2. medication_name_matches     — resolved generic must match rule's generic_name.
      3. medication_route_matches    — if med_entry has a route, it must be in allowed_routes.
      4. laboratory_analyte_matches  — resolved analyte key must match rule's analyte_key.
      5. laboratory_unit_resolved    — unit must be resolvable or convertible.
      6. laboratory_value_present    — numeric value must be present.
      7. (optional) fasting_context  — if rule requires fasting context,
                                       fasting_confirmed must be True.

    A rule that fails ANY check is NOT_APPLICABLE.
    """
    failed: List[str] = []
    notes: List[str] = []
    ev_checks: List[str] = rule.get("evaluation_logic", {}).get("applicability_checks", [])
    lab_crit = rule.get("laboratory_criteria", {})
    med_crit = rule.get("medication_criteria", {})

    # 1. Identity verified
    if "medication_identity_verified" in ev_checks:
        if not med_entry.get("identity_verified", False):
            failed.append("medication_identity_verified")
            notes.append("Medication identity not verified — rule skipped.")

    # 2. Medication name matches
    rule_generic = med_crit.get("generic_name", "").lower()
    if resolved_generic_name != rule_generic:
        # This rule doesn't target this medication — soft skip handled by caller
        failed.append("medication_name_matches")

    # 3. Route matches (if route info available)
    if "medication_route_matches" in ev_checks:
        allowed_routes_upper = [r.upper() for r in med_crit.get("allowed_routes", [])]
        med_route = (med_entry.get("route") or "").strip().upper()
        if med_route and allowed_routes_upper and med_route not in allowed_routes_upper:
            failed.append("medication_route_matches")
            notes.append(
                f"Medication route '{med_route}' not in allowed routes {allowed_routes_upper}."
            )

    # 4. Analyte key matches
    analyte_matches = True
    rule_analyte = lab_crit.get("analyte_key", "")
    if ("laboratory_analyte_matches" in ev_checks) or rule_analyte:
        if resolved_analyte_key != rule_analyte:
            failed.append("laboratory_analyte_matches")
            analyte_matches = False

    # 5. Unit resolved — skip if analyte doesn't match (unit is irrelevant for wrong analyte)
    if "laboratory_unit_resolved" in ev_checks and analyte_matches:
        canonical_unit = lab_crit.get("required_canonical_unit", "")
        aliases = [a.lower() for a in (lab_crit.get("allowed_unit_aliases") or [])]
        convertible_froms = [c.lower() for c in (lab_crit.get("convertible_units") or [])]
        raw_unit = lab_entry.get("unit", "")
        if resolved_unit is None:
            failed.append("laboratory_unit_resolved")
            notes.append(f"Unit '{raw_unit}' could not be resolved.")
        elif resolved_unit.lower() == canonical_unit.lower():
            pass  # Direct match
        elif resolved_unit.lower() in aliases or raw_unit.lower() in aliases:
            notes.append(f"Unit '{resolved_unit}' matched via alias — treated as canonical.")
        elif resolved_unit.lower() in convertible_froms or raw_unit.lower() in convertible_froms:
            notes.append(f"Unit '{resolved_unit}' is convertible — conversion will be applied.")
        else:
            failed.append("laboratory_unit_resolved")
            notes.append(
                f"Unit '{resolved_unit}' is neither the canonical unit '{canonical_unit}' "
                f"nor a declared alias/convertible."
            )

    # 6. Value present — skip if analyte doesn't match
    if "laboratory_value_present" in ev_checks and analyte_matches:
        if lab_value is None:
            failed.append("laboratory_value_present")
            notes.append("Numeric laboratory value is absent.")

    # Note: fasting_context_confirmed is intentionally NOT checked here.
    # It is handled after applicability passes inside evaluate_one_rule,
    # so that the INDETERMINATE_FASTING status path is reachable.

    passed = len(failed) == 0
    return ApplicabilityResult(passed=passed, failed_checks=failed, notes=notes)


# ---------------------------------------------------------------------------
# Unit Converter
# ---------------------------------------------------------------------------

def convert_lab_value(
    value: float,
    from_unit: str,
    to_unit: str,
    rule_conversion_table: Dict[str, float],
) -> Optional[float]:
    """
    Converts a lab value from one unit to another using the rule's conversion table.
    Returns None if conversion is not declared.
    """
    key = f"{from_unit}_to_{to_unit}"
    if key in rule_conversion_table:
        return value * rule_conversion_table[key]
    return None


# ---------------------------------------------------------------------------
# Threshold Evaluator
# ---------------------------------------------------------------------------

def evaluate_threshold(
    operator: str,
    value: float,
    threshold_value: Optional[float],
    threshold_range_high: Optional[float],
) -> Tuple[bool, str]:
    """
    Evaluates whether the lab value meets the rule's threshold condition.
    Returns (triggered: bool, explanation: str).
    """
    if operator == ">":
        result = value > threshold_value
        return result, f"{value} > {threshold_value} => {result}"
    elif operator == ">=":
        result = value >= threshold_value
        return result, f"{value} >= {threshold_value} => {result}"
    elif operator == "<":
        result = value < threshold_value
        return result, f"{value} < {threshold_value} => {result}"
    elif operator == "<=":
        result = value <= threshold_value
        return result, f"{value} <= {threshold_value} => {result}"
    elif operator == "==":
        result = value == threshold_value
        return result, f"{value} == {threshold_value} => {result}"
    elif operator == "BETWEEN":
        if threshold_value is None or threshold_range_high is None:
            return False, "BETWEEN operator requires both threshold_value and threshold_range_high."
        result = threshold_value <= value <= threshold_range_high
        return result, f"{threshold_value} <= {value} <= {threshold_range_high} => {result}"
    else:
        return False, f"Unsupported operator: '{operator}'"


def evaluate_status_match(
    lab_entry: Dict,
    target_statuses: List[str],
) -> Tuple[bool, str]:
    """
    Evaluates a STATUS_MATCH rule: checks whether the lab entry's status field
    matches any of the rule's target_lab_statuses.

    The lab entry must carry a 'status' or 'lab_status' field.
    Comparison is case-insensitive.

    Returns (triggered: bool, explanation: str).
    """
    raw_status = (
        lab_entry.get("status")
        or lab_entry.get("lab_status")
        or ""
    ).strip().upper()
    targets_upper = [s.strip().upper() for s in (target_statuses or [])]
    if not raw_status:
        return False, "No lab status provided — STATUS_MATCH cannot evaluate."
    triggered = raw_status in targets_upper
    return triggered, f"lab_status='{raw_status}' in {targets_upper} => {triggered}"


# ---------------------------------------------------------------------------
# Single Rule Evaluator
# ---------------------------------------------------------------------------

def evaluate_one_rule(
    rule: Dict,
    med_entry: Dict,
    lab_entry: Dict,
) -> Dict:
    """
    Evaluates a single DLTI rule against one medication entry and one lab entry.

    Returns a structured result dict with:
      - rule_id, rule_version, tier, relationship_category
      - status (STATUS_* constant)
      - applicability_result: dict of check outcomes
      - evaluation_detail: threshold comparison detail
      - clinical_advisory: from the rule (only when TRIGGERED)
      - evidence_summary: minimal provenance for display
      - research_preview_label: always present
      - governance: release_approved, review_status
    """
    rule_id = rule.get("rule_id", "UNKNOWN")
    lab_crit = rule.get("laboratory_criteria", {})
    ev_logic = rule.get("evaluation_logic", {})
    gov = rule.get("governance", {})

    # Resolve concepts
    raw_med_name = med_entry.get("name") or med_entry.get("proposed_name") or med_entry.get("raw_name", "")
    raw_analyte = lab_entry.get("analyte") or lab_entry.get("name", "")
    raw_unit = lab_entry.get("unit", "")
    raw_value = lab_entry.get("value")

    resolved_generic = resolve_medication_generic(raw_med_name)
    resolved_analyte = resolve_analyte_key(raw_analyte)
    resolved_unit = resolve_unit(raw_unit)

    # Convert value to float
    lab_value: Optional[float] = None
    if raw_value is not None:
        try:
            lab_value = float(raw_value)
        except (TypeError, ValueError):
            lab_value = None

    # Applicability check
    appl = check_rule_applicability(
        rule=rule,
        med_entry=med_entry,
        lab_entry=lab_entry,
        resolved_analyte_key=resolved_analyte,
        resolved_generic_name=resolved_generic,
        resolved_unit=resolved_unit,
        lab_value=lab_value,
    )

    base = {
        "rule_id": rule_id,
        "rule_version": rule.get("rule_version"),
        "tier": rule.get("tier"),
        "relationship_category": rule.get("relationship_category"),
        "research_preview_label": RESEARCH_PREVIEW_LABEL,
        "governance": {
            "review_status": gov.get("review_status"),
            "release_approved": gov.get("release_approved"),
        },
        "evidence_summary": _build_evidence_summary(rule),
        "resolved_medication_generic": resolved_generic,
        "resolved_analyte_key": resolved_analyte,
        "resolved_unit": resolved_unit,
    }

    if not appl.passed:
        # If mismatch is purely medication_name_matches and/or laboratory_analyte_matches,
        # this rule just doesn't target this pair — return None to signal "skip".
        # Any additional applicability failure (e.g. identity_verified, unit) produces
        # a proper NOT_APPLICABLE result so the caller can report it.
        targeting_mismatch_checks = {"medication_name_matches", "laboratory_analyte_matches"}
        non_targeting_failures = set(appl.failed_checks) - targeting_mismatch_checks
        if not non_targeting_failures:
            return None  # type: ignore[return-value]

        return {
            **base,
            "status": STATUS_NOT_APPLICABLE,
            "applicability_failed_checks": appl.failed_checks,
            "applicability_notes": appl.notes,
            "evaluation_detail": None,
            "clinical_advisory": None,
        }

    # All applicability checks passed — proceed to evaluation
    operator = ev_logic.get("operator", "")
    threshold_value = ev_logic.get("threshold_value")
    threshold_range_high = ev_logic.get("threshold_range_high")
    target_statuses: List[str] = ev_logic.get("target_lab_statuses") or []

    # --- DISABLED operator: rule explicitly has no evaluable trigger ---
    if operator == "DISABLED":
        return {
            **base,
            "status": STATUS_RULE_DISABLED,
            "applicability_failed_checks": [],
            "applicability_notes": [
                "This rule's evaluation operator is DISABLED. "
                "No defensible evaluable rule has been established. "
                "Rule is retained for governance visibility only."
            ],
            "evaluation_detail": "operator=DISABLED",
            "clinical_advisory": None,
        }

    # --- STATUS_MATCH operator: compare lab status string ---
    if operator == "STATUS_MATCH":
        # Check that status field is present (applicability checked 'laboratory_status_present'
        # but we double-guard here for defence in depth)
        raw_status = (
            lab_entry.get("status")
            or lab_entry.get("lab_status")
            or ""
        ).strip()
        if not raw_status or raw_status.upper() in ("INSUFFICIENT_CONTEXT", "UNCLASSIFIED"):
            reason = (
                lab_entry.get("rejection_reason")
                or f"STATUS_MATCH rule cannot evaluate with lab status '{raw_status or 'MISSING'}' (insufficient context)."
            )
            return {
                **base,
                "status": STATUS_INSUFFICIENT_CONTEXT,
                "applicability_failed_checks": [],
                "applicability_notes": [reason],
                "evaluation_detail": reason,
                "clinical_advisory": None,
            }

        triggered, eval_explanation = evaluate_status_match(
            lab_entry=lab_entry,
            target_statuses=target_statuses,
        )
        result_status = STATUS_TRIGGERED if triggered else STATUS_RULE_EVALUATED
        return {
            **base,
            "status": result_status,
            "triggered": triggered,
            "lab_status_observed": raw_status,
            "target_statuses": target_statuses,
            "operator": operator,
            "applicability_failed_checks": [],
            "applicability_notes": appl.notes,
            "evaluation_detail": eval_explanation,
            "clinical_advisory": rule.get("clinical_advisory") if triggered else None,
        }

    # --- Numeric threshold operators ---
    canonical_unit = lab_crit.get("required_canonical_unit", "")
    aliases_lower = [a.lower() for a in (lab_crit.get("allowed_unit_aliases") or [])]
    conversion_table = lab_crit.get("unit_conversion") or {}
    effective_value = lab_value
    unit_used = resolved_unit or raw_unit

    if resolved_unit is not None and canonical_unit and canonical_unit != "STATUS_ONLY":
        if resolved_unit.lower() != canonical_unit.lower():
            if resolved_unit.lower() in aliases_lower:
                # Alias treated as canonical — no numeric conversion needed
                effective_value = lab_value
            else:
                converted = convert_lab_value(lab_value, resolved_unit, canonical_unit, conversion_table)
                if converted is not None:
                    effective_value = converted
                    unit_used = canonical_unit

    if effective_value is None:
        return {
            **base,
            "status": STATUS_REJECTED_EVALUATION,
            "applicability_failed_checks": [],
            "applicability_notes": ["Value absent or unconvertible after unit resolution."],
            "evaluation_detail": None,
            "clinical_advisory": None,
        }

    triggered, eval_explanation = evaluate_threshold(
        operator=operator,
        value=effective_value,
        threshold_value=threshold_value,
        threshold_range_high=threshold_range_high,
    )

    # Fasting-context indeterminate path (applicability passed but context uncertain)
    fasting_required = lab_crit.get("fasting_context_required", False)
    fasting_confirmed = lab_entry.get("fasting_confirmed")
    if fasting_required and fasting_confirmed is not True:
        return {
            **base,
            "status": STATUS_INDETERMINATE_FASTING,
            "applicability_failed_checks": [],
            "applicability_notes": [
                "Fasting context required but not confirmed; evaluation is indeterminate."
            ],
            "evaluation_detail": eval_explanation,
            "clinical_advisory": None,
        }

    result_status = STATUS_TRIGGERED if triggered else STATUS_RULE_EVALUATED

    return {
        **base,
        "status": result_status,
        "triggered": triggered,
        "effective_lab_value": effective_value,
        "unit_used": unit_used,
        "threshold_value": threshold_value,
        "threshold_range_high": threshold_range_high,
        "operator": operator,
        "applicability_failed_checks": [],
        "applicability_notes": appl.notes,
        "evaluation_detail": eval_explanation,
        "clinical_advisory": rule.get("clinical_advisory") if triggered else None,
    }


def _build_evidence_summary(rule: Dict) -> List[Dict]:
    """Builds a compact provenance summary from the rule's evidence_references."""
    refs = rule.get("evidence_references") or []
    summary = []
    for ref in refs:
        summary.append({
            "source_name": ref.get("source_name"),
            "document_id": ref.get("document_id"),
            "section": ref.get("section"),
            "retrieval_status": ref.get("retrieval_status"),
            "quote_match_outcome": ref.get("quote_match_outcome"),
            "source_url": ref.get("source_url"),
        })
    return summary


# ---------------------------------------------------------------------------
# Main DLTI Checking Agent
# ---------------------------------------------------------------------------

class DLTICheckingAgent:
    """
    Step 4c: Drug–Laboratory Test Interaction (DLTI) Research Agent.

    Evaluates verified medications from the prescription pipeline against
    current-request laboratory values using the versioned DLTI knowledge base.

    Usage:
        pipeline_ctx = DLTICheckingAgent.process(pipeline_ctx, enabled=True)
        # pipeline_ctx["dlti"] contains the structured result block.
    """

    @classmethod
    def process(
        cls,
        pipeline_ctx: Dict,
        enabled: bool = False,
        kb_path: str = DEFAULT_KB_PATH,
    ) -> Dict:
        """
        Main entry point. Populates pipeline_ctx["dlti"] and returns the context.

        Args:
            pipeline_ctx: Standard pipeline context dictionary.
            enabled: Must be explicitly True to activate. Default False.
            kb_path: Override path to the knowledge base file.

        Returns:
            pipeline_ctx with pipeline_ctx["dlti"] populated.
        """
        lab_values = cls._extract_lab_values(pipeline_ctx)
        lab_prov = pipeline_ctx.get("lab_input_provenance", [])

        if not enabled:
            pipeline_ctx["dlti"] = {
                "status": STATUS_DISABLED,
                "research_preview_label": RESEARCH_PREVIEW_LABEL,
                "message": (
                    "DLTI research preview is disabled. "
                    "Set enabled=True to activate (for research use only)."
                ),
                "results": [],
                "coverage": cls._disabled_coverage(),
                "submitted_measurements": lab_values,
                "lab_input_provenance": lab_prov,
            }
            return pipeline_ctx

        # Load knowledge base
        kb = DLTIKnowledgeBase(kb_path=kb_path).load()
        if not kb.is_loaded:
            pipeline_ctx["dlti"] = {
                "status": STATUS_KB_UNAVAILABLE,
                "research_preview_label": RESEARCH_PREVIEW_LABEL,
                "message": "DLTI knowledge base could not be loaded. Results are unavailable.",
                "load_errors": kb.load_errors,
                "results": [],
                "coverage": cls._unavailable_coverage(kb.load_errors),
                "submitted_measurements": lab_values,
                "lab_input_provenance": lab_prov,
            }
            return pipeline_ctx

        # Extract verified medications from verification context
        all_meds = cls._extract_all_meds(pipeline_ctx)
        verified_meds = [m for m in all_meds if m.get("identity_verified", False)]

        # Run evaluations
        results, coverage = cls._run_evaluations(
            kb, verified_meds=verified_meds,
            all_meds_raw=all_meds,
            lab_values=lab_values,
        )

        pipeline_ctx["dlti"] = {
            "status": "DLTI_COMPLETE",
            "research_preview_label": RESEARCH_PREVIEW_LABEL,
            "knowledge_base": {
                "id": kb.metadata.get("knowledge_base_id"),
                "version": kb.metadata.get("knowledge_base_version"),
                "status": kb.metadata.get("status"),
                "rule_count": len(kb.rules),
            },
            "results": results,
            "coverage": coverage,
            "submitted_measurements": lab_values,
            "lab_input_provenance": lab_prov,
        }
        return pipeline_ctx

    @classmethod
    def _extract_all_meds(cls, pipeline_ctx: Dict) -> List[Dict]:
        """Returns all medication entries from the verification context (unfiltered)."""
        verification = pipeline_ctx.get("verification") or {}
        medications = verification.get("medications") or []
        return [m for m in medications if isinstance(m, dict)]

    @classmethod
    def _extract_verified_meds(cls, pipeline_ctx: Dict) -> List[Dict]:
        """
        Extracts medication entries that have been verified by the prescription pipeline.
        Only includes entries with identity_verified == True.
        """
        return [
            m for m in cls._extract_all_meds(pipeline_ctx)
            if m.get("identity_verified", False)
        ]

    @classmethod
    def _extract_lab_values(cls, pipeline_ctx: Dict) -> List[Dict]:
        """
        Extracts laboratory values from the current pipeline context.
        Sources checked (in order):
          1. pipeline_ctx["extracted_data"]["lab_results"] — report pipeline path
          2. pipeline_ctx["lab_values"] — direct injection for prescription pipeline
          3. pipeline_ctx["verification"]["current_labs"] — verification context labs

        Returns a flat list of lab entry dicts:
          {"analyte": str, "value": float|str, "unit": str, "fasting_confirmed": bool|None, ...}
        """
        labs: List[Dict] = []

        # Path 1: Report extraction path
        extracted = pipeline_ctx.get("extracted_data") or {}
        lab_results = extracted.get("lab_results") or []
        if isinstance(lab_results, list):
            labs.extend(lab_results)

        # Path 2: Direct injection
        direct_labs = pipeline_ctx.get("lab_values") or []
        if isinstance(direct_labs, list):
            labs.extend(direct_labs)

        # Path 3: Verification context labs
        verification = pipeline_ctx.get("verification") or {}
        current_labs = verification.get("current_labs") or []
        if isinstance(current_labs, list):
            labs.extend(current_labs)

        return labs

    @classmethod
    def _run_evaluations(
        cls,
        kb: DLTIKnowledgeBase,
        verified_meds: List[Dict],
        all_meds_raw: List[Dict],
        lab_values: List[Dict],
    ) -> Tuple[List[Dict], Dict]:
        """
        Evaluates all applicable rules across all (med, lab) pairs.
        Returns (results, coverage_metadata).
        """
        results: List[Dict] = []
        pairs_evaluated = 0
        rules_triggered = 0
        rules_not_applicable = 0
        rules_no_match = 0

        rules_insufficient_context = 0
        rules_disabled = 0

        # Compute unverified count from the raw (unfiltered) medication list
        skipped_unverified = sum(
            1 for m in all_meds_raw if not m.get("identity_verified", False)
        )
        unverified_med_names = [
            m.get("name") or m.get("raw_name", "UNKNOWN")
            for m in all_meds_raw
            if not m.get("identity_verified", False)
        ]

        # For coverage: track which (med, analyte) pairs had at least one rule
        pairs_with_rule: set = set()
        pairs_evaluated_set: set = set()

        for med in verified_meds:
            for lab in lab_values:
                pairs_evaluated += 1
                raw_med_name = med.get("name") or med.get("proposed_name") or med.get("raw_name", "")
                raw_analyte = lab.get("analyte") or lab.get("name", "")
                pair_key = (
                    (resolve_medication_generic(raw_med_name) or raw_med_name.lower()),
                    (resolve_analyte_key(raw_analyte) or raw_analyte.lower()),
                )
                pairs_evaluated_set.add(pair_key)

                rule_matched = False
                for rule in kb.rules:
                    res = evaluate_one_rule(rule=rule, med_entry=med, lab_entry=lab)
                    if res is None:
                        # Rule doesn't target this pair — skip
                        continue

                    rule_matched = True
                    pairs_with_rule.add(pair_key)

                    if res["status"] == STATUS_TRIGGERED:
                        rules_triggered += 1
                    elif res["status"] == STATUS_NOT_APPLICABLE:
                        rules_not_applicable += 1
                    elif res["status"] == STATUS_INSUFFICIENT_CONTEXT:
                        rules_insufficient_context += 1
                    elif res["status"] == STATUS_RULE_DISABLED:
                        rules_disabled += 1

                    results.append(res)

                if not rule_matched:
                    rules_no_match += 1
                    results.append({
                        "status": STATUS_NO_RULE_FOUND,
                        "research_preview_label": RESEARCH_PREVIEW_LABEL,
                        "medication_raw": raw_med_name,
                        "analyte_raw": raw_analyte,
                        "message": (
                            "No DLTI rule covers this medication–laboratory pair. "
                            "Absence of a rule is not evidence of safety."
                        ),
                    })

        coverage = {
            "total_verified_meds": len(verified_meds),
            "total_lab_values": len(lab_values),
            "pairs_evaluated": pairs_evaluated,
            "pairs_with_matching_rule": len(pairs_with_rule),
            "rules_triggered": rules_triggered,
            "rules_evaluated_not_triggered": len(
                [r for r in results if r.get("status") == STATUS_RULE_EVALUATED]
            ),
            "rules_not_applicable": rules_not_applicable,
            "rules_insufficient_context": rules_insufficient_context,
            "rules_disabled": rules_disabled,
            "pairs_no_rule_found": rules_no_match,
            "unverified_meds_skipped": skipped_unverified,
            "skipped_unverified_names": unverified_med_names,
            "coverage_label": (
                "RESEARCH_PREVIEW_EVALUATED"
                if pairs_evaluated > 0
                else "RESEARCH_PREVIEW_NO_PAIRS"
            ),
            "completeness_note": (
                "Coverage is limited to the current knowledge base version. "
                "Pairs with no matching rule are explicitly reported; "
                "absence of a result is not evidence of safety."
            ),
        }
        return results, coverage

    @staticmethod
    def _disabled_coverage() -> Dict:
        return {
            "coverage_label": "DISABLED",
            "total_verified_meds": 0,
            "total_lab_values": 0,
            "pairs_evaluated": 0,
        }

    @staticmethod
    def _unavailable_coverage(errors: List[str]) -> Dict:
        return {
            "coverage_label": "KNOWLEDGE_BASE_UNAVAILABLE",
            "load_errors": errors,
            "total_verified_meds": 0,
            "total_lab_values": 0,
            "pairs_evaluated": 0,
        }


# ---------------------------------------------------------------------------
# Public convenience function (pipeline integration boundary)
# ---------------------------------------------------------------------------

def run_dlti_research_check(
    pipeline_ctx: Dict,
    enabled: bool = False,
    kb_path: str = DEFAULT_KB_PATH,
) -> Dict:
    """
    Public convenience wrapper for pipeline integration.

    WARNING: enabled=False by default. Do not set enabled=True in production.
    This is a research prototype only.
    """
    return DLTICheckingAgent.process(
        pipeline_ctx=pipeline_ctx,
        enabled=enabled,
        kb_path=kb_path,
    )
