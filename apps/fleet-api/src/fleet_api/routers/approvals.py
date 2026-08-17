"""
Approval Router (v0.3.0).
Handles human regulatory decisions, single-transaction atomic approval commitments,
lease-fenced execution, and crash-safe projection synchronization.
"""
from typing import Any, Dict, Tuple
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from fleet_api.deps import (
    get_approval_workflow_service,
    get_approver_identity,
    get_checkpoint_store,
    get_orchestrator,
    get_resume_context_store,
)
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
    FleetExecutionStatus,
)
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.ports.orchestrator_port import ExecutionOrchestratorPort
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort
from fleet_governance_core.services.approval_workflow import ApprovalWorkflowService

router = APIRouter(prefix="/v1/approval", tags=["Approvals"])

class ApprovalDecisionRequestBody(BaseModel):
    checkpoint_id: str
    run_id: str
    approval_request_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=256)
    decision: ApprovalDecisionEnum
    reason: str = ""
    case_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digests: Dict[str, str] = Field(default_factory=dict)

@router.post("/decide", response_model=Dict[str, Any])
def submit_approval_decision(
    body: ApprovalDecisionRequestBody,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_approver_identity),
    orch: ExecutionOrchestratorPort = Depends(get_orchestrator),
    resume_store: ResumeContextStorePort = Depends(get_resume_context_store),
    checkpoint_store: CheckpointStorePort = Depends(get_checkpoint_store),
    approval_service: ApprovalWorkflowService = Depends(get_approval_workflow_service),
) -> Dict[str, Any]:
    """Submit an authorized human decision for a persisted pending checkpoint."""
    tenant_id, actor = identity

    # 1. Fetch real persisted checkpoint under tenant boundary (Fail closed: No self-minting!)
    checkpoint = checkpoint_store.get_checkpoint(tenant_id, body.checkpoint_id)
    if not checkpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkpoint not found under tenant.",
        )

    # 2. Verify run_id and approval_request_id correlation (Fail closed)
    if body.run_id != checkpoint.run_id:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Run ID mismatch.",
        )

    persisted_req = checkpoint_store.get_approval_request(tenant_id, body.checkpoint_id)
    if persisted_req is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Approval request not found for checkpoint.",
        )
    if str(body.approval_request_id) != str(persisted_req.approval_request_id):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Approval Request ID mismatch.",
        )

    # 3. Process approval with 3-way digest verification and idempotency check (single ACID transaction)
    try:
        fleet_record, pdx_decision = approval_service.process_approval_decision(
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            approval_request_id=str(body.approval_request_id),
            actor=actor,
            decision=body.decision,
            idempotency_key=body.idempotency_key,
            case_digest=body.case_digest,
            plan_digest=body.plan_digest,
            evidence_digests=body.evidence_digests,
            reason=body.reason,
        )
    except PreconditionFailedError as exc:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=f"Precondition Failed: {exc}") from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Idempotency Conflict: {exc}") from exc
    except CheckpointNotPendingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Checkpoint Invalid: {exc}") from exc
    except CheckpointNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Checkpoint Not Found: {exc}") from exc

    # 4. Handle Rejection Path
    if body.decision == ApprovalDecisionEnum.REJECTED:
        checkpoint_store.update_checkpoint_status(tenant_id, body.checkpoint_id, CheckpointStatusEnum.CANCELLED)
        return {
            "status": "decided",
            "decision": "rejected",
            "approval_record": fleet_record.model_dump(mode="json"),
            "pdx_resume": {"status": "rejected", "checkpoint_id": body.checkpoint_id},
        }

    # 5. Handle Approval & Resume with Lease Fencing
    ctx = resume_store.get_context(tenant_id, body.checkpoint_id)
    if ctx and ctx.status == FleetExecutionStatus.COMPLETED and ctx.result_identity:
        return {
            "status": "decided",
            "decision": body.decision.value,
            "approval_record": fleet_record.model_dump(mode="json"),
            "pdx_resume": {
                "status": "completed",
                "checkpoint_id": body.checkpoint_id,
                "artifact_identity": ctx.result_identity.model_dump(mode="json"),
            },
            "artifact_identity": ctx.result_identity.model_dump(mode="json"),
            "is_idempotent_replay": True,
        }

    cur_version = ctx.version if ctx else 1
    lease_id = None

    try:
        ctx, lease_id = resume_store.acquire_resume_lease(
            tenant_id=tenant_id,
            checkpoint_id=body.checkpoint_id,
            expected_version=cur_version,
            lease_owner=actor.sub,
            lease_duration_seconds=60,
        )
        cur_version = ctx.version
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Failed to acquire resume lease: {exc}",
        ) from exc

    # 6. Execute resume and artifact emission
    try:
        resume_result = orch.resume_with_decision(checkpoint, pdx_decision)
        raw_ident = resume_result.get("artifact_identity", {})
        result_ident = ArtifactStorageIdentity.model_validate(raw_ident)

        # Mark completed & emit resumed outbox
        resume_store.mark_resume_completed(
            tenant_id=tenant_id,
            checkpoint_id=body.checkpoint_id,
            expected_version=cur_version,
            lease_id=lease_id,
            result_identity=result_ident,
        )

        # Synchronize projection
        checkpoint_store.update_checkpoint_status(tenant_id, body.checkpoint_id, CheckpointStatusEnum.RESUMED)

        return {
            "status": "decided",
            "decision": body.decision.value,
            "approval_record": fleet_record.model_dump(mode="json"),
            "pdx_resume": resume_result,
            "artifact_identity": result_ident.model_dump(mode="json"),
        }

    except Exception as exc:
        # Record retryable failure without emitting resumed projection
        if lease_id:
            try:
                resume_store.mark_resume_failed(
                    tenant_id=tenant_id,
                    checkpoint_id=body.checkpoint_id,
                    expected_version=cur_version,
                    lease_id=lease_id,
                    safe_error_code="RESUME_EXECUTION_ERROR",
                    request_id=str(body.approval_request_id),
                )
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Resume execution error (state is retryable): {exc}",
        ) from exc
