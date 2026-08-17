"""
Storage and Artifact Identity Domain Models (v0.3.0).
Provides canonical representations of stored artifacts, atomic put results,
and opaque tenant storage key derivation.
"""
import hashlib
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

class StorageSchemeEnum(str, Enum):
    ARTIFACT = "artifact"
    GS = "gs"

from datetime import datetime, timezone
from uuid import uuid4

class ArtifactStorageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: f"art-{uuid4().hex[:12]}", min_length=1, max_length=128)
    uri: str = Field(min_length=5, max_length=512, pattern=r"^(artifact|gs)://[a-zA-Z0-9_.-]+(/[a-zA-Z0-9_.-]+)*$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0, le=100 * 1024 * 1024)
    media_type: str = Field(min_length=3, max_length=128)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PutArtifactStatus(str, Enum):
    CREATED = "created"
    ALREADY_EXISTS_SAME_DIGEST = "already_exists_same_digest"
    ALREADY_EXISTS_CONFLICTING_DIGEST = "already_exists_conflicting_digest"

class PutArtifactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PutArtifactStatus
    identity: ArtifactStorageIdentity
    sha256: str
    bytes_written: int

def derive_opaque_tenant_storage_key(tenant_id: str, salt: str = "fleet-tenant-v1") -> str:
    """
    Derive a deterministic opaque storage key from authenticated tenant_id.
    Ensures raw JWT tenant names (e.g. 'tenant-acme-corp') are never leaked directly into storage URIs.
    """
    digest = hashlib.sha256(f"{salt}:{tenant_id}".encode("utf-8")).hexdigest()[:24]
    return f"t-{digest}"
