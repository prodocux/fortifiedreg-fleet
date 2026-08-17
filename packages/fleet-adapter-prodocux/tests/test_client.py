"""
Unit Tests for FakeProDocuXIntakeAdapter.
Validates extraction payload against intake_response_v1.json schema.
"""
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from fleet_adapter_prodocux.fake import FakeProDocuXIntakeAdapter

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
SCHEMA_PATH = ROOT_DIR / "schemas" / "proposed_part_a_contracts" / "prodocux" / "intake_response_v1.json"

def test_fake_intake_extraction_conformance():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    adapter = FakeProDocuXIntakeAdapter()
    dummy_pdf_bytes = b"%PDF-1.4 synthetic SDS binary stream"

    result = adapter.extract_pages("synthetic_sds.pdf", dummy_pdf_bytes)

    # Validate against proposed schema
    validator.validate(result)

    assert result["status"] == "success"
    assert len(result["pages"]) == 1
    assert "AquaGlow" in result["pages"][0]["text"]
    assert result["truncation"]["truncated"] is False
