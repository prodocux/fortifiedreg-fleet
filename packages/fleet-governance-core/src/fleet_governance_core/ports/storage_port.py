"""
Artifact Storage Port Definition.
Defines abstract interface for storing and resolving immutable audit artifacts.
"""
from abc import ABC, abstractmethod
from fleet_governance_core.models.storage import ArtifactStorageIdentity

class ArtifactStoragePort(ABC):
    @abstractmethod
    def store_artifact(self, artifact_id: str, content: bytes, media_type: str) -> ArtifactStorageIdentity:
        """Persist content to object storage and return its canonical storage identity."""
        pass

    @abstractmethod
    def fetch_artifact(self, uri: str) -> bytes:
        """Fetch raw content from a valid storage URI."""
        pass
