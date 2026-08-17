"""
Document Content Resolver Port.
Abstract port for resolving binary content of supplier documents by tenant_id and doc_id.
"""
from abc import ABC, abstractmethod
from typing import Optional

class DocumentResolverPort(ABC):
    """Abstract port for retrieving raw document bytes by tenant_id and document identifier."""

    @abstractmethod
    def get_document_bytes(self, tenant_id: str, doc_id: str) -> Optional[bytes]:
        """Retrieve binary content for the given tenant and document identifier, or None if not found."""
        pass

    @abstractmethod
    def get_document_filename(self, tenant_id: str, doc_id: str) -> Optional[str]:
        """Retrieve filename metadata for the given tenant and document identifier, or None if not found."""
        pass
