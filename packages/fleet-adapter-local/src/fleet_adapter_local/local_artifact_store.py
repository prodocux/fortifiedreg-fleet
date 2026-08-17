"""
Local Atomic Crash-Safe Artifact Store (v0.3.0).
Implements ArtifactStorePort with atomic temporary staging, fsync,
cross-process exclusive link publishing, and non-overwrite collision detection.
"""
import hashlib
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
from uuid import uuid4

from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactResult,
    PutArtifactStatus,
)
from fleet_governance_core.ports.artifact_store_port import ArtifactStorePort


class LocalArtifactStore(ArtifactStorePort):
    def __init__(self, root_dir: str | Path = "./.artifact_store"):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _uri_to_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme not in ("artifact", "gs"):
            raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")

        # Strip leading slashes to prevent root escapes
        rel_path = f"{parsed.netloc}/{parsed.path.lstrip('/')}"
        clean_path = (self.root_dir / rel_path).resolve()

        # Strict containment check to prevent directory traversal and sibling-prefix attacks
        if not clean_path.is_relative_to(self.root_dir) or clean_path == self.root_dir:
            raise ValueError(f"Path traversal detected for URI: {uri}")

        # Support extended length paths on Windows (exceeding MAX_PATH 260 chars)
        if os.name == "nt" and not str(clean_path).startswith("\\\\?\\"):
            return Path("\\\\?\\" + str(clean_path))
        return clean_path

    def put_if_absent(
        self,
        identity: ArtifactStorageIdentity,
        content: bytes,
        sha256: str,
    ) -> PutArtifactResult:
        computed_sha = hashlib.sha256(content).hexdigest()
        if computed_sha != sha256:
            raise ValueError(f"Content SHA-256 mismatch: expected {sha256}, calculated {computed_sha}")

        target_path = self._uri_to_path(identity.uri)
        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            # 1. Fast check if final file already exists
            if target_path.exists():
                try:
                    existing_bytes = target_path.read_bytes()
                    existing_sha = hashlib.sha256(existing_bytes).hexdigest()
                    if existing_sha == sha256:
                        return PutArtifactResult(
                            status=PutArtifactStatus.ALREADY_EXISTS_SAME_DIGEST,
                            identity=identity,
                            sha256=existing_sha,
                            bytes_written=len(existing_bytes),
                        )
                    else:
                        return PutArtifactResult(
                            status=PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST,
                            identity=identity,
                            sha256=existing_sha,
                            bytes_written=len(existing_bytes),
                        )
                except FileNotFoundError:
                    # In race condition where file was deleted, continue to atomic staging
                    pass

            # 2. Crash-safe staging: write to unique temp file on the same directory/filesystem, flush & fsync
            temp_path = target_dir / f".t_{uuid4().hex[:12]}"
            try:
                with open(temp_path, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                # 3. Cross-Process Exclusive Atomic Publishing via os.link:
                # os.link creates target_path pointing to the staged file atomically.
                # If target_path was created concurrently by another process, os.link fails
                # immediately with FileExistsError without overwriting the existing target.
                try:
                    os.link(temp_path, target_path)
                    return PutArtifactResult(
                        status=PutArtifactStatus.CREATED,
                        identity=identity,
                        sha256=sha256,
                        bytes_written=len(content),
                    )
                except FileExistsError:
                    # Another process won the atomic creation race
                    existing_bytes = target_path.read_bytes()
                    existing_sha = hashlib.sha256(existing_bytes).hexdigest()
                    status = (
                        PutArtifactStatus.ALREADY_EXISTS_SAME_DIGEST
                        if existing_sha == sha256
                        else PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST
                    )
                    return PutArtifactResult(
                        status=status,
                        identity=identity,
                        sha256=existing_sha,
                        bytes_written=len(existing_bytes),
                    )
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
