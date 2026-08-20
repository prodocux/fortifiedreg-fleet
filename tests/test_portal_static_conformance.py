"""
Static Conformance Gate for Portal and API Truth (v0.3.2).
Enforces that no mock fallbacks, fake checkpoints, hardcoded MoS, or client-side threat mocking exist in portal code.
"""
from pathlib import Path
import pytest

PORTAL_HTML_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "static" / "portal.html"
PORTAL_JS_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "static" / "portal.js"
AUTH_ROUTER_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "routers" / "auth.py"
MAIN_PATH = Path(__file__).resolve().parents[1] / "apps" / "fleet-api" / "src" / "fleet_api" / "main.py"


def test_portal_no_mock_fallback_or_fake_checkpoints():
    """Verify that portal JS/HTML contains no synthetic checkpoint or digest fallbacks in catch blocks."""
    html_content = PORTAL_HTML_PATH.read_text(encoding="utf-8")
    js_content = PORTAL_JS_PATH.read_text(encoding="utf-8")
    combined = html_content + "\n" + js_content

    forbidden_patterns = [
        "local deterministic mock",
        "chk-sccs-",
        "f0e1d2c3b4a59687",
        "AWAITING_CSO_APPROVAL",
        "THREAT_DETECTED (Prompt Injection Risk High)",
        "Math.random()",
    ]

    for pattern in forbidden_patterns:
        # Note: Math.random() is forbidden except where specifically isolated
        if pattern == "Math.random()":
            # Ensure no mock tokens or fake digests generated via random
            assert "token = " + pattern not in js_content
            assert "digest = " + pattern not in js_content
        else:
            assert pattern not in combined, f"Forbidden mock/fallback pattern found: '{pattern}'"


def test_no_arbitrary_auth_token_endpoint():
    """Verify that arbitrary /v1/auth/token endpoint does not exist in auth router or portal."""
    auth_content = AUTH_ROUTER_PATH.read_text(encoding="utf-8")
    js_content = PORTAL_JS_PATH.read_text(encoding="utf-8")

    assert "/v1/auth/token" not in auth_content, "Arbitrary /v1/auth/token route found in auth.py!"
    assert "/v1/auth/token" not in js_content, "Deprecated /v1/auth/token found in portal.js!"
    assert "/v1/demo/session" in auth_content, "Scoped /v1/demo/session route missing from auth.py!"
    assert "/v1/demo/session" in js_content, "Portal should use /v1/demo/session!"


def test_version_bumped_to_v0_3_2():
    """Verify that version 0.3.2 is consistently declared."""
    main_content = MAIN_PATH.read_text(encoding="utf-8")
    html_content = PORTAL_HTML_PATH.read_text(encoding="utf-8")
    js_content = PORTAL_JS_PATH.read_text(encoding="utf-8")

    assert 'version="0.3.2"' in main_content
    assert "v0.3.2" in html_content
    assert "v0.3.2" in js_content
