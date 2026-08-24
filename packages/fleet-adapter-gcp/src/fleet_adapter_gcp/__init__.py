"""
Fleet Adapter GCP Package (v0.3.0).
Provides InMemory stores and DocumentResolver for local testing and scaffolding for live Cloud Firestore/Storage.
"""
from fleet_adapter_gcp.document_resolver import ThreadSafeDocumentResolver
from fleet_adapter_gcp.in_memory_stores import (
    FLEET_MAX_ARTIFACT_BYTES,
    InMemoryApprovalStore,
    InMemoryArtifactStorageAdapter,
    InMemoryAuditLog,
    InMemoryCheckpointStore,
    InMemoryMemoryStore,
)

__version__ = "0.4.0"
__all__ = [
    "InMemoryApprovalStore",
    "InMemoryAuditLog",
    "InMemoryArtifactStorageAdapter",
    "InMemoryCheckpointStore",
    "InMemoryMemoryStore",
    "ThreadSafeDocumentResolver",
    "FLEET_MAX_ARTIFACT_BYTES",
]
