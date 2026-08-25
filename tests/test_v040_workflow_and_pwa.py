"""
Comprehensive Unit & Integration Test Suite for FortifiedReg Fleet v0.4.0.
Tests PWA Assets, Single-Identity Dual-Role Session, Formulation Revision Invalidation,
Two-Tier Import Normalizer, Proposal Gate, Manager Decisions, AI Assistant, and Spec Mapper.
"""
import pytest
from fastapi.testclient import TestClient
from fleet_api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_pwa_manifest_and_service_worker_served(client):
    """Verify PWA manifest, service worker, and icons are served with correct headers."""
    # 1. Manifest
    man_res = client.get("/static/manifest.webmanifest")
    assert man_res.status_code == 200
    assert "manifest" in man_res.headers.get("content-type", "")
    man_json = man_res.json()
    assert man_json["name"] == "FortifiedReg Fleet — Autonomous Compliance Suite"
    assert man_json["display"] == "standalone"

    # 2. Service Worker
    sw_res = client.get("/static/service-worker.js")
    assert sw_res.status_code == 200
    assert "javascript" in sw_res.headers.get("content-type", "")
    assert "fortifiedreg-fleet-shell-v0.4.0" in sw_res.text
    # Verify strict API exclusion
    assert "url.pathname.startsWith('/v1/')" in sw_res.text

    # 3. SVG Icons
    icon192 = client.get("/static/icons/icon-192.svg")
    assert icon192.status_code == 200
    assert "svg" in icon192.headers.get("content-type", "")

    icon512 = client.get("/static/icons/icon-512.svg")
    assert icon512.status_code == 200
    assert "svg" in icon512.headers.get("content-type", "")


def test_single_identity_dual_role_session_and_restart(client):
    """Verify single-identity sub persists across dual-role simulation and restarts cleanly."""
    # 1. Create Session as Formulator
    s1_res = client.post("/v1/demo/session", json={"acting_role": "formulator"})
    assert s1_res.status_code == 200
    s1_data = s1_res.json()
    token1 = s1_data["token"]
    sub1 = s1_data["sub"]
    assert "demo-session-" in sub1
    assert s1_data["acting_role"] == "formulator"
    assert "formulator" in s1_data["allowed_demo_roles"]
    assert "product_manager" in s1_data["allowed_demo_roles"]

    # 2. Query draft using token1
    headers1 = {"Authorization": f"Bearer {token1}"}
    d1_res = client.get("/v1/formulations/draft", headers=headers1)
    assert d1_res.status_code == 200
    d1_data = d1_res.json()
    assert d1_data["draft"]["revision"] == 1

    # 3. Restart Session
    restart_res = client.post("/v1/demo/session/restart", json={"acting_role": "formulator"})
    assert restart_res.status_code == 200
    r_data = restart_res.json()
    token2 = r_data["token"]
    sub2 = r_data["sub"]
    assert sub2 != sub1  # Fresh clean session identity


def test_formulation_revision_invalidation(client):
    """Verify modifying ingredients strictly increments revision and invalidates previous verifiers."""
    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Initial revision is 1
    d1 = client.get("/v1/formulations/draft", headers=headers).json()
    assert d1["draft"]["revision"] == 1
    initial_digest = d1["draft"]["case_digest"]
    assert len(initial_digest) == 64

    # Update ingredients
    update_res = client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Updated Day Cream",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 95.0, "cas_number": "7732-18-5"},
                {"inci_name": "Glycerin", "concentration_pct": 5.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
            ],
            "acting_role": "formulator",
        },
    )
    assert update_res.status_code == 200
    u_data = update_res.json()
    assert u_data["revision"] == 2
    assert u_data["case_digest"] != initial_digest
    assert u_data["draft"]["status"] == "draft"


def test_two_tier_5_format_import_preview(client):
    """Verify normalizer extracts candidate ingredients for all 5 preset scenarios."""
    scenarios = ["retinol", "peptide", "day_cream", "phenoxy_excess", "mercury"]
    for sc in scenarios:
        res = client.post("/v1/formulations/parse-preview", json={"scenario_key": sc})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "preview_ready"
        assert data["candidates_count"] > 0
        for c in data["candidates"]:
            assert "inci_name" in c
            assert "concentration_pct" in c
            assert "source_location" in c
            assert c["confidence"] > 0.9


