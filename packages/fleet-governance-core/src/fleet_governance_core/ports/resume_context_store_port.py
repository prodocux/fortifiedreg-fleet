"""
Resume Context Store Port (v0.3.0).
Defines transactional persistence for execution contexts, lease fencing,
single-transaction approval commitments, and projection outbox synchronization.
"""
from typing import Any, Dict, List, Optional, Protocol, Tuple
from fleet_governance_core.models.approval import (
    FleetApprovalRecord,
    FleetExecutionStatus,
)
from fleet_governance_core.models.execution_context import (
    ExecutionContextRecord,
    ProjectionOutboxRecord,
)
from fleet_governance_core.models.storage import ArtifactStorageIdentity

class ResumeContextStorePort(Protocol):
    """
    Port for transactional persistence of execution context records and projection outboxes.
    """

    def save_context(self, record: ExecutionContextRecord) -> None:
        """Persist a new execution context record."""
        ...

    def get_context(self, tenant_id: str, checkpoint_id: str) -> Optional[ExecutionContextRecord]:
        """Retrieve execution context record by tenant and checkpoint ID."""
        ...

    def record_decision_and_transition(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        approval_record: FleetApprovalRecord,
        target_status: FleetExecutionStatus,
        outbox_target_pdx_status: Optional[str] = None,
    ) -> ExecutionContextRecord:
        """
        Atomically write immutable approval record, transition context status,
        and optionally create a projection outbox record within a single ACID transaction.
        """
        ...

    def acquire_resume_lease(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_owner: str,
        lease_duration_seconds: int = 60,
    ) -> Tuple[ExecutionContextRecord, str]:
        """
        Atomically acquire time-bounded execution lease if state is APPROVED_PENDING_RESUME,
        RESUME_FAILED_RETRYABLE, or expired RESUME_IN_PROGRESS.
        Returns the updated record and newly generated lease_id.
        """
        ...

    def mark_resume_completed(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_id: str,
        result_identity: ArtifactStorageIdentity,
    ) -> ExecutionContextRecord:
        """
        Atomically verify version and lease_id, transition status to COMPLETED,
        record result_identity, and create a ProjectionOutboxRecord with target_pdx_status='resumed'.
        """
        ...

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
        """
        Atomically verify version and lease_id, transition status to RESUME_FAILED_RETRYABLE (if retryable)
        or BLOCKED_REVIEW (if non-retryable), record sanitized last_error, and release the lease without emitting any resumed projection.
        """
        ...

    def get_pending_outbox_records(self, limit: int = 100) -> List[ProjectionOutboxRecord]:
        """Fetch pending projection outbox records for synchronization."""
        ...

    def mark_outbox_processed(self, outbox_id: str) -> None:
        """Mark an outbox record as successfully processed."""
        ...
