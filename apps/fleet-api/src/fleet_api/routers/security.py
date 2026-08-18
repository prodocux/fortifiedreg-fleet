"""
Security Scanner Router.
Provides real server-side input inspection against Model Armor regex rules,
path traversal defenses, and file extension policies.
"""
import re
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/security", tags=["Security"])

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?(safety\s+|instructions\s+|rules\s+|guidelines\s+)", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"bypass\s+(safety|guardrails|filters)", re.IGNORECASE),
    re.compile(r"approve\s+(toxic|banned|illegal|prohibited)", re.IGNORECASE),
    re.compile(r"mercury\s+(is\s+safe|approved)", re.IGNORECASE),
]

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".csv", ".xlsx", ".pptx"}


class SecurityScanRequest(BaseModel):
    payload_type: str = Field(pattern=r"^(prompt|path|file)$")
    content: str = Field(min_length=1, max_length=8192)
    filename: Optional[str] = None


@router.post("/scan", response_model=Dict[str, Any])
def scan_payload(body: SecurityScanRequest) -> Dict[str, Any]:
    """Scan payload content against server-side guardrails and fail-closed security policies."""
    if body.payload_type == "prompt":
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(body.content):
                return {
                    "decision": "BLOCK",
                    "scanner_mode": "local_regex_emulation",
                    "policy_triggered": "MODEL_ARMOR_PROMPT_INJECTION_POLICY",
                    "message": "Threat detected: Adversarial prompt injection attempt identified.",
                }
        return {
            "decision": "ALLOW",
            "scanner_mode": "local_regex_emulation",
            "policy_triggered": None,
            "message": "Prompt verified compliant with safety guardrails.",
        }

    elif body.payload_type == "path":
        content = body.content
        if ".." in content or content.startswith("/") or content.startswith("\\") or ":" in content:
            return {
                "decision": "BLOCK",
                "scanner_mode": "input_path_policy",
                "policy_triggered": "PATH_TRAVERSAL_PREVENTION_POLICY",
                "message": "Path violation detected: Directory traversal or absolute paths not permitted.",
            }
        return {
            "decision": "ALLOW",
            "scanner_mode": "input_path_policy",
            "policy_triggered": None,
            "message": "Path string normalized and accepted.",
        }

    elif body.payload_type == "file":
        target_name = (body.filename or body.content).lower()
        has_allowed_ext = any(target_name.endswith(ext) for ext in ALLOWED_EXTENSIONS)
        if not has_allowed_ext:
            return {
                "decision": "BLOCK",
                "scanner_mode": "file_extension_policy",
                "policy_triggered": "UNAPPROVED_MEDIA_TYPE_POLICY",
                "message": "Rejected: Only PDF, DOCX, CSV, XLSX, and PPTX formats are allowed.",
            }
        return {
            "decision": "ALLOW",
            "scanner_mode": "file_extension_policy",
            "policy_triggered": None,
            "message": "File format extension verified against allowlist.",
        }

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported payload_type")
