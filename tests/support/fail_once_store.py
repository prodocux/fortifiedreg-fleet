"""
Test support: FailOnceArtifactStore.
Subclasses LocalArtifactStore exclusively for test harness fault injection.
Zero footprint in production codebase.
"""
from pathlib import Path
from typing import Optional

from fleet_adapter_local.local_artifact_store import LocalArtifactStore
from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactResult,
)


class FailOnceArtifactStore(LocalArtifactStore):
    def __init__(self, root_dir: str | Path, trigger_file: Path | str):
        super().__init__(root_dir=root_dir)
        self.trigger_file = Path(trigger_file).resolve()

    def put_if_absent(
        self,
        identity: ArtifactStorageIdentity,
        content: bytes,
        sha256: str,
    ) -> PutArtifactResult:
        if self.trigger_file.exists():
            try:
                self.trigger_file.unlink()
            except OSError:
                pass
            raise IOError("Injected one-shot transient storage I/O failure during artifact publishing.")
        return super().put_if_absent(identity, content, sha256)
