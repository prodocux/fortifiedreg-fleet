"""
Audit Log Port Definition.
Defines abstract interface for append-only audit event persistence.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from fleet_governance_core.models.audit import AuditEvent

class AuditLogPort(ABC):
    @abstractmethod
    def append_audit_event(self, event: AuditEvent) -> None:
        """Append an immutable audit event to the ledger."""
        pass

    @abstractmethod
    def list_events_for_run(self, tenant_id: str, run_id: str) -> List[AuditEvent]:
        """Query audit events by run ID within tenant boundary."""
        pass

    @abstractmethod
    def list_all_events(self, tenant_id: str, limit: int = 50) -> List[AuditEvent]:
        """Query all audit events for a tenant bounded by limit."""
        pass
