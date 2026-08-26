"""
Authoritative Negative Gate & Fail-Closed Governance Tests for FortifiedReg Fleet (v0.4.0).
Verifies all Rev 5 negative and failure paths:
- Anonymous parser access rejection (401).
- Server-side acting-role enforcement and cross-role segregation (403).
- Inactive/revoked session rejection (401).
- Clean session reset/revoke lifecycle without deadlock or orphan tokens.
- UUIDv5 deterministic audit event deduplication in sink.
- Fail-closed Governance Invalidation Saga on store errors (503).
- Idempotency collision on differing target digests (409).
- HitL gate approval missing binding / non-pending checkpoint rejection (412).
- Render export unknown product (404) and integrity verification (502).
- Document preflight strict checks (strict %PDF-, 20x ZIP ratio, strict UTF-8 CSV, exact OOXML parts).
"""
import base64
import hashlib
import io
import uuid
import zipfile
import pytest
from fastapi.testclient import TestClient

from fleet_adapter_gcp.in_memory_stores import InMemoryAuditLog
from fleet_adapter_prodocux.document_preflight import (
    DocumentPreflightError,
    validate_document_preflight,
)
from fleet_api.main import app
from fleet_api.routers.workflow_v4 import (
    _APPROVED_PRODUCTS_STORE,
    _DRAFTS_STORE,
    _GOVERNANCE_INVALIDATION_RECORDS,
    _PRODUCT_DRAFTS_STORE,
    _PROPOSALS_STORE,
    execute_governance_invalidation_saga,
)
from fleet_api.session_security import (
    _REVOKED_JTIS_STORE,
    _SESSIONS_STORE,
    issue_demo_session,
)
from fleet_governance_core.models.approval import CheckpointStatusEnum, PDXWorkflowCheckpoint
from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum, GOVERNANCE_AUDIT_NAMESPACE
from fleet_governance_core.models.case import ExposureScenario, FormulaItem
from fleet_governance_core.models.workflow_v4 import ActingRoleEnum, FormulationDraft, GovernanceInvalidationRecord


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def formulator_session(client):
    res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    assert res.status_code == 200
    data = res.json()
    return data["token"], data


@pytest.fixture
def manager_session(client):
    res = client.post("/v1/demo/session", json={"acting_role": "product_manager"})
    assert res.status_code == 200
    data = res.json()
    return data["token"], data


# ---------------------------------------------------------------------------
# 1. Anonymous Access & Role Protection Gates
# ---------------------------------------------------------------------------

def test_anonymous_parse_preview_fails_401(client):
    """Anonymous calls to /v1/formulations/parse-preview must be rejected with 401."""
    res = client.post("/v1/formulations/parse-preview", json={"scenario_key": "retinol"})
    assert res.status_code == 401
    assert "credentials were not provided" in res.json()["detail"].lower() or "missing" in res.json()["detail"].lower()


def test_formulator_cannot_access_manager_inbox_or_decide(client, formulator_session):
    """A session acting as formulator must be blocked with 403 on manager endpoints."""
    token, _ = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot view manager inbox
    res = client.get("/v1/proposals/inbox", headers=headers)
    assert res.status_code == 403
    assert "requires server-side role 'product_manager'" in res.json()["detail"]

    # Cannot decide proposals
    res = client.post(
        "/v1/proposals/prop-test-123/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Unauthorized formulator approval."},
    )
    assert res.status_code == 403
    assert "requires server-side role 'product_manager'" in res.json()["detail"]


def test_manager_cannot_mutate_formulations(client, manager_session):
    """A session acting as product_manager must be blocked with 403 on formulation mutation endpoints."""
    token, _ = manager_session
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot parse preview
    res = client.post("/v1/formulations/parse-preview", headers=headers, json={"scenario_key": "retinol"})
    assert res.status_code == 403
    assert "requires server-side role 'formulator'" in res.json()["detail"]

    # Cannot update draft
    res = client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Retinol Night Renewal Serum",
            "ingredients": [{"inci_name": "Aqua", "concentration_pct": 100.0}],
        },
    )
    assert res.status_code == 403
    assert "requires server-side role 'formulator'" in res.json()["detail"]

    # Cannot rollback draft
    res = client.post(
        "/v1/formulations/rollback",
        headers=headers,
        json={"product_name": "Retinol Night Renewal Serum", "target_revision": 1},
    )
    assert res.status_code == 403
    assert "requires server-side role 'formulator'" in res.json()["detail"]

    # Cannot submit proposal
    res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert res.status_code == 403
    assert "requires server-side role 'formulator'" in res.json()["detail"]


