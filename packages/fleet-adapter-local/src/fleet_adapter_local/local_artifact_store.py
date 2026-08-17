"""
Local Atomic Crash-Safe Artifact Store (v0.3.0).
Implements ArtifactStorePort with atomic temporary staging, fsync,
and non-overwrite collision detection.
"""
import hashlib
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
from uuid import uuid4
from typing import Optional
from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactResult,
    PutArtifactStatus,
)
from fleet_governance_core.ports.artifact_store_port import ArtifactStorePort

class LocalArtifactStore(ArtifactStorePort):
    def __init__(
        self,
        root_dir: str | Path = "./.artifact_store",
        fail_once_file: Optional[Path | str] = None,
    ):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.fail_once_file = Path(fail_once_file).resolve() if fail_once_file else None

    def _uri_to_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme not in ("artifact", "gs"):
            raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")
        
        # Strip leading slashes to prevent root escapes
        rel_path = f"{parsed.netloc}/{parsed.path.lstrip('/')}"
        clean_path = (self.root_dir / rel_path).resolve()
        
        # Verify no directory traversal outside root_dir
        if not str(clean_path).startswith(str(self.root_dir)):
            raise ValueError(f"Path traversal detected for URI: {uri}")
        
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
            # Check one-shot transient fault trigger if configured
            trigger = self.fail_once_file
            if not trigger:
                env_val = os.getenv("FLEET_FAULT_INJECT_FAIL_ONCE_STORE_TRIGGER")
                if env_val:
                    trigger = Path(env_val).resolve()
            if trigger and trigger.exists():
                try:
                    trigger.unlink()
                except OSError:
                    pass
                raise IOError("Injected one-shot transient storage I/O failure during artifact publishing.")

            # 1. Check if final file already exists
            if target_path.exists():
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

            # 2. Crash-safe staging: write to unique temp file on the same filesystem, flush & fsync
            temp_path = target_dir / f".tmp_{uuid4().hex}"
            try:
                with open(temp_path, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                # 3. Publish to final path atomically if still absent
                # On Windows/Unix, using atomic link/replace under lock
                if target_path.exists():
                    # Concurrent write happened in gap
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

                os.replace(temp_path, target_path)
                return PutArtifactResult(
                    status=PutArtifactStatus.CREATED,
                    identity=identity,
                    sha256=sha256,
                    bytes_written=len(content),
                )
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
