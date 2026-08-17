"""
Artifact Store Port (v0.3.0).
Defines the atomic, race-free interface for persisting generated artifacts.
"""
from typing import Protocol
from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactResult,
)

class ArtifactStorePort(Protocol):
    """
    Port for atomic storage operations.
    Implementations must enforce race-free creation semantics (e.g. OS-level exclusive creation,
    SQLite BLOB transactions, or cloud generation preconditions).
    """

    def put_if_absent(
        self,
        identity: ArtifactStorageIdentity,
        content: bytes,
        sha256: str,
    ) -> PutArtifactResult:
        """
        Atomically persist artifact content if not present.
        If identical content already exists, safely return ALREADY_EXISTS_SAME_DIGEST.
        If conflicting content exists, return ALREADY_EXISTS_CONFLICTING_DIGEST.
        """
        ...