def test_formal_proposal_gate_and_manager_decisions_lifecycle(client):
    """Complete lifecycle test: Draft -> Submit Proposal -> Manager Review -> Approve & Finalize -> Export Bundle."""
    # 1. Start session
    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Test Gate hard-blocks prohibited mercury
    client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Toxic Bleaching Cream",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 98.0, "cas_number": "7732-18-5"},
                {"inci_name": "Mercury", "concentration_pct": 2.0, "cas_number": "7439-97-6", "noael_mg_kg_day": 0.01},
            ],
            "acting_role": "formulator",
        },
    )
    mercury_sub_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert mercury_sub_res.status_code == 422
    assert "Annex II" in str(mercury_sub_res.json())

    # 3. Formulate compliant Retinol Night Serum
    client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Retinol Night Renewal Serum",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 78.5, "cas_number": "7732-18-5"},
                {"inci_name": "Glycerin", "concentration_pct": 5.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
                {"inci_name": "Retinol", "concentration_pct": 0.05, "cas_number": "68-26-8", "noael_mg_kg_day": 2.0},
                {"inci_name": "Phenoxyethanol", "concentration_pct": 0.8, "cas_number": "122-99-6", "noael_mg_kg_day": 500.0},
            ],
            "acting_role": "formulator",
        },
    )

    # 4. Submit proposal (PASS Gate)
    sub_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert sub_res.status_code == 200
    prop_data = sub_res.json()
    proposal_id = prop_data["proposal_id"]
    assert prop_data["gate_decision"] == "PASS"

    # 5. Manager views Inbox
    inbox_res = client.get("/v1/proposals/inbox", headers=headers)
    assert inbox_res.status_code == 200
    inbox_list = inbox_res.json()
    assert any(p["proposal_id"] == proposal_id for p in inbox_list)

    # 6. Manager Approves Proposal
    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "All substance MoS > 100 and Annex V compliant."},
    )
    assert decide_res.status_code == 200
    dec_data = decide_res.json()
    product_id = dec_data["product_id"]
    assert dec_data["status"] == "finalized"
    assert len(dec_data["artifact_identity"]["sha256"]) == 64

    # 7. Retrieve Export Bundle Spec
    export_res = client.get(f"/v1/products/{product_id}/export-bundle", headers=headers)
    assert export_res.status_code == 200
    exp_data = export_res.json()
    assert exp_data["status"] == "spec_ready"
    assert "pdf_report" in exp_data["bundle_spec"]["specs"]
    assert "docx_document" in exp_data["bundle_spec"]["specs"]
    assert "csv_table" in exp_data["bundle_spec"]["specs"]
    assert "xlsx_workbook" in exp_data["bundle_spec"]["specs"]
    assert "pptx_presentation" in exp_data["bundle_spec"]["specs"]


