"""
Approval Store Port Definition.
Defines abstract interface for CAS optimistic locking and idempotency tracking.
"""
from abc import ABC, abstractmethod
from typing import Optional
from fleet_governance_core.models.approval import FleetApprovalRecord

class ApprovalStorePort(ABC):
    @abstractmethod
    def save_approval_record(self, record: FleetApprovalRecord) -> None:
        """Persist an approval record. Raises ConflictError if canonical_idempotency_key exists with different payload."""
        pass

    @abstractmethod
    def get_by_idempotency_key(self, canonical_idempotency_key: str) -> Optional[FleetApprovalRecord]:
        """Retrieve existing record by idempotency key."""
        pass

    @abstractmethod
    def get_by_checkpoint_id(self, tenant_id: str, checkpoint_id: str) -> Optional[FleetApprovalRecord]:
        """Retrieve existing decision record for a given tenant and checkpoint."""
        pass
