"""
Unit Tests validating Pydantic models against G1 fixtures.
"""
import json
from pathlib import Path
import pytest
from fleet_governance_core.models import (
    ArtifactStorageIdentity,
    AuditEvent,
    DossierCase,
    FleetApprovalRecord,
    PDXApprovalDecision,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
    VerifierResult,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"

def test_dossier_case_models():
    for f in ["c2_dossier_case_happy_path.json", "c2_dossier_case_toxicology_fail.json", "c2_dossier_case_missing_data.json"]:
        raw = json.loads((FIXTURES_DIR / f).read_text(encoding="utf-8"))["data"]
        case = DossierCase.model_validate(raw)
        assert case.product_name == raw["product_name"]

def test_verifier_result_models():
    for f in ["c3_verifier_result_pass.json", "c3_verifier_result_fail.json", "c3_verifier_result_review.json"]:
        raw = json.loads((FIXTURES_DIR / f).read_text(encoding="utf-8"))["data"]
        res = VerifierResult.model_validate(raw)
        assert res.status.value == raw["status"]

def test_approval_and_checkpoint_models():
    chk_raw = json.loads((FIXTURES_DIR / "c4_workflow_checkpoint_sample.json").read_text(encoding="utf-8"))["data"]
    chk = PDXWorkflowCheckpoint.model_validate(chk_raw)
    assert chk.checkpoint_id == chk_raw["checkpoint_id"]

    req_raw = json.loads((FIXTURES_DIR / "c4_approval_request_sample.json").read_text(encoding="utf-8"))["data"]
    req = PDXApprovalRequest.model_validate(req_raw)
    assert str(req.approval_request_id) == req_raw["approval_request_id"]

    dec_raw = json.loads((FIXTURES_DIR / "c4_approval_decision_sample.json").read_text(encoding="utf-8"))["data"]
    dec = PDXApprovalDecision.model_validate(dec_raw)
    assert str(dec.decision_id) == dec_raw["decision_id"]

    fleet_raw = json.loads((FIXTURES_DIR / "c4_fleet_approval_record_sample.json").read_text(encoding="utf-8"))["data"]
    fleet_rec = FleetApprovalRecord.model_validate(fleet_raw)
    assert fleet_rec.tenant_id == fleet_raw["tenant_id"]

def test_storage_and_audit_models():
    storage_raw = json.loads((FIXTURES_DIR / "c5_storage_identity_sample.json").read_text(encoding="utf-8"))["data"]
    storage = ArtifactStorageIdentity.model_validate(storage_raw)
    assert storage.uri == storage_raw["uri"]

    audit_raw = json.loads((FIXTURES_DIR / "c6_audit_event_sample.json").read_text(encoding="utf-8"))["data"]
    audit = AuditEvent.model_validate(audit_raw)
    assert audit.tenant_id == audit_raw["tenant_id"]
