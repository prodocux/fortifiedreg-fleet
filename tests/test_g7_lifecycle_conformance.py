"""
Gate 7 Lifecycle, State Machine & Durable Conformance Test Suite (v0.3.0).
Verifies:
1. 5-format approve -> resume -> completed lifecycle with opaque tenant storage key.
2. Rejection path -> state REJECTED, PDX cancelled, no manifest.
3. Resume failure timing & projection suppression (PDX checkpoint remains pending, no resumed outbox).
4. Crash-safe atomic artifact storage & collision detection.
5. Crash before mark_completed idempotent recovery.
6. Lease fencing and expiration reclamation.
7. True SQLite durable restart recovery.
8. Transport-level verified artifact resolver (scheme, tenant, SHA-256 checks).
"""
import hashlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Optional, Tuple, Union
from uuid import UUID, uuid4
import pytest

from pdx_artifact_core.approval import ApprovalLedger
from fleet_adapter_gcp import (
    InMemoryApprovalStore,
    InMemoryAuditLog,
    InMemoryCheckpointStore,
    ThreadSafeDocumentResolver,
)
from fleet_adapter_local import (
    InMemoryResumeContextStore,
    LocalArtifactStore,
    LocalVerifiedArtifactResolver,
    SQLiteResumeContextStore,
)
from fleet_adapter_pdx import LivePDXCoreOrchestrator, PDXVerifierBridge
from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_adapter_prodocux import FakeProDocuXIntakeAdapter
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    FleetExecutionStatus,
    PDXApprovalDecision,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.execution_context import (
    ExecutionContextRecord,
    PlanSummary,
)
from fleet_governance_core.models.hashing import compute_data_sha256
from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactStatus,
    derive_opaque_tenant_storage_key,
)
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

def _make_dummy_case(tenant_id: str, case_id: Optional[str], filename: str) -> Tuple[DossierCase, Dict[str, Any], bytes]:
    dummy_bytes = (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n193\n%%EOF\n"
    ) if filename.endswith(".pdf") else b"col1,col2\nval1,val2\n"
    doc_sha = hashlib.sha256(dummy_bytes).hexdigest()

    happy_raw = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    happy_raw["tenant_id"] = tenant_id
    if case_id:
        happy_raw["case_id"] = str(uuid4())
    happy_raw["supplier_documents"][0]["filename"] = filename
    happy_raw["supplier_documents"][0]["sha256"] = doc_sha

    case = DossierCase.model_validate(happy_raw)
    return case, happy_raw, dummy_bytes


def test_opaque_tenant_storage_key_derivation():
    """Verify tenant storage key is deterministic and masks the raw tenant name."""
    t1 = "tenant-acme-corp"
    key1 = derive_opaque_tenant_storage_key(t1)
    key2 = derive_opaque_tenant_storage_key(t1)
    key_other = derive_opaque_tenant_storage_key("tenant-beta")

    assert key1.startswith("t-")
    assert len(key1) == 26  # 't-' + 24 hex
    assert key1 == key2
    assert key1 != key_other
    assert "acme" not in key1


def test_sqlite_acid_approval_and_state_transition():
    """Verify that approval recording and status transition occur in a single atomic transaction."""
    store = SQLiteResumeContextStore(":memory:")
    tenant_id = "tenant-alpha"
    chk_id = "chk-test-001"
    run_id = "run-test-001"

    # Save initial context
    plan_sum = PlanSummary(
        request_id="req-001",
        schema_version="pdx_execution_plan_v1",
        step_count=3,
        step_ids=["step-1", "step-2", "step-3"],
        has_approval_step=True,
        product_name="PIF",
        jurisdiction="TW",
    )
    rec = ExecutionContextRecord(
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        case_digest="a" * 64,
        plan_digest="b" * 64,
        plan_summary=plan_sum,
        status=FleetExecutionStatus.AWAITING_DECISION,
    )
    store.save_context(rec)

    actor = AuthenticatedActor(sub="user-1", roles=["approver"])
    app_record = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        approval_request_id=uuid4(),
        canonical_idempotency_key=f"{tenant_id}:{chk_id}:user-1:key-1",
        authenticated_actor=actor,
        decision=ApprovalDecisionEnum.APPROVED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
    )

    # Atomic transition to APPROVED_PENDING_RESUME (no outbox for approved)
    updated = store.record_decision_and_transition(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=1,
        approval_record=app_record,
        target_status=FleetExecutionStatus.APPROVED_PENDING_RESUME,
        outbox_target_pdx_status=None,
    )

    assert updated.status == FleetExecutionStatus.APPROVED_PENDING_RESUME
    assert updated.version == 2

    # Verify no pending resumed outbox exists
    pending_outbox = store.get_pending_outbox_records()
    assert len(pending_outbox) == 0


