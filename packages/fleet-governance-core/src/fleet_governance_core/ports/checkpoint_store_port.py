"""
Checkpoint Store Port Definition.
Defines abstract interface for tenant-scoped checkpoint and approval request persistence and status transitions.
"""
from abc import ABC, abstractmethod
from typing import Optional
from fleet_governance_core.models.approval import (
    CheckpointStatusEnum,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)

class CheckpointStorePort(ABC):
    @abstractmethod
    def save_checkpoint(self, tenant_id: str, checkpoint: PDXWorkflowCheckpoint) -> None:
        """Persist a newly compiled or paused workflow checkpoint under tenant boundary."""
        pass

    @abstractmethod
    def get_checkpoint(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXWorkflowCheckpoint]:
        """Retrieve a checkpoint scoped to tenant. Returns None if absent."""
        pass

    @abstractmethod
    def update_checkpoint_status(
        self, tenant_id: str, checkpoint_id: str, status: CheckpointStatusEnum
    ) -> None:
        """Update checkpoint status (e.g. PENDING -> RESUMED or CANCELLED) with optimistic check."""
        pass

    @abstractmethod
    def save_approval_request(self, tenant_id: str, request: PDXApprovalRequest) -> None:
        """Persist a generated approval request linked to a pending checkpoint."""
        pass

    @abstractmethod
    def get_approval_request(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXApprovalRequest]:
        """Retrieve the approval request generated for a checkpoint."""
        pass