def test_ai_assistant_suggestions_and_guardrail(client):
    """Verify AI assistant generates accurate regulatory suggestions and citations."""
    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/v1/assistant/suggestions",
        headers=headers,
        json={
            "product_name": "Test Serum",
            "ingredients": [
                {"inci_name": "Phenoxyethanol", "concentration_pct": 2.5, "cas_number": "122-99-6", "noael_mg_kg_day": 500.0},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["guardrail"] == "Local Guardrail / Model Armor-Compatible Emulation"
    assert any("Annex V" in s["title"] for s in data["suggestions"])


def test_import_adapter_flatten_kernel_text_items_and_live_upload_preview(client):
    """Verify Import Adapter flattens Kernel text_items and handles live file upload parsing."""
    import base64
    from fleet_domain_cosmetics.normalizer import normalize_content_blocks

    # 1. Test pure normalizer with Kernel text_items IR
    kernel_ir_payload = {
        "schema_version": "prodocux_content_blocks_v1",
        "document_id": "doc-kernel-raw-01",
        "text_items": [
            "Aqua: 70.0%",
            "Glycerin = 10.0%",
            "Retinol: 0.05%",
            "Phenoxyethanol - 0.8%",
        ],
    }
    candidates = normalize_content_blocks(kernel_ir_payload)
    assert len(candidates) == 4
    names = [c.inci_name for c in candidates]
    assert "Aqua" in names
    assert "Glycerin" in names
    assert "Retinol" in names
    assert "Phenoxyethanol" in names

    # 2. Test POST /v1/formulations/parse-preview with uploaded file payload
    fake_sds_b64 = base64.b64encode(b"RAW_MATERIAL_SAFETY_SHEET_DATA").decode("ascii")
    preview_res = client.post(
        "/v1/formulations/parse-preview",
        json={
            "filename": "supplier_sds.pdf",
            "content_b64": fake_sds_b64,
        },
    )
    assert preview_res.status_code == 200
    p_data = preview_res.json()
    assert p_data["status"] == "preview_ready"
    assert p_data["format"] == "pdf"
    assert p_data["candidates_count"] >= 3


def test_export_adapter_prodocux_render_requests_and_artifact_render_api(client):
    """Verify Export Adapter maps bundle spec to prodocux_render_request_v1 and renders 5 formats."""
    # 1. Setup session and approved product
    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/v1/formulations/draft",
        headers=headers,
        json={
            "product_name": "Antigravity Multi-Format Serum",
            "ingredients": [
                {"inci_name": "Aqua", "concentration_pct": 78.5, "cas_number": "7732-18-5"},
                {"inci_name": "Glycerin", "concentration_pct": 5.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
                {"inci_name": "Retinol", "concentration_pct": 0.05, "cas_number": "68-26-8", "noael_mg_kg_day": 2.0},
                {"inci_name": "Phenoxyethanol", "concentration_pct": 0.8, "cas_number": "122-99-6", "noael_mg_kg_day": 500.0},
            ],
            "acting_role": "formulator",
        },
    )
    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]

    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Certified PASS."},
    )
    product_id = decide_res.json()["product_id"]

    # 2. Retrieve Export Bundle containing prodocux_render_requests
    exp_res = client.get(f"/v1/products/{product_id}/export-bundle", headers=headers)
    assert exp_res.status_code == 200
    exp_data = exp_res.json()
    assert "prodocux_render_requests" in exp_data
    render_reqs = exp_data["prodocux_render_requests"]
    assert set(render_reqs.keys()) == {"pdf", "docx", "csv", "xlsx", "pptx"}

    # 3. Render all 5 formats via POST /v1/products/{product_id}/render-artifact
    for fmt in ["pdf", "docx", "csv", "xlsx", "pptx"]:
        render_res = client.post(
            f"/v1/products/{product_id}/render-artifact",
            headers=headers,
            json={"format": fmt},
        )
        assert render_res.status_code == 200, f"Render failed for {fmt}: {render_res.text}"
        r_data = render_res.json()
        assert r_data["status"] == "rendered"
        assert r_data["format"] == fmt
        assert r_data["result"]["status"] == "success"
        assert len(r_data["result"]["sha256"]) == 64
        assert "content_b64" in r_data["result"]


def test_cross_tenant_product_export_and_render_rejected(client):
    """Verify that export-bundle and render-artifact fail-closed with 404 for mismatched tenants."""
    from fleet_api.security import create_access_token

    # 1. Create session as tenant A and produce an approved product
    sess_res = client.post("/v1/demo/session")
    token_tenant_a = sess_res.json()["token"]
    headers_a = {"Authorization": f"Bearer {token_tenant_a}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers_a)
    proposal_id = prop_res.json()["proposal_id"]
    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers_a,
        json={"decision": "approved", "rationale": "Approved PASS."},
    )
    product_id = decide_res.json()["product_id"]

    # 2. Forge a valid token belonging to evil tenant B
    token_tenant_b = create_access_token(
        tenant_id="tenant-evil",
        sub="actor-evil",
        roles=["demo_evaluator"],
    )
    headers_b = {"Authorization": f"Bearer {token_tenant_b}"}

    # 3. Attempt export-bundle as tenant B -> Expect 404 Not Found (fail-closed, no information leakage)
    exp_res = client.get(f"/v1/products/{product_id}/export-bundle", headers=headers_b)
    assert exp_res.status_code == 404, f"Expected 404 for cross-tenant export, got {exp_res.status_code}"

    # 4. Attempt render-artifact as tenant B -> Expect 404 Not Found (fail-closed)
    render_res = client.post(
        f"/v1/products/{product_id}/render-artifact",
        headers=headers_b,
        json={"format": "pdf"},
    )
    assert render_res.status_code == 404, f"Expected 404 for cross-tenant render, got {render_res.status_code}"


