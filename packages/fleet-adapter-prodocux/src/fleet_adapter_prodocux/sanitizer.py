"""
Intake Input Sanitizer.
Enforces DoS limits, filename basename regex, and payload size bounds.
"""
import re

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MiB limit
# Must start with alphanumeric/underscore/dash, contain valid chars, and end with .ext
SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*[.][a-zA-Z0-9]+$")

def sanitize_document_filename(filename: str) -> str:
    """Validate that filename is a plain safe basename without path traversals."""
    if not filename or len(filename) > 255:
        raise ValueError("Filename must be between 1 and 255 characters.")
    
    # Check for path separators
    if "/" in filename or "\\" in filename:
        raise ValueError("Filename must be a plain basename without path separators.")

    if not SAFE_FILENAME_REGEX.match(filename):
        raise ValueError(f"Filename '{filename}' is not a valid safe basename with extension.")

    return filename

def validate_document_payload(document_bytes: bytes, max_bytes: int = MAX_PDF_BYTES) -> None:
    """Check payload length to defend against memory exhaustion and decompression bombs."""
    if not document_bytes:
        raise ValueError("Document payload cannot be empty.")
    if len(document_bytes) > max_bytes:
        raise ValueError(f"Document payload size {len(document_bytes)} bytes exceeds limit of {max_bytes} bytes.")
