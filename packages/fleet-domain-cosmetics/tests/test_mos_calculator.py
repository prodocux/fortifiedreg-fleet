"""
Unit Tests for MoS Calculator in fleet-domain-cosmetics.
"""
import json
from pathlib import Path
import pytest
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.verifier import VerifierStatusEnum
from fleet_domain_cosmetics.mos_calculator import (
    calculate_mos,
    calculate_sed,
    evaluate_toxicology_mos,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"

def test_sed_calculation_precision():
    # Face cream: 1.54 g/day, 0.8% Phenoxyethanol, Rf=1.0, BW=60kg
    # SED = (1.54 * 1000 * 0.008 * 1.0) / 60 = 0.205333 mg/kg bw/day
    sed = calculate_sed(1.54, 0.8, 1.0, 60.0)
    assert round(sed, 4) == 0.2053

def test_mos_calculation_precision():
    # NOAEL = 500 mg/kg/day, SED = 0.205333
    # MoS = 500 / 0.205333 = 2435.06
    mos = calculate_mos(500.0, 0.205333)
    assert round(mos, 1) == 2435.1

def test_evaluate_happy_path_pass():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_toxicology_mos(case)
    assert res.status == VerifierStatusEnum.PASS
    assert "MOS_ABOVE_THRESHOLD_100" in res.reason_codes

def test_evaluate_toxicology_fail():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_toxicology_fail.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_toxicology_mos(case)
    assert res.status == VerifierStatusEnum.FAIL
    assert "MOS_BELOW_THRESHOLD_100" in res.reason_codes

def test_evaluate_missing_noael_review():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_missing_data.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_toxicology_mos(case)
    assert res.status == VerifierStatusEnum.REVIEW
    assert "MISSING_NOAEL_EVIDENCE" in res.reason_codes