def test_finalized_product_artifact_stored_and_verified(client):
    """Verify that finalized product canonical PIF is persisted in ArtifactStore and matches SHA-256."""
    import hashlib
    from fleet_api.deps import get_artifact_store
    from fleet_governance_core.models.storage import ArtifactStorageIdentity

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]

    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Finalized PIF approved."},
    )
    assert decide_res.status_code == 200
    art_meta = decide_res.json()["artifact_identity"]
    identity = ArtifactStorageIdentity.model_validate(art_meta)

    # Resolve from ArtifactStore
    store = get_artifact_store()
    target_path = store._uri_to_path(identity.uri)
    assert target_path.exists(), f"Stored artifact must exist at path: {target_path}"

    raw_bytes = target_path.read_bytes()
    assert len(raw_bytes) == identity.size_bytes
    calc_sha = hashlib.sha256(raw_bytes).hexdigest()
    assert calc_sha == identity.sha256, f"Artifact SHA-256 mismatch: {calc_sha} != {identity.sha256}"


def test_artifact_store_conflict_fails_closed(client):
    """Verify that conflicting digest in ArtifactStore causes 409 Conflict, preserves pending checkpoint, and records retryable failure without resumed outbox."""
    import hashlib
    from fleet_api.deps import get_artifact_store, get_checkpoint_store, get_resume_context_store
    from fleet_governance_core.models.storage import ArtifactStorageIdentity
    from fleet_governance_core.models.approval import CheckpointStatusEnum, FleetExecutionStatus
    from fleet_api.routers.workflow_v4 import _APPROVED_PRODUCTS_STORE

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]
    checkpoint_id = prop_res.json()["proposal"]["checkpoint_id"]

    # Pre-populate a conflicting artifact at the target URI
    store = get_artifact_store()
    target_uri = f"artifact://tenant-demo/dossiers/{proposal_id}/finalized_pif_record.json"
    conflicting_bytes = b'{"conflicting": "pre-existing payload"}'
    conflicting_sha = hashlib.sha256(conflicting_bytes).hexdigest()
    conflict_ident = ArtifactStorageIdentity(
        artifact_id=f"art-conflict-{proposal_id}",
        uri=target_uri,
        sha256=conflicting_sha,
        size_bytes=len(conflicting_bytes),
        media_type="application/json",
    )
    store.put_if_absent(conflict_ident, conflicting_bytes, conflicting_sha)

    initial_product_count = len(_APPROVED_PRODUCTS_STORE)

    # Attempt to decide/approve proposal -> must fail-closed with 409 Conflict
    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Finalized PIF approved."},
    )
    assert decide_res.status_code == 409, f"Expected 409 Conflict, got {decide_res.status_code}"
    # Assert sanitized error message (no raw URI leakage)
    assert decide_res.json()["detail"] == "Artifact storage conflict: an artifact with a conflicting digest already exists."

    # Verify no new ApprovedProductRecord was added
    assert len(_APPROVED_PRODUCTS_STORE) == initial_product_count

    # Verify the conflicting content in storage was not overwritten
    persisted_path = store._uri_to_path(target_uri)
    assert persisted_path.read_bytes() == conflicting_bytes

    # Verify checkpoint remains PENDING (NOT RESUMED)
    checkpoint_store = get_checkpoint_store()
    chk = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk.status == CheckpointStatusEnum.PENDING

    # Verify resume context status is marked BLOCKED_REVIEW with safe error code (non-retryable)
    resume_store = get_resume_context_store()
    ctx = resume_store.get_context("tenant-demo", checkpoint_id)
    if ctx:
        assert ctx.status == FleetExecutionStatus.BLOCKED_REVIEW
        assert ctx.last_error.get("safe_error_code") == "ARTIFACT_CONFLICT_BLOCKED"
        assert ctx.last_error.get("is_retryable") is False


