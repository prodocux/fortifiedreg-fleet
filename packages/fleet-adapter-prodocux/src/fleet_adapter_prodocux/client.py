"""
ProDocuX HTTP Intake Client Adapter (v0.3.0).
Implements IntakePort with strict URL validation, format-specific byte limits,
injectable client support, retry with exponential backoff, granular timeout vs connection errors,
and strict validation against capabilities contract drift (prodocux_intake_capabilities_v1).
"""
import base64
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import requests
from fleet_adapter_prodocux.sanitizer import sanitize_document_filename
from fleet_governance_core.ports.intake_port import IntakePort

# Exact upstream format limits from ProDocuX (pin 7a1d820...)
MAX_PDF_BYTES = 10 * 1024 * 1024           # 10 MiB (10,485,760 bytes)
MAX_DOCX_BYTES = 16 * 1024 * 1024         # 16 MiB (16,777,216 bytes)
MAX_TABLE_BYTES = 8 * 1024 * 1024         # 8 MiB (8,388,608 bytes)
MAX_WORKBOOK_BYTES = 16 * 1024 * 1024     # 16 MiB (16,777,216 bytes)
MAX_PRESENTATION_BYTES = 32 * 1024 * 1024 # 32 MiB (33,554,432 bytes)
FLEET_MAX_BYTES = 50 * 1024 * 1024        # 50 MiB Fleet upload boundary
MAX_PDF_PAGES = 50

FORMAT_LIMITS = {
    ".pdf": MAX_PDF_BYTES,
    ".docx": MAX_DOCX_BYTES,
    ".csv": MAX_TABLE_BYTES,
    ".xlsx": MAX_WORKBOOK_BYTES,
    ".pptx": MAX_PRESENTATION_BYTES,
}

EXPECTED_FORMAT_CAPABILITIES = {
    ".pdf": {"operation": "extract_pages", "max_bytes": MAX_PDF_BYTES, "max_pages": MAX_PDF_PAGES},
    ".docx": {"operation": "profile_document", "max_bytes": MAX_DOCX_BYTES},
    ".csv": {"operation": "profile_table", "max_bytes": MAX_TABLE_BYTES},
    ".xlsx": {"operation": "profile_workbook", "max_bytes": MAX_WORKBOOK_BYTES},
    ".pptx": {"operation": "profile_presentation", "max_bytes": MAX_PRESENTATION_BYTES},
}

class IntakePayloadError(ValueError):
    """Client-side error: invalid filename, unsupported format, or payload exceeding format limit (400)."""

class IntakeServiceUnavailableError(RuntimeError):
    """Base upstream service failure (502 / 504)."""

class IntakeTimeoutError(IntakeServiceUnavailableError):
    """Upstream service request timed out (504)."""

class IntakeConnectionError(IntakeServiceUnavailableError):
    """Upstream service connection refused or unreachable (502)."""

class IntakeConfigurationError(RuntimeError):
    """Configuration error: invalid or missing upstream URL."""

def validate_prodocux_url(url: str, is_production: bool = False) -> str:
    """Validate and sanitize upstream ProDocuX Base URL."""
    if not url or not isinstance(url, str):
        raise IntakeConfigurationError("ProDocuX Base URL is required and cannot be empty.")

    cleaned = url.strip()
    parsed = urlparse(cleaned)

    if parsed.scheme not in ("http", "https"):
        raise IntakeConfigurationError(
            f"Invalid URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted."
        )

    if is_production and parsed.scheme != "https":
        raise IntakeConfigurationError("HTTPS is strictly required for ProDocuX Base URL in production.")

    if parsed.username or parsed.password:
        raise IntakeConfigurationError("Credentials/userinfo are forbidden in ProDocuX Base URL.")

    if parsed.query or parsed.fragment:
        raise IntakeConfigurationError("Query parameters and fragments are forbidden in ProDocuX Base URL.")

    return cleaned.rstrip("/")

