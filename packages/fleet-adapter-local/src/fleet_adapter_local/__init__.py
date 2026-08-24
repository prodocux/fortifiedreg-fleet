"""
Local Persistence and Crash-Safe Storage Adapters for FortifiedReg Fleet (v0.3.0).
"""
from fleet_adapter_local.in_memory_store import InMemoryResumeContextStore
from fleet_adapter_local.local_artifact_resolver import LocalVerifiedArtifactResolver
from fleet_adapter_local.local_artifact_store import LocalArtifactStore
from fleet_adapter_local.sqlite_store import SQLiteResumeContextStore

__version__ = "0.4.0"
__all__ = [
    "InMemoryResumeContextStore",
    "SQLiteResumeContextStore",
    "LocalArtifactStore",
    "LocalVerifiedArtifactResolver",
]