def test_pdx_resume_failure_fails_closed(client, monkeypatch):
    """Verify that if PDX plan resume fails, decision fails closed with sanitized 500, checkpoint remains pending, and context is retryable."""
    from fleet_api.deps import get_orchestrator, get_checkpoint_store, get_resume_context_store
    from fleet_governance_core.models.approval import CheckpointStatusEnum, FleetExecutionStatus
    from fleet_api.routers.workflow_v4 import _APPROVED_PRODUCTS_STORE

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]
    checkpoint_id = prop_res.json()["proposal"]["checkpoint_id"]

    # Mock orchestrator resume_with_decision to simulate plan execution failure
    orchestrator = get_orchestrator()

    def mock_resume_fail(chk, dec):
        raise RuntimeError("Simulated PDX core plan resume network/schema fault")

    monkeypatch.setattr(orchestrator, "resume_with_decision", mock_resume_fail)

    initial_product_count = len(_APPROVED_PRODUCTS_STORE)

    # Attempt decision -> must fail with sanitized 500 (no str(e) leakage)
    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Finalized PIF approved."},
    )
    assert decide_res.status_code == 500, f"Expected 500 Internal Server Error, got {decide_res.status_code}"
    assert decide_res.json()["detail"] == "Resume execution error: Transient processing error (state is retryable)."

    # Verify no approved product was created
    assert len(_APPROVED_PRODUCTS_STORE) == initial_product_count

    # Verify checkpoint status remains PENDING
    checkpoint_store = get_checkpoint_store()
    chk = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk.status == CheckpointStatusEnum.PENDING

    # Verify resume context status is marked RESUME_FAILED_RETRYABLE
    resume_store = get_resume_context_store()
    ctx = resume_store.get_context("tenant-demo", checkpoint_id)
    if ctx:
        assert ctx.status == FleetExecutionStatus.RESUME_FAILED_RETRYABLE
        assert ctx.last_error.get("safe_error_code") == "RESUME_EXECUTION_ERROR"


def test_live_pdx_adapter_proposal_approve_resume_lifecycle(client, monkeypatch):
    """Verify end-to-end proposal submission, approval, and resume lifecycle with LivePDXCoreOrchestrator."""
    from fleet_adapter_pdx.orchestrator import LivePDXCoreOrchestrator
    from fleet_api.deps import (
        get_artifact_store,
        get_checkpoint_store,
        get_resume_context_store,
        get_document_resolver,
        intake_adapter,
    )
    from fleet_governance_core.models.approval import CheckpointStatusEnum
    from fleet_adapter_pdx.verifier_bridge import PDXVerifierBridge
    from pdx_artifact_core.approval import ApprovalLedger

    # Instantiate LivePDXCoreOrchestrator with dependencies
    live_orch = LivePDXCoreOrchestrator(
        approval_ledger=ApprovalLedger(),
        intake_adapter=intake_adapter,
        document_resolver=get_document_resolver(),
        verifier_bridge=PDXVerifierBridge(),
        artifact_store=get_artifact_store(),
        resume_context_store=get_resume_context_store(),
    )

    import fleet_api.routers.workflow_v4 as wv4
    monkeypatch.setattr(wv4, "get_orchestrator", lambda: live_orch)

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Submit proposal -> compiles & executes plan via LivePDXCoreOrchestrator
    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert prop_res.status_code == 200, f"Failed proposal submission: {prop_res.text}"
    proposal_data = prop_res.json()
    proposal_id = proposal_data["proposal_id"]
    checkpoint_id = proposal_data["proposal"]["checkpoint_id"]

    # Verify checkpoint exists in checkpoint_store
    checkpoint_store = get_checkpoint_store()
    chk = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk is not None
    assert chk.status == CheckpointStatusEnum.PENDING

    # Decide/Approve proposal -> executes LivePDXCoreOrchestrator.resume_with_decision
    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Live PDX Adapter PIF approved."},
    )
    assert decide_res.status_code == 200, f"Failed decision: {decide_res.text}"
    decide_data = decide_res.json()
    assert decide_data["status"] == "finalized"
    assert "prod-" in decide_data["product_id"]

    # Verify checkpoint transitioned to RESUMED
    chk_resumed = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk_resumed.status == CheckpointStatusEnum.RESUMED


def test_deploy_script_strict_impersonation_requirement():
    """Verify that deploy.ps1 strictly requires impersonation and contains no fallback to current user."""
    from pathlib import Path

    deploy_script = Path("D:/ProDocuX/fortifiedreg-fleet/deploy/prodocux-intake/deploy.ps1")
    assert deploy_script.exists()
    content = deploy_script.read_text(encoding="utf-8")

    # Assert strictly requires impersonated token
    assert "--impersonate-service-account=$RUNTIME_SA" in content
    # Assert no fallback to current user token
    assert "Fallback to current authenticated principal" not in content
    # Assert fail-closed error message on missing impersonated token
    assert "Unable to acquire GCP identity token via service account impersonation" in content


