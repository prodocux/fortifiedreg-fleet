"""
Local End-to-End Vertical Slice Integration Test (v0.2.0).
Validates complete lifecycle: Create -> Compile -> Verify -> Blocked Review / Fail Stop / Checkpoint -> Decision -> Resume -> Manifest.
"""
import json
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from fleet_api.main import app
from fleet_api.security import create_access_token

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    token = create_access_token(
        tenant_id="tenant-acme-corp",
        sub="usr-chief-safety-officer",
        roles=["safety_assessor", "approver", "cso"],
        email="cso@acme.com",
    )
    return {"Authorization": f"Bearer {token}"}

def test_full_local_e2e_happy_path_lifecycle(client, auth_headers):
    # 1. Create Happy Path Dossier
    raw_happy = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    create_res = client.post("/v1/dossiers/create", json=raw_happy, headers=auth_headers)
    assert create_res.status_code == 200
    case_id = create_res.json()["case_id"]
    case_digest = create_res.json()["case_digest"]

    # 2. Compile and Execute Plan -> Pauses at Checkpoint
    run_res = client.post(f"/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_res.status_code == 200
    exec_data = run_res.json()["execution"]
    assert exec_data["status"] == "awaiting_approval"
    checkpoint = exec_data["checkpoint"]
    plan_digest = run_res.json()["plan_digest"]
    approval_request_id = exec_data["approval_request_id"]
    assert approval_request_id is not None
    assert "step_human_regulatory_approval" in checkpoint["pending_step_ids"]
    assert "step_assemble_pif_manifest" in checkpoint["pending_step_ids"]

    # 3. Human CSO Decides and Signs Off
    decision_body = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "run_id": checkpoint["run_id"],
        "approval_request_id": approval_request_id,
        "idempotency_key": f"idemp-{case_id[:8]}",
        "decision": "approved",
        "reason": "All toxicology parameters verified against SCCS 12th revision and Annex II/V restrictions.",
        "case_digest": case_digest,
        "plan_digest": plan_digest,
        "evidence_digests": checkpoint["evidence_digests"],
    }
    decide_res = client.post("/v1/approval/decide", json=decision_body, headers=auth_headers)
    assert decide_res.status_code == 200
    decide_json = decide_res.json()
    assert decide_json["status"] == "decided"
    assert decide_json["pdx_resume"]["status"] == "completed"
    assert decide_json["pdx_resume"]["final_manifest"]["status"] == "FINALIZED_COMPLIANT"

    # 4. Verify Immutable Audit Ledger Trail
    audit_res = client.get(f"/v1/audit/runs/{checkpoint['run_id']}", headers=auth_headers)
    assert audit_res.status_code == 200
    events = audit_res.json()
    event_types = [e["event_type"] for e in events]
    assert "CHECKPOINT_CREATED" in event_types
    assert "APPROVAL_DECIDED" in event_types

def test_local_e2e_toxicology_fail_stops_pipeline(client, auth_headers):
    raw_fail = json.loads((FIXTURES_DIR / "c2_dossier_case_toxicology_fail.json").read_text(encoding="utf-8"))["data"]
    create_res = client.post("/v1/dossiers/create", json=raw_fail, headers=auth_headers)
    case_id = create_res.json()["case_id"]

    run_res = client.post(f"/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_res.status_code == 200
    exec_data = run_res.json()["execution"]
    # Must fail early and stop without approval checkpoint
    assert exec_data["status"] == "failed"
    assert "checkpoint" not in exec_data

def test_local_e2e_missing_data_blocked_on_review(client, auth_headers):
    raw_missing = json.loads((FIXTURES_DIR / "c2_dossier_case_missing_data.json").read_text(encoding="utf-8"))["data"]
    create_res = client.post("/v1/dossiers/create", json=raw_missing, headers=auth_headers)
    case_id = create_res.json()["case_id"]

    run_res = client.post(f"/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_res.status_code == 200
    exec_data = run_res.json()["execution"]
    # Must block on review without reaching approval or finalization
    assert exec_data["status"] == "blocked_review"
    assert "checkpoint" not in exec_data
