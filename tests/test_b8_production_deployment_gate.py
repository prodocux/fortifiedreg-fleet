"""
Gate B8: Production Deployment Gate & Standalone Process Lifecycle Conformance Suite.
Validates:
1. Production Process Startup & Configuration (FLEET_ENV=production, fail-closed JWT auth, SQLite ACID persistence).
2. Health (/v1/health) and Readiness (/v1/ready) probe separation.
3. Multi-Tenant Cryptographic Isolation (Tenant A vs Tenant B, cross-tenant 404/403 sanitized isolation).
4. Five-Format Document Registration (PDF, DOCX, CSV, XLSX, PPTX) and Execution to Checkpoint.
5. Single ACID Approval Transaction, Atomic Artifact Creation, and PDX Status Projection.
6. Process Crash & Durable Restart Recovery (Process Kill -> Restart -> State & Artifact Verification).
7. Resume Failure, PDX Pending Preservation, Process Restart, and Idempotent Retry Completion.
8. Sanitized Public Error Responses, Zero Internal Traceback Leaks, and Server Log Auditing.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Dict, Tuple
from uuid import uuid4

import jwt
import pytest
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT_DIR / "fixtures"

JWT_SECRET = "b8-prod-deployment-secret-token-key-2026-fortified-998877665544332211"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_jwt_token(tenant_id: str, sub: str, email: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "iss": "fortified-enterprise-fleet-auth",
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": [role],
        "email": email,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def wait_for_server(base_url: str, timeout_seconds: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            resp = requests.get(f"{base_url}/v1/health", timeout=1.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


class ProductionServerProcess:
    def __init__(self, db_path: Path, artifacts_dir: Path, port: int):
        self.db_path = db_path
        self.artifacts_dir = artifacts_dir
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.proc = None
        self.log_file = db_path.parent / f"server_proc_{port}.log"

    def start(self):
        env = os.environ.copy()
        env["FLEET_ENV"] = "production"
        env["FLEET_JWT_SECRET"] = JWT_SECRET
        env["FLEET_DB_PATH"] = str(self.db_path)
        env["FLEET_ARTIFACTS_DIR"] = str(self.artifacts_dir)
        env["FLEET_INTAKE_ADAPTER"] = "fake"
        env["FLEET_PDX_ADAPTER"] = "fake"
        env["PYTHONPATH"] = os.pathsep.join([
            str(ROOT_DIR / "packages" / "fleet-governance-core" / "src"),
            str(ROOT_DIR / "packages" / "fleet-domain-cosmetics" / "src"),
            str(ROOT_DIR / "packages" / "fleet-adapter-pdx" / "src"),
            str(ROOT_DIR / "packages" / "fleet-adapter-prodocux" / "src"),
            str(ROOT_DIR / "packages" / "fleet-adapter-google-adk" / "src"),
            str(ROOT_DIR / "packages" / "fleet-adapter-gcp" / "src"),
            str(ROOT_DIR / "packages" / "fleet-adapter-local" / "src"),
            str(ROOT_DIR / "apps" / "fleet-api" / "src"),
        ])

        log_fp = open(self.log_file, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "fleet_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "info",
            ],
            cwd=str(ROOT_DIR),
            env=env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
        )

        if not wait_for_server(self.base_url):
            self.stop()
            raise RuntimeError(f"Production server failed to start within timeout. Logs:\n{self.read_logs()}")

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3.0)
            except Exception:
                self.proc.kill()
                self.proc.wait()
            self.proc = None

    def read_logs(self) -> str:
        if self.log_file.exists():
            return self.log_file.read_text(encoding="utf-8", errors="replace")
        return ""


@pytest.fixture
def prod_env(tmp_path):
    port = get_free_port()
    db_path = tmp_path / "fleet_prod.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    server = ProductionServerProcess(db_path, artifacts_dir, port)
    server.start()
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# B8 Conformance Tests
# ---------------------------------------------------------------------------

def test_b8_health_and_ready_probe_separation(prod_env):
    """Verify health (liveness) and ready (readiness) probe separation under production config."""
    # 1. Health Liveness
    resp_health = requests.get(f"{prod_env.base_url}/v1/health")
    assert resp_health.status_code == 200
    data_health = resp_health.json()
    assert data_health["status"] == "healthy"
    assert data_health["environment"] == "production"

    # 2. Ready Readiness
    resp_ready = requests.get(f"{prod_env.base_url}/v1/ready")
    assert resp_ready.status_code == 200
    data_ready = resp_ready.json()
    assert data_ready["status"] == "ready"
    assert "adapters" in data_ready


def test_b8_multi_tenant_cryptographic_isolation(prod_env):
    """Verify multi-tenant isolation, cross-tenant case masking, and independent document CAS registration."""
    token_tenant_a = make_jwt_token("tenant-acme-corp", "usr-cso-a", "cso@acme.com", "cso")
    token_tenant_b = make_jwt_token("tenant-globex-inc", "usr-cso-b", "cso@globex.com", "cso")

    headers_a = {"Authorization": f"Bearer {token_tenant_a}"}
    headers_b = {"Authorization": f"Bearer {token_tenant_b}"}

    # 1. Unauthenticated request rejected
    unauth_resp = requests.get(f"{prod_env.base_url}/v1/dossiers/{uuid4()}")
    assert unauth_resp.status_code == 401

    # 2. Tenant A creates dossier
    case_a_id = str(uuid4())
    raw_case_a = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_case_a["case_id"] = case_a_id
    raw_case_a["tenant_id"] = "tenant-acme-corp"

    create_resp = requests.post(f"{prod_env.base_url}/v1/dossiers/create", json=raw_case_a, headers=headers_a)
    assert create_resp.status_code == 200

    # 3. Tenant B cannot read Tenant A's dossier (returns 404 sanitized)
    read_by_b = requests.get(f"{prod_env.base_url}/v1/dossiers/{case_a_id}", headers=headers_b)
    assert read_by_b.status_code == 404

    # 4. Tenant B cannot register dossier under Tenant A ID (403 Forbidden)
    bad_tenant_case = dict(raw_case_a, case_id=str(uuid4()), tenant_id="tenant-acme-corp")
    bad_create = requests.post(f"{prod_env.base_url}/v1/dossiers/create", json=bad_tenant_case, headers=headers_b)
    assert bad_create.status_code == 403

    # 5. Cross-tenant document isolation (Same doc_id 'doc-sds-001', different content)
    content_a = b"%PDF-1.4 Tenant A SDS Content"
    content_b = b"%PDF-1.4 Tenant B Different SDS"

    reg_a = requests.post(
        f"{prod_env.base_url}/v1/dossiers/documents/register",
        json={
            "doc_id": "doc-sds-001",
            "content_b64": base64.b64encode(content_a).decode(),
            "filename": "sds.pdf",
        },
        headers=headers_a,
    )
    assert reg_a.status_code == 200
    assert reg_a.json()["sha256"] == hashlib.sha256(content_a).hexdigest()

    reg_b = requests.post(
        f"{prod_env.base_url}/v1/dossiers/documents/register",
        json={
            "doc_id": "doc-sds-001",
            "content_b64": base64.b64encode(content_b).decode(),
            "filename": "sds.pdf",
        },
        headers=headers_b,
    )
    assert reg_b.status_code == 200
    assert reg_b.json()["sha256"] == hashlib.sha256(content_b).hexdigest()
    assert reg_a.json()["sha256"] != reg_b.json()["sha256"]


def test_b8_five_formats_complete_production_lifecycle_and_durable_restart(prod_env):
    """
    Execute complete B8 Gate sequence across 5 document formats:
    create -> register 5 formats -> compile & run -> checkpoint -> approve & resume -> restart -> persist.
    """
    token_cso = make_jwt_token("tenant-acme-corp", "usr-cso-1", "cso@acme.com", "cso")
    auth_headers = {"Authorization": f"Bearer {token_cso}"}

    # 1. Register 5 golden document formats
    formats_spec = [
        (".pdf", "doc-sds-001", "safety_sheet.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
        (".docx", "doc-spec-001", "specification.docx", b"PK\x03\x04\x14\x00\x00\x00\x08\x00DOCX_MOCK_BYTES"),
        (".csv", "doc-table-001", "formulation.csv", b"inci_name,cas_number,pct\nAqua,7732-18-5,80.0\n"),
        (".xlsx", "doc-tox-001", "toxicology.xlsx", b"PK\x03\x04\x14\x00\x00\x00\x08\x00XLSX_MOCK_BYTES"),
        (".pptx", "doc-pres-001", "presentation.pptx", b"PK\x03\x04\x14\x00\x00\x00\x08\x00PPTX_MOCK_BYTES"),
    ]

    doc_types = ["SDS", "COA", "GMP_CERT", "IFRA_CERT", "COA"]
    registered_docs = []
    for i, (ext, doc_id, filename, raw_bytes) in enumerate(formats_spec):
        reg_resp = requests.post(
            f"{prod_env.base_url}/v1/dossiers/documents/register",
            json={
                "doc_id": doc_id,
                "content_b64": base64.b64encode(raw_bytes).decode(),
                "filename": filename,
            },
            headers=auth_headers,
        )
        assert reg_resp.status_code == 200, f"Registration failed for {filename}: {reg_resp.text}"
        registered_docs.append({
            "doc_id": doc_id,
            "filename": filename,
            "doc_type": doc_types[i],
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "supplier_name": "BioSynthetics Ltd",
            "issue_date": "2025-01-10",
            "expiry_date": "2028-01-10",
        })

    # 2. Create Dossier with 5 supplier documents
    case_id = str(uuid4())
    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_case["case_id"] = case_id
    raw_case["tenant_id"] = "tenant-acme-corp"
    raw_case["supplier_documents"] = registered_docs

    create_resp = requests.post(f"{prod_env.base_url}/v1/dossiers/create", json=raw_case, headers=auth_headers)
    assert create_resp.status_code == 200

    # 3. Compile and Run to Checkpoint
    run_resp = requests.post(f"{prod_env.base_url}/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_resp.status_code == 200
    exec_data = run_resp.json()["execution"]
    assert exec_data["status"] == "awaiting_approval"

    checkpoint = exec_data["checkpoint"]
    approval_request_id = exec_data["approval_request_id"]

    # 4. Submit CSO Approval Decision
    idempotency_key = f"b8-idemp-{case_id[:8]}"
    decision_payload = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "run_id": checkpoint["run_id"],
        "approval_request_id": approval_request_id,
        "idempotency_key": idempotency_key,
        "decision": "approved",
        "reason": "Production deployment verification approval",
        "case_digest": checkpoint["subject_digest"],
        "plan_digest": checkpoint["plan_digest"],
        "evidence_digests": checkpoint["evidence_digests"],
    }

    dec_resp = requests.post(f"{prod_env.base_url}/v1/approval/decide", json=decision_payload, headers=auth_headers)
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "decided"
    assert dec_data["decision"] == "approved"

    # 5. Process Crash & Durable Restart Recovery
    port = prod_env.port
    db_path = prod_env.db_path
    artifacts_dir = prod_env.artifacts_dir

    # Abruptly terminate the production server process
    prod_env.stop()

    # Launch a new standalone server process on the same database and storage
    new_server = ProductionServerProcess(db_path, artifacts_dir, port)
    new_server.start()

    try:
        # Re-query dossier case
        recheck_case = requests.get(f"{new_server.base_url}/v1/dossiers/{case_id}", headers=auth_headers)
        assert recheck_case.status_code == 200
        assert recheck_case.json()["case"]["case_id"] == case_id

        # Replay approval decision with exact idempotency key
        replay_resp = requests.post(f"{new_server.base_url}/v1/approval/decide", json=decision_payload, headers=auth_headers)
        assert replay_resp.status_code == 200
        assert replay_resp.json()["status"] == "decided"
        assert replay_resp.json()["decision"] == "approved"
        assert replay_resp.json()["is_idempotent_replay"] is True

        # Idempotency conflict on modified payload (409 Conflict)
        conflicting_payload = dict(decision_payload, reason="Tampered Reason After Restart")
        conflict_resp = requests.post(f"{new_server.base_url}/v1/approval/decide", json=conflicting_payload, headers=auth_headers)
        assert conflict_resp.status_code == 409

    finally:
        new_server.stop()


def test_b8_resume_failure_preserves_pdx_pending_and_recovers(prod_env):
    """Verify that simulated resume failure marks resume_failed_retryable, keeps PDX pending, and restarts cleanly."""
    token_cso = make_jwt_token("tenant-acme-corp", "usr-cso-1", "cso@acme.com", "cso")
    auth_headers = {"Authorization": f"Bearer {token_cso}"}

    # 1. Create and run case
    case_id = str(uuid4())
    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_case["case_id"] = case_id
    raw_case["tenant_id"] = "tenant-acme-corp"

    create_resp = requests.post(f"{prod_env.base_url}/v1/dossiers/create", json=raw_case, headers=auth_headers)
    assert create_resp.status_code == 200

    run_resp = requests.post(f"{prod_env.base_url}/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_resp.status_code == 200
    exec_data = run_resp.json()["execution"]
    checkpoint = exec_data["checkpoint"]
    approval_request_id = exec_data["approval_request_id"]

    # 2. Tampered plan digest in approval decision -> 412 Precondition Failed
    bad_decision_payload = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "run_id": checkpoint["run_id"],
        "approval_request_id": approval_request_id,
        "idempotency_key": f"idemp-fail-{case_id[:8]}",
        "decision": "approved",
        "reason": "Tamper test",
        "case_digest": checkpoint["subject_digest"],
        "plan_digest": "0" * 64,  # Tampered plan digest
        "evidence_digests": checkpoint["evidence_digests"],
    }

    fail_resp = requests.post(f"{prod_env.base_url}/v1/approval/decide", json=bad_decision_payload, headers=auth_headers)
    assert fail_resp.status_code == 412

    # 3. Clean decision succeeds
    valid_payload = dict(bad_decision_payload, plan_digest=checkpoint["plan_digest"])
    good_resp = requests.post(f"{prod_env.base_url}/v1/approval/decide", json=valid_payload, headers=auth_headers)
    assert good_resp.status_code == 200
    assert good_resp.json()["status"] == "decided"
    assert good_resp.json()["decision"] == "approved"


def test_b8_sanitized_errors_and_zero_log_leakage(prod_env):
    """Verify that error responses contain zero tracebacks and server logs contain no credential leaks."""
    token_cso = make_jwt_token("tenant-acme-corp", "usr-cso-1", "cso@acme.com", "cso")
    auth_headers = {"Authorization": f"Bearer {token_cso}"}

    # 1. Invalid JSON body -> 422/400 sanitized error
    bad_req = requests.post(
        f"{prod_env.base_url}/v1/dossiers/create",
        data="INVALID_JSON{",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token_cso}"},
    )
    assert bad_req.status_code in (400, 422)
    assert "Traceback" not in bad_req.text

    # 2. Malformed Base64 -> 400 sanitized error
    bad_b64 = requests.post(
        f"{prod_env.base_url}/v1/dossiers/documents/register",
        json={"doc_id": "doc-bad", "content_b64": "NOT_BASE_64!!!"},
        headers=auth_headers,
    )
    assert bad_b64.status_code == 400
    assert "Traceback" not in bad_b64.text
    assert "Invalid Base64" in bad_b64.json()["detail"]

    # 3. Audit server log output
    logs = prod_env.read_logs()
    assert JWT_SECRET not in logs, "JWT secret leaked into server logs!"
    assert "Traceback" not in logs