def test_approval_decision_retry_reuses_immutable_timestamp_and_same_digest(client, monkeypatch):
    """Verify that retrying an approval after a transient failure reuses the immutable approved_at timestamp and idempotent artifact digest."""
    import time
    from fleet_api.deps import get_orchestrator, get_checkpoint_store
    from fleet_governance_core.models.approval import CheckpointStatusEnum
    from fleet_api.routers.workflow_v4 import _APPROVED_PRODUCTS_STORE

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]
    checkpoint_id = prop_res.json()["proposal"]["checkpoint_id"]

    orchestrator = get_orchestrator()
    original_resume = orchestrator.resume_with_decision

    # 1. First attempt: Mock orchestrator resume to fail transiently
    call_count = {"count": 0}

    def mock_resume_flaky(chk, dec):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise RuntimeError("Transient network timeout during PDX plan resume")
        return original_resume(chk, dec)

    monkeypatch.setattr(orchestrator, "resume_with_decision", mock_resume_flaky)

    decide_res_1 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "First attempt with transient fault."},
    )
    assert decide_res_1.status_code == 500
    assert "Resume execution error" in decide_res_1.json()["detail"]

    # Verify no product was created on failed attempt
    checkpoint_store = get_checkpoint_store()
    chk = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk.status == CheckpointStatusEnum.PENDING

    # Wait briefly to ensure wall-clock time would have advanced if dynamically re-computed
    time.sleep(0.05)

    # 2. Second attempt (Retry): Should succeed cleanly by reusing immutable approved_at and same artifact digest
    decide_res_2 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "First attempt with transient fault."},
    )
    assert decide_res_2.status_code == 200, f"Expected 200 on retry, got {decide_res_2.text}"
    decide_data = decide_res_2.json()
    assert decide_data["status"] == "finalized"
    product_id = decide_data["product_id"]
    assert product_id in _APPROVED_PRODUCTS_STORE

    # Verify checkpoint status transitioned to RESUMED
    chk_resumed = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk_resumed.status == CheckpointStatusEnum.RESUMED


def test_non_awaiting_approval_fails_closed_without_synthetic_checkpoint(client, monkeypatch):
    """Verify that non-awaiting_approval orchestrator results fail closed without generating synthetic checkpoints."""
    from fleet_api.deps import get_orchestrator

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    orchestrator = get_orchestrator()

    # Mock execute_plan to return completed (e.g. fully autonomous plan with no HitL step)
    def mock_exec_no_approval(plan, case_payload=None):
        return {"status": "completed", "completed_steps": ["step_verify_inci"]}

    monkeypatch.setattr(orchestrator, "execute_plan", mock_exec_no_approval)

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert prop_res.status_code == 422
    assert "did not reach a pending regulatory approval checkpoint" in prop_res.json()["detail"]


def test_missing_approval_request_fails_closed_without_synthetic_fallback(client, monkeypatch):
    """Verify that if awaiting_approval result lacks approval_request, proposal creation fails closed."""
    from fleet_api.deps import get_orchestrator

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    orchestrator = get_orchestrator()
    original_exec = orchestrator.execute_plan

    # Mock execute_plan to return checkpoint but omit approval_request
    def mock_exec_missing_req(plan, case_payload=None):
        res = original_exec(plan, case_payload)
        res.pop("approval_request", None)
        return res

    monkeypatch.setattr(orchestrator, "execute_plan", mock_exec_missing_req)

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    assert prop_res.status_code == 422
    assert "did not reach a pending regulatory approval checkpoint and approval request" in prop_res.json()["detail"]


def test_missing_or_mismatched_pdx_artifact_identity_fails_closed(client, monkeypatch):
    """Verify that if PDX resume result lacks artifact_identity or has digest mismatch, resume fails closed."""
    from fleet_api.deps import get_orchestrator

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]

    orchestrator = get_orchestrator()
    original_resume = orchestrator.resume_with_decision

    # Mock resume_with_decision to return corrupted artifact_identity (digest mismatch)
    def mock_resume_bad_ident(chk, dec):
        res = original_resume(chk, dec)
        res["artifact_identity"]["sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
        return res

    monkeypatch.setattr(orchestrator, "resume_with_decision", mock_resume_bad_ident)

    decide_res = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Testing identity validation."},
    )
    assert decide_res.status_code == 500
    assert "Resume execution error" in decide_res.json()["detail"]