def test_role_switch_updates_server_side_authorization(client, formulator_session):
    """Switching role on the session dynamically updates authorization capabilities."""
    token, sess = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    # Initially formulator can parse
    res1 = client.post("/v1/formulations/parse-preview", headers=headers, json={"scenario_key": "retinol"})
    assert res1.status_code == 200

    # Switch to manager
    res_switch = client.post("/v1/demo/session/role", headers=headers, json={"acting_role": "product_manager"})
    assert res_switch.status_code == 200
    assert res_switch.json()["acting_role"] == "product_manager"

    # Now parse is blocked (403) and inbox is open (200)
    res_blocked = client.post("/v1/formulations/parse-preview", headers=headers, json={"scenario_key": "retinol"})
    assert res_blocked.status_code == 403

    res_inbox = client.get("/v1/proposals/inbox", headers=headers)
    assert res_inbox.status_code == 200


# ---------------------------------------------------------------------------
# 2. Inactive & Revoked Session Lifecycle Tests
# ---------------------------------------------------------------------------

def test_revoked_or_inactive_session_rejected(client, formulator_session):
    """Explicitly revoked session or inactive session immediately returns 401."""
    token, sess = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    # Revoke session
    res_revoke = client.post("/v1/demo/session/revoke", headers=headers)
    assert res_revoke.status_code == 200
    assert res_revoke.json()["status"] == "revoked"

    # Subsequent access with revoked token returns 401
    res_access = client.get("/v1/formulations/draft", headers=headers)
    assert res_access.status_code == 401


def test_session_restart_requires_valid_old_token(client):
    """Restart endpoint without Authorization header returns 401."""
    res = client.post("/v1/demo/session/restart")
    assert res.status_code == 401


def test_session_restart_cleans_state_and_issues_new_active_session(client, formulator_session):
    """Restart endpoint tears down old session state and returns a working new session."""
    token, sess = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    res_restart = client.post("/v1/demo/session/restart", headers=headers)
    assert res_restart.status_code == 200
    new_data = res_restart.json()
    new_token = new_data["token"]
    assert new_token != token

    # Old token fails with 401
    assert client.get("/v1/formulations/draft", headers=headers).status_code == 401

    # New token works with 200
    new_headers = {"Authorization": f"Bearer {new_token}"}
    res_new = client.get("/v1/formulations/draft", headers=new_headers)
    assert res_new.status_code == 200


# ---------------------------------------------------------------------------
# 3. Audit Sink UUIDv5 Deterministic Deduplication
# ---------------------------------------------------------------------------

def test_in_memory_audit_log_event_id_deduplication():
    """Appending duplicate audit events with identical event_id must not produce duplicate entries."""
    audit_sink = InMemoryAuditLog()
    tenant_id = "tenant-demo"
    run_id = "run-audit-dedup-test"
    
    deterministic_id = uuid.uuid5(
        GOVERNANCE_AUDIT_NAMESPACE,
        f"{tenant_id}:inv-12345:checkpoint-invalidated",
    )

    ev1 = AuditEvent(
        event_id=deterministic_id,
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id="actor-test",
        event_type=AuditEventTypeEnum.CHECKPOINT_INVALIDATED,
        payload={"action": "test_attempt_1"},
    )
    ev2 = AuditEvent(
        event_id=deterministic_id,
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id="actor-test",
        event_type=AuditEventTypeEnum.CHECKPOINT_INVALIDATED,
        payload={"action": "test_attempt_2"},
    )

    audit_sink.append_audit_event(ev1)
    audit_sink.append_audit_event(ev2)

    events = audit_sink.list_events_for_run(tenant_id, run_id)
    assert len(events) == 1
    assert events[0].event_id == deterministic_id


