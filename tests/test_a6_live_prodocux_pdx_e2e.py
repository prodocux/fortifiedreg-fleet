"""
A6 Live ProDocuX & PDX Artifact Engine Integration E2E Test Suite (v0.4.0).
Validates:
1. Two-commit provenance & Compatibility Manifest v3 byte-identical SHA-256 verification (9591ab36...).
2. Exact Commit A'' pins for ProDocuX (53c4784d...) and PDX Core (37e89752...).
3. 5-format binary intake -> extract-blocks -> Fleet normalization pipeline.
4. 5-format render spec mapping -> prodocux_render_request_v1 -> live artifact render pipeline (both inline and delivery_mode=artifact with GET /v1/render/artifacts/{id} verification).
5. Strict URI boundary enforcement (only artifact:// permitted in Kernel requests, rejecting gs:// and signed URLs).
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

from fleet_api.main import app as fleet_app
from fleet_adapter_prodocux import ProDocuXHttpIntakeAdapter
from fleet_domain_cosmetics.normalizer import normalize_content_blocks
from fleet_domain_cosmetics.export_spec_mapper import (
    map_approved_product_to_render_bundle,
    map_bundle_to_prodocux_render_requests,
)
from fleet_governance_core.models.workflow_v4 import ApprovedProductRecord
from fleet_governance_core.models.storage import ArtifactStorageIdentity

PRODOCUX_REPO_DIR = Path("D:/ProDocuX/prodocux")
COMPATIBILITY_V3_SHA256 = "9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b"
PIN_PRODOCUX_COMMIT_A = "53c4784d4b2bae4437252a287193e897973e8474"
PIN_PDX_COMMIT_A = "37e89752560b22dc8724d470dce96187f19e3f98"


@pytest.fixture(scope="module")
def prodocux_app_instance():
    """Import and return in-process ProDocuX live FastAPI app instance."""
    if str(PRODOCUX_REPO_DIR) not in sys.path and PRODOCUX_REPO_DIR.exists():
        sys.path.insert(0, str(PRODOCUX_REPO_DIR))
    try:
        from api.main import app as pdx_app
        return pdx_app
    except Exception as exc:
        pytest.skip(f"Live ProDocuX application not importable: {exc}")


@pytest.fixture
def fleet_client():
    return TestClient(fleet_app)


def test_a6_compatibility_manifest_v3_provenance_and_pins(fleet_client):
    """Verify Compatibility Manifest v3 is byte-identical and Commit A'' pins match exactly."""
    # 1. Check local manifest SHA-256
    manifest_path = Path(__file__).resolve().parents[1] / "compatibility" / "pdx_prodocux_compatibility_v3.json"
    assert manifest_path.exists(), "pdx_prodocux_compatibility_v3.json missing in Fleet!"
    calculated_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert calculated_sha == COMPATIBILITY_V3_SHA256, f"Manifest SHA mismatch: {calculated_sha}"

    manifest_alias_path = Path(__file__).resolve().parents[1] / "compatibility" / "compatibility_manifest.json"
    if manifest_alias_path.exists():
        assert hashlib.sha256(manifest_alias_path.read_bytes()).hexdigest() == COMPATIBILITY_V3_SHA256

    # 2. Check /v1/version endpoint reflections
    res = fleet_client.get("/v1/version")
    assert res.status_code == 200
    v_data = res.json()
    assert v_data["prodocux_pin"] == PIN_PRODOCUX_COMMIT_A
    assert v_data["pdx_core_pin"] == PIN_PDX_COMMIT_A
    assert v_data["compatibility_manifest_sha256"] == COMPATIBILITY_V3_SHA256

    # 3. Check manifest content structure
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pdx_prodocux_compatibility_v3"
    assert manifest["prodocux"]["pin"]["commit"] == PIN_PRODOCUX_COMMIT_A
    assert manifest["pdx_artifact_engine"]["pin"]["commit"] == PIN_PDX_COMMIT_A


def test_a6_live_five_formats_extract_blocks_and_fleet_normalizer(prodocux_app_instance):
    """Verify live ProDocuX extract-blocks endpoint extracts content blocks for all 5 formats and feeds Fleet normalizer."""
    live_intake_client = TestClient(prodocux_app_instance)
    adapter = ProDocuXHttpIntakeAdapter(
        base_url="http://testserver",
        http_client=live_intake_client,
        is_production=False,
    )

    # Load valid 5-format golden samples
    samples_path = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "static" / "samples.json"
    samples_dict = json.loads(samples_path.read_text(encoding="utf-8"))

    for fmt, item in samples_dict.items():
        fn = item["fn"]
        raw_bytes = base64.b64decode(item["b64"])
        ext_res = adapter.extract_content_blocks(fn, raw_bytes)
        assert ext_res is not None
        assert "content" in ext_res or "schema_version" in ext_res
        assert "source_sha256" in ext_res
        assert len(ext_res["source_sha256"]) == 64

        # Feed to Fleet cosmetics normalizer
        candidates = normalize_content_blocks(ext_res)
        assert isinstance(candidates, list)


def test_a6_live_five_formats_render_artifact_and_sha256_fingerprint(prodocux_app_instance):
    """Verify live ProDocuX render artifact endpoint executes Fleet prodocux_render_request_v1 specs across 5 formats."""
    live_intake_client = TestClient(prodocux_app_instance)
    adapter = ProDocuXHttpIntakeAdapter(
        base_url="http://testserver",
        http_client=live_intake_client,
        is_production=False,
    )

    # 1. Construct ApprovedProductRecord & Render Bundle
    product = ApprovedProductRecord(
        product_id="prod-a6-live-01",
        tenant_id="tenant-demo",
        session_id="sess-a6-live",
        proposal_id="prop-a6-live",
        revision=1,
        product_name="ProDocuX Live Serum",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        checkpoint_id="chk-a6-live",
        artifact_identity=ArtifactStorageIdentity(
            artifact_id="art-a6-live",
            uri="artifact://fleet-compliance-artifacts/dossiers/prop-a6-live/finalized_pif_record.json",
            sha256="c" * 64,
            size_bytes=2048,
            media_type="application/json",
        ),
        approval_metadata={"approved_by": "signatory", "sha256_checksum": "c" * 64},
    )

    ingredients = [
        {"inci_name": "Aqua", "concentration_pct": 78.5, "cas_number": "7732-18-5"},
        {"inci_name": "Glycerin", "concentration_pct": 5.0, "cas_number": "56-81-5", "noael_mg_kg_day": 1000.0},
        {"inci_name": "Retinol", "concentration_pct": 0.05, "cas_number": "68-26-8", "noael_mg_kg_day": 2.0},
        {"inci_name": "Phenoxyethanol", "concentration_pct": 0.8, "cas_number": "122-99-6", "noael_mg_kg_day": 500.0},
    ]
    sccs_summary = {"status": "PASS", "all_mos_safe": True}

    bundle_spec = map_approved_product_to_render_bundle(product, ingredients, sccs_summary)
    render_requests = map_bundle_to_prodocux_render_requests(bundle_spec)

    # 2. Render all 5 formats live (inline mode)
    for fmt in ["pdf", "docx", "csv", "xlsx", "pptx"]:
        render_req = render_requests[fmt]
        render_res = adapter.render_artifact(render_req)
        assert render_res["status"] == "completed"
        assert render_res["target_format"] == fmt
        assert len(render_res["output_sha256"]) == 64
        assert "content_b64" in render_res

    # 3. Test delivery_mode="artifact" with GET /v1/render/artifacts/{artifact_id} retrieval and SHA-256 validation
    req_artifact_mode = dict(render_requests["docx"])
    req_artifact_mode["output"] = {
        "output_name": "summary.docx",
        "delivery_mode": "artifact",
    }
    render_res_art = adapter.render_artifact(req_artifact_mode)
    assert render_res_art["status"] == "completed"
    assert "artifact" in render_res_art
    art_meta = render_res_art["artifact"]
    assert art_meta["uri"].startswith("artifact://")
    art_id = art_meta["artifact_id"]

    # Call GET /v1/render/artifacts/{art_id}
    get_resp = live_intake_client.get(f"/v1/render/artifacts/{art_id}")
    assert get_resp.status_code == 200
    downloaded_bytes = get_resp.content
    calc_sha = hashlib.sha256(downloaded_bytes).hexdigest()
    assert calc_sha == render_res_art["output_sha256"], "Downloaded artifact SHA256 must match output_sha256"


def test_a6_strict_uri_boundary_enforcement(prodocux_app_instance):
    """Verify ProDocuX Kernel render endpoint strictly rejects gs:// and signed URLs in render requests."""
    live_intake_client = TestClient(prodocux_app_instance)
    adapter = ProDocuXHttpIntakeAdapter(
        base_url="http://testserver",
        http_client=live_intake_client,
        is_production=False,
    )

    # 1. Attempt render request with gs:// URI
    bad_gs_req = {
        "artifact_type": "prodocux_render_request_v1",
        "format": "docx",
        "title": "Invalid GS Request",
        "metadata": {"template_uri": "gs://my-bucket/template.docx"},
    }
    with pytest.raises(Exception):
        adapter.render_artifact(bad_gs_req)

    # 2. Attempt render request with signed URL
    bad_signed_url_req = {
        "artifact_type": "prodocux_render_request_v1",
        "format": "pdf",
        "title": "Invalid Signed URL Request",
        "metadata": {"template_uri": "https://storage.googleapis.com/bucket/doc.pdf?X-Goog-Signature=abc123def"},
    }
    with pytest.raises(Exception):
        adapter.render_artifact(bad_signed_url_req)
