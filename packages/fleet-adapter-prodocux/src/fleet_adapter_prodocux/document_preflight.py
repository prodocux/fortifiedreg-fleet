"""
Document Preflight Module for ProDocuX Adapter (v0.4.0).
Provides defense-in-depth preflight checks before dispatching binary payloads to the ProDocuX binary service.
Enforces container limits, magic bytes, ZIP structure safety, and CSV encoding policies.
"""
import io
import re
import zipfile
from typing import Dict, Optional, Tuple

# Format-specific raw byte ceilings (Fleet bounded preflight)
FORMAT_BYTE_LIMITS: Dict[str, int] = {
    "pdf": 8 * 1024 * 1024,   # 8 MiB
    "docx": 5 * 1024 * 1024,  # 5 MiB
    "csv": 2 * 1024 * 1024,   # 2 MiB
    "xlsx": 5 * 1024 * 1024,  # 5 MiB
    "pptx": 8 * 1024 * 1024,  # 8 MiB
}

MAX_BASE64_LENGTH = 11_200_000  # Enforces ~8 MiB max encoded payload

ZIP_MAX_ENTRIES = 100
ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MiB
ZIP_MAX_COMPRESSION_RATIO = 20.0  # Rev 5 threshold for OOXML XML entries


class DocumentPreflightError(ValueError):
    """Raised when an uploaded document fails adapter-level preflight validation."""
    pass


def validate_document_preflight(format_type: str, raw_bytes: bytes, filename: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validate binary document format, size, magic bytes, and container safety.
    Returns (True, format_type) or raises DocumentPreflightError.
    """
    fmt = (format_type or "").lower().strip().lstrip(".")
    if fmt not in FORMAT_BYTE_LIMITS:
        raise DocumentPreflightError(f"Unsupported format '{fmt}'. Allowed formats: {list(FORMAT_BYTE_LIMITS.keys())}")

    max_bytes = FORMAT_BYTE_LIMITS[fmt]
    if len(raw_bytes) > max_bytes:
        raise DocumentPreflightError(
            f"File size {len(raw_bytes)} bytes exceeds the {fmt.upper()} maximum of {max_bytes} bytes ({max_bytes // (1024 * 1024)} MiB)."
        )

    if len(raw_bytes) < 4:
        raise DocumentPreflightError("File payload is truncated or empty.")

    if filename:
        clean_name = filename.strip()
        if "/" in clean_name or "\\" in clean_name or ".." in clean_name or ":" in clean_name:
            raise DocumentPreflightError("Filename contains invalid or dangerous path traversal characters.")
        if not clean_name.lower().endswith(f".{fmt}"):
            raise DocumentPreflightError(f"Filename '{filename}' does not match declared format '{fmt}'.")

    # Format-specific container checks
    if fmt == "pdf":
        _validate_pdf_preflight(raw_bytes)
    elif fmt in ("docx", "xlsx", "pptx"):
        _validate_ooxml_zip_preflight(fmt, raw_bytes)
    elif fmt == "csv":
        _validate_csv_preflight(raw_bytes)

    return True, fmt


def _validate_pdf_preflight(data: bytes) -> None:
    """Check PDF magic header."""
    if not data.startswith(b"%PDF-"):
        raise DocumentPreflightError("Invalid PDF header: Missing '%PDF-' magic bytes.")


def _validate_ooxml_zip_preflight(fmt: str, data: bytes) -> None:
    """
    Inspect ZIP container safety for OOXML formats (DOCX, XLSX, PPTX).
    Enforces zip-bomb limits, traversal prevention, and checks essential OOXML entries.
    """
    if not data.startswith(b"PK\x03\x04"):
        raise DocumentPreflightError(f"Invalid {fmt.upper()} header: Missing standard ZIP 'PK\\x03\\x04' magic bytes.")

    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            infolist = zf.infolist()
            if len(infolist) > ZIP_MAX_ENTRIES:
                raise DocumentPreflightError(
                    f"ZIP member count {len(infolist)} exceeds safety threshold of {ZIP_MAX_ENTRIES}."
                )

            total_uncompressed = 0
            entry_names = []
            for info in infolist:
                # Check for password/encryption
                if info.flag_bits & 0x1:
                    raise DocumentPreflightError("Encrypted or password-protected OOXML packages are forbidden.")

                # Traversal check on member names
                name = info.filename
                if name.startswith("/") or name.startswith("\\") or ".." in name or ":" in name:
                    raise DocumentPreflightError(f"Dangerous entry name '{name}' detected in ZIP container.")

                total_uncompressed += info.file_size
                if total_uncompressed > ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise DocumentPreflightError(
                        f"ZIP declared uncompressed size exceeds {ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB safety ceiling."
                    )

                if info.compress_size > 0 and info.file_size > 10 * 1024:
                    ratio = info.file_size / info.compress_size
                    if ratio > ZIP_MAX_COMPRESSION_RATIO:
                        raise DocumentPreflightError(
                            f"ZIP compression ratio {ratio:.1f}x for entry '{name}' exceeds safety threshold {ZIP_MAX_COMPRESSION_RATIO}x."
                        )

                entry_names.append(name)

            # Check mandatory OOXML Content_Types
            if "[Content_Types].xml" not in entry_names:
                raise DocumentPreflightError(f"Malformed {fmt.upper()}: Missing mandatory '[Content_Types].xml'.")

            # Check format-specific root XML part
            if fmt == "docx" and "word/document.xml" not in entry_names:
                raise DocumentPreflightError("Malformed DOCX: Missing 'word/document.xml' root structure.")
            elif fmt == "xlsx" and "xl/workbook.xml" not in entry_names:
                raise DocumentPreflightError("Malformed XLSX: Missing 'xl/workbook.xml' root structure.")
            elif fmt == "pptx" and "ppt/presentation.xml" not in entry_names:
                raise DocumentPreflightError("Malformed PPTX: Missing 'ppt/presentation.xml' root structure.")

    except zipfile.BadZipFile:
        raise DocumentPreflightError(f"Corrupted or invalid ZIP container for {fmt.upper()}.")


def _validate_csv_preflight(data: bytes) -> None:
    """Validate CSV text encoding strictly requiring UTF-8 and check for NUL bytes."""
    if b"\x00" in data:
        raise DocumentPreflightError("CSV contains NUL (\\x00) bytes which are prohibited in text documents.")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentPreflightError("CSV encoding validation failed: Only strict UTF-8 is permitted.")

    if not text.strip():
        raise DocumentPreflightError("CSV payload is empty.")