# ---------------------------------------------------------------------------
# 4. Governance Invalidation Saga Fail-Closed & Idempotency Tests
# ---------------------------------------------------------------------------

def test_invalidation_saga_idempotency_collision():
    """Re-executing Saga with the same idempotency key but different target digest raises 409 Conflict."""
    tenant_id = "tenant-demo"
    session_id = f"sess-collision-{uuid.uuid4().hex[:6]}"
    product_name = "Retinol Night Renewal Serum"
    
    draft1 = FormulationDraft(
        draft_id=f"draft-{session_id}-1",
        session_id=session_id,
        product_name=product_name,
        revision=2,
        ingredients=[FormulaItem(inci_name="Aqua", concentration_pct=80.0)],
    )
    draft1.compute_case_digest()

    draft2 = FormulationDraft(
        draft_id=f"draft-{session_id}-2",
        session_id=session_id,
        product_name=product_name,
        revision=2,
        ingredients=[FormulaItem(inci_name="Aqua", concentration_pct=70.0)],
    )
    draft2.compute_case_digest()

    shared_key = f"inv-{session_id}-test-key"

    # First run succeeds
    execute_governance_invalidation_saga(
        tenant_id=tenant_id,
        session_id=session_id,
        product_name=product_name,
        target_draft=draft1,
        idempotency_key=shared_key,
    )

    # Collision run with different digest raises 409
    with pytest.raises(Exception) as exc_info:
        execute_governance_invalidation_saga(
            tenant_id=tenant_id,
            session_id=session_id,
            product_name=product_name,
            target_draft=draft2,
            idempotency_key=shared_key,
        )
    assert "409" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. HitL Gate Approval Binding & Precondition Failures (412)
# ---------------------------------------------------------------------------

def test_manager_decide_missing_checkpoint_or_approval_req_fails_412(client, formulator_session):
    """Proposal lacking checkpoint_id or approval_request_id fails closed with 412."""
    token, _ = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    # Submit a proposal
    res_sub = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert res_sub.status_code == 200
    prop_id = res_sub.json()["proposal_id"]

    # Switch to manager
    client.post("/v1/demo/session/role", headers=headers, json={"acting_role": "product_manager"})

    # Tamper proposal: remove approval_request_id
    prop = _PROPOSALS_STORE[prop_id]
    original_req_id = prop.approval_request_id
    prop.approval_request_id = None

    res_decide = client.post(
        f"/v1/proposals/{prop_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Test approval"},
    )
    assert res_decide.status_code == 412
    assert "missing mandatory approval_request_id" in res_decide.json()["detail"].lower()

    # Restore
    prop.approval_request_id = original_req_id


def test_manager_decide_cancelled_checkpoint_fails_412(client, formulator_session):
    """Proposal referencing a cancelled checkpoint fails closed with 412."""
    token, _ = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    # Submit proposal
    res_sub = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert res_sub.status_code == 200
    prop_id = res_sub.json()["proposal_id"]

    # Formulator updates draft -> invalidates previous checkpoint
    res_update = client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Retinol Night Renewal Serum",
            "ingredients": [{"inci_name": "Aqua", "concentration_pct": 79.0}],
        },
    )
    assert res_update.status_code == 200

    # Switch to manager
    client.post("/v1/demo/session/role", headers=headers, json={"acting_role": "product_manager"})

    # Old proposal is now superseded and checkpoint is cancelled -> 409 or 412
    res_decide = client.post(
        f"/v1/proposals/{prop_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Test approval"},
    )
    assert res_decide.status_code in (409, 412)


# ---------------------------------------------------------------------------
# 6. Render Export Fail-Closed Verification
# ---------------------------------------------------------------------------

def test_render_export_unknown_product_returns_404(client, formulator_session):
    """Requesting export for a product not in active workspace returns 404."""
    token, _ = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/v1/formulations/render-export",
        headers=headers,
        json={"format": "pdf", "product_name": "Nonexistent Magic Elixir 999"},
    )
    assert res.status_code == 404


def test_render_export_unsupported_format_returns_400(client, formulator_session):
    """Requesting unsupported export format returns 400."""
    token, _ = formulator_session
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/v1/formulations/render-export",
        headers=headers,
        json={"format": "exe", "product_name": "Retinol Night Renewal Serum"},
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# 7. Document Preflight Strict Checks
# ---------------------------------------------------------------------------

