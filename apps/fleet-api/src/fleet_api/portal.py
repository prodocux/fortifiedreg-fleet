"""
Web Portal HTML Loader for FortifiedReg Fleet (v0.3.2).
Reads the clean static portal.html from the filesystem.
"""
from pathlib import Path

_STATIC_HTML_PATH = Path(__file__).resolve().parent / "static" / "portal.html"

if _STATIC_HTML_PATH.exists():
    PORTAL_HTML = _STATIC_HTML_PATH.read_text(encoding="utf-8")
else:
    PORTAL_HTML = "<!DOCTYPE html><html><body>Fleet Portal v0.3.2</body></html>"
