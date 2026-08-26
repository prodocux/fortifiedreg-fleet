"""
Thread-Safe In-Memory Resume Context Store (v0.3.0).
Provides in-memory reference implementation of ResumeContextStorePort.
"""
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
from fleet_governance_core.models.approval import (
    FleetApprovalRecord,
    FleetExecutionStatus,
)
from fleet_governance_core.models.execution_context import (
    ExecutionContextRecord,
    ProjectionOutboxRecord,
)
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort

class InMemoryResumeContextStore(ResumeContextStorePort):
    def __init__(self):
        self._lock = threading.RLock()
        self._contexts: Dict[Tuple[str, str], ExecutionContextRecord] = {}
        self._approval_records: Dict[Tuple[str, str], FleetApprovalRecord] = {}
        self._outbox: Dict[str, ProjectionOutboxRecord] = {}

    def save_context(self, record: ExecutionContextRecord) -> None:
        with self._lock:
            key = (record.tenant_id, record.checkpoint_id)
            self._contexts[key] = record.model_copy(deep=True)

    def get_context(self, tenant_id: str, checkpoint_id: str) -> Optional[ExecutionContextRecord]:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            record = self._contexts.get(key)
            return record.model_copy(deep=True) if record else None

    def invalidate_context(self, tenant_id: str, checkpoint_id: str) -> None:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            rec = self._contexts.get(key)
            if rec:
                rec.status = FleetExecutionStatus.CANCELLED
                rec.lease_id = None
                rec.lease_owner = None

    def record_decision_and_transition(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        approval_record: FleetApprovalRecord,
        target_status: FleetExecutionStatus,
        outbox_target_pdx_status: Optional[str] = None,
    ) -> ExecutionContextRecord:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            rec = self._contexts.get(key)
            if not rec:
                raise ValueError(f"ExecutionContext not found for {key}")
            if rec.version != expected_version:
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {rec.version}")
            if rec.status != FleetExecutionStatus.AWAITING_DECISION:
                raise ValueError(f"Invalid transition from state {rec.status}")

            # 1. Record immutable approval
            self._approval_records[key] = approval_record.model_copy(deep=True)

            # 2. Transition context status & bump version
            rec.status = target_status
            rec.version += 1

            # 3. Create projection outbox if specified
            if outbox_target_pdx_status:
                outbox_id = f"outbox-{uuid4().hex}"
                self._outbox[outbox_id] = ProjectionOutboxRecord(
                    outbox_id=outbox_id,
                    tenant_id=tenant_id,
                    checkpoint_id=checkpoint_id,
                    target_pdx_status=outbox_target_pdx_status,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )

            return rec.model_copy(deep=True)

    def acquire_resume_lease(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_owner: str,
        lease_duration_seconds: int = 60,
    ) -> Tuple[ExecutionContextRecord, str]:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            rec = self._contexts.get(key)
            if not rec:
                raise ValueError(f"ExecutionContext not found for {key}")
            if rec.version != expected_version:
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {rec.version}")

            now_iso = datetime.now(timezone.utc).isoformat()
            is_expired_in_progress = (
                rec.status == FleetExecutionStatus.RESUME_IN_PROGRESS
                and rec.lease_expires_at is not None
                and rec.lease_expires_at < now_iso
            )
            is_valid_state = (
                rec.status in (FleetExecutionStatus.APPROVED_PENDING_RESUME, FleetExecutionStatus.RESUME_FAILED_RETRYABLE)
                or is_expired_in_progress
            )
            if not is_valid_state:
                raise ValueError(f"Cannot acquire resume lease from state {rec.status} (lease active: {rec.lease_id})")

            lease_id = str(uuid4())
            rec.lease_id = lease_id
            rec.lease_owner = lease_owner
            expires_at = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + lease_duration_seconds, timezone.utc)
            rec.lease_expires_at = expires_at.isoformat()
            rec.attempt_count += 1
            rec.status = FleetExecutionStatus.RESUME_IN_PROGRESS
            rec.version += 1

            return rec.model_copy(deep=True), lease_id

    def mark_resume_completed(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_id: str,
        result_identity: ArtifactStorageIdentity,
    ) -> ExecutionContextRecord:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            rec = self._contexts.get(key)
            if not rec:
                raise ValueError(f"ExecutionContext not found for {key}")
            if rec.version != expected_version:
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {rec.version}")
            if rec.lease_id != lease_id:
                raise ValueError(f"Lease mismatch: expected {lease_id}, got {rec.lease_id}")
            if rec.status != FleetExecutionStatus.RESUME_IN_PROGRESS:
                raise ValueError(f"Invalid state for completion: {rec.status}")

            rec.status = FleetExecutionStatus.COMPLETED
            rec.result_identity = result_identity
            rec.lease_id = None
            rec.lease_owner = None
            rec.lease_expires_at = None
            rec.version += 1

            # Emit resumed projection outbox record
            outbox_id = f"outbox-{uuid4().hex}"
            self._outbox[outbox_id] = ProjectionOutboxRecord(
                outbox_id=outbox_id,
                tenant_id=tenant_id,
                checkpoint_id=checkpoint_id,
                target_pdx_status="resumed",
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            return rec.model_copy(deep=True)

    def mark_resume_failed(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_id: str,
        safe_error_code: str,
        request_id: str,
        is_retryable: bool = True,
    ) -> ExecutionContextRecord:
        with self._lock:
            key = (tenant_id, checkpoint_id)
            rec = self._contexts.get(key)
            if not rec:
                raise ValueError(f"ExecutionContext not found for {key}")
            if rec.version != expected_version:
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {rec.version}")
            if rec.lease_id != lease_id:
                raise ValueError(f"Lease mismatch: expected {lease_id}, got {rec.lease_id}")

            rec.status = (
                FleetExecutionStatus.RESUME_FAILED_RETRYABLE
                if is_retryable
                else FleetExecutionStatus.BLOCKED_REVIEW
            )
            rec.last_error = {
                "safe_error_code": safe_error_code,
                "request_id": request_id,
                "is_retryable": is_retryable,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            rec.lease_id = None
            rec.lease_owner = None
            rec.lease_expires_at = None
            rec.version += 1

            return rec.model_copy(deep=True)

    def get_pending_outbox_records(self, limit: int = 100) -> List[ProjectionOutboxRecord]:
        with self._lock:
            pending = [r.model_copy(deep=True) for r in self._outbox.values() if r.processed_at is None]
            return pending[:limit]

    def mark_outbox_processed(self, outbox_id: str) -> None:
        with self._lock:
            if outbox_id in self._outbox:
                self._outbox[outbox_id].processed_at = datetime.now(timezone.utc).isoformat()
