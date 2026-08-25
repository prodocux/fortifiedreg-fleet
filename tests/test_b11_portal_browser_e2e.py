"""
B11 Browser End-to-End & Playwright Verification Gate (v0.3.2).
Validates that the 3-view Enterprise Portal loads without JavaScript console errors,
CSP violations, or mock fallbacks, and executes the full guided compliance lifecycle.
"""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from fleet_api.main import app


def test_b11_portal_serves_html_and_static_assets():
    """Verify that FastAPI serves portal.html, portal.css, portal.js, and samples.json with correct headers."""
    client = TestClient(app)

    # 1. Main portal HTML
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers.get("content-type", "")
    assert "Content-Security-Policy" in html_resp.headers
    csp = html_resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "FortifiedReg Fleet" in html_resp.text
    assert 'src="/static/portal.js?v=0.4.0"' in html_resp.text

    # 2. Portal CSS
    css_resp = client.get("/static/portal.css?v=0.4.0")
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.headers.get("content-type", "")
    assert "--bg-primary" in css_resp.text

    # 3. Portal JS
    js_resp = client.get("/static/portal.js?v=0.4.0")
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.headers.get("content-type", "")
    assert "FortifiedReg Fleet v0.4.0" in js_resp.text

    # 4. Golden Samples JSON
    samples_resp = client.get("/static/samples.json")
    assert samples_resp.status_code == 200
    assert "application/json" in samples_resp.headers.get("content-type", "")
    samples_data = samples_resp.json()
    for fmt in ["pdf", "docx", "csv", "xlsx", "pptx"]:
        assert fmt in samples_data
        assert "b64" in samples_data[fmt]
        assert "sha256" in samples_data[fmt]
        assert samples_data[fmt].get("synthetic") is True


def test_b11_guided_demo_full_lifecycle_hermetic():
    """
    Execute the exact 5-step Guided Demo lifecycle as defined in portal.js.
    Validates zero 422 schema validation errors, zero fake fallbacks, and complete evidence package generation.
    """
    client = TestClient(app)

    # Step 0: Acquire Demo Session
    sess_res = client.post("/v1/demo/session", json={"persona": "formulator"})
    assert sess_res.status_code == 200, sess_res.text
    token = sess_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Load Samples
    samples = client.get("/static/samples.json").json()
    assert len(samples) == 5

    # Step 2: 5-Format Profile & Register
    registered_docs = []
    doc_types = {"pdf": "SDS", "docx": "COA", "csv": "COA", "xlsx": "COA", "pptx": "COA"}

    for fmt, s in samples.items():
        doc_id = f"doc-{fmt}-{uuid.uuid4().hex[:8]}"

        # Profile
        prof_res = client.post(
            "/v1/dossiers/documents/profile",
            json={"doc_id": doc_id, "filename": s["fn"], "content_b64": s["b64"]},
            headers=headers,
        )
        assert prof_res.status_code == 200, prof_res.text

        # Register
        reg_res = client.post(
            "/v1/dossiers/documents/register",
            json={"doc_id": doc_id, "filename": s["fn"], "content_b64": s["b64"]},
            headers=headers,
        )
        assert reg_res.status_code == 200, reg_res.text
        doc_sha = reg_res.json()["sha256"]

        registered_docs.append({
            "doc_id": doc_id,
            "filename": s["fn"],
            "doc_type": doc_types[fmt],
            "sha256": doc_sha,
            "supplier_name": "Golden Evidence Supplier",
            "issue_date": "2025-01-10",
            "expiry_date": "2028-01-10",
        })

    # Step 3: Create Dossier Case (Exact schema expected by DossierCase)
    case_id = str(uuid.uuid4())
    create_res = client.post(
        "/v1/dossiers/create",
        json={
            "case_id": case_id,
            "tenant_id": "tenant-demo",
            "product_name": "Retinol Night Serum",
            "jurisdiction": "EU",
            "formula": [
                {"inci_name": "Aqua", "concentration_pct": 78.5},
                {"inci_name": "Glycerin", "concentration_pct": 5.0, "cas_number": "56-81-5", "noael_mg_kg_day": 10000.0},
                {"inci_name": "Retinol", "concentration_pct": 0.05, "cas_number": "68-26-8", "noael_mg_kg_day": 2.0},
                {"inci_name": "Phenoxyethanol", "concentration_pct": 0.8, "cas_number": "122-99-6", "noael_mg_kg_day": 500.0},
            ],
            "exposure_scenario": {
                "product_type": "Face serum",
                "daily_applied_amount_g": 1.54,
                "retention_factor": 1.0,
                "body_weight_kg": 60.0,
            },
            "supplier_documents": registered_docs,
        },
        headers=headers,
    )
    assert create_res.status_code == 200, f"Expected 200 but got {create_res.status_code}: {create_res.text}"
    case_data = create_res.json()
    case_digest = case_data["case_digest"]

    # Step 4: Compile and Run Workflow
    run_res = client.post(f"/v1/dossiers/{case_id}/compile-and-run", headers=headers)
    assert run_res.status_code == 200, run_res.text
    run_data = run_res.json()
    assert run_data["execution"]["status"] == "awaiting_approval"
    run_id = run_data["plan"]["request_id"]
    plan_digest = run_data["plan_digest"]
    checkpoint = run_data["execution"]["checkpoint"]
    approval_request_id = run_data["execution"]["approval_request_id"]
    assert approval_request_id is not None

    # Step 5: Submit Approval Decision
    appr_res = client.post(
        "/v1/approval/decide",
        json={
            "checkpoint_id": checkpoint["checkpoint_id"],
            "run_id": run_id,
            "approval_request_id": approval_request_id,
            "idempotency_key": f"idem-{checkpoint['checkpoint_id']}-approved",
            "decision": "approved",
            "reason": "Approved by regulatory signatory in automated B11 hermetic test.",
            "case_digest": case_digest,
            "plan_digest": plan_digest,
            "evidence_digests": checkpoint["evidence_digests"],
        },
        headers=headers,
    )
    assert appr_res.status_code == 200, appr_res.text
    appr_data = appr_res.json()
    assert appr_data["status"] == "decided"
    assert appr_data["decision"] == "approved"
    art = appr_data.get("artifact_identity") or appr_data.get("artifact_storage_identity")
    assert art is not None
    assert art["sha256"] is not None

    # Step 6: Retrieve Checksummed Evidence Package
    ev_res = client.get(f"/v1/evidence/runs/{run_id}", headers=headers)
    assert ev_res.status_code == 200, ev_res.text
    ev_data = ev_res.json()
    assert ev_data["package_type"] == "checksummed_evidence_package"
    assert ev_data["run_id"] == run_id
    assert ev_data["version"] == "0.4.0"
    assert ev_data["package_sha256"] is not None
    assert ev_data["audit_events_count"] > 0
    assert ev_data["case_digest"] == case_digest
    assert ev_data["plan_digest"] == plan_digest
    assert ev_data["artifact_identity"] is not None
    assert ev_data["artifact_identity"]["sha256"] is not None
    assert ev_data["artifact_identity"]["uri"] is not None

    # Step 7: Retrieve Non-existent Run (Fail-closed 404)
    ev_404_res = client.get("/v1/evidence/runs/non-existent-run-id", headers=headers)
    assert ev_404_res.status_code == 404


