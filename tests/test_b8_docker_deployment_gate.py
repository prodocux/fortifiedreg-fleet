"""
Gate B8-Docker: Docker Container Integration & Packaging Conformance Suite.
Validates:
1. Dynamic OCI Revision-Pinned Docker Image Build (org.opencontainers.image.revision = Fleet HEAD SHA).
2. Inside-Image Package Provenance & Compatibility Manifest Verification (pdx==61cff57..., prodocux==c8acd2b...).
3. Fail-Closed Production Runtime Enforcement:
   - FLEET_ENV=production with fake PDX adapter -> fails-closed.
   - FLEET_ENV=production with fake intake adapter -> fails-closed.
   - Invalid mode values (e.g. 'liv') -> fails-closed with ValueError.
4. Non-Root Execution Security (fleetuser uid 10001).
5. Separated Health (/v1/health) and Readiness (/v1/ready) Probes.
6. Multi-Tenant Cryptographic Isolation within Container Network.
7. Five-Format Intake Registration, Checkpoint Execution, Single-Transaction Approval, and Artifact Generation (Container Integration).
8. Container Hard Kill (docker kill) & Persistent Volume Restart Recovery (SQLite + Artifacts volume recovery).
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple
from uuid import uuid4

import jwt
from openpyxl import Workbook
from pypdf import PdfWriter
import pytest
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT_DIR / "fixtures"

JWT_SECRET = "b8-docker-prod-deployment-secret-key-2026-fortified-998877665544332211"

EXPECTED_PDX_COMMIT = "61cff57ec7938165234dd895177dccade7ac1a5f"
EXPECTED_PRODOCUX_COMMIT = "c8acd2ba69c23458cb2589d8450246fe9b16424f"
EXPECTED_MANIFEST_SHA = "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303"


def get_current_git_commit() -> str:
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT_DIR), capture_output=True, text=True, check=True)
    return res.stdout.strip()


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


def wait_for_server(base_url: str, timeout_seconds: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            resp = requests.get(f"{base_url}/v1/health", timeout=1.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="session")
def docker_test_image():
    """Build a uniquely tagged test Docker image pinned to the current git HEAD commit."""
    try:
        check = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if check.returncode != 0:
            pytest.skip("Docker daemon is not running locally")
    except Exception:
        pytest.skip("Docker CLI not available")

    head_commit = get_current_git_commit()
    image_tag = f"fortifiedreg-fleet:test-{head_commit[:8]}"

    build_cmd = [
        "docker",
        "build",
        "--build-arg",
        f"GIT_COMMIT={head_commit}",
        "-t",
        image_tag,
        str(ROOT_DIR),
    ]
    subprocess.run(build_cmd, check=True, capture_output=True, text=True)

    yield image_tag, head_commit

    # Cleanup test image
    subprocess.run(["docker", "rmi", "-f", image_tag], capture_output=True, text=True)


class DockerContainerProcess:
    def __init__(
        self,
        image_tag: str,
        data_dir: Path,
        artifacts_dir: Path,
        port: int,
        extra_env: Optional[Dict[str, str]] = None,
    ):
        self.image_tag = image_tag
        self.data_dir = data_dir
        self.artifacts_dir = artifacts_dir
        self.port = port
        self.extra_env = extra_env or {}
        self.base_url = f"http://127.0.0.1:{port}"
        self.container_id = None
        self.container_name = f"fleet-test-{uuid4().hex[:8]}"

    def start(self):
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            self.container_name,
            "-p",
            f"{self.port}:8000",
            "-e",
            f"FLEET_JWT_SECRET={JWT_SECRET}",
            "-e",
            "FLEET_ENV=test",
            "-e",
            "FLEET_INTAKE_ADAPTER=fake",
            "-e",
            "FLEET_PDX_ADAPTER=fake",
            "-v",
            f"{self.data_dir.resolve()}:/app/data",
            "-v",
            f"{self.artifacts_dir.resolve()}:/app/artifacts",
        ]
        for k, v in self.extra_env.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.append(self.image_tag)

        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.container_id = res.stdout.strip()

        if not wait_for_server(self.base_url):
            logs = self.read_logs()
            self.stop()
            raise RuntimeError(f"Docker container failed to start within timeout. Logs:\n{logs}")

    def kill(self):
        """Simulate abrupt hard crash (docker kill) without graceful exit."""
        if self.container_name:
            subprocess.run(["docker", "kill", self.container_name], capture_output=True, text=True)
            subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True, text=True)
            self.container_id = None

    def stop(self):
        """Gracefully stop and remove container."""
        if self.container_name:
            subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True, text=True)
            self.container_id = None

    def read_logs(self) -> str:
        if self.container_name:
            res = subprocess.run(["docker", "logs", self.container_name], capture_output=True, text=True)
            return res.stdout + res.stderr
        return ""


@pytest.fixture
def docker_env(docker_test_image, tmp_path):
    image_tag, _ = docker_test_image
    port = get_free_port()
    data_dir = tmp_path / "docker_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = tmp_path / "docker_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    container = DockerContainerProcess(image_tag, data_dir, artifacts_dir, port)
    container.start()
    try:
        yield container
    finally:
        container.stop()


def generate_valid_document_bytes() -> Dict[str, Tuple[str, str, bytes]]:
    """Generate 5 valid binary documents for registration."""
    # 1. Valid PDF
    pdf_buf = io.BytesIO()
    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=100, height=100)
    pdf_writer.write(pdf_buf)
    pdf_bytes = pdf_buf.getvalue()

    # 2. Valid DOCX
    docx_bytes = (
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x00\x00!\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x13\x00\x00\x00[Content_Types].xml<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        b"<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"></Types>PK\x01\x02"
        b"\x14\x00\x14\x00\x00\x00\x08\x00\x00\x00!\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x13\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00[Content_Types].xmlPK\x05\x06\x00\x00"
        b"\x00\x00\x01\x00\x01\x00A\x00\x00\x00\x87\x00\x00\x00\x00\x00"
    )

    # 3. Valid CSV
    csv_bytes = b"inci_name,cas_number,percentage\nAqua,7732-18-5,85.0\nGlycerin,56-81-5,5.0\n"

    # 4. Valid XLSX
    xlsx_buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Ingredients"
    ws.append(["Component", "Percent"])
    ws.append(["Retinol", 0.05])
    wb.save(xlsx_buf)
    xlsx_bytes = xlsx_buf.getvalue()

    # 5. Valid PPTX
    pptx_bytes = (
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x00\x00!\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x13\x00\x00\x00[Content_Types].xml<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        b"<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"></Types>PK\x01\x02"
        b"\x14\x00\x14\x00\x00\x00\x08\x00\x00\x00!\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x13\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00[Content_Types].xmlPK\x05\x06\x00\x00"
        b"\x00\x00\x01\x00\x01\x00A\x00\x00\x00\x87\x00\x00\x00\x00\x00"
    )

    return {
        ".pdf": ("doc-sds-001", "safety_sheet.pdf", pdf_bytes),
        ".docx": ("doc-spec-001", "specification.docx", docx_bytes),
        ".csv": ("doc-table-001", "formulation.csv", csv_bytes),
        ".xlsx": ("doc-tox-001", "toxicology.xlsx", xlsx_bytes),
        ".pptx": ("doc-pres-001", "presentation.pptx", pptx_bytes),
    }


# ---------------------------------------------------------------------------
# B8-Docker Deployment Conformance Tests
# ---------------------------------------------------------------------------

def test_docker_image_provenance_and_revision_integrity(docker_test_image):
    """Verify that packages installed in the Docker image match exact upstream GitHub RC pins, compatibility manifest, and Fleet HEAD commit."""
    image_tag, head_commit = docker_test_image

    # 1. Verify OCI Image Revision Label
    inspect_cmd = ["docker", "inspect", image_tag, "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}']
    inspect_res = subprocess.run(inspect_cmd, capture_output=True, text=True, check=True)
    assert inspect_res.stdout.strip() == head_commit, f"Expected OCI revision {head_commit}, got {inspect_res.stdout.strip()}"

    # 2. Inspect direct_url.json inside container
    cmd = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python3",
        image_tag,
        "-c",
        """
