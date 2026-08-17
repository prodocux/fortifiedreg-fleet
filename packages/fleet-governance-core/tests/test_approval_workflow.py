"""
Unit Tests for ApprovalWorkflowService in fleet-governance-core.
"""
from typing import Dict, List, Optional
from uuid import UUID
import pytest
from fleet_governance_core.exceptions import (
    CheckpointNotFoundError,
    CheckpointNotPendingError,
    IdempotencyConflictError,
    PreconditionFailedError,
)
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent
from fleet_governance_core.ports.approval_store_port import ApprovalStorePort
from fleet_governance_core.ports.audit_log_port import AuditLogPort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.services.approval_workflow import ApprovalWorkflowService

class InMemoryApprovalStore(ApprovalStorePort):
    def __init__(self):
        self.records_by_key: Dict[str, FleetApprovalRecord] = {}

    def save_approval_record(self, record: FleetApprovalRecord) -> None:
        self.records_by_key[record.canonical_idempotency_key] = record

    def get_by_idempotency_key(self, canonical_idempotency_key: str) -> Optional[FleetApprovalRecord]:
        return self.records_by_key.get(canonical_idempotency_key)

    def get_by_checkpoint_id(self, tenant_id: str, checkpoint_id: str) -> Optional[FleetApprovalRecord]:
        for r in self.records_by_key.values():
            if r.tenant_id == tenant_id and r.checkpoint_id == checkpoint_id:
                return r
        return None

class InMemoryAuditLog(AuditLogPort):
    def __init__(self):
        self.events: List[AuditEvent] = []

    def append_audit_event(self, event: AuditEvent) -> None:
        self.events.append(event)

    def list_events_for_run(self, tenant_id: str, run_id: str) -> List[AuditEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id and e.run_id == run_id]

class InMemoryCheckpointStore(CheckpointStorePort):
    def __init__(self):
        self.checkpoints: Dict[str, Dict[str, PDXWorkflowCheckpoint]] = {}  # tenant_id -> {id: chk}
        self.requests: Dict[str, Dict[str, PDXApprovalRequest]] = {}  # tenant_id -> {checkpoint_id: req}

    def save_checkpoint(self, tenant_id: str, checkpoint: PDXWorkflowCheckpoint) -> None:
        self.checkpoints.setdefault(tenant_id, {})[checkpoint.checkpoint_id] = checkpoint

    def get_checkpoint(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXWorkflowCheckpoint]:
        return self.checkpoints.get(tenant_id, {}).get(checkpoint_id)

    def update_checkpoint_status(self, tenant_id: str, checkpoint_id: str, status: CheckpointStatusEnum) -> None:
        chk = self.checkpoints.get(tenant_id, {}).get(checkpoint_id)
        if chk:
            chk.status = status

    def save_approval_request(self, tenant_id: str, request: PDXApprovalRequest) -> None:
        self.requests.setdefault(tenant_id, {})[request.checkpoint_id] = request

    def get_approval_request(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXApprovalRequest]:
        return self.requests.get(tenant_id, {}).get(checkpoint_id)

@pytest.fixture
def workflow():
    store = InMemoryApprovalStore()
    audit = InMemoryAuditLog()
    chk_store = InMemoryCheckpointStore()
    service = ApprovalWorkflowService(approval_store=store, audit_log=audit, checkpoint_store=chk_store)
    return service, store, audit, chk_store

@pytest.fixture
def sample_checkpoint(workflow):
    _, _, _, chk_store = workflow
    chk = PDXWorkflowCheckpoint(
        checkpoint_id="chk-001",
        run_id="run-001",
        subject_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
        status=CheckpointStatusEnum.PENDING,
    )
    req = PDXApprovalRequest(
        approval_request_id=UUID("11111111-1111-4111-8111-111111111111"),
        run_id="run-001",
        checkpoint_id="chk-001",
        subject_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )
    chk_store.save_checkpoint("tenant-1", chk)
    chk_store.save_approval_request("tenant-1", req)
    return chk

@pytest.fixture
def sample_actor():
    return AuthenticatedActor(sub="usr-safety-lead", email="lead@acme.com", roles=["approver"])

def test_successful_approval_decision(workflow, sample_checkpoint, sample_actor):
    service, store, audit, chk_store = workflow
    record, pdx_dec = service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-001",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
        reason="Looks good",
    )

    assert record.decision == ApprovalDecisionEnum.APPROVED
    assert pdx_dec.decision == ApprovalDecisionEnum.APPROVED
    assert len(audit.events) == 1
    assert audit.events[0].event_type == "APPROVAL_DECIDED"
    
    updated_chk = chk_store.get_checkpoint("tenant-1", sample_checkpoint.checkpoint_id)
    assert updated_chk.status == CheckpointStatusEnum.RESUMED

