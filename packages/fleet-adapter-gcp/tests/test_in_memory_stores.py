"""
Unit Tests for in-memory GCP stores in fleet-adapter-gcp.
"""
from uuid import uuid4
import pytest
from fleet_adapter_gcp import (
    InMemoryApprovalStore,
    InMemoryAuditLog,
    InMemoryArtifactStorageAdapter,
    InMemoryCheckpointStore,
    FLEET_MAX_ARTIFACT_BYTES,
)
from fleet_governance_core.exceptions import IdempotencyConflictError
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum

def test_in_memory_approval_store_and_retrieve_by_key():
    store = InMemoryApprovalStore()
    record = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id="tenant-alpha",
        run_id="run-001",
        checkpoint_id="chk-001",
        canonical_idempotency_key="tenant-alpha:chk-001:usr-1:key-1",
        authenticated_actor=AuthenticatedActor(sub="usr-1"),
        decision=ApprovalDecisionEnum.APPROVED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
    )

    store.save_approval_record(record)
    retrieved = store.get_by_idempotency_key("tenant-alpha:chk-001:usr-1:key-1")
    assert retrieved is not None
    assert retrieved.approval_record_id == record.approval_record_id

def test_in_memory_approval_idempotency_conflict():
    store = InMemoryApprovalStore()
    record1 = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id="tenant-alpha",
        run_id="run-001",
        checkpoint_id="chk-001",
        canonical_idempotency_key="tenant-alpha:chk-001:usr-1:key-1",
        authenticated_actor=AuthenticatedActor(sub="usr-1"),
        decision=ApprovalDecisionEnum.APPROVED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
    )
    store.save_approval_record(record1)

    record2 = FleetApprovalRecord(
        approval_record_id=uuid4(),
        tenant_id="tenant-alpha",
        run_id="run-001",
        checkpoint_id="chk-001",
        canonical_idempotency_key="tenant-alpha:chk-001:usr-1:key-1",
        authenticated_actor=AuthenticatedActor(sub="usr-1"),
        decision=ApprovalDecisionEnum.REJECTED,
        subject_case_digest="a" * 64,
        plan_digest="b" * 64,
    )

    with pytest.raises(IdempotencyConflictError):
        store.save_approval_record(record2)

def test_in_memory_audit_log_append_and_query():
    log = InMemoryAuditLog()
    event = AuditEvent(
        event_id=uuid4(),
        tenant_id="tenant-alpha",
        run_id="run-100",
        event_type=AuditEventTypeEnum.CASE_CREATED,
        actor_id="usr-test",
        payload={"action": "create"},
    )

    log.append_audit_event(event)
    events = log.list_events_for_run(tenant_id="tenant-alpha", run_id="run-100")
    assert len(events) == 1
    assert events[0].event_type == AuditEventTypeEnum.CASE_CREATED

    other_events = log.list_events_for_run(tenant_id="tenant-beta", run_id="run-100")
    assert len(other_events) == 0

def test_in_memory_checkpoint_store():
    chk_store = InMemoryCheckpointStore()
    chk = PDXWorkflowCheckpoint(
        checkpoint_id="chk-alpha-001",
        run_id="run-001",
        subject_digest="a" * 64,
        plan_digest="b" * 64,
        status=CheckpointStatusEnum.PENDING,
    )
    chk_store.save_checkpoint("tenant-alpha", chk)

    retrieved = chk_store.get_checkpoint("tenant-alpha", "chk-alpha-001")
    assert retrieved is not None
    assert retrieved.status == CheckpointStatusEnum.PENDING

    # Cross-tenant isolation
    assert chk_store.get_checkpoint("tenant-beta", "chk-alpha-001") is None

    chk_store.update_checkpoint_status("tenant-alpha", "chk-alpha-001", CheckpointStatusEnum.RESUMED)
    assert chk_store.get_checkpoint("tenant-alpha", "chk-alpha-001").status == CheckpointStatusEnum.RESUMED

def test_in_memory_gcs_store_and_fetch():
    adapter = InMemoryArtifactStorageAdapter(default_bucket="acme-dossiers", default_prefix="pif")
    content = b"%PDF-1.4 sample PDF dossier content"

    identity = adapter.store_artifact(artifact_id="art-pif-001", content=content, media_type="application/pdf")

    assert identity.artifact_id == "art-pif-001"
    assert identity.uri == "gs://acme-dossiers/pif/art-pif-001.pdf"
    assert identity.size_bytes == len(content)

    fetched = adapter.fetch_artifact(identity.uri)
    assert fetched == content

def test_in_memory_gcs_reject_empty():
    adapter = InMemoryArtifactStorageAdapter()
    with pytest.raises(ValueError, match="cannot be empty"):
        adapter.store_artifact(artifact_id="art-001", content=b"")

def test_in_memory_gcs_reject_over_50mb():
    adapter = InMemoryArtifactStorageAdapter()
    oversized = b"x" * (FLEET_MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds Fleet maximum ceiling"):
        adapter.store_artifact(artifact_id="art-large", content=oversized)