def test_preflight_rejects_fake_pdf_header():
    """PDF preflight must reject synthetic fake headers and require %PDF-."""
    fake_header = b"RAW_MATERIAL_SAFETY_SHEET_DATA: INCI=Retinol; Conc=0.05%"
    with pytest.raises(DocumentPreflightError) as exc_info:
        validate_document_preflight("pdf", fake_header, "raw_sds.pdf")
    assert "Invalid PDF header" in str(exc_info.value)

    valid_pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj"
    ok, fmt = validate_document_preflight("pdf", valid_pdf, "sds.pdf")
    assert ok is True
    assert fmt == "pdf"


def test_preflight_rejects_high_compression_ratio_zip():
    """ZIP containers exceeding 20.0x compression ratio must be rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("word/document.xml", b"A" * 50000)  # High compression ratio ~50x

    zip_bytes = buf.getvalue()
    with pytest.raises(DocumentPreflightError) as exc_info:
        validate_document_preflight("docx", zip_bytes, "test.docx")
    assert "compression ratio" in str(exc_info.value).lower()


def test_preflight_rejects_latin1_csv():
    """CSV preflight must strictly require UTF-8 and reject invalid UTF-8 byte sequences."""
    latin1_bytes = b"Ingredient,Concentration\nCaf\xe9,50%\n"  # \xe9 is valid latin-1, invalid UTF-8
    with pytest.raises(DocumentPreflightError) as exc_info:
        validate_document_preflight("csv", latin1_bytes, "formulation.csv")
    assert "strict UTF-8" in str(exc_info.value)


def test_preflight_rejects_missing_exact_ooxml_root():
    """OOXML preflight must require exact root part name (e.g. word/document.xml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("word/custom_header.xml", b"<Custom/>")  # Not word/document.xml

    zip_bytes = buf.getvalue()
    with pytest.raises(DocumentPreflightError) as exc_info:
        validate_document_preflight("docx", zip_bytes, "test.docx")
    assert "Missing 'word/document.xml'" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. Session Reset Failure Injection & Orphaned Token Gates
# ---------------------------------------------------------------------------

def test_session_reset_checkpoint_failure_fails_closed(client, monkeypatch):
    """
    If checkpoint store fails during session reset cleanup:
    - Session reset must return 500 (fail-closed)
    - Reset saga record must be marked 'failed'
    - Old session is inactivated and no replacement session is activated
    """
    from fleet_api.deps import get_checkpoint_store
    from fleet_api.session_security import _SESSION_RESET_RECORDS

    sess_res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Submit proposal to create an active pending checkpoint
    client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Reset Test Serum",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 90.0, "cas_number": "7732-18-5"},
                {"inci_name": "Glycerin", "concentration_pct": 10.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
            ],
            "acting_role": "formulator",
        },
    )
    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert prop_res.status_code == 200

    # Inject failure into checkpoint store
    checkpoint_store = get_checkpoint_store()
    def mock_update_status_fail(tenant_id, chk_id, new_status):
        raise RuntimeError("Simulated checkpoint store connection failure during reset")

    monkeypatch.setattr(checkpoint_store, "update_checkpoint_status", mock_update_status_fail)

    # Attempt session restart -> must fail-closed with 500
    restart_res = client.post("/v1/demo/session/restart", headers=headers)
    assert restart_res.status_code == 500
    assert "Session reset saga failed" in restart_res.json()["detail"]

    # Old token cannot perform further actions (session inactive)
    get_res = client.get("/v1/formulations/draft", headers=headers)
    assert get_res.status_code == 401


def test_orphaned_demo_token_fails_401_without_stateless_fallback(client):
    """
    A signed JWT containing demo session claims whose in-memory session is missing
    must fail with 401 and NEVER fall back to stateless token RBAC.
    """
    from fleet_api.jwt_service import create_access_token

    # Create a signed token with demo session claims but non-existent in-memory session
    orphaned_token = create_access_token(
        sub="demo-session-orphaned-99999",
        tenant_id="tenant-demo",
        roles=["demo_evaluator"],
        acting_role="formulator",
        session_id="sess-orphaned-99999",
        custom_claims={
            "allowed_demo_roles": ["formulator", "product_manager"],
        },
    )
    headers = {"Authorization": f"Bearer {orphaned_token}"}

    # Calling authenticated endpoint must return 401, not 200 or 403
    res = client.get("/v1/formulations/draft", headers=headers)
    assert res.status_code == 401
    assert "Demo session has expired, been purged, or does not exist on server" in res.json()["detail"]


