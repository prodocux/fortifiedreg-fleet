"""
Artifact Content Resolver Port (v0.3.0).
Defines the transport-level verified content retrieval interface.
"""
from typing import Protocol
from fleet_governance_core.models.storage import ArtifactStorageIdentity

class ArtifactContentResolverPort(Protocol):
    """
    Port for retrieving and validating stored artifact bytes.
    Enforces URI scheme validation, tenant ownership validation, and SHA-256 digest comparison.
    """

    def read_verified(
        self,
        identity: ArtifactStorageIdentity,
        expected_digest: str,
        tenant_id: str,
    ) -> bytes:
        """
        Read and verify artifact content bytes against expected SHA-256 and tenant ownership.
        Fails closed with TamperedArtifactError if digests mismatch or unauthorized tenant access occurs.
        """
        ...