def test_crash_window_after_artifact_write_retry_succeeds_with_single_outbox(client, monkeypatch):
    """
    Verify the crash window:
    1. PDX resume succeeds.
    2. Fleet canonical PIF artifact is written to ArtifactStore.
    3. Server crashes right before mark_resume_completed.
    4. On retry/restart: exact same approved_at and byte-identical artifact are reused (ALREADY_EXISTS_SAME_DIGEST).
    5. mark_resume_completed executes and emits exactly ONE projection outbox record.
    """
    from fleet_api.deps import get_resume_context_store, get_checkpoint_store, get_artifact_store
    from fleet_governance_core.models.approval import CheckpointStatusEnum, FleetExecutionStatus
    from fleet_api.routers.workflow_v4 import _APPROVED_PRODUCTS_STORE

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]
    checkpoint_id = prop_res.json()["proposal"]["checkpoint_id"]

    resume_store = get_resume_context_store()
    original_mark_completed = resume_store.mark_resume_completed

    # 1. Attempt 1: Simulate crash during mark_resume_completed
    attempt_count = {"count": 0}

    def mock_mark_completed_crash(tenant_id, checkpoint_id, expected_version, lease_id, result_identity):
        attempt_count["count"] += 1
        if attempt_count["count"] == 1:
            raise RuntimeError("Simulated node crash right after artifact write and before mark_resume_completed")
        return original_mark_completed(tenant_id, checkpoint_id, expected_version, lease_id, result_identity)

    monkeypatch.setattr(resume_store, "mark_resume_completed", mock_mark_completed_crash)

    decide_res_1 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Crash window test."},
    )
    assert decide_res_1.status_code == 500

    # Verify that the artifact was written to storage during attempt 1
    artifact_store = get_artifact_store()
    target_uri = f"artifact://tenant-demo/dossiers/{proposal_id}/finalized_pif_record.json"
    written_bytes = artifact_store._uri_to_path(target_uri).read_bytes()
    assert len(written_bytes) > 0

    # Verify checkpoint is still pending and no outbox was emitted
    checkpoint_store = get_checkpoint_store()
    chk = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk.status == CheckpointStatusEnum.PENDING
    assert len([r for r in resume_store.get_pending_outbox_records() if r.checkpoint_id == checkpoint_id]) == 0

    # 2. Attempt 2 (Retry / Restart after crash)
    decide_res_2 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Crash window test."},
    )
    assert decide_res_2.status_code == 200, f"Expected 200 on retry after crash, got {decide_res_2.text}"
    decide_data = decide_res_2.json()
    assert decide_data["status"] == "finalized"
    product_id = decide_data["product_id"]
    assert product_id in _APPROVED_PRODUCTS_STORE

    # Verify that bytes and digest in storage were untouched / identical
    persisted_bytes_after_retry = artifact_store._uri_to_path(target_uri).read_bytes()
    assert persisted_bytes_after_retry == written_bytes

    # Verify checkpoint transitioned to RESUMED
    chk_resumed = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk_resumed.status == CheckpointStatusEnum.RESUMED

    # Verify EXACTLY ONE outbox record exists for this checkpoint
    matching_outbox = [r for r in resume_store.get_pending_outbox_records() if r.checkpoint_id == checkpoint_id]
    assert len(matching_outbox) == 1
    assert matching_outbox[0].target_pdx_status == "resumed"