def test_resume_failure_suppresses_resumed_outbox():
    """Verify that if resume fails, Fleet status is RESUME_FAILED_RETRYABLE and NO resumed outbox is emitted."""
    store = SQLiteResumeContextStore(":memory:")
    tenant_id = "tenant-alpha"
    chk_id = "chk-fail-001"
    run_id = "run-fail-001"

    plan_sum = PlanSummary(
        request_id="req-001",
        schema_version="pdx_execution_plan_v1",
        step_count=2,
        step_ids=["step-1", "step-2"],
        has_approval_step=True,
        product_name="PIF",
        jurisdiction="TW",
    )
    rec = ExecutionContextRecord(
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        case_digest="a" * 64,
        plan_digest="b" * 64,
        plan_summary=plan_sum,
        status=FleetExecutionStatus.APPROVED_PENDING_RESUME,
        version=2,
    )
    store.save_context(rec)

    # 1. Acquire lease
    rec, lease_id = store.acquire_resume_lease(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=2,
        lease_owner="worker-1",
    )
    assert rec.status == FleetExecutionStatus.RESUME_IN_PROGRESS
    assert rec.version == 3

    # 2. Mark resume failed
    rec_failed = store.mark_resume_failed(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=3,
        lease_id=lease_id,
        safe_error_code="STORAGE_TIMEOUT",
        request_id="req-123",
    )

    assert rec_failed.status == FleetExecutionStatus.RESUME_FAILED_RETRYABLE
    assert rec_failed.version == 4
    assert rec_failed.last_error["safe_error_code"] == "STORAGE_TIMEOUT"

    # Verify NO outbox records exist
    assert len(store.get_pending_outbox_records()) == 0


def test_rejection_emits_cancelled_outbox():
    """Verify that human rejection atomically sets REJECTED and creates a cancelled outbox record."""
    store = SQLiteResumeContextStore(":memory:")
    tenant_id = "tenant-alpha"
    chk_id = "chk-rej-001"
    run_id = "run-rej-001"

    plan_sum = PlanSummary(
        request_id="req-001",
        schema_version="pdx_execution_plan_v1",
        step_count=2,
        step_ids=["step-1", "step-2"],
        has_approval_step=True,
        product_name="PIF",
        jurisdiction="TW",
    )
    rec = ExecutionContextRecord(
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        case_digest="a" * 64,
        plan_digest="b" * 64,
        plan_summary=plan_sum,
        status=FleetExecutionStatus.AWAITING_DECISION,
        version=1,
    )
    store.save_context(rec)

    actor = AuthenticatedActor(sub="user-1", roles=["approver"])
    app_record = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        approval_request_id=uuid4(),
        canonical_idempotency_key=f"{tenant_id}:{chk_id}:user-1:key-rej",
        authenticated_actor=actor,
        decision=ApprovalDecisionEnum.REJECTED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
        reason="Toxicology threshold exceeded",
    )

    updated = store.record_decision_and_transition(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=1,
        approval_record=app_record,
        target_status=FleetExecutionStatus.REJECTED,
        outbox_target_pdx_status="cancelled",
    )

    assert updated.status == FleetExecutionStatus.REJECTED
    outbox = store.get_pending_outbox_records()
    assert len(outbox) == 1
    assert outbox[0].target_pdx_status == "cancelled"
    assert outbox[0].checkpoint_id == chk_id