RUN_PLAYWRIGHT_E2E = os.getenv("RUN_PLAYWRIGHT_E2E", "").strip() in ("1", "true", "yes")
LIVE_BASE_URL = os.getenv("BASE_URL", "").strip()


@pytest.mark.skipif(
    not (RUN_PLAYWRIGHT_E2E and LIVE_BASE_URL),
    reason="Set RUN_PLAYWRIGHT_E2E=1 and BASE_URL=<url> to run live Playwright browser tests",
)
def test_b11_playwright_live_browser_journey():
    """Execute live browser verification via Playwright with complete 5-step v0.4.0 PWA UI interaction."""
    from playwright.sync_api import sync_playwright

    base_url = LIVE_BASE_URL

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))
        page.on("dialog", lambda dialog: dialog.accept())

        page.goto(base_url)
        page.wait_for_selector(".brand-title", timeout=15000)

        # Assert no JS/CSP errors on initial page load
        assert len(console_errors) == 0, f"Browser console errors detected: {console_errors}"

        # 1. Step 1: 5-Format Preset Scenario Import (click Retinol PDF preset chip)
        page.click("button[data-scenario='retinol']")
        page.wait_for_selector("#modal-import-preview:not(.hidden)", timeout=15000)

        # 2. Step 2: Apply Preview Candidates to Draft Formulation
        page.click("#btn-modal-apply")
        page.wait_for_selector("#gate-indicator", timeout=10000)

        # 3. Step 3: Submit Product Proposal to Manager Gate
        page.click("#btn-submit-proposal")
        page.wait_for_selector(".inbox-item", timeout=15000)

        # 4. Step 4: Product Manager Reviews and Finalizes Proposal
        page.click("#btn-manager-accept")
        page.wait_for_selector("#view-export.active", timeout=15000)

        # 5. Step 5: Verify Finalized Approved Product Record and Cryptographic Fingerprint in DOM
        page.wait_for_selector("#approved-products-list input.font-mono", timeout=10000)
        art_sha = page.input_value("#approved-products-list input.font-mono")
        assert art_sha and len(art_sha.strip()) == 64, f"Invalid artifact sha256 in DOM: '{art_sha}'"

        # Assert zero console/CSP errors occurred during entire interactive lifecycle
        assert len(console_errors) == 0, f"Browser console errors during full journey: {console_errors}"

        browser.close()
