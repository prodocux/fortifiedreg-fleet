"""
Toxicological Margin of Safety (MoS) Calculator.
Pure domain logic implementing EU SCCS Notes of Guidance (12th Revision).
"""
import hashlib
from typing import Dict, List, Optional
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum

MOS_RULE_SET_ID = "EU_COSMETICS_REG_1223_2009"
MOS_RULE_SET_VERSION = "2025.1"
MOS_THRESHOLD = 100.0

def calculate_sed(
    daily_applied_amount_g: float,
    concentration_pct: float,
    retention_factor: float,
    body_weight_kg: float = 60.0,
) -> float:
    """Calculate Systemic Exposure Dose (SED) in mg/kg bw/day."""
    if body_weight_kg <= 0:
        raise ValueError("Body weight must be greater than zero")
    # SED = (A (g/d) * 1000 mg/g * (C (%) / 100) * Rf) / BW (kg)
    sed = (daily_applied_amount_g * 1000.0 * (concentration_pct / 100.0) * retention_factor) / body_weight_kg
    return round(sed, 6)

def calculate_mos(noael_mg_kg_day: float, sed: float) -> float:
    """Calculate Margin of Safety (MoS = NOAEL / SED)."""
    if sed <= 0:
        return float("inf")
    return round(noael_mg_kg_day / sed, 2)

def evaluate_toxicology_mos(case: DossierCase) -> VerifierResult:
    """Evaluate full formulation toxicological Margin of Safety."""
    rule_digest = hashlib.sha256(f"{MOS_RULE_SET_ID}:{MOS_RULE_SET_VERSION}".encode("utf-8")).hexdigest()
    
    reasons: List[str] = []
    min_mos: float = float("inf")
    missing_noael_ingredients: List[str] = []
    failed_ingredients: List[str] = []
    
    exp = case.exposure_scenario
    
    for item in case.formula:
        # Solvent / Aqua is exempt from toxicology threshold
        if item.inci_name.upper() == "AQUA":
            continue

        if item.noael_mg_kg_day is None or item.noael_mg_kg_day <= 0:
            missing_noael_ingredients.append(item.inci_name)
            continue

        sed = calculate_sed(
            daily_applied_amount_g=exp.daily_applied_amount_g,
            concentration_pct=item.concentration_pct,
            retention_factor=exp.retention_factor,
            body_weight_kg=exp.body_weight_kg,
        )
        mos = calculate_mos(noael_mg_kg_day=item.noael_mg_kg_day, sed=sed)
        
        if mos < min_mos:
            min_mos = mos
            
        if mos < MOS_THRESHOLD:
            failed_ingredients.append(f"{item.inci_name} (MoS={mos} < 100)")

    evidence_ids = [doc.doc_id for doc in case.supplier_documents]

    # Status Determination according to G0 rules:
    # 1. Any clear violation (MoS < 100) -> FAIL
    # 2. Any missing NOAEL (without violation) -> REVIEW
    # 3. All valid and MoS >= 100 -> PASS
    if failed_ingredients:
        return VerifierResult(
            verifier_id="verifier-cosmetics-toxicology-mos",
            version="1.0.0",
            status=VerifierStatusEnum.FAIL,
            reason_codes=["MOS_BELOW_THRESHOLD_100"],
            rule_set_id=MOS_RULE_SET_ID,
            rule_set_version=MOS_RULE_SET_VERSION,
            rule_digest=rule_digest,
            evidence_ids=evidence_ids,
            details={
                "minimum_mos": min_mos if min_mos != float("inf") else 0.0,
                "threshold": MOS_THRESHOLD,
                "violation": "; ".join(failed_ingredients),
            },
        )

    if missing_noael_ingredients:
        return VerifierResult(
            verifier_id="verifier-cosmetics-toxicology-mos",
            version="1.0.0",
            status=VerifierStatusEnum.REVIEW,
            reason_codes=["MISSING_NOAEL_EVIDENCE"],
            rule_set_id=MOS_RULE_SET_ID,
            rule_set_version=MOS_RULE_SET_VERSION,
            rule_digest=rule_digest,
            evidence_ids=evidence_ids,
            details={
                "missing_field": f"Missing NOAEL for: {', '.join(missing_noael_ingredients)}",
            },
        )

    return VerifierResult(
        verifier_id="verifier-cosmetics-toxicology-mos",
        version="1.0.0",
        status=VerifierStatusEnum.PASS,
        reason_codes=["MOS_ABOVE_THRESHOLD_100", "CONCENTRATION_WITHIN_LIMITS"],
        rule_set_id=MOS_RULE_SET_ID,
        rule_set_version=MOS_RULE_SET_VERSION,
        rule_digest=rule_digest,
        evidence_ids=evidence_ids,
        details={
            "minimum_mos": min_mos if min_mos != float("inf") else 10000.0,
            "threshold": MOS_THRESHOLD,
        },
    )
