"""
Gate 6A: ProDocuX HTTP Live Endpoint Conformance Test.
Tests against a live running ProDocuX server when PRODOCUX_LIVE_URL is provided.
If the live server is not running or not configured, this suite explicitly skips
and reports 'SKIPPED (NOT RUN)' rather than falsely claiming PASS.
"""
import datetime
import io
import os
import pytest
import requests
from fleet_adapter_prodocux import ProDocuXHttpIntakeAdapter, validate_prodocux_url

PRODOCUX_LIVE_URL = os.getenv("PRODOCUX_LIVE_URL") or os.getenv("PRODOCUX_BASE_URL")
PIN_PRODOCUX_COMMIT = "7a1d820639910c1d92b31de6eaf0a371f7386182"

@pytest.fixture
def live_adapter():
    if not PRODOCUX_LIVE_URL:
        pytest.skip("PRODOCUX_LIVE_URL not configured -> G6A Live Conformance: SKIPPED (NOT RUN)")

    try:
        # Fast probe
        resp = requests.get(f"{PRODOCUX_LIVE_URL.rstrip('/')}/v1/version", timeout=3.0)
        if resp.status_code != 200:
            pytest.skip(f"PRODOCUX live endpoint returned status {resp.status_code} -> SKIPPED (NOT RUN)")
    except Exception as exc:
        pytest.skip(f"PRODOCUX live endpoint unreachable ({exc}) -> G6A Live Conformance: SKIPPED (NOT RUN)")

    return ProDocuXHttpIntakeAdapter(base_url=PRODOCUX_LIVE_URL, is_production=False)

def test_live_prodocux_endpoint_conformance(live_adapter):
    """Verify live ProDocuX HTTP server version, capabilities, and document intake."""
    ver = live_adapter.get_version()
    assert ver.get("kernel_version") == "0.2.0"
    assert ver.get("api_version") == "v1"

    ready = live_adapter.check_readiness()
    assert ready.get("status") == "ready"
    assert ready.get("schema_version") == "prodocux_intake_capabilities_v1"

    # Ingest a live sample PDF
    from pypdf import PdfWriter
    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buf)
    
    extract_resp = live_adapter.extract_pages("live_test.pdf", buf.getvalue())
    assert extract_resp.get("status") in ("success", "ocr_required")

    # Record evidence metadata
    evidence = {
        "gate": "G6A_LIVE_CONFORMANCE",
        "status": "PASS",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "endpoint_sanitized": validate_prodocux_url(PRODOCUX_LIVE_URL),
        "upstream_commit_pin": PIN_PRODOCUX_COMMIT,
        "kernel_version": ver.get("kernel_version"),
        "api_version": ver.get("api_version"),
        "pdf_source_sha256": extract_resp.get("source_sha256"),
    }
    assert evidence["status"] == "PASS"
