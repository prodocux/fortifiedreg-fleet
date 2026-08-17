"""
In-Memory Storage Adapters for Local Testing & Emulation.
Thread-safe in-memory stores for Checkpoints, Approvals, Audit Logs, and Artifacts.
"""
import hashlib
import threading
from typing import Any, Dict, List, Optional
from fleet_governance_core.exceptions import IdempotencyConflictError
from fleet_governance_core.models.approval import (
    CheckpointStatusEnum,
    FleetApprovalRecord,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.ports.approval_store_port import ApprovalStorePort
from fleet_governance_core.ports.audit_log_port import AuditLogPort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.ports.memory_port import MemoryPort
from fleet_governance_core.ports.storage_port import ArtifactStoragePort

FLEET_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024  # 50 MiB Fleet Ceiling

class InMemoryCheckpointStore(CheckpointStorePort):
    def __init__(self):
        self._lock = threading.Lock()
        self._checkpoints: Dict[str, Dict[str, PDXWorkflowCheckpoint]] = {}  # tenant_id -> {id: chk}
        self._requests: Dict[str, Dict[str, PDXApprovalRequest]] = {}  # tenant_id -> {checkpoint_id: req}

    def save_checkpoint(self, tenant_id: str, checkpoint: PDXWorkflowCheckpoint) -> None:
        with self._lock:
            self._checkpoints.setdefault(tenant_id, {})[checkpoint.checkpoint_id] = checkpoint

    def get_checkpoint(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXWorkflowCheckpoint]:
        with self._lock:
            chk = self._checkpoints.get(tenant_id, {}).get(checkpoint_id)
            return chk.model_copy() if chk else None

    def update_checkpoint_status(
        self, tenant_id: str, checkpoint_id: str, status: CheckpointStatusEnum
    ) -> None:
        with self._lock:
            chk = self._checkpoints.get(tenant_id, {}).get(checkpoint_id)
            if chk:
                chk.status = status

    def save_approval_request(self, tenant_id: str, request: PDXApprovalRequest) -> None:
        with self._lock:
            self._requests.setdefault(tenant_id, {})[request.checkpoint_id] = request

    def get_approval_request(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXApprovalRequest]:
        with self._lock:
            req = self._requests.get(tenant_id, {}).get(checkpoint_id)
            return req.model_copy() if req else None

class InMemoryApprovalStore(ApprovalStorePort):
    def __init__(self):
        self._lock = threading.Lock()
        self._memory_db: Dict[str, Dict[str, FleetApprovalRecord]] = {}  # tenant_id -> {key: record}

    def save_approval_record(self, record: FleetApprovalRecord) -> None:
        with self._lock:
            tenant_db = self._memory_db.setdefault(record.tenant_id, {})
            existing = tenant_db.get(record.canonical_idempotency_key)
            
            if existing:
                if existing.model_dump(mode="json") == record.model_dump(mode="json"):
                    return
                raise IdempotencyConflictError(
                    f"Idempotency key '{record.canonical_idempotency_key}' is already assigned to a different decision."
                )

            tenant_db[record.canonical_idempotency_key] = record

    def get_by_idempotency_key(self, canonical_idempotency_key: str) -> Optional[FleetApprovalRecord]:
        with self._lock:
            parts = canonical_idempotency_key.split(":")
            if not parts:
                return None
            tenant_id = parts[0]
            rec = self._memory_db.get(tenant_id, {}).get(canonical_idempotency_key)
            return rec.model_copy() if rec else None

    def get_by_checkpoint_id(self, tenant_id: str, checkpoint_id: str) -> Optional[FleetApprovalRecord]:
        with self._lock:
            tenant_db = self._memory_db.get(tenant_id, {})
            for rec in tenant_db.values():
                if rec.checkpoint_id == checkpoint_id:
                    return rec.model_copy()
            return None

class InMemoryAuditLog(AuditLogPort):
    def __init__(self):
        self._lock = threading.Lock()
        self._log_db: Dict[str, List[AuditEvent]] = {}  # tenant_id -> list of events

    def append_audit_event(self, event: AuditEvent) -> None:
        with self._lock:
            tenant_events = self._log_db.setdefault(event.tenant_id, [])
            tenant_events.append(event)

    def list_events_for_run(self, tenant_id: str, run_id: str) -> List[AuditEvent]:
        with self._lock:
            tenant_events = self._log_db.get(tenant_id, [])
            return [e.model_copy() for e in tenant_events if e.run_id == run_id]

class InMemoryArtifactStorageAdapter(ArtifactStoragePort):
    def __init__(self, default_bucket: str = "fleet-compliance-artifacts", default_prefix: str = "dossiers"):
        self._lock = threading.Lock()
        self._bucket = default_bucket
        self._prefix = default_prefix.strip("/")
        self._memory_blob_store: Dict[str, bytes] = {}

    def store_artifact(
        self, artifact_id: str, content: bytes, media_type: str = "application/pdf"
    ) -> ArtifactStorageIdentity:
        if not content:
            raise ValueError("Artifact content cannot be empty.")
        if len(content) > FLEET_MAX_ARTIFACT_BYTES:
            raise ValueError(
                f"Artifact size {len(content)} bytes exceeds Fleet maximum ceiling of {FLEET_MAX_ARTIFACT_BYTES} bytes."
            )

        sha = hashlib.sha256(content).hexdigest()
        safe_id = artifact_id.replace("..", "").replace("/", "_").replace("\\", "_")
        ext = "pdf" if "pdf" in media_type else "bin"
        uri = f"gs://{self._bucket}/{self._prefix}/{safe_id}.{ext}"

        with self._lock:
            self._memory_blob_store[uri] = content

        return ArtifactStorageIdentity(
            artifact_id=artifact_id,
            uri=uri,
            sha256=sha,
            size_bytes=len(content),
            media_type=media_type,
        )

    def fetch_artifact(self, uri: str) -> bytes:
        with self._lock:
            if uri not in self._memory_blob_store:
                raise FileNotFoundError(f"Artifact at {uri} not found.")
            return self._memory_blob_store[uri]

class InMemoryMemoryStore(MemoryPort):
    def __init__(self):
        self._lock = threading.Lock()
        self._memories: Dict[str, List[Dict[str, Any]]] = {}

    def store_approved_memory(
        self, tenant_id: str, memory_id: str, memory_type: str, content: Dict[str, Any], approval_record_id: str
    ) -> None:
        rec = {
            "memory_id": memory_id,
            "memory_type": memory_type,
            "content": content,
            "approval_record_id": approval_record_id,
        }
        with self._lock:
            self._memories.setdefault(tenant_id, []).append(rec)

    def query_approved_memories(
        self, tenant_id: str, memory_type: str, query_filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        with self._lock:
            mems = self._memories.get(tenant_id, [])
            return [dict(m) for m in mems if m["memory_type"] == memory_type]
