"""
Fleet Adapter ProDocuX Package (v0.3.0).
Provides production HTTP adapter and local mock adapter for ProDocuX Kernel integration.
"""
from fleet_adapter_prodocux.client import (
    FLEET_MAX_BYTES,
    FORMAT_LIMITS,
    MAX_DOCX_BYTES,
    MAX_PDF_BYTES,
    MAX_PRESENTATION_BYTES,
    MAX_TABLE_BYTES,
    MAX_WORKBOOK_BYTES,
    IntakeConfigurationError,
    IntakeConnectionError,
    IntakePayloadError,
    IntakeServiceUnavailableError,
    IntakeTimeoutError,
    ProDocuXHttpIntakeAdapter,
    ProDocuXIntakeClient,
    validate_prodocux_url,
)
from fleet_adapter_prodocux.fake import FakeProDocuXIntakeAdapter
from fleet_adapter_prodocux.sanitizer import (
    sanitize_document_filename,
    validate_document_payload,
)

__version__ = "0.4.0"
__all__ = [
    "sanitize_document_filename",
    "validate_document_payload",
    "validate_prodocux_url",
    "ProDocuXHttpIntakeAdapter",
    "ProDocuXIntakeClient",
    "FakeProDocuXIntakeAdapter",
    "IntakePayloadError",
    "IntakeServiceUnavailableError",
    "IntakeTimeoutError",
    "IntakeConnectionError",
    "IntakeConfigurationError",
    "MAX_PDF_BYTES",
    "MAX_DOCX_BYTES",
    "MAX_TABLE_BYTES",
    "MAX_WORKBOOK_BYTES",
    "MAX_PRESENTATION_BYTES",
    "FLEET_MAX_BYTES",
    "FORMAT_LIMITS",
]