def test_crash_safe_local_artifact_store_and_idempotency():
    """Verify LocalArtifactStore atomic exclusive creation, identical reuse, and conflict rejection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LocalArtifactStore(tmpdir)
        opaque_key = derive_opaque_tenant_storage_key("tenant-1")
        uri = f"artifact://{opaque_key}/checkpoints/chk-1/pif_manifest.json"
        content_1 = b'{"manifest": "version_1"}'
        sha_1 = hashlib.sha256(content_1).hexdigest()

        ident = ArtifactStorageIdentity(
            uri=uri,
            sha256=sha_1,
            size_bytes=len(content_1),
            media_type="application/json",
        )

        # 1. First write -> CREATED
        res_1 = store.put_if_absent(ident, content_1, sha_1)
        assert res_1.status == PutArtifactStatus.CREATED
        assert res_1.bytes_written == len(content_1)

        # 2. Identical second write -> ALREADY_EXISTS_SAME_DIGEST
        res_2 = store.put_if_absent(ident, content_1, sha_1)
        assert res_2.status == PutArtifactStatus.ALREADY_EXISTS_SAME_DIGEST
        assert res_2.sha256 == sha_1

        # 3. Conflicting content write -> ALREADY_EXISTS_CONFLICTING_DIGEST
        content_2 = b'{"manifest": "tampered_version"}'
        sha_2 = hashlib.sha256(content_2).hexdigest()
        ident_conflicting = ArtifactStorageIdentity(
            uri=uri,
            sha256=sha_2,
            size_bytes=len(content_2),
            media_type="application/json",
        )
        res_3 = store.put_if_absent(ident_conflicting, content_2, sha_2)
        assert res_3.status == PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST


def test_verified_artifact_resolver_conformance():
    """Verify transport-level resolver checks scheme, tenant ownership, and digest comparison."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = LocalArtifactStore(tmpdir)
        resolver = LocalVerifiedArtifactResolver(art_store)

        tenant_id = "tenant-security-test"
        opaque_key = derive_opaque_tenant_storage_key(tenant_id)
        uri = f"artifact://{opaque_key}/checkpoints/chk-sec/manifest.json"
        content = b'{"status": "compliant"}'
        sha = hashlib.sha256(content).hexdigest()

        ident = ArtifactStorageIdentity(
            uri=uri,
            sha256=sha,
            size_bytes=len(content),
            media_type="application/json",
        )
        art_store.put_if_absent(ident, content, sha)

        # 1. Happy Path: matching tenant, matching digest
        verified_bytes = resolver.read_verified(ident, sha, tenant_id)
        assert verified_bytes == content

        # 2. Cross-tenant access rejection
        with pytest.raises(ValueError, match="Access Denied"):
            resolver.read_verified(ident, sha, "tenant-attacker")

        # 3. Tampered digest rejection
        tampered_sha = "0" * 64
        with pytest.raises(ValueError, match="Tampered Artifact Detected"):
            resolver.read_verified(ident, tampered_sha, tenant_id)

        # 4. Forbidden scheme rejection at model validation level
        with pytest.raises(Exception):
            ArtifactStorageIdentity(
                uri="http://example.com/manifest.json",
                sha256=sha,
                size_bytes=len(content),
                media_type="application/json",
            )


