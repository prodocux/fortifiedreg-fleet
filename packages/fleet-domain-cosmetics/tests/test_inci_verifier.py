"""
Unit Tests for INCI Verifier in fleet-domain-cosmetics.
"""
import json
from pathlib import Path
import pytest
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.verifier import VerifierStatusEnum
from fleet_domain_cosmetics.inci_verifier import evaluate_inci_compliance

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"

def test_inci_happy_path_pass():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_inci_compliance(case)
    assert res.status == VerifierStatusEnum.PASS
    assert "INCI_COMPLIANT" in res.reason_codes

def test_inci_prohibited_substance_fail():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    # Inject Hydroquinone (Annex II prohibited)
    case.formula.append(
        type(case.formula[0])(inci_name="HYDROQUINONE", concentration_pct=0.1)
    )
    res = evaluate_inci_compliance(case)
    assert res.status == VerifierStatusEnum.FAIL
    assert "ANNEX_RESTRICTION_VIOLATION" in res.reason_codes
    assert "HYDROQUINONE" in res.details["violation"]

def test_inci_preservative_exceeded_fail():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_toxicology_fail.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    # Phenoxyethanol is 2.5% > 1.0% limit
    res = evaluate_inci_compliance(case)
    assert res.status == VerifierStatusEnum.FAIL
    assert "PHENOXYETHANOL" in res.details["violation"]
