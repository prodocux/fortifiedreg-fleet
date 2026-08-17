"""
INCI Inventory & Annex Restriction Verifier.
Checks ingredients against Annex II (Prohibited) and Annex V (Preservative Limits) of Regulation (EC) No 1223/2009.
"""
import hashlib
from typing import Dict, List
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum

INCI_RULE_SET_ID = "EU_COSMETICS_REG_1223_2009_INCI"
INCI_RULE_SET_VERSION = "2025.1"

# Prohibited Substances (Annex II)
PROHIBITED_INCI = {
    "HYDROQUINONE",
    "MERCURY",
    "CHLOROFORM",
    "BITHIONOL",
    "VINYL CHLORIDE",
}

# Restricted Preservatives (Annex V) with Max Allowed Concentration %
RESTRICTED_PRESERVATIVES: Dict[str, float] = {
    "PHENOXYETHANOL": 1.0,
    "METHYLPARABEN": 0.4,
    "ETHYLPARABEN": 0.4,
    "PROPYLPARABEN": 0.14,
    "BENZYL ALCOHOL": 1.0,
    "SALICYLIC ACID": 0.5,
}

def evaluate_inci_compliance(case: DossierCase) -> VerifierResult:
    """Verify formulation ingredients against Annex II and Annex V restrictions."""
    rule_digest = hashlib.sha256(f"{INCI_RULE_SET_ID}:{INCI_RULE_SET_VERSION}".encode("utf-8")).hexdigest()
    evidence_ids = [doc.doc_id for doc in case.supplier_documents]

    violations: List[str] = []
    
    for item in case.formula:
        name_upper = item.inci_name.upper().strip()

        # 1. Annex II Prohibited Check
        if name_upper in PROHIBITED_INCI:
            violations.append(f"Prohibited substance {name_upper} (Annex II violation)")

        # 2. Annex V Preservative Limits Check
        if name_upper in RESTRICTED_PRESERVATIVES:
            max_allowed = RESTRICTED_PRESERVATIVES[name_upper]
            if item.concentration_pct > max_allowed:
                violations.append(
                    f"{name_upper} concentration {item.concentration_pct}% exceeds max allowed {max_allowed}% (Annex V)"
                )

    if violations:
        return VerifierResult(
            verifier_id="verifier-cosmetics-inci-compliance",
            version="1.0.0",
            status=VerifierStatusEnum.FAIL,
            reason_codes=["ANNEX_RESTRICTION_VIOLATION"],
            rule_set_id=INCI_RULE_SET_ID,
            rule_set_version=INCI_RULE_SET_VERSION,
            rule_digest=rule_digest,
            evidence_ids=evidence_ids,
            details={"violation": "; ".join(violations)},
        )

    return VerifierResult(
        verifier_id="verifier-cosmetics-inci-compliance",
        version="1.0.0",
        status=VerifierStatusEnum.PASS,
        reason_codes=["INCI_COMPLIANT"],
        rule_set_id=INCI_RULE_SET_ID,
        rule_set_version=INCI_RULE_SET_VERSION,
        rule_digest=rule_digest,
        evidence_ids=evidence_ids,
        details={"status": "All ingredients comply with Annex II and Annex V limits."},
    )
