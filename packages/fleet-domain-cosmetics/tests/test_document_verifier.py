"""
Unit Tests for Supplier Document Verifier in fleet-domain-cosmetics.
"""
import json
from pathlib import Path
import pytest
from fleet_domain_cosmetics.document_verifier import evaluate_supplier_documents
from fleet_governance_core.models.case import DossierCase, SupplierDocument, DocumentTypeEnum
from fleet_governance_core.models.verifier import VerifierStatusEnum

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"

def test_supplier_documents_happy_path():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_supplier_documents(case, current_date_iso="2026-08-01T00:00:00+00:00")
    assert res.status == VerifierStatusEnum.PASS
    assert "SUPPLIER_DOCUMENTS_VERIFIED" in res.reason_codes

def test_supplier_documents_empty_review():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_missing_data.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    res = evaluate_supplier_documents(case)
    assert res.status == VerifierStatusEnum.REVIEW
    assert "NO_SUPPLIER_DOCUMENTS_ATTACHED" in res.reason_codes

def test_supplier_documents_expired_fail():
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw)
    case.supplier_documents.append(
        SupplierDocument(
            doc_id="DOC-EXPIRED-001",
            filename="doc-expired.pdf",
            doc_type=DocumentTypeEnum.COA,
            sha256="a" * 64,
            supplier_name="OldChem Ltd",
            expiry_date="2024-01-01T00:00:00Z",
        )
    )
    res = evaluate_supplier_documents(case, current_date_iso="2026-08-01T00:00:00+00:00")
    assert res.status == VerifierStatusEnum.FAIL
    assert "SUPPLIER_DOCUMENT_EXPIRED" in res.reason_codes
