"""
Approval Workflow Service (v0.3.0).
Encapsulates 3-way digest verification, approval_request_id binding, actor role authorization,
idempotency checking, single-transaction atomic decision & Fleet status transition, and audit logging.
"""
from typing import Dict, Optional, Tuple
from uuid import UUID, uuid4
from fleet_governance_core.exceptions import (
    CheckpointNotFoundError,
    CheckpointNotPendingError,
    IdempotencyConflictError,
    PreconditionFailedError,
)
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    FleetExecutionStatus,
    PDXApprovalDecision,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum
from fleet_governance_core.ports.approval_store_port import ApprovalStorePort
from fleet_governance_core.ports.audit_log_port import AuditLogPort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort

AUTHORIZED_APPROVER_ROLES = {"approver", "regulatory_approver", "safety_assessor", "cso", "demo_evaluator"}

class ApprovalWorkflowService:
    def __init__(
        self,
        approval_store: ApprovalStorePort,
        audit_log: AuditLogPort,
        checkpoint_store: Optional[CheckpointStorePort] = None,
        resume_context_store: Optional[ResumeContextStorePort] = None,
    ):
        self._store = approval_store
        self._audit = audit_log
        self._checkpoints = checkpoint_store
        self._resume_contexts = resume_context_store

    def build_canonical_idempotency_key(
        self, tenant_id: str, checkpoint_id: str, actor_id: str, idempotency_key: str
    ) -> str:
        return f"{tenant_id}:{checkpoint_id}:{actor_id}:{idempotency_key}"

    def process_approval_decision(
        self,
        tenant_id: str,
        checkpoint: PDXWorkflowCheckpoint,
        approval_request_id: str,
        actor: AuthenticatedActor,
        decision: ApprovalDecisionEnum,
        idempotency_key: str,
        case_digest: str,
        plan_digest: str,
        evidence_digests: Dict[str, str],
        reason: str = "",
    ) -> Tuple[FleetApprovalRecord, PDXApprovalDecision]:
        """Process a human approval decision with 3-way digest verification and idempotency."""
        # 0. Authorization check: Actor must have authorized approver role
        if not any(r.lower() in AUTHORIZED_APPROVER_ROLES for r in actor.roles):
            raise PreconditionFailedError(
                "Actor lacks required approver authorization."
            )

        # 1. Validate checkpoint store and persisted approval request existence BEFORE idempotency lookup
        persisted_chk = None
        if self._checkpoints is not None:
            persisted_chk = self._checkpoints.get_checkpoint(tenant_id, checkpoint.checkpoint_id)
            if not persisted_chk:
                raise CheckpointNotFoundError(
                    f"Checkpoint '{checkpoint.checkpoint_id}' not found under tenant."
                )

            # 1.1 Validate against persisted approval request (Fail-closed)
            persisted_req = self._checkpoints.get_approval_request(tenant_id, checkpoint.checkpoint_id)
            if persisted_req is None:
                raise PreconditionFailedError(
                    f"Missing approval request for checkpoint '{checkpoint.checkpoint_id}' under tenant."
                )
            if str(persisted_req.approval_request_id) != str(approval_request_id):
                raise PreconditionFailedError(
                    f"Approval Request ID mismatch: provided {approval_request_id} != persisted {persisted_req.approval_request_id}"
                )

        canonical_key = self.build_canonical_idempotency_key(
            tenant_id=tenant_id,
            checkpoint_id=checkpoint.checkpoint_id,
            actor_id=actor.sub,
            idempotency_key=idempotency_key,
        )

        req_uuid = UUID(str(approval_request_id))

        # 2. Check existing record by idempotency key (Exact payload & strict approval_request_id match)
        existing = self._store.get_by_idempotency_key(canonical_key)
        if existing:
            if (
                existing.decision == decision
                and existing.subject_case_digest == case_digest
                and existing.plan_digest == plan_digest
                and existing.evidence_digests == evidence_digests
                and (existing.reason or "") == (reason or "")
                and existing.approval_request_id == req_uuid
            ):
                pdx_dec = PDXApprovalDecision(
                    decision_id=existing.approval_record_id,
                    approval_request_id=req_uuid,
                    checkpoint_id=checkpoint.checkpoint_id,
                    idempotency_key=idempotency_key,
                    actor_id=actor.sub,
                    decision=decision,
                    reason=existing.reason,
                    subject_digest=case_digest,
                    plan_digest=plan_digest,
                    evidence_digests=evidence_digests,
                    decided_at=existing.decided_at,
                )
                return existing, pdx_dec
            raise IdempotencyConflictError(
                "Idempotency key was already used with different decision payload, reason, or approval request ID."
            )

        # 3. Verify 3 Independent Digests
        if case_digest != checkpoint.subject_digest:
            raise PreconditionFailedError("Case digest mismatch.")
        if plan_digest != checkpoint.plan_digest:
            raise PreconditionFailedError("Plan digest mismatch.")
        if evidence_digests != checkpoint.evidence_digests:
            raise PreconditionFailedError("Evidence digests mismatch.")

        # 4. Verify checkpoint is in PENDING status for new decisions
        if self._resume_contexts is not None:
            ctx = self._resume_contexts.get_context(tenant_id, checkpoint.checkpoint_id)
            if ctx is not None and ctx.status != FleetExecutionStatus.AWAITING_DECISION:
                raise CheckpointNotPendingError(
                    f"Checkpoint execution is in status {ctx.status.value}, not awaiting_decision."
                )

        if persisted_chk is not None:
            if persisted_chk.status != CheckpointStatusEnum.PENDING:
                raise CheckpointNotPendingError(
                    f"Checkpoint is in status {persisted_chk.status}, not PENDING."
                )
        else:
            if checkpoint.status != CheckpointStatusEnum.PENDING:
                raise CheckpointNotPendingError(
                    f"Checkpoint is in status {checkpoint.status}, not PENDING."
                )

        # 5. Construct domain persistence record & PDX decision
        record_id = uuid4()

        fleet_record = FleetApprovalRecord(
            approval_record_id=record_id,
            tenant_id=tenant_id,
            run_id=checkpoint.run_id,
            checkpoint_id=checkpoint.checkpoint_id,
            approval_request_id=req_uuid,
            canonical_idempotency_key=canonical_key,
            authenticated_actor=actor,
            decision=decision,
            reason=reason,
            subject_case_digest=case_digest,
            plan_digest=plan_digest,
            evidence_digests=evidence_digests,
        )

        pdx_decision = PDXApprovalDecision(
            decision_id=record_id,
            approval_request_id=req_uuid,
            checkpoint_id=checkpoint.checkpoint_id,
            idempotency_key=idempotency_key,
            actor_id=actor.sub,
            decision=decision,
            reason=reason,
            subject_digest=case_digest,
            plan_digest=plan_digest,
            evidence_digests=evidence_digests,
            decided_at=fleet_record.decided_at,
        )

        # 6. Single-transaction or sequential persistence
        if self._resume_contexts is not None:
            ctx = self._resume_contexts.get_context(tenant_id, checkpoint.checkpoint_id)
            if ctx is None:
                from fleet_governance_core.models.execution_context import (
                    ExecutionContextRecord,
                    PlanSummary,
                )
                from fleet_governance_core.models.storage import (
                    ArtifactStorageIdentity,
                    derive_opaque_tenant_storage_key,
                )
                plan_sum = PlanSummary(
                    request_id=checkpoint.run_id,
                    schema_version="pdx_execution_plan_v1",
                    step_count=1,
                    step_ids=["step_approval"],
                    has_approval_step=True,
                    product_name="PIF",
                    jurisdiction="TW",
                )
                opaque_tenant_key = derive_opaque_tenant_storage_key(tenant_id)
                plan_ident = ArtifactStorageIdentity(
                    uri=f"artifact://{opaque_tenant_key}/plans/{checkpoint.run_id}.json",
                    sha256=plan_digest,
                    size_bytes=100,
                    media_type="application/json",
                )
                case_ident = ArtifactStorageIdentity(
                    uri=f"artifact://{opaque_tenant_key}/cases/{checkpoint.run_id}.json",
                    sha256=case_digest,
                    size_bytes=100,
                    media_type="application/json",
                )
                default_ctx = ExecutionContextRecord(
                    tenant_id=tenant_id,
                    run_id=checkpoint.run_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                    case_digest=case_digest,
                    case_storage_identity=case_ident,
                    plan_digest=plan_digest,
                    plan_storage_identity=plan_ident,
                    plan_summary=plan_sum,
                    status=FleetExecutionStatus.AWAITING_DECISION,
                    version=1,
                )
                self._resume_contexts.save_context(default_ctx)
                expected_ver = 1
            else:
                expected_ver = ctx.version

            if decision == ApprovalDecisionEnum.APPROVED:
                target_status = FleetExecutionStatus.APPROVED_PENDING_RESUME
                outbox_status = None  # PDX checkpoint remains pending until resume completes
            else:
                target_status = FleetExecutionStatus.REJECTED
                outbox_status = "cancelled"  # PDX projection cancelled

            self._resume_contexts.record_decision_and_transition(
                tenant_id=tenant_id,
                checkpoint_id=checkpoint.checkpoint_id,
                expected_version=expected_ver,
                approval_record=fleet_record,
                target_status=target_status,
                outbox_target_pdx_status=outbox_status,
            )
            # Also save to approval_store
            self._store.save_approval_record(fleet_record)
            if outbox_status and self._checkpoints is not None:
                self._checkpoints.update_checkpoint_status(tenant_id, checkpoint.checkpoint_id, CheckpointStatusEnum.CANCELLED)
        else:
            self._store.save_approval_record(fleet_record)
            if self._checkpoints is not None:
                new_status = (
                    CheckpointStatusEnum.RESUMED
                    if decision == ApprovalDecisionEnum.APPROVED
                    else CheckpointStatusEnum.CANCELLED
                )
                self._checkpoints.update_checkpoint_status(tenant_id, checkpoint.checkpoint_id, new_status)

        # 7. Emit immutable audit event
        audit_event = AuditEvent(
            tenant_id=tenant_id,
            run_id=checkpoint.run_id,
            event_type=AuditEventTypeEnum.APPROVAL_DECIDED,
            actor_id=actor.sub,
            payload={
                "decision": decision.value,
                "checkpoint_id": checkpoint.checkpoint_id,
                "approval_request_id": str(req_uuid),
                "idempotency_key": canonical_key,
            },
        )
        self._audit.append_audit_event(audit_event)

        return fleet_record, pdx_decision
