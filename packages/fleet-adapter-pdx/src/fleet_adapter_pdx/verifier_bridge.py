"""
PDX Verifier Bridge.
Implements VerifierRegistryPort to dispatch domain verifiers.
"""
from typing import Any, Dict
from fleet_domain_cosmetics.inci_verifier import evaluate_inci_compliance
from fleet_domain_cosmetics.mos_calculator import evaluate_toxicology_mos
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum
from fleet_governance_core.ports.verifier_registry_port import VerifierRegistryPort

class PDXVerifierBridge(VerifierRegistryPort):
    """Bridges registered domain verifiers to PDX execution steps."""

    def run_verifier(self, verifier_id: str, payload: Dict[str, Any]) -> VerifierResult:
        case = DossierCase.model_validate(payload)
        
        if verifier_id == "verifier-cosmetics-toxicology-mos":
            return evaluate_toxicology_mos(case)
        elif verifier_id == "verifier-cosmetics-inci-compliance":
            return evaluate_inci_compliance(case)
        else:
            return VerifierResult(
                verifier_id=verifier_id,
                version="1.0.0",
                status=VerifierStatusEnum.FAIL,
                reason_codes=["UNKNOWN_VERIFIER_ID"],
                rule_set_id="CORE_REGISTRY",
                rule_set_version="1.0",
                rule_digest="0" * 64,
                evidence_ids=[],
                details={"error": f"Verifier '{verifier_id}' is not registered."},
            )
