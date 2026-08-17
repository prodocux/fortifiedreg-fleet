"""
Approved Memory Port Definition (G5).
Defines abstract interface for tenant-isolated, approved regulatory knowledge memory store.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class MemoryPort(ABC):
    @abstractmethod
    def store_approved_memory(
        self, tenant_id: str, memory_id: str, memory_type: str, content: Dict[str, Any], approval_record_id: str
    ) -> None:
        """Store an approved regulatory finding in tenant memory ledger linked to approval record."""
        pass

    @abstractmethod
    def query_approved_memories(
        self, tenant_id: str, memory_type: str, query_filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Query approved regulatory findings under tenant boundary."""
        pass
