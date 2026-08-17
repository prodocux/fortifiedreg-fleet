"""
Gate 6B: PDX Core Primitives Live Conformance Test Suite (v0.3.0).
Validates:
1. Local development and release Git provenance (93ec3514261bf89e9cb88b79f524e3fbc5ef4402) and package version (0.2.0a2).
2. Plan compiler deterministic request_id derivation and dynamic multi-format tool mapping.
3. Strict dependency injection in LivePDXCoreOrchestrator constructor (requiring ledger, intake_adapter, document_resolver).
4. Strict tenant isolation in DocumentResolverPort & ThreadSafeDocumentResolver (cross-tenant same doc_id isolation).
5. Strict SHA-256 Digest Binding between resolver binary content, case declaration, and plan inputs.
6. Typed upstream error preservation (IntakeTimeoutError / IntakeConnectionError re-raised cleanly).
7. Run-bound checkpoint isolation across concurrent unmodified runs without cross-talk or cache collisions.
8. Emitted approval request caching and strict binding in resume_with_decision (rejecting forged request IDs).
9. Persistent thread-safe ApprovalLedger lifecycle:
   - Identical replay matching using public get_by_idempotency_key().
   - Idempotency conflict rejection on modified payload.
   - Rejection of second decision on already decided checkpoint.
10. Fail-closed on missing cached plan during resume_with_decision.
11. Resumed plan generation via pdx_artifact_core.approval.build_resumed_plan and host manifest assembly.
12. Storage identity validation via pdx_artifact_core.storage.validate_artifact_storage_identity.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest

import pdx_artifact_core
from pdx_artifact_core.approval import ApprovalError, ApprovalLedger
from fleet_adapter_gcp.document_resolver import ThreadSafeDocumentResolver
from fleet_adapter_pdx.orchestrator import LivePDXCoreOrchestrator
from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_adapter_prodocux import FakeProDocuXIntakeAdapter, IntakeTimeoutError
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    PDXApprovalDecision,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase

PDX_REPO = Path("D:/ProDocuX/pdx-artifact-engine")
PIN_PDX_COMMIT = "93ec3514261bf89e9cb88b79f524e3fbc5ef4402"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Minimal valid PDF fixture
SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>\nendobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n193\n%%EOF\n"
)
SAMPLE_PDF_SHA256 = hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()

# ---------------------------------------------------------------------------
# 1. Package & Provenance Metadata Verification
# ---------------------------------------------------------------------------

def test_pdx_core_local_development_provenance():
    """Verify that pdx-artifact-core is at 0.2.0a2 and local sibling checkout HEAD is exact pin."""
    assert pdx_artifact_core.__version__ == "0.2.0a2"

    dist = importlib.metadata.distribution("pdx-artifact-core")
    assert dist.version == "0.2.0a2"

    # Verify that the exact commit pin exists in the upstream repository
    res = subprocess.run(
        ["git", "-C", str(PDX_REPO), "rev-parse", "--verify", PIN_PDX_COMMIT],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"PDX commit {PIN_PDX_COMMIT} missing: {res.stderr}"

    head_commit = subprocess.check_output(
        ["git", "-C", str(PDX_REPO), "rev-parse", "HEAD"], text=True
    ).strip()
    assert head_commit == PIN_PDX_COMMIT

def test_pdx_core_release_git_provenance():
    """Verify distribution direct_url.json VCS commit provenance in release environments."""
    dist = importlib.metadata.distribution("pdx-artifact-core")
    direct_url_raw = dist.read_text("direct_url.json")
    assert direct_url_raw is not None, "direct_url.json must exist in installed metadata"

    direct_url = json.loads(direct_url_raw)
    if "vcs_info" in direct_url:
        assert direct_url["vcs_info"]["vcs"] == "git"
        assert direct_url["vcs_info"]["commit_id"] == PIN_PDX_COMMIT
    elif direct_url.get("dir_info", {}).get("editable"):
        pytest.skip(
            "pdx-artifact-core is installed as local editable distribution; "
            "Release VCS direct_url provenance check skipped in dev mode (requires clean venv git install)."
        )
    else:
        pytest.fail(f"Invalid distribution direct_url metadata: {direct_url}")

# ---------------------------------------------------------------------------
# 2. Plan Compiler Unique Run ID & Format Mapping
# ---------------------------------------------------------------------------

def test_pdx_compiler_unmodified_produces_unique_case_bound_request_ids():
    """Verify that compile_case_to_pdx_plan derives unique request_id directly from case.case_id."""
    raw1 = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw1["case_id"] = str(uuid4())
    case1 = DossierCase.model_validate(raw1)

    raw2 = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw2["case_id"] = str(uuid4())
    case2 = DossierCase.model_validate(raw2)

    plan1 = compile_case_to_pdx_plan(case1)
    plan2 = compile_case_to_pdx_plan(case2)

    assert plan1["request_id"] != plan2["request_id"]
    assert plan1["request_id"] == f"run-pif-{case1.case_id}"
    assert plan2["request_id"] == f"run-pif-{case2.case_id}"

def test_pdx_compiler_dynamic_format_mapping():
    """Verify that compiler dynamically assigns prodocux tool based on authoritative doc.filename."""
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw["supplier_documents"] = [
        {"doc_id": "doc-01", "filename": "spec.docx", "doc_type": "COA", "sha256": "0" * 64, "supplier_name": "Supplier 1", "expiry_date": "2028-01-10"},
        {"doc_id": "doc-02", "filename": "table.csv", "doc_type": "SDS", "sha256": "1" * 64, "supplier_name": "Supplier 2", "expiry_date": "2028-01-10"},
        {"doc_id": "doc-03", "filename": "data.xlsx", "doc_type": "SDS", "sha256": "2" * 64, "supplier_name": "Supplier 3", "expiry_date": "2028-01-10"},
        {"doc_id": "doc-04", "filename": "slides.pptx", "doc_type": "IFRA_CERT", "sha256": "3" * 64, "supplier_name": "Supplier 4", "expiry_date": "2028-01-10"},
        {"doc_id": "doc-05", "filename": "report.pdf", "doc_type": "SDS", "sha256": "4" * 64, "supplier_name": "Supplier 5", "expiry_date": "2028-01-10"},
    ]
    case = DossierCase.model_validate(raw)
    plan = compile_case_to_pdx_plan(case)

    tools_by_step = {s["id"]: s.get("tool") for s in plan["steps"] if s["kind"] == "tool"}
    assert tools_by_step["step_extract_doc_0_doc-01"] == "prodocux.profile_document"
    assert tools_by_step["step_extract_doc_1_doc-02"] == "prodocux.profile_table"
    assert tools_by_step["step_extract_doc_2_doc-03"] == "prodocux.profile_workbook"
    assert tools_by_step["step_extract_doc_3_doc-04"] == "prodocux.profile_presentation"
    assert tools_by_step["step_extract_doc_4_doc-05"] == "prodocux.extract_pages"

# ---------------------------------------------------------------------------
# 3. DocumentResolverPort, Tenant Isolation & Digest Binding
# ---------------------------------------------------------------------------

class TrackingIntakeAdapter(FakeProDocuXIntakeAdapter):
    def __init__(self):
        super().__init__()
        self.extracted_docs = []

    def extract_pages(self, document_filename: str, document_bytes: bytes, max_pages: int = 50):
        self.extracted_docs.append((document_filename, len(document_bytes)))
        return {
            "status": "success",
            "document_filename": document_filename,
            "page_count": 2,
            "source_sha256": hashlib.sha256(document_bytes).hexdigest(),
            "pages": [{"page_number": 1, "text": "Extracted Content"}],
        }

@pytest.fixture
def shared_ledger():
    return ApprovalLedger()

@pytest.fixture
def tracking_intake():
    return TrackingIntakeAdapter()

@pytest.fixture
def populated_doc_resolver():
    resolver = ThreadSafeDocumentResolver()
    resolver.register_document(
        tenant_id="tenant-acme-corp",
        doc_id="doc-sds-001",
        content=SAMPLE_PDF_BYTES,
        filename="doc-sds-001.pdf",
    )
    return resolver

@pytest.fixture
def live_orchestrator(shared_ledger, tracking_intake, populated_doc_resolver):
    return LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=populated_doc_resolver,
    )

def test_live_pdx_constructor_requires_all_dependencies(shared_ledger, tracking_intake, populated_doc_resolver):
    """Verify that LivePDXCoreOrchestrator fails fast if any required dependency is missing."""
    with pytest.raises(ValueError, match="requires approval_ledger, intake_adapter, and document_resolver"):
        LivePDXCoreOrchestrator(approval_ledger=None, intake_adapter=tracking_intake, document_resolver=populated_doc_resolver) # type: ignore

    with pytest.raises(ValueError, match="requires approval_ledger, intake_adapter, and document_resolver"):
        LivePDXCoreOrchestrator(approval_ledger=shared_ledger, intake_adapter=None, document_resolver=populated_doc_resolver) # type: ignore

    with pytest.raises(ValueError, match="requires approval_ledger, intake_adapter, and document_resolver"):
        LivePDXCoreOrchestrator(approval_ledger=shared_ledger, intake_adapter=tracking_intake, document_resolver=None) # type: ignore

def test_live_pdx_real_document_resolver_execution(live_orchestrator, tracking_intake):
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    
    # 1. Compile & Validate Plan
    plan = live_orchestrator.compile_execution_plan(happy_raw)
    assert plan["schema_version"] == "pdx_execution_plan_v1"

    # 2. Execute Plan to Approval Checkpoint
    exec_res = live_orchestrator.execute_plan(plan, happy_raw)
    assert exec_res["status"] == "awaiting_approval"
    
    # Verify real intake adapter was actually invoked with bytes from resolver
    assert len(tracking_intake.extracted_docs) >= 1
    assert tracking_intake.extracted_docs[0][0] == "doc-sds-001.pdf"
    assert tracking_intake.extracted_docs[0][1] == len(SAMPLE_PDF_BYTES)

def test_live_pdx_cross_tenant_same_doc_id_isolation(shared_ledger, tracking_intake):
    """Verify that Tenant A and Tenant B using the same doc_id never bleed or overwrite each other."""
    resolver = ThreadSafeDocumentResolver()
    
    bytes_a = SAMPLE_PDF_BYTES
    sha_a = hashlib.sha256(bytes_a).hexdigest()

    bytes_b = SAMPLE_PDF_BYTES + b"\n% Tenant B Modification"
    sha_b = hashlib.sha256(bytes_b).hexdigest()

    resolver.register_document("tenant-alpha", "doc-shared-id", bytes_a, "shared.pdf")
    resolver.register_document("tenant-beta", "doc-shared-id", bytes_b, "shared.pdf")

    # Assert resolver retrieves distinct bytes per tenant
    assert resolver.get_document_bytes("tenant-alpha", "doc-shared-id") == bytes_a
    assert resolver.get_document_bytes("tenant-beta", "doc-shared-id") == bytes_b

    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=resolver,
    )

    raw_a = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_a["tenant_id"] = "tenant-alpha"
    raw_a["supplier_documents"] = [{"doc_id": "doc-shared-id", "filename": "shared.pdf", "doc_type": "SDS", "sha256": sha_a, "supplier_name": "Supplier Alpha", "expiry_date": "2028-01-10"}]
    plan_a = orch.compile_execution_plan(raw_a)
    res_a = orch.execute_plan(plan_a, raw_a)
    assert res_a["status"] == "awaiting_approval"

    raw_b = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw_b["tenant_id"] = "tenant-beta"
    raw_b["supplier_documents"] = [{"doc_id": "doc-shared-id", "filename": "shared.pdf", "doc_type": "SDS", "sha256": sha_b, "supplier_name": "Supplier Beta", "expiry_date": "2028-01-10"}]
    plan_b = orch.compile_execution_plan(raw_b)
    res_b = orch.execute_plan(plan_b, raw_b)
    assert res_b["status"] == "awaiting_approval"

def test_live_pdx_tampered_document_sha256_fails_closed(shared_ledger, tracking_intake, populated_doc_resolver):
    """Verify that if document content does not match the case/plan declared sha256, execution fails closed."""
    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=populated_doc_resolver,
    )
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    # Tampered declared SHA-256
    happy_raw["supplier_documents"][0]["sha256"] = "9" * 64
    plan = orch.compile_execution_plan(happy_raw)

    with pytest.raises(RuntimeError, match="Document content SHA-256 mismatch"):
        orch.execute_plan(plan, happy_raw)

def test_live_pdx_missing_document_content_fails_closed(shared_ledger, tracking_intake):
    """Verify that when document content is missing in resolver, execution fails closed."""
    empty_resolver = ThreadSafeDocumentResolver()
    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=empty_resolver,
    )
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    plan = orch.compile_execution_plan(happy_raw)

    with pytest.raises(RuntimeError, match="not found in document resolver"):
        orch.execute_plan(plan, happy_raw)

def test_live_pdx_unmatched_tool_step_fails_closed(live_orchestrator):
    """Verify that a tool step referencing an unresolvable supplier document fails closed."""
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    plan = live_orchestrator.compile_execution_plan(happy_raw)

    # Insert an unmatchable tool step
    plan["steps"].insert(0, {
        "id": "step_extract_doc_999_unmatched",
        "kind": "tool",
        "name": "Extract phantom document",
        "tool": "prodocux.extract_pages",
        "inputs": {"document_id": "doc-phantom-999", "document_filename": "phantom.pdf", "sha256": "0" * 64},
        "outputs": ["text_phantom"],
    })

    with pytest.raises(RuntimeError, match="not found in case supplier_documents"):
        live_orchestrator.execute_plan(plan, happy_raw)

def test_live_pdx_typed_upstream_timeout_error_preserved(shared_ledger, populated_doc_resolver):
    """Verify that IntakeTimeoutError is preserved as typed exception without being wrapped in generic RuntimeError."""
    class TimeoutIntakeAdapter(FakeProDocuXIntakeAdapter):
        def extract_pages(self, *args, **kwargs):
            raise IntakeTimeoutError("Upstream ProDocuX service timed out after 15s")

    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=TimeoutIntakeAdapter(),
        document_resolver=populated_doc_resolver,
    )
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    plan = orch.compile_execution_plan(happy_raw)

    with pytest.raises(IntakeTimeoutError, match="timed out"):
        orch.execute_plan(plan, happy_raw)

# ---------------------------------------------------------------------------
# 4. Checkpoint Isolation Across Multiple Unmodified Runs
# ---------------------------------------------------------------------------

def test_live_pdx_multi_run_checkpoint_isolation(shared_ledger, tracking_intake, populated_doc_resolver):
    """Verify that two separate unmodified dossier runs generate distinct checkpoint IDs and can be approved independently."""
    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=populated_doc_resolver,
    )

    happy_raw_1 = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw_1["case_id"] = str(uuid4())
    happy_raw_1["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    plan_1 = orch.compile_execution_plan(happy_raw_1)

    happy_raw_2 = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw_2["case_id"] = str(uuid4())
    happy_raw_2["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    plan_2 = orch.compile_execution_plan(happy_raw_2)

    # Execute both runs to awaiting_approval
    res_1 = orch.execute_plan(plan_1, happy_raw_1)
    res_2 = orch.execute_plan(plan_2, happy_raw_2)

    chk_1 = res_1["checkpoint"]
    chk_2 = res_2["checkpoint"]

    # Verify checkpoint IDs are unique and run-bound
    assert chk_1["checkpoint_id"] != chk_2["checkpoint_id"]
    assert str(happy_raw_1["case_id"]) in chk_1["checkpoint_id"]
    assert str(happy_raw_2["case_id"]) in chk_2["checkpoint_id"]

    # Approve Run 1
    dec_1 = {
        "decision_id": str(uuid4()),
        "approval_request_id": res_1["approval_request_id"],
        "checkpoint_id": chk_1["checkpoint_id"],
        "idempotency_key": "idemp-multi-01",
        "actor_id": "usr-lead-01",
        "decision": "approved",
        "reason": "Approved run 1",
        "subject_digest": chk_1["subject_digest"],
        "plan_digest": chk_1["plan_digest"],
        "evidence_digests": chk_1["evidence_digests"],
    }
    resume_1 = orch.resume_with_decision(chk_1, dec_1)
    assert resume_1["status"] == "completed"

    # Approve Run 2
    dec_2 = {
        "decision_id": str(uuid4()),
        "approval_request_id": res_2["approval_request_id"],
        "checkpoint_id": chk_2["checkpoint_id"],
        "idempotency_key": "idemp-multi-02",
        "actor_id": "usr-lead-02",
        "decision": "approved",
        "reason": "Approved run 2",
        "subject_digest": chk_2["subject_digest"],
        "plan_digest": chk_2["plan_digest"],
        "evidence_digests": chk_2["evidence_digests"],
    }
    resume_2 = orch.resume_with_decision(chk_2, dec_2)
    assert resume_2["status"] == "completed"

    # Verify both distinct records in ApprovalLedger
    assert shared_ledger.get_by_idempotency_key("idemp-multi-01") is not None
    assert shared_ledger.get_by_idempotency_key("idemp-multi-02") is not None
    assert shared_ledger.get_by_checkpoint_id(chk_1["checkpoint_id"]) is not None
    assert shared_ledger.get_by_checkpoint_id(chk_2["checkpoint_id"]) is not None

# ---------------------------------------------------------------------------
# 5. Persistent ApprovalLedger Lifecycle, Replay & Request Binding
# ---------------------------------------------------------------------------

def test_live_pdx_approval_ledger_persistence_and_replay(live_orchestrator):
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    plan = live_orchestrator.compile_execution_plan(happy_raw)
    exec_res = live_orchestrator.execute_plan(plan, happy_raw)
    
    checkpoint_dict = exec_res["checkpoint"]
    approval_request_id = exec_res["approval_request_id"]

    decision_id = uuid4()
    decision_payload = {
        "decision_id": str(decision_id),
        "approval_request_id": str(approval_request_id),
        "checkpoint_id": checkpoint_dict["checkpoint_id"],
        "idempotency_key": "idemp-shared-ledger-01",
        "actor_id": "usr-safety-lead",
        "decision": "approved",
        "reason": "All toxicology parameters verified against SCCS 12th revision.",
        "subject_digest": checkpoint_dict["subject_digest"],
        "plan_digest": checkpoint_dict["plan_digest"],
        "evidence_digests": checkpoint_dict["evidence_digests"],
    }

    # 1. Initial decision succeeds and generates finalized manifest
    resume_res = live_orchestrator.resume_with_decision(checkpoint_dict, decision_payload)
    assert resume_res["status"] == "completed"
    assert resume_res["final_manifest"]["status"] == "FINALIZED_COMPLIANT"
    assert "artifact_identity" in resume_res
    assert resume_res["artifact_identity"]["uri"].startswith("artifact://")

    # 2. Verify ledger public query methods
    rec = live_orchestrator.approval_ledger.get_by_idempotency_key("idemp-shared-ledger-01")
    assert rec is not None
    assert rec["decision"] == "approved"
    assert rec["actor_id"] == "usr-safety-lead"

    rec_by_chk = live_orchestrator.approval_ledger.get_by_checkpoint_id(checkpoint_dict["checkpoint_id"])
    assert rec_by_chk is not None
    assert rec_by_chk["decision_id"] == str(decision_id)

    # 3. Replay with exact same payload succeeds (idempotent return from persistent ledger)
    replay_res = live_orchestrator.resume_with_decision(checkpoint_dict, decision_payload)
    assert replay_res["status"] == "completed"
    assert replay_res["final_manifest"]["decision_id"] == str(decision_id)

    # 4. Reused idempotency key with conflicting payload -> MUST raise ApprovalError
    conflicting_payload = dict(decision_payload)
    conflicting_payload["decision"] = "rejected"
    with pytest.raises(ApprovalError, match="idempotency key was reused with different content"):
        live_orchestrator.resume_with_decision(checkpoint_dict, conflicting_payload)

    # 5. Second decision on already decided checkpoint with a different key -> MUST raise ApprovalError
    new_decision_payload = dict(decision_payload)
    new_decision_payload["idempotency_key"] = "idemp-new-key-02"
    with pytest.raises(ApprovalError, match="checkpoint was already decided"):
        live_orchestrator.resume_with_decision(checkpoint_dict, new_decision_payload)

def test_live_pdx_rejects_forged_approval_request_id(live_orchestrator):
    """Verify that caller cannot forge an approval request ID not emitted for this checkpoint."""
    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw["supplier_documents"][0]["sha256"] = SAMPLE_PDF_SHA256
    plan = live_orchestrator.compile_execution_plan(happy_raw)
    exec_res = live_orchestrator.execute_plan(plan, happy_raw)
    
    checkpoint_dict = exec_res["checkpoint"]
    forged_request_id = str(uuid4())

    decision_payload = {
        "decision_id": str(uuid4()),
        "approval_request_id": forged_request_id,
        "checkpoint_id": checkpoint_dict["checkpoint_id"],
        "idempotency_key": "idemp-forged-01",
        "actor_id": "usr-safety-lead",
        "decision": "approved",
        "reason": "Safety verified",
        "subject_digest": checkpoint_dict["subject_digest"],
        "plan_digest": checkpoint_dict["plan_digest"],
        "evidence_digests": checkpoint_dict["evidence_digests"],
    }
    with pytest.raises(ApprovalError, match="Approval request ID mismatch"):
        live_orchestrator.resume_with_decision(checkpoint_dict, decision_payload)

# ---------------------------------------------------------------------------
# 6. Fail-Closed on Missing Plan
# ---------------------------------------------------------------------------

def test_live_pdx_fail_closed_on_missing_plan_cache(shared_ledger, tracking_intake, populated_doc_resolver):
    """Verify that resume_with_decision refuses to forge plan and fails closed when plan is not cached."""
    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=populated_doc_resolver,
    )
    orphan_chk = {
        "checkpoint_id": "chk-orphan-001",
        "run_id": "run-nonexistent-999",
        "subject_digest": "0" * 64,
        "plan_digest": "1" * 64,
        "completed_step_ids": ["step_1"],
        "pending_step_ids": ["step_2"],
        "evidence_digests": {},
        "status": "pending",
    }
    decision_payload = {
        "decision_id": str(uuid4()),
        "approval_request_id": str(uuid4()),
        "checkpoint_id": orphan_chk["checkpoint_id"],
        "idempotency_key": "idemp-orphan-01",
        "actor_id": "usr-safety-lead",
        "decision": "approved",
        "reason": "Safety verified",
        "subject_digest": orphan_chk["subject_digest"],
        "plan_digest": orphan_chk["plan_digest"],
        "evidence_digests": orphan_chk["evidence_digests"],
    }
    with pytest.raises(RuntimeError, match="not found in host cache"):
        orch.resume_with_decision(orphan_chk, decision_payload)

# ---------------------------------------------------------------------------
# 7. Early Halting on Verifier Fail / Review
# ---------------------------------------------------------------------------

def test_live_pdx_early_stop_on_toxicology_fail(live_orchestrator):
    fail_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_toxicology_fail.json").read_text(encoding="utf-8"))["data"]
    plan = live_orchestrator.compile_execution_plan(fail_raw)
    exec_res = live_orchestrator.execute_plan(plan, fail_raw)
    
    assert exec_res["status"] == "failed"
    assert "checkpoint" not in exec_res

def test_live_pdx_blocked_on_missing_data_review(live_orchestrator):
    missing_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_missing_data.json").read_text(encoding="utf-8"))["data"]
    plan = live_orchestrator.compile_execution_plan(missing_raw)
    exec_res = live_orchestrator.execute_plan(plan, missing_raw)
    
    assert exec_res["status"] == "blocked_review"
    assert "checkpoint" not in exec_res

# ---------------------------------------------------------------------------
# 8. Deterministic Tool <-> Format Consistency & Exact Lookup Protection
# ---------------------------------------------------------------------------

def test_live_pdx_plan_tool_format_drift_fails_closed(shared_ledger, tracking_intake):
    """Verify that runtime fails closed if declared plan tool does not match the actual document format tool."""
    resolver = ThreadSafeDocumentResolver()
    resolver.register_document("tenant-acme-corp", "doc-sds-001", SAMPLE_PDF_BYTES, "doc-sds-001.docx")

    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=resolver,
    )
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw["supplier_documents"] = [{
        "doc_id": "doc-sds-001",
        "filename": "doc-sds-001.docx",
        "doc_type": "SDS",
        "sha256": SAMPLE_PDF_SHA256,
        "supplier_name": "Acme Supplier",
        "expiry_date": "2028-01-10",
    }]
    plan = orch.compile_execution_plan(raw)
    
    # Intentionally corrupt the plan tool to forge an extract_pages call on a docx file
    for s in plan["steps"]:
        if s.get("kind") == "tool":
            s["tool"] = "prodocux.extract_pages"

    with pytest.raises(RuntimeError, match="plan-runtime tool drift"):
        orch.execute_plan(plan, raw)

def test_live_pdx_filename_drift_fails_closed(shared_ledger, tracking_intake):
    """Verify that runtime fails closed if document filename registered in resolver differs from plan declaration."""
    resolver = ThreadSafeDocumentResolver()
    resolver.register_document("tenant-acme-corp", "doc-sds-001", SAMPLE_PDF_BYTES, "mismatched_filename.pdf")

    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=resolver,
    )
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw["supplier_documents"] = [{
        "doc_id": "doc-sds-001",
        "filename": "doc-sds-001.pdf",
        "doc_type": "SDS",
        "sha256": SAMPLE_PDF_SHA256,
        "supplier_name": "Acme Supplier",
        "expiry_date": "2028-01-10",
    }]
    plan = orch.compile_execution_plan(raw)

    with pytest.raises(RuntimeError, match="Fail-closed on filename drift"):
        orch.execute_plan(plan, raw)

def test_live_pdx_exact_document_id_lookup_avoids_substring_collision(shared_ledger, tracking_intake):
    """Verify that doc-1 does not match doc-10 and exact document_id equality is used."""
    resolver = ThreadSafeDocumentResolver()
    bytes_1 = SAMPLE_PDF_BYTES
    bytes_10 = SAMPLE_PDF_BYTES + b"\n% Doc 10"
    sha_1 = hashlib.sha256(bytes_1).hexdigest()
    sha_10 = hashlib.sha256(bytes_10).hexdigest()

    resolver.register_document("tenant-acme-corp", "doc-1", bytes_1, "doc-1.pdf")
    resolver.register_document("tenant-acme-corp", "doc-10", bytes_10, "doc-10.pdf")

    orch = LivePDXCoreOrchestrator(
        approval_ledger=shared_ledger,
        intake_adapter=tracking_intake,
        document_resolver=resolver,
    )
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw["supplier_documents"] = [
        {"doc_id": "doc-1", "filename": "doc-1.pdf", "doc_type": "SDS", "sha256": sha_1, "supplier_name": "Supplier 1", "expiry_date": "2028-01-10"},
        {"doc_id": "doc-10", "filename": "doc-10.pdf", "doc_type": "COA", "sha256": sha_10, "supplier_name": "Supplier 10", "expiry_date": "2028-01-10"},
    ]
    plan = orch.compile_execution_plan(raw)
    res = orch.execute_plan(plan, raw)
    assert res["status"] == "awaiting_approval"

def test_resolver_cas_rejects_same_bytes_different_filename():
    """Verify that ThreadSafeDocumentResolver CAS rejects re-registration with different filename."""
    resolver = ThreadSafeDocumentResolver()
    resolver.register_document("tenant-test", "doc-01", SAMPLE_PDF_BYTES, "doc-01.pdf")

    # Re-registration with exact same bytes and filename succeeds idempotently
    resolver.register_document("tenant-test", "doc-01", SAMPLE_PDF_BYTES, "doc-01.pdf")

    # Re-registration with same bytes but different filename fails with ValueError
    with pytest.raises(ValueError, match="already exists with different content or filename"):
        resolver.register_document("tenant-test", "doc-01", SAMPLE_PDF_BYTES, "renamed_doc.pdf")

@pytest.mark.parametrize("invalid_filename", ["malware.exe", "notes.txt", "archive.zip", "no_extension"])
def test_compiler_rejects_unsupported_document_formats(invalid_filename: str):
    """Verify that plan compiler fails closed on unsupported or missing extensions without defaulting to PDF."""
    raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    raw["supplier_documents"] = [
        {
            "doc_id": "doc-invalid",
            "filename": invalid_filename,
            "doc_type": "SDS",
            "sha256": SAMPLE_PDF_SHA256,
            "supplier_name": "Invalid Supplier",
            "expiry_date": "2028-01-10",
        }
    ]
    case = DossierCase.model_validate(raw)
    with pytest.raises(ValueError, match="Unsupported document format"):
        compile_case_to_pdx_plan(case)


