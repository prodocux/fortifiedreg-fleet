"""
Static Conformance Gate for Portal and API Truth.
Enforces that no mock fallbacks, fake checkpoints, hardcoded MoS, or client-side threat mocking exist in portal code.
"""
from pathlib import Path
import pytest

PORTAL_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "portal.py"
AUTH_ROUTER_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "routers" / "auth.py"
MAIN_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "main.py"


def test_portal_no_mock_fallback_or_fake_checkpoints():
    """Verify that portal.py contains no synthetic checkpoint or digest fallbacks in catch blocks."""
    content = PORTAL_PATH.read_text(encoding="utf-8")

    forbidden_patterns = [
        "local deterministic mock",
        "chk-sccs-",
        "f0e1d2c3b4a59687",
        "AWAITING_CSO_APPROVAL",
        "THREAT_DETECTED (Prompt Injection Risk High)",
    ]

    for pattern in forbidden_patterns:
        assert pattern not in content, f"Forbidden mock/fallback pattern found in portal.py: '{pattern}'"


def test_no_arbitrary_auth_token_endpoint():
    """Verify that arbitrary /v1/auth/token endpoint does not exist in auth router or portal."""
    auth_content = AUTH_ROUTER_PATH.read_text(encoding="utf-8")
    portal_content = PORTAL_PATH.read_text(encoding="utf-8")

    assert "/v1/auth/token" not in auth_content, "Arbitrary /v1/auth/token route found in auth.py!"
    assert "/v1/auth/token" not in portal_content, "Deprecated /v1/auth/token found in portal.py!"
    assert "/v1/demo/session" in auth_content, "Scattered /v1/demo/session route missing from auth.py!"
    assert "/v1/demo/session" in portal_content, "Portal should use /v1/demo/session!"


def test_version_bumped_to_v0_3_1():
    """Verify that version 0.3.1 is consistently declared."""
    main_content = MAIN_PATH.read_text(encoding="utf-8")
    portal_content = PORTAL_PATH.read_text(encoding="utf-8")

    assert 'version="0.3.1"' in main_content
    assert "v0.3.1" in portal_content
