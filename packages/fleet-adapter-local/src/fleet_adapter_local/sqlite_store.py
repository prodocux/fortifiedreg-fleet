"""
SQLite Transactional Resume Context Store (v0.3.0).
Implements ResumeContextStorePort with ACID SQLite transactions, atomic CAS transitions,
and lease fencing.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from fleet_governance_core.models.approval import (
    CheckpointStatusEnum,
    FleetApprovalRecord,
    FleetExecutionStatus,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.execution_context import (
    ExecutionContextRecord,
    PlanSummary,
    ProjectionOutboxRecord,
)
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.ports.approval_store_port import ApprovalStorePort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort

from contextlib import contextmanager

class SQLiteResumeContextStore(ResumeContextStorePort, CheckpointStorePort, ApprovalStorePort):
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._mem_conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False) if self.db_path == ":memory:" else None
        if self._mem_conn:
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _connection(self):
        if self._mem_conn:
            yield self._mem_conn
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        if self._mem_conn:
            self._mem_conn.close()
            self._mem_conn = None

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cases (
                    tenant_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    case_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, case_id)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    tenant_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, checkpoint_id)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    tenant_id TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_contexts (
                    tenant_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    case_digest TEXT NOT NULL,
                    case_storage_identity TEXT,
                    plan_digest TEXT NOT NULL,
                    plan_storage_identity TEXT,
                    plan_summary TEXT NOT NULL,
                    approval_request TEXT,
                    evidence_digests TEXT NOT NULL,
                    document_storage_identities TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    lease_id TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    result_identity TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, checkpoint_id)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_records (
                    tenant_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    canonical_idempotency_key TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, checkpoint_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_records_idemp ON approval_records (canonical_idempotency_key);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projection_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    target_pdx_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0
                );
            """)
            conn.commit()

    def save_case(self, tenant_id: str, case: DossierCase) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO cases (tenant_id, case_id, case_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, case_id) DO UPDATE SET
                    case_json=excluded.case_json
            """, (tenant_id, str(case.case_id), json.dumps(case.model_dump(mode="json")), now_iso))
            conn.commit()

    def get_case(self, tenant_id: str, case_id: str) -> Optional[DossierCase]:
        with self._lock, self._connection() as conn:
            cur = conn.execute("SELECT case_json FROM cases WHERE tenant_id = ? AND case_id = ?", (tenant_id, case_id))
            row = cur.fetchone()
            if not row:
                return None
            return DossierCase.model_validate(json.loads(row["case_json"]))

    def save_checkpoint(self, tenant_id: str, checkpoint: PDXWorkflowCheckpoint) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO checkpoints (tenant_id, checkpoint_id, checkpoint_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, checkpoint_id) DO UPDATE SET
                    checkpoint_json=excluded.checkpoint_json
            """, (tenant_id, checkpoint.checkpoint_id, json.dumps(checkpoint.model_dump(mode="json")), now_iso))
            conn.commit()

    def get_checkpoint(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXWorkflowCheckpoint]:
        with self._lock, self._connection() as conn:
            cur = conn.execute("SELECT checkpoint_json FROM checkpoints WHERE tenant_id = ? AND checkpoint_id = ?", (tenant_id, checkpoint_id))
            row = cur.fetchone()
            if not row:
                return None
            return PDXWorkflowCheckpoint.model_validate(json.loads(row["checkpoint_json"]))

    def update_checkpoint_status(self, tenant_id: str, checkpoint_id: str, status: CheckpointStatusEnum) -> None:
        with self._lock, self._connection() as conn:
            cur = conn.execute("SELECT checkpoint_json FROM checkpoints WHERE tenant_id = ? AND checkpoint_id = ?", (tenant_id, checkpoint_id))
            row = cur.fetchone()
            if row:
                chk_data = json.loads(row["checkpoint_json"])
                chk_data["status"] = status.value
                conn.execute(
                    "UPDATE checkpoints SET checkpoint_json = ? WHERE tenant_id = ? AND checkpoint_id = ?",
                    (json.dumps(chk_data), tenant_id, checkpoint_id),
                )
                conn.commit()

    def save_approval_request(self, tenant_id: str, request: PDXApprovalRequest) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO approval_requests (tenant_id, approval_request_id, checkpoint_id, request_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, approval_request_id) DO UPDATE SET
                    request_json=excluded.request_json
            """, (tenant_id, str(request.approval_request_id), request.checkpoint_id, json.dumps(request.model_dump(mode="json")), now_iso))
            conn.commit()

    def get_approval_request(self, tenant_id: str, checkpoint_id: str) -> Optional[PDXApprovalRequest]:
        with self._lock, self._connection() as conn:
            cur = conn.execute("SELECT request_json FROM approval_requests WHERE tenant_id = ? AND checkpoint_id = ?", (tenant_id, checkpoint_id))
            row = cur.fetchone()
            if not row:
                return None
            return PDXApprovalRequest.model_validate(json.loads(row["request_json"]))

    def save_approval_record(self, record: FleetApprovalRecord) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO approval_records (tenant_id, checkpoint_id, canonical_idempotency_key, record_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, checkpoint_id) DO UPDATE SET
                    canonical_idempotency_key=excluded.canonical_idempotency_key,
                    record_json=excluded.record_json
            """, (
                record.tenant_id,
                record.checkpoint_id,
                record.canonical_idempotency_key,
                json.dumps(record.model_dump(mode="json")),
                now_iso,
            ))
            conn.commit()

    def get_by_idempotency_key(self, canonical_idempotency_key: str) -> Optional[FleetApprovalRecord]:
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                "SELECT record_json FROM approval_records WHERE canonical_idempotency_key = ?",
                (canonical_idempotency_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return FleetApprovalRecord.model_validate(json.loads(row["record_json"]))

    def get_by_checkpoint_id(self, tenant_id: str, checkpoint_id: str) -> Optional[FleetApprovalRecord]:
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                "SELECT record_json FROM approval_records WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return FleetApprovalRecord.model_validate(json.loads(row["record_json"]))

    def save_context(self, record: ExecutionContextRecord) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO execution_contexts (
                    tenant_id, checkpoint_id, run_id, case_digest, case_storage_identity,
                    plan_digest, plan_storage_identity, plan_summary, approval_request,
                    evidence_digests, document_storage_identities, status, version,
                    lease_id, lease_owner, lease_expires_at, attempt_count, result_identity,
                    last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, checkpoint_id) DO UPDATE SET
                    status=excluded.status,
                    version=excluded.version,
                    updated_at=excluded.updated_at
            """, (
                record.tenant_id,
                record.checkpoint_id,
                record.run_id,
                record.case_digest,
                json.dumps(record.case_storage_identity.model_dump(mode="json")) if record.case_storage_identity else None,
                record.plan_digest,
                json.dumps(record.plan_storage_identity.model_dump(mode="json")) if record.plan_storage_identity else None,
                json.dumps(record.plan_summary.model_dump(mode="json")),
                json.dumps(record.approval_request.model_dump(mode="json")) if record.approval_request else None,
                json.dumps(record.evidence_digests),
                json.dumps({k: v.model_dump(mode="json") for k, v in record.document_storage_identities.items()}),
                record.status.value,
                record.version,
                record.lease_id,
                record.lease_owner,
                record.lease_expires_at,
                record.attempt_count,
                json.dumps(record.result_identity.model_dump(mode="json")) if record.result_identity else None,
                json.dumps(record.last_error) if record.last_error else None,
                now_iso,
                now_iso,
            ))
            conn.commit()

    def get_context(self, tenant_id: str, checkpoint_id: str) -> Optional[ExecutionContextRecord]:
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def invalidate_context(self, tenant_id: str, checkpoint_id: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE execution_contexts SET status = ?, lease_id = NULL, lease_owner = NULL, updated_at = ? WHERE tenant_id = ? AND checkpoint_id = ?",
                (FleetExecutionStatus.CANCELLED.value, now_iso, tenant_id, checkpoint_id),
            )
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> ExecutionContextRecord:
        case_ident = json.loads(row["case_storage_identity"]) if row["case_storage_identity"] else None
        plan_ident = json.loads(row["plan_storage_identity"]) if row["plan_storage_identity"] else None
        plan_sum = json.loads(row["plan_summary"])
        app_req = json.loads(row["approval_request"]) if row["approval_request"] else None
        ev_digests = json.loads(row["evidence_digests"])
        doc_idents = json.loads(row["document_storage_identities"])
        res_ident = json.loads(row["result_identity"]) if row["result_identity"] else None
        err = json.loads(row["last_error"]) if row["last_error"] else None

        return ExecutionContextRecord(
            tenant_id=row["tenant_id"],
            checkpoint_id=row["checkpoint_id"],
            run_id=row["run_id"],
            case_digest=row["case_digest"],
            case_storage_identity=ArtifactStorageIdentity.model_validate(case_ident) if case_ident else None,
            plan_digest=row["plan_digest"],
            plan_storage_identity=ArtifactStorageIdentity.model_validate(plan_ident) if plan_ident else None,
            plan_summary=PlanSummary.model_validate(plan_sum),
            approval_request=app_req,
            evidence_digests=ev_digests,
            document_storage_identities={k: ArtifactStorageIdentity.model_validate(v) for k, v in doc_idents.items()},
            status=FleetExecutionStatus(row["status"]),
            version=row["version"],
            lease_id=row["lease_id"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            attempt_count=row["attempt_count"],
            result_identity=ArtifactStorageIdentity.model_validate(res_ident) if res_ident else None,
            last_error=err,
        )

    def record_decision_and_transition(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        approval_record: FleetApprovalRecord,
        target_status: FleetExecutionStatus,
        outbox_target_pdx_status: Optional[str] = None,
    ) -> ExecutionContextRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise ValueError(f"ExecutionContext not found for {(tenant_id, checkpoint_id)}")

            if row["version"] != expected_version:
                conn.rollback()
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {row['version']}")

            if row["status"] != FleetExecutionStatus.AWAITING_DECISION.value:
                conn.rollback()
                raise ValueError(f"Invalid transition from state {row['status']}")

            # 1. Insert immutable approval record
            conn.execute("""
                INSERT INTO approval_records (tenant_id, checkpoint_id, canonical_idempotency_key, record_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, checkpoint_id) DO UPDATE SET
                    canonical_idempotency_key=excluded.canonical_idempotency_key,
                    record_json=excluded.record_json
            """, (
                tenant_id,
                checkpoint_id,
                approval_record.canonical_idempotency_key,
                json.dumps(approval_record.model_dump(mode="json")),
                now_iso,
            ))

            # 2. Transition execution status & increment version
            new_version = expected_version + 1
            conn.execute("""
                UPDATE execution_contexts
                SET status = ?, version = ?, updated_at = ?
                WHERE tenant_id = ? AND checkpoint_id = ? AND version = ?
            """, (
                target_status.value,
                new_version,
                now_iso,
                tenant_id,
                checkpoint_id,
                expected_version,
            ))

            # 3. Create projection outbox if specified (e.g. cancelled on reject)
            if outbox_target_pdx_status:
                outbox_id = f"outbox-{uuid4().hex}"
                conn.execute("""
                    INSERT INTO projection_outbox (outbox_id, tenant_id, checkpoint_id, target_pdx_status, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    outbox_id,
                    tenant_id,
                    checkpoint_id,
                    outbox_target_pdx_status,
                    now_iso,
                ))

            conn.commit()

            # Return updated record
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            return self._row_to_record(cur.fetchone())

    def acquire_resume_lease(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_owner: str,
        lease_duration_seconds: int = 60,
    ) -> Tuple[ExecutionContextRecord, str]:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        expires_dt = datetime.fromtimestamp(now_dt.timestamp() + lease_duration_seconds, timezone.utc)
        expires_iso = expires_dt.isoformat()
        lease_id = str(uuid4())

        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise ValueError(f"ExecutionContext not found for {(tenant_id, checkpoint_id)}")

            if row["version"] != expected_version:
                conn.rollback()
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {row['version']}")

            current_status = row["status"]
            current_lease_expires = row["lease_expires_at"]
            is_expired = (
                current_status == FleetExecutionStatus.RESUME_IN_PROGRESS.value
                and current_lease_expires is not None
                and current_lease_expires < now_iso
            )
            is_valid = (
                current_status in (
                    FleetExecutionStatus.APPROVED_PENDING_RESUME.value,
                    FleetExecutionStatus.RESUME_FAILED_RETRYABLE.value,
                )
                or is_expired
            )

            if not is_valid:
                conn.rollback()
                raise ValueError(f"Cannot acquire lease from state {current_status} (active lease: {row['lease_id']})")

            new_version = expected_version + 1
            new_attempts = row["attempt_count"] + 1

            conn.execute("""
                UPDATE execution_contexts
                SET status = ?, version = ?, lease_id = ?, lease_owner = ?,
                    lease_expires_at = ?, attempt_count = ?, updated_at = ?
                WHERE tenant_id = ? AND checkpoint_id = ? AND version = ?
            """, (
                FleetExecutionStatus.RESUME_IN_PROGRESS.value,
                new_version,
                lease_id,
                lease_owner,
                expires_iso,
                new_attempts,
                now_iso,
                tenant_id,
                checkpoint_id,
                expected_version,
            ))
            conn.commit()

            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            return self._row_to_record(cur.fetchone()), lease_id

    def mark_resume_completed(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_id: str,
        result_identity: ArtifactStorageIdentity,
    ) -> ExecutionContextRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise ValueError(f"ExecutionContext not found for {(tenant_id, checkpoint_id)}")

            if row["version"] != expected_version:
                conn.rollback()
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {row['version']}")

            if row["lease_id"] != lease_id:
                conn.rollback()
                raise ValueError(f"Lease mismatch: expected {lease_id}, got {row['lease_id']}")

            new_version = expected_version + 1
            conn.execute("""
                UPDATE execution_contexts
                SET status = ?, version = ?, lease_id = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, result_identity = ?, updated_at = ?
                WHERE tenant_id = ? AND checkpoint_id = ? AND version = ?
            """, (
                FleetExecutionStatus.COMPLETED.value,
                new_version,
                json.dumps(result_identity.model_dump(mode="json")),
                now_iso,
                tenant_id,
                checkpoint_id,
                expected_version,
            ))

            # Emit resumed projection outbox record
            outbox_id = f"outbox-{uuid4().hex}"
            conn.execute("""
                INSERT INTO projection_outbox (outbox_id, tenant_id, checkpoint_id, target_pdx_status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                outbox_id,
                tenant_id,
                checkpoint_id,
                "resumed",
                now_iso,
            ))

            conn.commit()

            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            return self._row_to_record(cur.fetchone())

    def mark_resume_failed(
        self,
        tenant_id: str,
        checkpoint_id: str,
        expected_version: int,
        lease_id: str,
        safe_error_code: str,
        request_id: str,
        is_retryable: bool = True,
    ) -> ExecutionContextRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        err_json = json.dumps({
            "safe_error_code": safe_error_code,
            "request_id": request_id,
            "is_retryable": is_retryable,
            "timestamp": now_iso,
        })
        target_status = (
            FleetExecutionStatus.RESUME_FAILED_RETRYABLE.value
            if is_retryable
            else FleetExecutionStatus.BLOCKED_REVIEW.value
        )
        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise ValueError(f"ExecutionContext not found for {(tenant_id, checkpoint_id)}")

            if row["version"] != expected_version:
                conn.rollback()
                raise ValueError(f"CAS Conflict: expected version {expected_version}, got {row['version']}")

            if row["lease_id"] != lease_id:
                conn.rollback()
                raise ValueError(f"Lease mismatch: expected {lease_id}, got {row['lease_id']}")

            new_version = expected_version + 1
            conn.execute("""
                UPDATE execution_contexts
                SET status = ?, version = ?, lease_id = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = ?
                WHERE tenant_id = ? AND checkpoint_id = ? AND version = ?
            """, (
                target_status,
                new_version,
                err_json,
                now_iso,
                tenant_id,
                checkpoint_id,
                expected_version,
            ))
            conn.commit()

            cur = conn.execute(
                "SELECT * FROM execution_contexts WHERE tenant_id = ? AND checkpoint_id = ?",
                (tenant_id, checkpoint_id),
            )
            return self._row_to_record(cur.fetchone())

    def get_pending_outbox_records(self, limit: int = 100) -> List[ProjectionOutboxRecord]:
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM projection_outbox WHERE processed_at IS NULL ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
            return [
                ProjectionOutboxRecord(
                    outbox_id=r["outbox_id"],
                    tenant_id=r["tenant_id"],
                    checkpoint_id=r["checkpoint_id"],
                    target_pdx_status=r["target_pdx_status"],
                    created_at=r["created_at"],
                    processed_at=r["processed_at"],
                    attempt_count=r["attempt_count"],
                )
                for r in rows
            ]

    def mark_outbox_processed(self, outbox_id: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE projection_outbox SET processed_at = ? WHERE outbox_id = ?",
                (now_iso, outbox_id),
            )
            conn.commit()
