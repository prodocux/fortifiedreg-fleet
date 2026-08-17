"""
Gate 6A: ProDocuX HTTP Live Endpoint Conformance Test.
Tests against a live running ProDocuX server when PRODOCUX_LIVE_URL (or PRODOCUX_BASE_URL) is provided.
If the live server is not running or not configured, this suite explicitly skips
and reports 'SKIPPED (NOT RUN)' rather than falsely claiming PASS.
"""
import base64
import datetime
import io
import os
from openpyxl import Workbook
from pypdf import PdfWriter
import pytest
import requests
from fleet_adapter_prodocux import ProDocuXHttpIntakeAdapter, validate_prodocux_url

PRODOCUX_LIVE_URL = os.getenv("PRODOCUX_LIVE_URL") or os.getenv("PRODOCUX_BASE_URL")
PIN_PRODOCUX_COMMIT = "c8acd2ba69c23458cb2589d8450246fe9b16424f"


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
    """Verify live ProDocuX HTTP server version, capabilities, and document intake across all 5 formats."""
    # 1. Version Check
    ver = live_adapter.get_version()
    assert ver.get("kernel_version") == "0.2.0"
    assert ver.get("api_version") == "v1"

    # 2. Readiness and Capabilities Check
    ready = live_adapter.check_readiness()
    assert ready.get("status") == "ready"
    assert ready.get("schema_version") == "prodocux_intake_capabilities_v1"

    # 3. PDF Extraction
    buf_pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buf_pdf)
    extract_pdf = live_adapter.extract_pages("live_test.pdf", buf_pdf.getvalue())
    assert extract_pdf.get("status") in ("success", "ocr_required")

    # 4. DOCX Profiling
    from docx import Document
    doc = Document()
    doc.add_heading("Specification", 0)
    doc.add_paragraph("Valid docx specification content.")
    buf_docx = io.BytesIO()
    doc.save(buf_docx)
    profile_docx = live_adapter.profile_document("live_test.docx", buf_docx.getvalue())
    assert profile_docx.get("schema_version") == "prodocux_docx_profile_v1"

    # 5. CSV Table Profiling
    csv_bytes = b"inci_name,cas_number,percentage\nAqua,7732-18-5,85.0\n"
    profile_csv = live_adapter.profile_table("live_test.csv", csv_bytes)
    assert profile_csv.get("schema_version") == "prodocux_table_profile_v1"

    # 6. XLSX Workbook Profiling
    buf_xlsx = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Ingredients"
    ws.append(["Component", "Percent"])
    ws.append(["Retinol", 0.05])
    wb.save(buf_xlsx)
    profile_xlsx = live_adapter.profile_workbook("live_test.xlsx", buf_xlsx.getvalue())
    assert profile_xlsx.get("schema_version") == "prodocux_workbook_profile_v1"

    # 7. PPTX Presentation Profiling
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Presentation Title"
    buf_pptx = io.BytesIO()
    prs.save(buf_pptx)
    profile_pptx = live_adapter.profile_presentation("live_test.pptx", buf_pptx.getvalue())
    assert profile_pptx.get("schema_version") == "prodocux_presentation_profile_v1"

    # Record evidence metadata
    evidence = {
        "gate": "G6A_LIVE_CONFORMANCE",
        "status": "PASS",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "endpoint_sanitized": validate_prodocux_url(PRODOCUX_LIVE_URL),
        "upstream_commit_pin": PIN_PRODOCUX_COMMIT,
        "kernel_version": ver.get("kernel_version"),
        "api_version": ver.get("api_version"),
        "pdf_source_sha256": extract_pdf.get("source_sha256"),
        "docx_schema_version": profile_docx.get("schema_version"),
        "csv_schema_version": profile_csv.get("schema_version"),
        "xlsx_schema_version": profile_xlsx.get("schema_version"),
        "pptx_schema_version": profile_pptx.get("schema_version"),
    }
    assert evidence["status"] == "PASS"
