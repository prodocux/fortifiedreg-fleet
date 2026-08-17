"""
Fake ProDocuX Intake Adapter (v0.3.0).
Implements IntakePort for deterministic offline tests across all 5 formats (PDF, DOCX, CSV, XLSX, PPTX).
"""
import hashlib
from typing import Any, Dict, Optional
from fleet_adapter_prodocux.sanitizer import sanitize_document_filename, validate_document_payload
from fleet_governance_core.ports.intake_port import IntakePort

class FakeProDocuXIntakeAdapter(IntakePort):
    def __init__(self, synthetic_pages_text: Optional[str] = None):
        self._synthetic_text = synthetic_pages_text or (
            "SYNTHETIC RAW MATERIAL SAFETY DATA SHEET\n"
            "Product: AquaGlow Peptide\n"
            "Supplier: BioSynthetics Ltd\n"
            "CAS: 56-81-5\n"
            "NOAEL (oral, rat): 1000 mg/kg bw/day"
        )

    def extract_pages(
        self, document_filename: str, document_bytes: bytes, max_pages: int = 50
    ) -> Dict[str, Any]:
        safe_filename = sanitize_document_filename(document_filename)
        validate_document_payload(document_bytes)
        source_sha = hashlib.sha256(document_bytes).hexdigest()

        return {
            "status": "success",
            "source_sha256": source_sha,
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text": self._synthetic_text,
                    "ocr_required": False,
                }
            ],
            "truncation": {
                "truncated": False,
                "total_characters": len(self._synthetic_text),
            },
        }

    def profile_document(
        self, document_filename: str, document_bytes: bytes
    ) -> Dict[str, Any]:
        safe_filename = sanitize_document_filename(document_filename)
        validate_document_payload(document_bytes)
        source_sha = hashlib.sha256(document_bytes).hexdigest()

        return {
            "status": "success",
            "document_filename": safe_filename,
            "source_sha256": source_sha,
            "paragraph_count": 5,
            "table_count": 1,
            "word_count": 120,
        }

    def profile_table(
        self, document_filename: str, document_bytes: bytes
    ) -> Dict[str, Any]:
        safe_filename = sanitize_document_filename(document_filename)
        validate_document_payload(document_bytes)
        source_sha = hashlib.sha256(document_bytes).hexdigest()

        return {
            "status": "success",
            "document_filename": safe_filename,
            "source_sha256": source_sha,
            "row_count": 10,
            "column_count": 4,
            "columns": ["col1", "col2", "col3", "col4"],
        }

    def profile_workbook(
        self, document_filename: str, document_bytes: bytes
    ) -> Dict[str, Any]:
        safe_filename = sanitize_document_filename(document_filename)
        validate_document_payload(document_bytes)
        source_sha = hashlib.sha256(document_bytes).hexdigest()

        return {
            "status": "success",
            "document_filename": safe_filename,
            "source_sha256": source_sha,
            "sheet_count": 2,
            "sheets": ["Sheet1", "Sheet2"],
            "total_rows": 25,
        }

    def profile_presentation(
        self, document_filename: str, document_bytes: bytes
    ) -> Dict[str, Any]:
        safe_filename = sanitize_document_filename(document_filename)
        validate_document_payload(document_bytes)
        source_sha = hashlib.sha256(document_bytes).hexdigest()

        return {
            "status": "success",
            "document_filename": safe_filename,
            "source_sha256": source_sha,
            "slide_count": 6,
            "total_words": 150,
        }
