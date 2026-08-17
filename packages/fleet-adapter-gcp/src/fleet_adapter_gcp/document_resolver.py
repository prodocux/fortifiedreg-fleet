"""
Thread-safe Document Content Resolver Adapter.
Implements DocumentResolverPort with thread locking, strict tenant isolation, immutable CAS, and filename metadata.
"""
import hashlib
from threading import Lock
from typing import Dict, Optional, Tuple
from fleet_governance_core.ports.document_resolver_port import DocumentResolverPort

class DocumentRecord:
    def __init__(self, content: bytes, filename: Optional[str] = None):
        self.content = content
        self.filename = filename
        self.sha256 = hashlib.sha256(content).hexdigest()

class ThreadSafeDocumentResolver(DocumentResolverPort):
    """Thread-safe document content resolver with strict tenant isolation."""

    def __init__(self):
        self._lock = Lock()
        self._store: Dict[Tuple[str, str], DocumentRecord] = {}  # (tenant_id, doc_id) -> DocumentRecord

    def register_document(
        self,
        tenant_id: str,
        doc_id: str,
        content: bytes,
        filename: Optional[str] = None,
        expected_sha256: Optional[str] = None,
    ) -> str:
        """
        Register raw document bytes under a specific tenant.
        Enforces immutability: identical replay succeeds; conflicting bytes on existing (tenant, doc_id) raises ValueError.
        """
        if not tenant_id or not isinstance(tenant_id, str):
            raise ValueError("tenant_id is required and must be a non-empty string")
        if not doc_id or not isinstance(doc_id, str):
            raise ValueError("doc_id is required and must be a non-empty string")
        if content is None or not isinstance(content, (bytes, bytearray)):
            raise ValueError("content must be non-empty binary bytes")

        raw_bytes = bytes(content)
        digest = hashlib.sha256(raw_bytes).hexdigest()

        if expected_sha256 and digest.casefold() != expected_sha256.strip().casefold():
            raise ValueError(
                f"Document content SHA-256 '{digest}' does not match expected digest '{expected_sha256}'"
            )

        key = (tenant_id, doc_id)
        with self._lock:
            if key in self._store:
                existing = self._store[key]
                if existing.sha256 == digest and existing.filename == filename:
                    # Idempotent re-registration of exact same content and filename
                    return digest
                raise ValueError(
                    f"Document with doc_id '{doc_id}' for tenant '{tenant_id}' is immutable and already exists with different content or filename."
                )

            self._store[key] = DocumentRecord(content=raw_bytes, filename=filename)
            return digest

    def set_document(self, tenant_id: str, doc_id: str, content: bytes, filename: Optional[str] = None) -> None:
        """Helper for test fixtures."""
        self.register_document(tenant_id=tenant_id, doc_id=doc_id, content=content, filename=filename)

    def get_document_bytes(self, tenant_id: str, doc_id: str) -> Optional[bytes]:
        """Retrieve binary content strictly scoped to tenant_id."""
        if not tenant_id or not doc_id:
            return None
        with self._lock:
            rec = self._store.get((tenant_id, doc_id))
            return rec.content if rec else None

    def get_document_filename(self, tenant_id: str, doc_id: str) -> Optional[str]:
        """Retrieve stored filename metadata strictly scoped to tenant_id."""
        if not tenant_id or not doc_id:
            return None
        with self._lock:
            rec = self._store.get((tenant_id, doc_id))
            return rec.filename if rec else None

    def has_document(self, tenant_id: str, doc_id: str) -> bool:
        """Check if document exists under tenant."""
        if not tenant_id or not doc_id:
            return False
        with self._lock:
            return (tenant_id, doc_id) in self._store
