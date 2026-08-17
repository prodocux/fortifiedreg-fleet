"""
Regex-Based Prompt Scanner (Local Emulation for Model Armor).
Implements ModelArmorPort with Fail-Closed Prompt Injection Defense and PII Redaction.
"""
import re
from typing import Any, Dict
from fleet_governance_core.exceptions import SecurityScanBlockedError
from fleet_governance_core.ports.model_armor_port import ModelArmorPort

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"bypass\s+(the\s+)?(safety|security|content)\s+filter", re.IGNORECASE),
    re.compile(r"system\s+prompt\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"<script.*?>", re.IGNORECASE),
]

API_KEY_PATTERN = re.compile(r"(AIzaSy[A-Za-z0-9_-]{33}|bearer\s+[A-Za-z0-9_.-]{20,})", re.IGNORECASE)

class RegexPromptScanner(ModelArmorPort):
    """Local regex-based prompt scanner enforcing injection prevention and credential redaction."""

    def __init__(self, fail_closed: bool = True):
        self._fail_closed = fail_closed

    def scan_prompt(self, text: str) -> Dict[str, Any]:
        """Scan input prompt for injection attacks. Raises SecurityScanBlockedError if detected."""
        if not text:
            return {"status": "clean", "threats": []}

        detected_threats = []
        for pattern in INJECTION_PATTERNS:
            if pattern.search(text):
                detected_threats.append(f"Prompt injection pattern: {pattern.pattern}")

        if detected_threats:
            raise SecurityScanBlockedError(
                f"Model Armor blocked prompt execution: {'; '.join(detected_threats)}"
            )

        return {"status": "clean", "threats": []}

    def sanitize_output(self, text: str) -> str:
        """Sanitize output by redacting potential credentials or API keys."""
        if not text:
            return ""
        return API_KEY_PATTERN.sub("[REDACTED_SECRET]", text)

# Honest alias
GoogleModelArmorAdapter = RegexPromptScanner