def test_mismatched_approval_request_id_rejected(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    with pytest.raises(PreconditionFailedError, match="Approval Request ID mismatch"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="22222222-2222-4222-8222-222222222222",  # Mismatch
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_missing_approval_request_rejected(workflow, sample_actor):
    service, _, _, chk_store = workflow
    chk = PDXWorkflowCheckpoint(
        checkpoint_id="chk-no-req",
        run_id="run-001",
        subject_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
        status=CheckpointStatusEnum.PENDING,
    )
    chk_store.save_checkpoint("tenant-1", chk)
    # Do NOT save approval request

    with pytest.raises(PreconditionFailedError, match="Missing approval request"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=chk,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )


def test_unauthorized_role_rejected(workflow, sample_checkpoint):
    service, _, _, _ = workflow
    unauthorized_actor = AuthenticatedActor(sub="usr-guest", email="guest@acme.com", roles=["viewer"])
    with pytest.raises(PreconditionFailedError, match="lacks required approver authorization"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=unauthorized_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_unknown_checkpoint_not_found(workflow, sample_actor):
    service, _, _, _ = workflow
    unregistered_chk = PDXWorkflowCheckpoint(
        checkpoint_id="chk-unregistered",
        run_id="run-002",
        subject_digest="a" * 64,
        plan_digest="b" * 64,
        status=CheckpointStatusEnum.PENDING,
    )
    with pytest.raises(CheckpointNotFoundError, match="not found under tenant"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=unregistered_chk,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={},
        )

def test_rejection_on_case_digest_mismatch(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    with pytest.raises(PreconditionFailedError, match="Case digest mismatch"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="x" * 64,  # Mismatched
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_rejection_on_plan_digest_mismatch(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    with pytest.raises(PreconditionFailedError, match="Plan digest mismatch"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="x" * 64,  # Mismatched
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_rejection_on_evidence_digest_mismatch(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    with pytest.raises(PreconditionFailedError, match="Evidence digests mismatch"):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "x" * 64},  # Mismatched
        )

def test_rejection_on_non_pending_checkpoint(workflow, sample_checkpoint, sample_actor):
    service, _, _, chk_store = workflow
    chk_store.update_checkpoint_status("tenant-1", sample_checkpoint.checkpoint_id, CheckpointStatusEnum.RESUMED)
    with pytest.raises(CheckpointNotPendingError):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_idempotent_retry_returns_existing(workflow, sample_checkpoint, sample_actor):
    service, _, audit, _ = workflow
    rec1, dec1 = service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-001",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )

    rec2, dec2 = service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-001",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )

    assert rec1.approval_record_id == rec2.approval_record_id
    assert dec1.decision_id == dec2.decision_id
    assert len(audit.events) == 1  # No duplicate audit event for idempotent retry

def test_idempotency_conflict_on_different_payload(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-001",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )

    # Re-use key-001 but with REJECTED
    with pytest.raises(IdempotencyConflictError):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.REJECTED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_idempotent_replay_with_different_approval_request_id_rejected(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-001",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )

    # Re-send same key-001 and same digests but with a different approval_request_id
    with pytest.raises((PreconditionFailedError, IdempotencyConflictError)):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="99999999-9999-4999-8999-999999999999",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-001",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_idempotent_replay_with_none_approval_request_id_in_existing_record_fails(workflow, sample_checkpoint, sample_actor):
    service, store, _, _ = workflow
    
    # Store legacy/unmigrated record with approval_request_id = None
    canonical_key = service.build_canonical_idempotency_key(
        tenant_id="tenant-1",
        checkpoint_id=sample_checkpoint.checkpoint_id,
        actor_id=sample_actor.sub,
        idempotency_key="key-none-id",
    )
    legacy_record = FleetApprovalRecord(
        tenant_id="tenant-1",
        run_id=sample_checkpoint.run_id,
        checkpoint_id=sample_checkpoint.checkpoint_id,
        approval_request_id=None,
        canonical_idempotency_key=canonical_key,
        authenticated_actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
    )
    store.save_approval_record(legacy_record)

    # Replay with a valid UUID must raise IdempotencyConflictError, strictly rejecting None
    with pytest.raises(IdempotencyConflictError):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-none-id",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
        )

def test_idempotent_replay_with_different_reason_fails(workflow, sample_checkpoint, sample_actor):
    service, _, _, _ = workflow
    service.process_approval_decision(
        tenant_id="tenant-1",
        checkpoint=sample_checkpoint,
        approval_request_id="11111111-1111-4111-8111-111111111111",
        actor=sample_actor,
        decision=ApprovalDecisionEnum.APPROVED,
        idempotency_key="key-reason-diff",
        case_digest="a" * 64,
        plan_digest="b" * 64,
        evidence_digests={"doc1.pdf": "c" * 64},
        reason="Initial sign-off note A",
    )

    # Same key, same digests, same request ID, but different reason -> MUST fail with IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError):
        service.process_approval_decision(
            tenant_id="tenant-1",
            checkpoint=sample_checkpoint,
            approval_request_id="11111111-1111-4111-8111-111111111111",
            actor=sample_actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key="key-reason-diff",
            case_digest="a" * 64,
            plan_digest="b" * 64,
            evidence_digests={"doc1.pdf": "c" * 64},
            reason="Modified sign-off note B",
        )