class ProDocuXHttpIntakeAdapter(IntakePort):
    """Production HTTP adapter communicating with upstream ProDocuX Kernel."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        http_client: Any = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        is_production: Optional[bool] = None,
    ):
        fleet_env = os.getenv("FLEET_ENV", "production").lower()
        prod_mode = is_production if is_production is not None else (fleet_env not in ("test", "local", "dev"))

        if base_url is None:
            env_url = os.getenv("PRODOCUX_BASE_URL")
            if not env_url:
                if prod_mode:
                    raise IntakeConfigurationError(
                        "PRODOCUX_BASE_URL environment variable is mandatory in production/staging."
                    )
                env_url = "http://localhost:8900"
            base_url = env_url

        self._base_url = validate_prodocux_url(base_url, is_production=prod_mode)
        self._client = http_client or requests.Session()
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)

    @property
    def base_url(self) -> str:
        return self._base_url

    def validate_and_check_size(self, filename: str, content: bytes) -> tuple[str, str]:
        """Validate filename and enforce format-specific effective limits before transmission."""
        safe_filename = sanitize_document_filename(filename)
        ext = Path(safe_filename).suffix.casefold()

        if ext not in FORMAT_LIMITS:
            raise IntakePayloadError(
                f"Unsupported document format '{ext}'. Allowed formats: {sorted(FORMAT_LIMITS.keys())}"
            )

        effective_limit = min(FLEET_MAX_BYTES, FORMAT_LIMITS[ext])
        size = len(content)

        if size == 0:
            raise IntakePayloadError("Document payload is empty (0 bytes).")

        if size > effective_limit:
            raise IntakePayloadError(
                f"Document size ({size} bytes) exceeds effective limit of {effective_limit} bytes for format '{ext}'."
            )

        return safe_filename, ext

    def _execute_http(self, method: str, endpoint: str, json_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute HTTP request with retry on transient failures and fine-grained error mapping."""
        url = f"{self._base_url}{endpoint}"
        last_error = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                # Support both requests.Session and starlette.testclient.TestClient
                if hasattr(self._client, "request"):
                    resp = self._client.request(method, url, json=json_payload, timeout=self._timeout)
                elif method.upper() == "GET":
                    resp = self._client.get(url, timeout=self._timeout)
                elif method.upper() == "POST":
                    resp = self._client.post(url, json=json_payload, timeout=self._timeout)
                else:
                    raise IntakePayloadError(f"Unsupported HTTP method '{method}'")

                # Successful response
                if resp.status_code == 200:
                    return resp.json()

                # Client-side 4xx errors: fail immediately without retry
                if 400 <= resp.status_code < 500:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")
                    except Exception:
                        detail = resp.text[:120]
                    raise IntakePayloadError(f"ProDocuX rejected request ({resp.status_code}): {detail}")

                # Server-side 5xx errors (502, 503, 504) -> candidate for retry
                if resp.status_code in (502, 503, 504) and attempt < self._max_attempts:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue

                if resp.status_code == 504:
                    raise IntakeTimeoutError(f"ProDocuX upstream timed out with status {resp.status_code}")
                raise IntakeConnectionError(f"ProDocuX upstream service returned error status {resp.status_code}")

            except IntakePayloadError:
                raise
            except requests.Timeout as exc:
                last_error = IntakeTimeoutError(f"ProDocuX request timed out after {self._timeout}s")
                if attempt < self._max_attempts:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise last_error from exc
            except (requests.ConnectionError, IntakeConnectionError) as exc:
                last_error = IntakeConnectionError(f"ProDocuX service unreachable at '{self._base_url}': {exc}")
                if attempt < self._max_attempts:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise last_error from exc
            except IntakeTimeoutError as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise last_error from exc
            except Exception as exc:
                last_error = IntakeConnectionError(
                    f"ProDocuX service unreachable at '{self._base_url}': {type(exc).__name__}"
                )
                if attempt < self._max_attempts:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise last_error from exc

        raise last_error or IntakeServiceUnavailableError(f"ProDocuX request failed after {self._max_attempts} attempts")

    def extract_pages(
        self, document_filename: str, document_bytes: bytes, max_pages: int = 50
    ) -> Dict[str, Any]:
        """Extract pages from PDF document using ProDocuX Kernel."""
        safe_filename, ext = self.validate_and_check_size(document_filename, document_bytes)
        if ext != ".pdf":
            raise IntakePayloadError(f"extract_pages requires .pdf format, got '{ext}'")

        doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "document_filename": safe_filename,
            "document_b64": doc_b64,
            "max_pages": max_pages,
        }
        return self._execute_http("POST", "/v1/intake/extract-pages", payload)

    def profile_document(self, document_filename: str, document_bytes: bytes) -> Dict[str, Any]:
        """Profile DOCX document metadata and structure using ProDocuX Kernel."""
        safe_filename, ext = self.validate_and_check_size(document_filename, document_bytes)
        if ext != ".docx":
            raise IntakePayloadError(f"profile_document requires .docx format, got '{ext}'")

        doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "document_filename": safe_filename,
            "document_b64": doc_b64,
        }
        return self._execute_http("POST", "/v1/intake/profile-document", payload)

    def profile_table(self, document_filename: str, document_bytes: bytes) -> Dict[str, Any]:
        """Profile CSV table metadata and columns using ProDocuX Kernel."""
        safe_filename, ext = self.validate_and_check_size(document_filename, document_bytes)
        if ext != ".csv":
            raise IntakePayloadError(f"profile_table requires .csv format, got '{ext}'")

        doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "document_filename": safe_filename,
            "document_b64": doc_b64,
        }
        return self._execute_http("POST", "/v1/intake/profile-table", payload)

    def profile_workbook(self, document_filename: str, document_bytes: bytes) -> Dict[str, Any]:
        """Profile XLSX workbook metadata and sheets using ProDocuX Kernel."""
        safe_filename, ext = self.validate_and_check_size(document_filename, document_bytes)
        if ext != ".xlsx":
            raise IntakePayloadError(f"profile_workbook requires .xlsx format, got '{ext}'")

        doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "document_filename": safe_filename,
            "document_b64": doc_b64,
        }
        return self._execute_http("POST", "/v1/intake/profile-workbook", payload)

    def profile_presentation(self, document_filename: str, document_bytes: bytes) -> Dict[str, Any]:
        """Profile PPTX presentation metadata and slides using ProDocuX Kernel."""
        safe_filename, ext = self.validate_and_check_size(document_filename, document_bytes)
        if ext != ".pptx":
            raise IntakePayloadError(f"profile_presentation requires .pptx format, got '{ext}'")

        doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "document_filename": safe_filename,
            "document_b64": doc_b64,
        }
        return self._execute_http("POST", "/v1/intake/profile-presentation", payload)

    def get_version(self) -> Dict[str, Any]:
        """Retrieve upstream ProDocuX version and schemas."""
        return self._execute_http("GET", "/v1/version")

    def check_readiness(self) -> Dict[str, Any]:
        """
        Check upstream ProDocuX readiness against typed capabilities contract,
        verifying format availability, max_bytes, and max_pages against contract drift.
        """
        version_data = self.get_version()
        capabilities = self._execute_http("GET", "/v1/intake/capabilities")
        
        schema_version = capabilities.get("schema_version")
        if schema_version != "prodocux_intake_capabilities_v1":
            raise IntakeServiceUnavailableError(
                f"Unexpected capabilities schema version '{schema_version}', expected 'prodocux_intake_capabilities_v1'"
            )

        formats = capabilities.get("formats", [])
        formats_by_ext = {}
        for f in formats:
            for ext in f.get("extensions", []):
                formats_by_ext[ext] = f

        # Validate all 5 required formats against expected limits and availability
        for ext, expected in EXPECTED_FORMAT_CAPABILITIES.items():
            if ext not in formats_by_ext:
                raise IntakeServiceUnavailableError(f"Capabilities drift: missing format capability for '{ext}'")
            
            cap = formats_by_ext[ext]
            if cap.get("status") != "available":
                raise IntakeServiceUnavailableError(f"Capabilities drift: format '{ext}' status is '{cap.get('status')}', expected 'available'")
            if cap.get("operation") != expected["operation"]:
                raise IntakeServiceUnavailableError(f"Capabilities drift: format '{ext}' operation is '{cap.get('operation')}', expected '{expected['operation']}'")
            if cap.get("max_bytes") != expected["max_bytes"]:
                raise IntakeServiceUnavailableError(f"Capabilities drift: format '{ext}' max_bytes is {cap.get('max_bytes')}, expected {expected['max_bytes']}")
            if "max_pages" in expected and cap.get("max_pages") != expected["max_pages"]:
                raise IntakeServiceUnavailableError(f"Capabilities drift: format '{ext}' max_pages is {cap.get('max_pages')}, expected {expected['max_pages']}")

        return {
            "status": "ready",
            "schema_version": schema_version,
            "kernel_version": version_data.get("kernel_version", capabilities.get("kernel_version")),
            "api_version": version_data.get("api_version", capabilities.get("api_version")),
            "formats": formats,
        }

# Backward-compatible alias
ProDocuXIntakeClient = ProDocuXHttpIntakeAdapter
