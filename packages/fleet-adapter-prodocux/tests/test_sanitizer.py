"""
Unit Tests for Intake Sanitizer in fleet-adapter-prodocux.
"""
import pytest
from fleet_adapter_prodocux.sanitizer import (
    MAX_PDF_BYTES,
    sanitize_document_filename,
    validate_document_payload,
)

def test_valid_basenames_allowed():
    assert sanitize_document_filename("sds_aquaglow.pdf") == "sds_aquaglow.pdf"
    assert sanitize_document_filename("raw_material-2026.docx") == "raw_material-2026.docx"

@pytest.mark.parametrize("bad_name", [
    "../sds.pdf",
    "..\\sds.pdf",
    "/root/sds.pdf",
    "C:\\sds.pdf",
    "folder/sds.pdf",
    ".",
    "..",
    ".hidden.pdf",
    "no_ext",
])
def test_invalid_filenames_rejected(bad_name: str):
    with pytest.raises(ValueError):
        sanitize_document_filename(bad_name)

def test_payload_size_validation():
    validate_document_payload(b"%PDF-1.4 dummy content")

    with pytest.raises(ValueError, match="cannot be empty"):
        validate_document_payload(b"")

    with pytest.raises(ValueError, match="exceeds limit"):
        validate_document_payload(b"x" * (MAX_PDF_BYTES + 1))