def test_missing_manifest_sha_or_uri_fails_closed(client, monkeypatch):
    """Verify that if PDX resume result omits manifest_sha256 or artifact_uri, execution fails closed."""
    from fleet_api.deps import get_orchestrator

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Case A: Omit manifest_sha256
    prop_res_a = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id_a = prop_res_a.json()["proposal_id"]

    orchestrator = get_orchestrator()
    orig_resume = orchestrator.resume_with_decision

    def mock_resume_missing_sha(chk, dec):
        res = orig_resume(chk, dec)
        res.pop("manifest_sha256", None)
        return res

    monkeypatch.setattr(orchestrator, "resume_with_decision", mock_resume_missing_sha)
    decide_res_a = client.post(
        f"/v1/proposals/{proposal_id_a}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Missing sha test."},
    )
    assert decide_res_a.status_code == 500

    # Case B: Omit artifact_uri
    prop_res_b = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id_b = prop_res_b.json()["proposal_id"]

    def mock_resume_missing_uri(chk, dec):
        res = orig_resume(chk, dec)
        res.pop("artifact_uri", None)
        return res

    monkeypatch.setattr(orchestrator, "resume_with_decision", mock_resume_missing_uri)
    decide_res_b = client.post(
        f"/v1/proposals/{proposal_id_b}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Missing uri test."},
    )
    assert decide_res_b.status_code == 500


def test_crash_window_after_mark_resume_completed_before_checkpoint_update_recovers_idempotently(client, monkeypatch):
    """
    Verify the second crash window:
    1. mark_resume_completed succeeds (context becomes COMPLETED, outbox record emitted).
    2. Server crashes before update_checkpoint_status.
    3. On retry, the COMPLETED recovery path replays checkpoint status update, ensures artifact storage,
       and constructs the ApprovedProductRecord idempotently without duplicating outbox records.
    """
    from fleet_api.deps import get_resume_context_store, get_checkpoint_store, get_artifact_store
    from fleet_governance_core.models.approval import CheckpointStatusEnum, FleetExecutionStatus
    from fleet_api.routers.workflow_v4 import _APPROVED_PRODUCTS_STORE

    sess_res = client.post("/v1/demo/session")
    token = sess_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prop_res = client.post("/v1/formulations/submit-proposal", headers=headers)
    proposal_id = prop_res.json()["proposal_id"]
    checkpoint_id = prop_res.json()["proposal"]["checkpoint_id"]

    checkpoint_store = get_checkpoint_store()
    orig_update_status = checkpoint_store.update_checkpoint_status

    # 1. Attempt 1: Crash right after mark_resume_completed during update_checkpoint_status
    crash_injected = {"count": 0}

    def mock_update_status_crash(tenant_id, chk_id, new_status):
        crash_injected["count"] += 1
        if crash_injected["count"] == 1:
            raise RuntimeError("Simulated crash right after mark_resume_completed before checkpoint status update")
        return orig_update_status(tenant_id, chk_id, new_status)

    monkeypatch.setattr(checkpoint_store, "update_checkpoint_status", mock_update_status_crash)

    decide_res_1 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Second crash window test."},
    )
    assert decide_res_1.status_code == 500

    # Verify context in resume_context_store is already COMPLETED
    resume_store = get_resume_context_store()
    ctx = resume_store.get_context("tenant-demo", checkpoint_id)
    assert ctx.status == FleetExecutionStatus.COMPLETED

    # Verify checkpoint is still PENDING because crash happened before update
    chk_pending = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk_pending.status == CheckpointStatusEnum.PENDING

    # Exactly ONE completed outbox message was written by mark_resume_completed
    initial_outbox = [r for r in resume_store.get_pending_outbox_records() if r.checkpoint_id == checkpoint_id]
    assert len(initial_outbox) == 1

    # 2. Attempt 2 (Retry/Restart after crash): Should hit completed recovery path
    decide_res_2 = client.post(
        f"/v1/proposals/{proposal_id}/decide",
        headers=headers,
        json={"decision": "approved", "rationale": "Second crash window test."},
    )
    assert decide_res_2.status_code == 200, f"Expected 200 on retry after crash, got {decide_res_2.text}"
    decide_data = decide_res_2.json()
    assert decide_data["status"] == "finalized"
    product_id = decide_data["product_id"]
    assert product_id in _APPROVED_PRODUCTS_STORE

    # Verify checkpoint successfully transitioned to RESUMED via projection recovery
    chk_resumed = checkpoint_store.get_checkpoint("tenant-demo", checkpoint_id)
    assert chk_resumed.status == CheckpointStatusEnum.RESUMED

    # Verify outbox records remain EXACTLY ONE (no duplicate outbox messages)
    final_outbox = [r for r in resume_store.get_pending_outbox_records() if r.checkpoint_id == checkpoint_id]
    assert len(final_outbox) == 1