import json, glob, sys
pdx_files = glob.glob('/usr/local/lib/python3.12/site-packages/pdx_artifact_core-*.dist-info/direct_url.json')
pdx_info = json.load(open(pdx_files[0])) if pdx_files else {}
pdx_commit = pdx_info.get("vcs_info", {}).get("commit_id", "")

prodocux_files = glob.glob('/usr/local/lib/python3.12/site-packages/prodocux-*.dist-info/direct_url.json')
pdx_doc_info = json.load(open(prodocux_files[0])) if prodocux_files else {}
prodocux_commit = pdx_doc_info.get("vcs_info", {}).get("commit_id", "")

import hashlib, pathlib
manifest_path = pathlib.Path('/app/compatibility/pdx_prodocux_compatibility_v1.json')
manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.exists() else ""

print(json.dumps({
    "pdx_commit": pdx_commit,
    "prodocux_commit": prodocux_commit,
    "manifest_sha": manifest_sha,
}))
""",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    provenance = json.loads(res.stdout.strip())

    assert provenance["pdx_commit"] == EXPECTED_PDX_COMMIT, f"Expected PDX pin {EXPECTED_PDX_COMMIT}, got {provenance['pdx_commit']}"
    assert provenance["prodocux_commit"] == EXPECTED_PRODOCUX_COMMIT, f"Expected ProDocuX pin {EXPECTED_PRODOCUX_COMMIT}, got {provenance['prodocux_commit']}"
    assert provenance["manifest_sha"] == EXPECTED_MANIFEST_SHA, f"Expected Manifest SHA {EXPECTED_MANIFEST_SHA}, got {provenance['manifest_sha']}"


def test_docker_production_mode_fails_closed_on_fake_adapters_or_bad_modes(docker_test_image):
    """Verify that container configured with FLEET_ENV=production rejects fake adapters and invalid modes."""
    image_tag, _ = docker_test_image

    # 1. FLEET_ENV=production with FLEET_PDX_ADAPTER=fake must exit with error
    cmd_fake_pdx = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_JWT_SECRET={JWT_SECRET}",
        "-e",
        "FLEET_ENV=production",
        "-e",
        "FLEET_PDX_ADAPTER=fake",
        "-e",
        "FLEET_INTAKE_ADAPTER=live",
        image_tag,
    ]
    res_fake_pdx = subprocess.run(cmd_fake_pdx, capture_output=True, text=True)
    assert res_fake_pdx.returncode != 0
    assert "Fail-closed: Fake PDX orchestrator is prohibited in production" in res_fake_pdx.stdout + res_fake_pdx.stderr

    # 2. FLEET_ENV=production with FLEET_INTAKE_ADAPTER=fake must exit with error
    cmd_fake_intake = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_JWT_SECRET={JWT_SECRET}",
        "-e",
        "FLEET_ENV=production",
        "-e",
        "FLEET_PDX_ADAPTER=live",
        "-e",
        "FLEET_INTAKE_ADAPTER=fake",
        image_tag,
    ]
    res_fake_intake = subprocess.run(cmd_fake_intake, capture_output=True, text=True)
    assert res_fake_intake.returncode != 0
    assert "Fail-closed: Fake intake adapter is prohibited in production" in res_fake_intake.stdout + res_fake_intake.stderr

    # 3. Invalid adapter typo (e.g. 'liv') must exit with error
    cmd_bad_mode = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_JWT_SECRET={JWT_SECRET}",
        "-e",
        "FLEET_ENV=test",
        "-e",
        "FLEET_PDX_ADAPTER=liv",
        image_tag,
    ]
    res_bad_mode = subprocess.run(cmd_bad_mode, capture_output=True, text=True)
    assert res_bad_mode.returncode != 0
    assert "Invalid FLEET_PDX_ADAPTER" in res_bad_mode.stdout + res_bad_mode.stderr

    # 4. Unknown FLEET_ENV typo (e.g. 'prodution') must exit with error
    cmd_bad_env = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_JWT_SECRET={JWT_SECRET}",
        "-e",
        "FLEET_ENV=prodution",
        "-e",
        "FLEET_PDX_ADAPTER=fake",
        "-e",
        "FLEET_INTAKE_ADAPTER=fake",
        image_tag,
    ]
    res_bad_env = subprocess.run(cmd_bad_env, capture_output=True, text=True)
    assert res_bad_env.returncode != 0
    assert "Invalid FLEET_ENV" in res_bad_env.stdout + res_bad_env.stderr

    # 5. Empty FLEET_ENV must exit with error
    cmd_empty_env = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_JWT_SECRET={JWT_SECRET}",
        "-e",
        "FLEET_ENV=",
        "-e",
        "FLEET_PDX_ADAPTER=fake",
        "-e",
        "FLEET_INTAKE_ADAPTER=fake",
        image_tag,
    ]
    res_empty_env = subprocess.run(cmd_empty_env, capture_output=True, text=True)
    assert res_empty_env.returncode != 0
    assert "FLEET_ENV cannot be empty" in res_empty_env.stdout + res_empty_env.stderr


def test_docker_non_root_execution_security(docker_test_image):
    """Verify that container executes as unprivileged non-root user (fleetuser, uid=10001)."""
    image_tag, _ = docker_test_image
    cmd = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "id",
        image_tag,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = res.stdout.strip()
    assert "uid=10001(fleetuser)" in output, f"Container must run as uid 10001, got: {output}"


def test_docker_health_and_ready_probes(docker_env):
    """Verify health and ready probe endpoints on running container."""
    # 1. Health Probe
    resp_health = requests.get(f"{docker_env.base_url}/v1/health")
    assert resp_health.status_code == 200
    data_health = resp_health.json()
    assert data_health["status"] == "healthy"
    assert data_health["environment"] == "test"

    # 2. Ready Probe
    resp_ready = requests.get(f"{docker_env.base_url}/v1/ready")
    assert resp_ready.status_code == 200
    data_ready = resp_ready.json()
    assert data_ready["status"] == "ready"


def test_docker_multi_tenant_isolation(docker_env):
    """Verify cryptographic tenant isolation inside the container."""
    token_tenant_a = make_jwt_token("tenant-acme-corp", "usr-cso-a", "cso@acme.com", "cso")
    token_tenant_b = make_jwt_token("tenant-globex-inc", "usr-cso-b", "cso@globex.com", "cso")

    headers_a = {"Authorization": f"Bearer {token_tenant_a}"}
    headers_b = {"Authorization": f"Bearer {token_tenant_b}"}

    # 1. Create case for Tenant A
    case_a_id = str(uuid4())
    raw_case_a = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_case_a["case_id"] = case_a_id
    raw_case_a["tenant_id"] = "tenant-acme-corp"

    create_resp = requests.post(f"{docker_env.base_url}/v1/dossiers/create", json=raw_case_a, headers=headers_a)
    assert create_resp.status_code == 200

    # 2. Tenant B cannot view Tenant A's case (404 Not Found)
    get_by_b = requests.get(f"{docker_env.base_url}/v1/dossiers/{case_a_id}", headers=headers_b)
    assert get_by_b.status_code == 404

    # 3. Tenant B cannot write under Tenant A tenant_id (403 Forbidden)
    bad_case = dict(raw_case_a, case_id=str(uuid4()), tenant_id="tenant-acme-corp")
    bad_create = requests.post(f"{docker_env.base_url}/v1/dossiers/create", json=bad_case, headers=headers_b)
    assert bad_create.status_code == 403


def test_docker_five_formats_integration_and_volume_restart(docker_env, docker_test_image, tmp_path):
    """
    Execute container integration lifecycle:
    1. Register 5 document formats (PDF, DOCX, CSV, XLSX, PPTX).
    2. Create dossier case and run to checkpoint.
    3. Submit CSO approval decision -> creates final artifact.
    4. Abruptly kill container (docker kill).
    5. Start new container on same data and artifacts volumes.
    6. Verify state recovery, idempotent replay, conflict rejection, and artifact integrity.
    """
    image_tag, _ = docker_test_image
    token_cso = make_jwt_token("tenant-acme-corp", "usr-cso-1", "cso@acme.com", "cso")
    auth_headers = {"Authorization": f"Bearer {token_cso}"}

    # 1. Register 5 supplier documents
    docs_map = generate_valid_document_bytes()
    doc_types = ["SDS", "COA", "GMP_CERT", "IFRA_CERT", "COA"]
    registered_docs = []

    for i, (ext, (doc_id, filename, raw_bytes)) in enumerate(docs_map.items()):
        reg_resp = requests.post(
            f"{docker_env.base_url}/v1/dossiers/documents/register",
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

    # 2. Create Dossier
    case_id = str(uuid4())
    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_case["case_id"] = case_id
    raw_case["tenant_id"] = "tenant-acme-corp"
    raw_case["supplier_documents"] = registered_docs

    create_resp = requests.post(f"{docker_env.base_url}/v1/dossiers/create", json=raw_case, headers=auth_headers)
    assert create_resp.status_code == 200

    # 3. Compile and Run to Checkpoint
    run_resp = requests.post(f"{docker_env.base_url}/v1/dossiers/{case_id}/compile-and-run", headers=auth_headers)
    assert run_resp.status_code == 200
    exec_data = run_resp.json()["execution"]
    assert exec_data["status"] == "awaiting_approval"

    checkpoint = exec_data["checkpoint"]
    approval_request_id = exec_data["approval_request_id"]

    # 4. Submit CSO Approval Decision
    idempotency_key = f"docker-idemp-{case_id[:8]}"
    decision_payload = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "run_id": checkpoint["run_id"],
        "approval_request_id": approval_request_id,
        "idempotency_key": idempotency_key,
        "decision": "approved",
        "reason": "Docker container integration verification approval",
        "case_digest": checkpoint["subject_digest"],
        "plan_digest": checkpoint["plan_digest"],
        "evidence_digests": checkpoint["evidence_digests"],
    }

    dec_resp = requests.post(f"{docker_env.base_url}/v1/approval/decide", json=decision_payload, headers=auth_headers)
    assert dec_resp.status_code == 200, f"Approval decision failed: {dec_resp.text}"
    dec_data = dec_resp.json()
    assert dec_data["status"] == "decided"
    assert dec_data["decision"] == "approved"
    artifact_ident = dec_data["artifact_identity"]

    # 5. Hard kill container
    data_dir = docker_env.data_dir
    artifacts_dir = docker_env.artifacts_dir
    port = docker_env.port

    docker_env.kill()

    # 6. Start new container on the same persistent volumes
    new_container = DockerContainerProcess(image_tag, data_dir, artifacts_dir, port)
    new_container.start()

    try:
        # Re-check case retrieval
        get_resp = requests.get(f"{new_container.base_url}/v1/dossiers/{case_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["case"]["case_id"] == case_id

        # Idempotent replay with same payload
        replay_resp = requests.post(f"{new_container.base_url}/v1/approval/decide", json=decision_payload, headers=auth_headers)
        assert replay_resp.status_code == 200
        assert replay_resp.json()["status"] == "decided"
        assert replay_resp.json()["is_idempotent_replay"] is True
        assert replay_resp.json()["artifact_identity"]["sha256"] == artifact_ident["sha256"]

        # Conflict on altered payload (409 Conflict)
        conflict_payload = dict(decision_payload, reason="Altered Reason After Container Restart")
        conflict_resp = requests.post(f"{new_container.base_url}/v1/approval/decide", json=conflict_payload, headers=auth_headers)
        assert conflict_resp.status_code == 409

    finally:
        new_container.stop()
