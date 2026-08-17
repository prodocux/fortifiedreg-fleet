"""
Dossier Management Router.
Handles dossier creation, document content registration, plan compilation, and execution orchestration.
"""
import base64
import hashlib
from typing import Any, Dict, Optional, Tuple
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fleet_api.deps import (
    get_audit_log,
    get_checkpoint_store,
    get_document_resolver,
    get_orchestrator,
    get_tenant_and_actor,
)
from fleet_governance_core.ports.audit_log_port import AuditLogPort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort
from fleet_governance_core.ports.document_resolver_port import DocumentResolverPort
from fleet_governance_core.ports.orchestrator_port import ExecutionOrchestratorPort
from fleet_governance_core.models.approval import (
    AuthenticatedActor,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.hashing import compute_data_sha256

router = APIRouter(prefix="/v1/dossiers", tags=["Dossiers"])

CASES_DB: Dict[str, Dict[str, DossierCase]] = {}  # tenant_id -> {case_id_str: case}

from pathlib import Path

MAX_BASE64_CHARS = 68_000_000  # ~50 MiB raw ceiling
FORMAT_LIMITS = {
    ".pdf": 10 * 1024 * 1024,
    ".docx": 16 * 1024 * 1024,
    ".csv": 8 * 1024 * 1024,
    ".xlsx": 16 * 1024 * 1024,
    ".pptx": 32 * 1024 * 1024,
}

from pydantic import BaseModel, Field

class DocumentRegistrationRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    content_b64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)
    filename: Optional[str] = Field(default=None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_.-]+$")
    expected_sha256: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

@router.post("/documents/register", response_model=Dict[str, Any])
def register_document(
    req: DocumentRegistrationRequest,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
    resolver: DocumentResolverPort = Depends(get_document_resolver),
) -> Dict[str, Any]:
    """Register raw binary document content for a supplier document in the tenant's resolver."""
    tenant_id, actor = identity

    if not req.doc_id or not req.doc_id.strip():
        raise HTTPException(status_code=400, detail="Invalid doc_id provided.")

    if not req.content_b64 or len(req.content_b64) > MAX_BASE64_CHARS:
        raise HTTPException(status_code=400, detail="Document payload exceeds maximum allowed request ceiling.")

    # Strict Base64 Decoding with sanitized static error
    try:
        raw_bytes = base64.b64decode(req.content_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Base64 payload encoding.")

    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Document content cannot be empty.")

    # Validate format and enforce format size limits
    filename = req.filename or f"{req.doc_id}.pdf"
    ext = Path(filename).suffix.casefold()
    if ext not in FORMAT_LIMITS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported document format.",
        )

    limit = FORMAT_LIMITS[ext]
    if len(raw_bytes) > limit:
        raise HTTPException(
            status_code=400,
            detail="Document payload exceeds maximum allowed size for format.",
        )

    # Register with CAS & tenant scoping
    try:
        sha256_digest = resolver.register_document(
            tenant_id=tenant_id,
            doc_id=req.doc_id,
            content=raw_bytes,
            filename=filename,
            expected_sha256=req.expected_sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Document already registered with different content.")

    return {
        "status": "registered",
        "doc_id": req.doc_id,
        "tenant_id": tenant_id,
        "filename": filename,
        "sha256": sha256_digest,
        "size_bytes": len(raw_bytes),
    }

@router.post("/create", response_model=Dict[str, Any])
def create_dossier(
    case: DossierCase,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
    audit_log: AuditLogPort = Depends(get_audit_log),
) -> Dict[str, Any]:
    """Create a new product regulatory dossier case and compute canonical digest."""
    tenant_id, actor = identity

    # Ensure payload tenant matches authenticated tenant
    if case.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail=f"Payload tenant_id '{case.tenant_id}' does not match authenticated token tenant '{tenant_id}'",
        )

    case_id_str = str(case.case_id)
    CASES_DB.setdefault(tenant_id, {})[case_id_str] = case
    case_digest = compute_data_sha256(case)

    # Emit audit event
    audit_log.append_audit_event(
        AuditEvent(
            tenant_id=tenant_id,
            run_id=f"run-pif-{case_id_str}",
            event_type=AuditEventTypeEnum.CASE_CREATED,
            actor_id=actor.sub,
            payload={
                "case_id": case_id_str,
                "product_name": case.product_name,
                "case_digest": case_digest,
            },
        )
    )

    return {
        "status": "created",
        "case_id": case_id_str,
        "product_name": case.product_name,
        "case_digest": case_digest,
    }

@router.post("/{case_id}/compile-and-run", response_model=Dict[str, Any])
def compile_and_run_dossier(
    case_id: UUID,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
    orch: ExecutionOrchestratorPort = Depends(get_orchestrator),
    checkpoint_store: CheckpointStorePort = Depends(get_checkpoint_store),
    audit_log: AuditLogPort = Depends(get_audit_log),
) -> Dict[str, Any]:
    """Compile dossier case into PDX plan and run through deterministic verifiers."""
    tenant_id, actor = identity
    case_id_str = str(case_id)
    case = CASES_DB.get(tenant_id, {}).get(case_id_str)
    if not case:
        raise HTTPException(status_code=404, detail=f"Dossier case '{case_id_str}' not found.")

    case_payload = case.model_dump(mode="json")
    
    # 1. Compile Plan (request_id derived uniquely from case.case_id)
    plan = orch.compile_execution_plan(case_payload)
    plan_digest = compute_data_sha256(plan)

    audit_log.append_audit_event(
        AuditEvent(
            tenant_id=tenant_id,
            run_id=plan.get("request_id", f"run-{case_id_str[:8]}"),
            event_type=AuditEventTypeEnum.PLAN_COMPILED,
            actor_id=actor.sub,
            payload={"plan_digest": plan_digest},
        )
    )

    # 2. Execute Plan
    exec_result = orch.execute_plan(plan, case_payload=case_payload)

    # 3. If paused at checkpoint, persist real checkpoint AND approval request to checkpoint store
    if exec_result.get("status") == "awaiting_approval":
        chk_dict = exec_result["checkpoint"]
        checkpoint = PDXWorkflowCheckpoint.model_validate(chk_dict)
        checkpoint_store.save_checkpoint(tenant_id, checkpoint)

        if "approval_request" in exec_result:
            req_dict = exec_result["approval_request"]
            approval_req = PDXApprovalRequest.model_validate(req_dict)
            checkpoint_store.save_approval_request(tenant_id, approval_req)
        
        audit_log.append_audit_event(
            AuditEvent(
                tenant_id=tenant_id,
                run_id=checkpoint.run_id,
                event_type=AuditEventTypeEnum.CHECKPOINT_CREATED,
                actor_id=actor.sub,
                payload={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "approval_request_id": exec_result.get("approval_request_id"),
                },
            )
        )

    return {
        "case_id": case_id_str,
        "plan": plan,
        "plan_digest": plan_digest,
        "execution": exec_result,
    }

@router.get("/{case_id}", response_model=Dict[str, Any])
def get_dossier(
    case_id: UUID,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> Dict[str, Any]:
    """Retrieve dossier case details and canonical digest."""
    tenant_id, _ = identity
    case_id_str = str(case_id)
    case = CASES_DB.get(tenant_id, {}).get(case_id_str)
    if not case:
        raise HTTPException(status_code=404, detail=f"Dossier case '{case_id_str}' not found.")

    return {
        "case": case.model_dump(mode="json"),
        "case_digest": compute_data_sha256(case),
    }