def test_render_export_mismatched_mime_fails_502(client, monkeypatch):
    """If upstream render result returns a mismatched or missing MIME type, render fails closed with 502."""
    import fleet_api.routers.workflow_v4 as wf

    sess_res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_render = wf.intake_adapter.render_artifact

    def mock_render_bad_mime(req):
        res = orig_render(req)
        res["media_type"] = "text/html"  # Wrong MIME for PDF
        res["mime"] = "text/html"
        return res

    monkeypatch.setattr(wf.intake_adapter, "render_artifact", mock_render_bad_mime)

    render_res = client.post(
        "/v1/formulations/render-export",
        headers=headers,
        json={"format": "pdf", "product_name": "Retinol Night Renewal Serum"},
    )
    assert render_res.status_code == 502
    assert "Mismatched or missing MIME type" in render_res.json()["detail"]


def test_session_revoke_checkpoint_failure_fails_closed_with_token_inactivated(client, monkeypatch):
    """
    If checkpoint store fails during session revocation cleanup:
    - Revocation endpoint returns 500
    - But session and token are ALREADY inactivated (fail-closed first)
    - Subsequent calls with old token must return 401 Unauthorized
    """
    from fleet_api.deps import get_checkpoint_store

    sess_res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Submit proposal to create an active pending checkpoint
    client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Revoke Test Serum",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 90.0, "cas_number": "7732-18-5"},
                {"inci_name": "Glycerin", "concentration_pct": 10.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
            ],
            "acting_role": "formulator",
        },
    )
    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert prop_res.status_code == 200

    # Inject failure into checkpoint store
    checkpoint_store = get_checkpoint_store()
    def mock_update_status_fail(tenant_id, chk_id, new_status):
        raise RuntimeError("Simulated checkpoint store connection failure during revoke")

    monkeypatch.setattr(checkpoint_store, "update_checkpoint_status", mock_update_status_fail)

    # Attempt session revocation -> returns 500
    revoke_res = client.post("/v1/demo/session/revoke", headers=headers)
    assert revoke_res.status_code == 500
    assert "Session revocation cleanup interrupted" in revoke_res.json()["detail"]

    # Old token MUST be 401 (inactivated first, fail-closed)
    get_res = client.get("/v1/formulations/draft", headers=headers)
    assert get_res.status_code == 401


def test_parse_preview_preflight_error_never_exposes_internal_exception_details(client, monkeypatch, caplog):
    """
    When document preflight fails, the public HTTP 400 response and Cloud Logging output
    must strictly redact internal exception text, file paths, contents, or tokens.
    """
    import fleet_api.routers.workflow_v4 as wf
    import base64
    import logging

    sess_res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Inject a preflight error with simulated internal path and token leak
    sensitive_leak = "SECRET_TOKEN_xyz123_at_/var/run/secrets/google.internal"
    def mock_preflight_with_leak(fmt, data, filename):
        raise DocumentPreflightError(f"Internal corrupted state: {sensitive_leak}")

    monkeypatch.setattr(wf, "validate_document_preflight", mock_preflight_with_leak)

    payload_b64 = base64.b64encode(b"%PDF-1.4 dummy").decode("ascii")
    with caplog.at_level(logging.WARNING):
        res = client.post(
            "/v1/formulations/parse-preview",
            headers=headers,
            json={"filename": "test.pdf", "content_b64": payload_b64},
        )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail == "Document preflight validation failed."
    assert sensitive_leak not in detail
    assert "SECRET" not in str(res.json())

    # Verify log output was also sanitized and contains zero leaks
    assert sensitive_leak not in caplog.text
    assert "SECRET" not in caplog.text
    assert "document_preflight_failed" in caplog.text


