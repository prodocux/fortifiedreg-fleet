"""
Unit Tests for ProDocuX HTTP Intake Client and URL Validation.
Validates:
1. FakeProDocuXIntakeAdapter extraction schema conformance.
2. validate_prodocux_url strict HTTPS default in production.
3. PRODOCUX_TRUSTED_HTTP_HOSTS exact-hostname matching without wildcard/suffix/IP heuristics.
"""
import json
import os
from pathlib import Path
from jsonschema import Draft202012Validator
import pytest
from fleet_adapter_prodocux.client import IntakeConfigurationError, validate_prodocux_url
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


def test_validate_prodocux_url_production_rules(monkeypatch):
    """Verify strict HTTPS enforcement and exact-hostname trusted HTTP list in production."""
    # 1. Non-production permits localhost http
    assert validate_prodocux_url("http://localhost:8900", is_production=False) == "http://localhost:8900"

    # 2. Production defaults to requiring HTTPS
    monkeypatch.delenv("PRODOCUX_TRUSTED_HTTP_HOSTS", raising=False)
    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://localhost:8900", is_production=True)

    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://127.0.0.1:8900", is_production=True)

    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://172.1.2.3:8900", is_production=True)

    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://10.0.0.1:8900", is_production=True)

    # 3. Production with PRODOCUX_TRUSTED_HTTP_HOSTS exact match
    monkeypatch.setenv("PRODOCUX_TRUSTED_HTTP_HOSTS", "prodocux-live, prodocux-mesh")
    assert (
        validate_prodocux_url("http://prodocux-live:8900", is_production=True)
        == "http://prodocux-live:8900"
    )
    assert (
        validate_prodocux_url("http://PRODOCUX-MESH:8900", is_production=True)
        == "http://PRODOCUX-MESH:8900"
    )

    # 4. Suffix/subdomain attacks fail
    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://prodocux-live.attacker.example:8900", is_production=True)

    with pytest.raises(IntakeConfigurationError, match="HTTPS is strictly required"):
        validate_prodocux_url("http://evil-prodocux-live:8900", is_production=True)

    # 5. Invalid URL schemes, userinfo, query, fragment
    with pytest.raises(IntakeConfigurationError, match="Invalid URL scheme"):
        validate_prodocux_url("ftp://prodocux-live:8900", is_production=False)

    with pytest.raises(IntakeConfigurationError, match="Credentials/userinfo are forbidden"):
        validate_prodocux_url("http://user:pass@prodocux-live:8900", is_production=False)

    with pytest.raises(IntakeConfigurationError, match="Query parameters and fragments are forbidden"):
        validate_prodocux_url("http://prodocux-live:8900?token=leak", is_production=False)

    with pytest.raises(IntakeConfigurationError, match="Query parameters and fragments are forbidden"):
        validate_prodocux_url("http://prodocux-live:8900#section", is_production=False)
