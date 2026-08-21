"""
Hermetic Unit and Integration Tests for verify_remote.py CLI (v0.3.2).
Validates that verify_remote.py fails closed on readiness degraded, commit mismatch, package checksum tampering,
and successfully attestations produce canonical SHA-256 evidence.
"""
import json
from pathlib import Path
import unittest.mock as mock
import pytest
import requests
from starlette.testclient import TestClient

from fleet_api.main import app
from scripts.verify_remote import (
    compute_canonical_evidence_sha256,
    compute_canonical_package_sha256,
    run_remote_verification,
)


def test_canonical_checksum_computation():
    """Verify that canonical checksums are deterministic and exclude self-referencing checksum keys."""
    sample_evidence = {
        "evidence_type": "checksummed_remote_verification_evidence",
        "verified_at": "2026-08-21T10:00:00Z",
        "target_url": "https://example.com",
        "version": "0.3.2",
        "probes": {"health_probe": {"status": "PASS"}},
        "summary": "ALL_CHECKS_PASSED",
        "evidence_sha256": "fake_sha_to_be_excluded",
    }

    sha1 = compute_canonical_evidence_sha256(sample_evidence)
    assert len(sha1) == 64

    # Modifying excluded key does not change checksum
    sample_evidence["evidence_sha256"] = "different_sha"
    sha2 = compute_canonical_evidence_sha256(sample_evidence)
    assert sha1 == sha2

    # Modifying payload changes checksum
    sample_evidence["version"] = "0.3.3"
    sha3 = compute_canonical_evidence_sha256(sample_evidence)
    assert sha1 != sha3


def test_canonical_package_checksum_computation():
    """Verify that package checksum matches server logic."""
    client = TestClient(app)
    sess_res = client.post("/v1/demo/session", json={"persona": "formulator"})
    token = sess_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    from fleet_api.deps import audit_log
    from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum
    audit_log.append_audit_event(
        AuditEvent(
            tenant_id="tenant-demo",
            run_id="run-test-pkg-checksum",
            event_type=AuditEventTypeEnum.PLAN_COMPILED,
            actor_id="usr-test",
            payload={"plan_digest": "a" * 64, "case_digest": "b" * 64},
        )
    )

    ev_res = client.get("/v1/evidence/runs/run-test-pkg-checksum", headers=headers)
    assert ev_res.status_code == 200
    ev_data = ev_res.json()

    recomputed = compute_canonical_package_sha256(ev_data)
    assert ev_data["package_sha256"] == recomputed


def test_verify_remote_fails_on_readiness_503():
    """Verify that verify_remote fails if readiness is 503 or degraded."""
    def mock_get(url, *args, **kwargs):
        resp = requests.Response()
        if "/v1/health" in url:
            resp.status_code = 200
            resp._content = json.dumps({"status": "healthy", "version": "0.3.2"}).encode()
        elif "/v1/ready" in url:
            resp.status_code = 503
            resp._content = json.dumps({"status": "degraded", "adapters": {"intake": {"status": "unavailable"}}}).encode()
        else:
            resp.status_code = 200
            resp._content = b"{}"
        return resp

    with mock.patch("requests.get", side_effect=mock_get):
        success = run_remote_verification(base_url="https://mock-service.run.app", run_lifecycle=False)
        assert success is False


def test_verify_remote_fails_on_commit_mismatch():
    """Verify that verify_remote fails if expected git commit does not match remote version."""
    def mock_get(url, *args, **kwargs):
        resp = requests.Response()
        if "/v1/health" in url:
            resp.status_code = 200
            resp._content = json.dumps({"status": "healthy", "version": "0.3.2"}).encode()
        elif "/v1/ready" in url:
            resp.status_code = 200
            resp._content = json.dumps({"status": "ready", "adapters": {"intake": {"status": "ready"}, "orchestrator": {"status": "ready"}}}).encode()
        elif "/v1/version" in url:
            resp.status_code = 200
            resp._content = json.dumps({
                "fleet_version": "0.3.2",
                "fleet_commit": "1111111111111111111111111111111111111111",
                "cloud_run_revision": "fortifiedreg-fleet-00001-abc",
                "image_digest": "sha256:aaaa",
                "pdx_core_pin": "61cff57ec7938165234dd895177dccade7ac1a5f",
                "prodocux_pin": "c8acd2ba69c23458cb2589d8450246fe9b16424f",
                "compatibility_manifest_sha256": "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303",
            }).encode()
        else:
            resp.status_code = 200
            resp._content = b"{}"
        return resp

    with mock.patch("requests.get", side_effect=mock_get):
        success = run_remote_verification(
            base_url="https://mock-service.run.app",
            run_lifecycle=False,
            expected_fleet_commit="2222222222222222222222222222222222222222",
        )
        assert success is False


def test_verify_remote_fails_on_tampered_package_checksum():
    """Verify that verify_remote fails when evidence package checksum has been tampered."""
    tampered_package = {
        "package_type": "checksummed_evidence_package",
        "version": "0.3.2",
        "run_id": "run-test-1",
        "package_sha256": "bad_tampered_checksum_00000000000000000000000000000000000000000000",
        "artifact_identity": {"uri": "artifact://test", "sha256": "a" * 64},
    }

    def mock_get(url, *args, **kwargs):
        resp = requests.Response()
        if "/v1/health" in url:
            resp.status_code = 200
            resp._content = json.dumps({"status": "healthy", "version": "0.3.2"}).encode()
        elif "/v1/ready" in url:
            resp.status_code = 200
            resp._content = json.dumps({"status": "ready", "adapters": {"intake": {"status": "ready"}, "orchestrator": {"status": "ready"}}}).encode()
        elif "/v1/version" in url:
            resp.status_code = 200
            resp._content = json.dumps({
                "fleet_version": "0.3.2",
                "fleet_commit": "1111111111111111111111111111111111111111",
                "cloud_run_revision": "fortifiedreg-fleet-00001-abc",
                "pdx_core_pin": "61cff57ec7938165234dd895177dccade7ac1a5f",
                "prodocux_pin": "c8acd2ba69c23458cb2589d8450246fe9b16424f",
                "compatibility_manifest_sha256": "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303",
            }).encode()
        elif "/v1/verification/manifest" in url:
            resp.status_code = 200
            resp._content = json.dumps({
                "manifest_sha256": "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303",
                "verification_gates": {"B1_schema_contract": "PASS_LOCAL", "B7_lifecycle_conformance": "PASS_LOCAL"},
            }).encode()
        elif "/static/samples.json" in url:
            resp.status_code = 200
            resp._content = b"{}"
        elif "/v1/evidence/runs/" in url:
            resp.status_code = 200
            resp._content = json.dumps(tampered_package).encode()
        else:
            resp.status_code = 200
            resp._content = b"{}"
        return resp

    def mock_post(url, *args, **kwargs):
        resp = requests.Response()
        if "/v1/demo/session" in url:
            resp.status_code = 200
            resp._content = json.dumps({"tenant_id": "tenant-demo", "roles": ["demo_evaluator"], "access_token": "mock-token"}).encode()
        elif "/v1/security/scan" in url:
            resp.status_code = 200
            resp._content = json.dumps({"decision": "BLOCK"}).encode()
        else:
            resp.status_code = 200
            resp._content = b"{}"
        return resp

    with mock.patch("requests.get", side_effect=mock_get), mock.patch("requests.post", side_effect=mock_post):
        success = run_remote_verification(base_url="https://mock-service.run.app", run_lifecycle=True)
        assert success is False