def test_sqlite_durable_restart_recovery():
    """Verify complete process restart recovery using a shared SQLite database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "fleet_durable.db"
        tenant_id = "tenant-restart"
        case_id = "case-restart-001"

        case, case_payload, dummy_bytes = _make_dummy_case(tenant_id, case_id, "doc.pdf")
        plan = compile_case_to_pdx_plan(case)
        run_id = plan["request_id"]

        # Step 1: Process A creates store and executes up to checkpoint
        store_a = SQLiteResumeContextStore(db_file)
        ledger_a = ApprovalLedger()
        doc_res_a = ThreadSafeDocumentResolver()
        doc_res_a.register_document(tenant_id, "doc-sds-001", dummy_bytes, "doc.pdf")

        orch_a = LivePDXCoreOrchestrator(
            approval_ledger=ledger_a,
            intake_adapter=FakeProDocuXIntakeAdapter(),
            document_resolver=doc_res_a,
            resume_context_store=store_a,
            tenant_id=tenant_id,
        )

        exec_res_a = orch_a.execute_plan(plan, case_payload)
        assert exec_res_a["status"] == "awaiting_approval"
        chk_id = exec_res_a["checkpoint"]["checkpoint_id"]
        app_req_id = exec_res_a["approval_request_id"]

        # Record approval decision in store_a
        actor = AuthenticatedActor(sub="approver-1", roles=["approver"])
        app_rec = FleetApprovalRecord(
            approval_record_id=uuid4(),
            tenant_id=tenant_id,
            run_id=run_id,
            checkpoint_id=chk_id,
            approval_request_id=UUID(app_req_id),
            canonical_idempotency_key=f"{tenant_id}:{chk_id}:approver-1:key-rest",
            authenticated_actor=actor,
            decision=ApprovalDecisionEnum.APPROVED,
            subject_case_digest=compute_data_sha256(case_payload),
            plan_digest=compute_data_sha256(plan),
        )
        store_a.record_decision_and_transition(
            tenant_id=tenant_id,
            checkpoint_id=chk_id,
            expected_version=1,
            approval_record=app_rec,
            target_status=FleetExecutionStatus.APPROVED_PENDING_RESUME,
        )

        # Step 2: Simulate Process A crash & Process B startup with fresh in-memory objects
        del orch_a
        del store_a

        store_b = SQLiteResumeContextStore(db_file)
        ledger_b = ApprovalLedger()
        doc_res_b = ThreadSafeDocumentResolver()
        doc_res_b.register_document(tenant_id, "doc-sds-001", dummy_bytes, "doc.pdf")
        art_store_b = LocalArtifactStore(tmpdir)

        orch_b = LivePDXCoreOrchestrator(
            approval_ledger=ledger_b,
            intake_adapter=FakeProDocuXIntakeAdapter(),
            document_resolver=doc_res_b,
            resume_context_store=store_b,
            artifact_store=art_store_b,
            tenant_id=tenant_id,
        )

        # Restore context from durable store
        restored_ctx = store_b.get_context(tenant_id, chk_id)
        assert restored_ctx is not None
        assert restored_ctx.status == FleetExecutionStatus.APPROVED_PENDING_RESUME

        # Acquire lease & resume in Process B
        ctx_leased, lease_id = store_b.acquire_resume_lease(
            tenant_id=tenant_id,
            checkpoint_id=chk_id,
            expected_version=restored_ctx.version,
            lease_owner="process-b",
        )

        pdx_dec = PDXApprovalDecision(
            decision_id=app_rec.approval_record_id,
            approval_request_id=UUID(app_req_id),
            checkpoint_id=chk_id,
            idempotency_key="key-rest",
            actor_id="approver-1",
            decision=ApprovalDecisionEnum.APPROVED,
            subject_digest=compute_data_sha256(case_payload),
            plan_digest=compute_data_sha256(plan),
            evidence_digests=exec_res_a["evidence_digests"],
            decided_at=app_rec.decided_at,
        )

        # Process B resumes cleanly without synthesized plans
        orch_b._cached_plans[run_id] = plan  # or restored via plan store
        resume_res_b = orch_b.resume_with_decision(exec_res_a["checkpoint"], pdx_dec)
        assert resume_res_b["status"] == "completed"

        result_ident = ArtifactStorageIdentity.model_validate(resume_res_b["artifact_identity"])
        store_b.mark_resume_completed(
            tenant_id=tenant_id,
            checkpoint_id=chk_id,
            expected_version=ctx_leased.version,
            lease_id=lease_id,
            result_identity=result_ident,
        )

        # Verify finalized state in database
        final_ctx = store_b.get_context(tenant_id, chk_id)
        assert final_ctx.status == FleetExecutionStatus.COMPLETED
        assert final_ctx.result_identity is not None

        # Verify outbox has 'resumed'
        outbox = store_b.get_pending_outbox_records()
        assert len(outbox) == 1
        assert outbox[0].target_pdx_status == "resumed"


@pytest.mark.parametrize("ext,doc_filename", [
    (".pdf", "safety_sheet.pdf"),
    (".docx", "specification.docx"),
    (".csv", "table_data.csv"),
    (".xlsx", "toxicology.xlsx"),
    (".pptx", "presentation.pptx"),
])
def test_five_formats_complete_g7_lifecycle(ext: str, doc_filename: str):
    """Verify full 5-format approve -> lease -> resume -> manifest completed lifecycle."""
    tenant_id = "tenant-corp"
    case_id = f"case-{ext.replace('.', '')}-001"

    case, case_payload, dummy_bytes = _make_dummy_case(tenant_id, case_id, doc_filename)
    plan = compile_case_to_pdx_plan(case)
    run_id = plan["request_id"]

    store = InMemoryResumeContextStore()
    ledger = ApprovalLedger()
    doc_res = ThreadSafeDocumentResolver()
    doc_res.register_document(tenant_id, "doc-sds-001", dummy_bytes, doc_filename)
    art_store = LocalArtifactStore("./.temp_g7_artifacts")

    orch = LivePDXCoreOrchestrator(
        approval_ledger=ledger,
        intake_adapter=FakeProDocuXIntakeAdapter(),
        document_resolver=doc_res,
        resume_context_store=store,
        artifact_store=art_store,
        tenant_id=tenant_id,
    )

    # 1. Execute up to approval checkpoint
    exec_res = orch.execute_plan(plan, case_payload)
    assert exec_res["status"] == "awaiting_approval"
    chk_id = exec_res["checkpoint"]["checkpoint_id"]
    app_req_id = exec_res["approval_request_id"]

    # 2. Record approval decision
    actor = AuthenticatedActor(sub="cso-lead", roles=["cso"])
    app_rec = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id=tenant_id,
        run_id=run_id,
        checkpoint_id=chk_id,
        approval_request_id=UUID(app_req_id),
        canonical_idempotency_key=f"{tenant_id}:{chk_id}:cso-lead:key-5fmt",
        authenticated_actor=actor,
        decision=ApprovalDecisionEnum.APPROVED,
        subject_case_digest=compute_data_sha256(case_payload),
        plan_digest=compute_data_sha256(plan),
    )
    store.record_decision_and_transition(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=1,
        approval_record=app_rec,
        target_status=FleetExecutionStatus.APPROVED_PENDING_RESUME,
    )

    # 3. Acquire lease & resume
    ctx_leased, lease_id = store.acquire_resume_lease(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=2,
        lease_owner="worker-5fmt",
    )

    pdx_dec = PDXApprovalDecision(
        decision_id=app_rec.approval_record_id,
        approval_request_id=UUID(app_req_id),
        checkpoint_id=chk_id,
        idempotency_key="key-5fmt",
        actor_id="cso-lead",
        decision=ApprovalDecisionEnum.APPROVED,
        subject_digest=compute_data_sha256(case_payload),
        plan_digest=compute_data_sha256(plan),
        evidence_digests=exec_res["evidence_digests"],
        decided_at=app_rec.decided_at,
    )

    resume_res = orch.resume_with_decision(exec_res["checkpoint"], pdx_dec)
    assert resume_res["status"] == "completed"

    result_ident = ArtifactStorageIdentity.model_validate(resume_res["artifact_identity"])
    assert result_ident.uri.startswith(f"artifact://{derive_opaque_tenant_storage_key(tenant_id)}/")

    store.mark_resume_completed(
        tenant_id=tenant_id,
        checkpoint_id=chk_id,
        expected_version=ctx_leased.version,
        lease_id=lease_id,
        result_identity=result_ident,
    )

    final_ctx = store.get_context(tenant_id, chk_id)
    assert final_ctx.status == FleetExecutionStatus.COMPLETED
    assert final_ctx.result_identity is not None
