"""
Workflow v0.4.0 Router for FortifiedReg Fleet.
Exposes Session Lifecycle, Formulation Draft with Revision Invalidation,
Two-tier 5-Format Import Preview, Proposal Submission Gate, Manager Decisions,
and Approved Product Record Export Bundle.
Single-instance demo-grade security and governance hardening.
"""
import base64
import hashlib
import json
import logging
import re
import threading
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from fleet_adapter_prodocux.document_preflight import (
    DocumentPreflightError,
    MAX_BASE64_LENGTH,
    validate_document_preflight,
)
from fleet_api.deps import (
    FLEET_ENV,
    get_approval_store,
    get_approval_workflow_service,
    get_artifact_store,
    get_audit_log,
    get_checkpoint_store,
    get_orchestrator,
    get_resume_context_store,
    intake_adapter,
    orchestrator,
)
from fleet_api.security import (
    get_current_actor_and_tenant,
    get_optional_tenant_and_actor,
    get_tenant_and_actor,
    require_acting_role,
    require_formulator,
    require_product_manager,
)
from fleet_api.session_security import (
    execute_session_reset_saga,
    issue_demo_session,
    revoke_demo_session,
    set_acting_role,
    validate_session,
)
from fleet_domain_cosmetics.inci_verifier import evaluate_inci_compliance
from fleet_domain_cosmetics.mos_calculator import evaluate_toxicology_mos
from fleet_domain_cosmetics.normalizer import (
    NormalizedIngredientCandidate,
    normalize_content_blocks,
)
from fleet_domain_cosmetics.export_spec_mapper import (
    DraftRenderSpec,
    map_approved_product_to_render_bundle,
    map_bundle_to_prodocux_render_requests,
    map_draft_to_render_bundle,
)
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    ApprovalRequestStatusEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    FleetExecutionStatus,
    PDXApprovalDecision,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import (
    AuditEvent,
    AuditEventTypeEnum,
    GOVERNANCE_AUDIT_NAMESPACE,
)
from fleet_governance_core.models.case import ExposureScenario, FormulaItem
from fleet_governance_core.models.execution_context import ExecutionContextRecord, PlanSummary
from fleet_governance_core.models.hashing import canonical_json_dumps, compute_data_sha256
from fleet_governance_core.models.storage import ArtifactStorageIdentity, PutArtifactStatus
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum
from fleet_governance_core.models.workflow_v4 import (
    ActingRoleEnum,
    ApprovedProductRecord,
    ContentBlockItem,
    DemoSession,
    FormulationDraft,
    FormulationStatusEnum,
    GateDecisionEnum,
    GovernanceInvalidationRecord,
    ProDocuXContentBlocksContract,
    ProductProposal,
    ProposalStatusEnum,
)

router = APIRouter(prefix="/v1", tags=["Workflow v0.4.0"])

# Ephemeral in-memory store for session, draft, proposal, and approved product states
_GOVERNANCE_LOCK = threading.Lock()
_GOVERNANCE_INVALIDATION_RECORDS: Dict[str, GovernanceInvalidationRecord] = {}

_DRAFTS_STORE: Dict[str, FormulationDraft] = {}
_PRODUCT_DRAFTS_STORE: Dict[str, Dict[str, FormulationDraft]] = {}  # session_id/sub -> { product_name: FormulationDraft }
_REVISION_HISTORY_STORE: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}  # session_id/sub -> { product_name: [snapshots] }
_PROPOSALS_STORE: Dict[str, ProductProposal] = {}
_APPROVED_PRODUCTS_STORE: Dict[str, ApprovedProductRecord] = {}

RENDER_FORMAT_ALLOWLIST = {
    "pdf": {"mime": "application/pdf", "magic": b"%PDF-", "max_bytes": 8 * 1024 * 1024},
    "docx": {"mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "magic": b"PK\x03\x04", "max_bytes": 5 * 1024 * 1024},
    "xlsx": {"mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "magic": b"PK\x03\x04", "max_bytes": 5 * 1024 * 1024},
    "pptx": {"mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "magic": b"PK\x03\x04", "max_bytes": 8 * 1024 * 1024},
    "csv": {"mime": "text/csv", "magic": None, "max_bytes": 2 * 1024 * 1024},
}


def _initialize_presets_for_session(session_id: str, sub: str) -> None:
    """Populates baseline preset products for a fresh session."""
    _PRODUCT_DRAFTS_STORE[session_id] = {}
    _PRODUCT_DRAFTS_STORE[sub] = _PRODUCT_DRAFTS_STORE[session_id]
    _REVISION_HISTORY_STORE[session_id] = {}
    _REVISION_HISTORY_STORE[sub] = _REVISION_HISTORY_STORE[session_id]

    now_iso = datetime.now(timezone.utc).isoformat()
    default_presets = [
        (
            "Retinol Night Renewal Serum",
            [
                FormulaItem(inci_name="Aqua", concentration_pct=78.5, cas_number="7732-18-5"),
                FormulaItem(inci_name="Glycerin", concentration_pct=5.0, cas_number="56-81-5", noael_mg_kg_day=1000.0),
                FormulaItem(inci_name="Retinol", concentration_pct=0.05, cas_number="68-26-8", noael_mg_kg_day=2.0),
                FormulaItem(inci_name="Phenoxyethanol", concentration_pct=0.8, cas_number="122-99-6", noael_mg_kg_day=500.0),
            ]
        ),
        (
            "Active Peptide Eye Cream",
            [
                FormulaItem(inci_name="Aqua", concentration_pct=95.0, cas_number="7732-18-5"),
                FormulaItem(inci_name="Palmitoyl Tripeptide-38", concentration_pct=2.0, cas_number="1447824-23-8"),
                FormulaItem(inci_name="Phenoxyethanol", concentration_pct=0.5, cas_number="122-99-6", noael_mg_kg_day=500.0),
            ]
        ),
        (
            "Compliant Day Cream",
            [
                FormulaItem(inci_name="Aqua", concentration_pct=90.0, cas_number="7732-18-5"),
                FormulaItem(inci_name="Glycerin", concentration_pct=5.0, cas_number="56-81-5", noael_mg_kg_day=1000.0),
                FormulaItem(inci_name="Tocopherol", concentration_pct=0.5, cas_number="59-02-9", noael_mg_kg_day=500.0),
                FormulaItem(inci_name="Phenoxyethanol", concentration_pct=0.7, cas_number="122-99-6", noael_mg_kg_day=500.0),
            ]
        ),
        (
            "Excess Preservative Cream",
            [
                FormulaItem(inci_name="Aqua", concentration_pct=90.0, cas_number="7732-18-5"),
                FormulaItem(inci_name="Phenoxyethanol", concentration_pct=2.5, cas_number="122-99-6", noael_mg_kg_day=500.0),
            ]
        ),
        (
            "Mercury Bleaching Cream",
            [
                FormulaItem(inci_name="Aqua", concentration_pct=88.0, cas_number="7732-18-5"),
                FormulaItem(inci_name="Mercury", concentration_pct=2.0, cas_number="7439-97-6", noael_mg_kg_day=0.01),
            ]
        ),
    ]

    for p_name, p_ings in default_presets:
        p_draft = FormulationDraft(
            draft_id=f"draft-{session_id}-{uuid.uuid4().hex[:4]}",
            session_id=session_id,
            product_name=p_name,
            revision=1,
            ingredients=p_ings,
        )
        p_draft.compute_case_digest()
        _PRODUCT_DRAFTS_STORE[session_id][p_name] = p_draft
        _REVISION_HISTORY_STORE[session_id][p_name] = [
            {
                "revision": 1,
                "timestamp": now_iso,
                "case_digest": p_draft.case_digest,
                "ingredients_count": len(p_ings),
                "ingredients": [i.model_dump(mode="json") for i in p_ings],
                "product_name": p_name,
                "note": "Preset baseline (Revision 1)",
            }
        ]

    init_draft = _PRODUCT_DRAFTS_STORE[session_id]["Retinol Night Renewal Serum"]
    _DRAFTS_STORE[session_id] = init_draft
    _DRAFTS_STORE[sub] = init_draft


def _cleanup_session_governance_state(tenant_id: str, session_id: str, sub: str) -> None:
    """Cancels all active proposals and checkpoints for a resetting session across session_id and sub."""
    checkpoint_store = get_checkpoint_store()
    keys_to_clean = {k for k in (session_id, sub) if k}
    for p_id, p in list(_PROPOSALS_STORE.items()):
        if p.session_id in keys_to_clean and p.status == ProposalStatusEnum.PENDING_REVIEW:
            if p.checkpoint_id:
                checkpoint_store.update_checkpoint_status(tenant_id, p.checkpoint_id, CheckpointStatusEnum.CANCELLED)
            p.status = ProposalStatusEnum.SUPERSEDED
            p.decided_at = datetime.now(timezone.utc).isoformat()

    # Clear drafts for both keys only after checkpoint cancellations succeed
    for key in keys_to_clean:
        _PRODUCT_DRAFTS_STORE.pop(key, None)
        _REVISION_HISTORY_STORE.pop(key, None)
        _DRAFTS_STORE.pop(key, None)


# ---------------------------------------------------------------------------
# 1. Session Management (Single Identity with Dual-Role Acting)
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    acting_role: Optional[ActingRoleEnum] = None
    persona: Optional[str] = None


class SwitchRoleRequest(BaseModel):
    acting_role: ActingRoleEnum


class SessionResponse(BaseModel):
    token: str
    access_token: str
    session_id: str
    sub: str
    tenant_id: str
    acting_role: ActingRoleEnum
    allowed_demo_roles: List[str]
    expires_at: str
    disclaimer: str = (
        "Demo Role Simulation: A single evaluator simulates Formulator and Manager. "
        "Single-instance demo-grade security and governance hardening."
    )


@router.post("/demo/session", response_model=SessionResponse)
async def create_demo_session(req: Optional[CreateSessionRequest] = None) -> SessionResponse:
    """Issue a 120-minute demo session token with dual-role acting simulation."""
    if req and req.acting_role:
        acting_role = req.acting_role
    elif req and req.persona:
        if req.persona in ("product_manager", "cso", "safety_assessor"):
            acting_role = ActingRoleEnum.PRODUCT_MANAGER
        else:
            acting_role = ActingRoleEnum.FORMULATOR
    else:
        acting_role = ActingRoleEnum.FORMULATOR

    token, session_obj = issue_demo_session(acting_role=acting_role, ttl_minutes=120)
    _initialize_presets_for_session(session_obj.session_id, session_obj.sub)

    return SessionResponse(
        token=token,
        access_token=token,
        session_id=session_obj.session_id,
        sub=session_obj.sub,
        tenant_id=session_obj.tenant_id,
        acting_role=session_obj.acting_role,
        allowed_demo_roles=session_obj.allowed_demo_roles,
        expires_at=session_obj.expires_at,
    )


@router.post("/demo/session/restart", response_model=SessionResponse)
async def restart_demo_session(
    request: Request,
    req: Optional[CreateSessionRequest] = None,
) -> SessionResponse:
    """
    Terminates existing session via recoverable reset saga, revoking prior JTIs and re-initializing baselines.
    """
    auth_hdr = request.headers.get("Authorization", "")
    if not auth_hdr or not auth_hdr.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header for session restart.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    new_token, new_session = execute_session_reset_saga(
        auth_hdr,
        cleanup_governance_fn=_cleanup_session_governance_state,
    )

    _initialize_presets_for_session(new_session.session_id, new_session.sub)

    return SessionResponse(
        token=new_token,
        access_token=new_token,
        session_id=new_session.session_id,
        sub=new_session.sub,
        tenant_id=new_session.tenant_id,
        acting_role=new_session.acting_role,
        allowed_demo_roles=new_session.allowed_demo_roles,
        expires_at=new_session.expires_at,
    )


@router.post("/demo/session/revoke", response_model=Dict[str, Any])
async def revoke_demo_session_endpoint(
    request: Request,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """Revokes caller's active session and cancels pending proposals without issuing orphan tokens."""
    auth_hdr = request.headers.get("Authorization", "")
    revoke_demo_session(auth_hdr, cleanup_governance_fn=_cleanup_session_governance_state)
    return {"status": "revoked", "message": "Session and all active tokens have been revoked."}


@router.post("/demo/session/role", response_model=Dict[str, Any])
async def switch_session_acting_role(
    req: SwitchRoleRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """Switch server-side acting role (formulator vs. product_manager)."""
    tenant_id, actor = auth_context
    session = set_acting_role(actor.sub, req.acting_role)
    return {"status": "role_switched", "acting_role": session.acting_role.value}


# ---------------------------------------------------------------------------
# 2. Formulation Management with Revision Invalidation & Version History
# ---------------------------------------------------------------------------

class UpdateDraftRequest(BaseModel):
    product_name: str
    ingredients: List[FormulaItem]
    exposure_scenario: Optional[ExposureScenario] = None
    acting_role: ActingRoleEnum = ActingRoleEnum.FORMULATOR


class RollbackDraftRequest(BaseModel):
    product_name: str
    target_revision: int


class RenderDraftExportRequest(BaseModel):
    format: str = Field(description="Render format: pdf, docx, csv, xlsx, pptx")
    product_name: Optional[str] = None
    ingredients: Optional[List[FormulaItem]] = None


def execute_governance_invalidation_saga(
    tenant_id: str,
    session_id: str,
    product_name: str,
    target_draft: FormulationDraft,
    idempotency_key: Optional[str] = None,
) -> FormulationDraft:
    """
    Executes a crash-safe, idempotent, fail-closed Governance Invalidation Saga:
    1. Records or resumes a GovernanceInvalidationRecord.
    2. Idempotently marks all matching PENDING_REVIEW proposals as SUPERSEDED.
    3. Idempotently cancels underlying PDX checkpoints (fail-closed, no swallowed errors).
    4. Idempotently invalidates resume contexts (fail-closed, no swallowed errors).
    5. Idempotently emits CHECKPOINT_INVALIDATED audit event with deterministic UUIDv5.
    6. Idempotently persists the target draft matching target_digest.
    7. Marks Saga as completed.
    """
    key = idempotency_key or f"inv-{session_id}-{product_name}-rev{target_draft.revision}"
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"

    with _GOVERNANCE_LOCK:
        existing_record = _GOVERNANCE_INVALIDATION_RECORDS.get(key)
        if existing_record:
            if existing_record.status == "completed":
                if existing_record.target_digest != target_draft.case_digest:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Conflict: Invalidation already completed with different target digest.",
                    )
                stored = _PRODUCT_DRAFTS_STORE.get(session_id, {}).get(product_name)
                if stored and stored.case_digest == target_draft.case_digest:
                    return stored
            elif existing_record.target_digest != target_draft.case_digest:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Conflict: Invalidation in progress for differing target digest.",
                )
            rec = existing_record
        else:
            current_draft = _PRODUCT_DRAFTS_STORE.get(session_id, {}).get(product_name)
            src_digest = current_draft.case_digest if current_draft else ""
            rec = GovernanceInvalidationRecord(
                invalidation_id=inv_id,
                idempotency_key=key,
                tenant_id=tenant_id,
                session_id=session_id,
                product_name=product_name,
                source_revision=target_draft.revision - 1,
                source_digest=src_digest,
                target_revision=target_draft.revision,
                target_digest=target_draft.case_digest,
                target_draft_payload=target_draft.model_dump(mode="json"),
                status="in_progress",
            )
            _GOVERNANCE_INVALIDATION_RECORDS[key] = rec

    # Always reconstruct target draft strictly from frozen payload
    frozen_target = FormulationDraft.model_validate(rec.target_draft_payload)

    checkpoint_store = get_checkpoint_store()
    resume_store = get_resume_context_store()
    audit_log = get_audit_log()

    try:
        # Step 1: Idempotently supersede matching proposals
        if not rec.step_proposals_superseded:
            for p_id, p in _PROPOSALS_STORE.items():
                if p.session_id == session_id and p.product_name == product_name and p.status == ProposalStatusEnum.PENDING_REVIEW:
                    p.status = ProposalStatusEnum.SUPERSEDED
                    p.decided_at = datetime.now(timezone.utc).isoformat()
            rec.step_proposals_superseded = True

        # Step 2: Idempotently cancel PDX checkpoints (FAIL-CLOSED: NO EXCEPTION SWALLOWING)
        if not rec.step_checkpoints_cancelled:
            for p_id, p in _PROPOSALS_STORE.items():
                if p.session_id == session_id and p.product_name == product_name and p.checkpoint_id:
                    checkpoint_store.update_checkpoint_status(tenant_id, p.checkpoint_id, CheckpointStatusEnum.CANCELLED)
            rec.step_checkpoints_cancelled = True

        # Step 3: Invalidate resume context (FAIL-CLOSED: NO EXCEPTION SWALLOWING)
        if not rec.step_resume_invalidated:
            for p_id, p in _PROPOSALS_STORE.items():
                if p.session_id == session_id and p.product_name == product_name and p.checkpoint_id:
                    resume_store.invalidate_context(tenant_id, p.checkpoint_id)
            rec.step_resume_invalidated = True

        # Step 4: Emit deterministic audit event (UUIDv5 deduplicated)
        if not rec.step_audit_emitted:
            deterministic_event_id = uuid.uuid5(
                GOVERNANCE_AUDIT_NAMESPACE,
                f"{tenant_id}:{rec.invalidation_id}:checkpoint-invalidated",
            )
            audit_log.append_audit_event(
                AuditEvent(
                    event_id=deterministic_event_id,
                    tenant_id=tenant_id,
                    run_id=session_id,
                    actor_id=session_id,
                    event_type=AuditEventTypeEnum.CHECKPOINT_INVALIDATED,
                    payload={
                        "action": "governance_invalidation_superseded",
                        "invalidation_id": rec.invalidation_id,
                        "product_name": product_name,
                        "target_revision": frozen_target.revision,
                        "target_digest": frozen_target.case_digest,
                    },
                )
            )
            rec.step_audit_emitted = True

        # Step 5: Idempotently persist target draft
        if not rec.step_draft_persisted:
            with _GOVERNANCE_LOCK:
                prod_store = _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})
                hist_store = _REVISION_HISTORY_STORE.setdefault(session_id, {})
                prod_store[product_name] = frozen_target
                _DRAFTS_STORE[session_id] = frozen_target
                hist_list = hist_store.setdefault(product_name, [])
                if not any(h.get("revision") == frozen_target.revision for h in hist_list):
                    hist_list.append({
                        "revision": frozen_target.revision,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "case_digest": frozen_target.case_digest,
                        "ingredients_count": len(frozen_target.ingredients),
                        "ingredients": [i.model_dump(mode="json") for i in frozen_target.ingredients],
                        "product_name": product_name,
                        "note": f"Revision {frozen_target.revision} (Saga Invalidation Verified)",
                    })
            rec.step_draft_persisted = True

        # Step 6: Mark completed
        rec.status = "completed"
        rec.completed_at = datetime.now(timezone.utc).isoformat()
        return frozen_target

    except HTTPException:
        raise
    except Exception as exc:
        rec.status = "failed"
        rec.error_message = "Governance invalidation interrupted"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Governance invalidation saga failed (fail-closed): Checkpoint or resume store operation failed.",
        )


@router.get("/formulations/draft", response_model=Dict[str, Any])
async def get_formulation_draft(
    product_name: Optional[str] = None,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """Retrieve current formulation draft and revision history for the active product/session."""
    tenant_id, actor = auth_context
    session_id = actor.sub

    prod_store = _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})
    hist_store = _REVISION_HISTORY_STORE.setdefault(session_id, {})

    if product_name:
        if product_name not in prod_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product draft '{product_name}' not found in active session.",
            )
        draft = prod_store[product_name]
    else:
        draft = _DRAFTS_STORE.get(session_id)

    if not draft:
        draft = FormulationDraft(
            draft_id=f"draft-{session_id}",
            session_id=session_id,
            product_name="Retinol Night Renewal Serum",
            revision=1,
            ingredients=[
                FormulaItem(inci_name="Aqua", concentration_pct=78.5, cas_number="7732-18-5"),
                FormulaItem(inci_name="Glycerin", concentration_pct=5.0, cas_number="56-81-5", noael_mg_kg_day=1000.0),
                FormulaItem(inci_name="Retinol", concentration_pct=0.05, cas_number="68-26-8", noael_mg_kg_day=2.0),
                FormulaItem(inci_name="Phenoxyethanol", concentration_pct=0.8, cas_number="122-99-6", noael_mg_kg_day=500.0),
            ],
        )
        draft.compute_case_digest()
        _DRAFTS_STORE[session_id] = draft
        prod_store[draft.product_name] = draft
        hist_store[draft.product_name] = [
            {
                "revision": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "case_digest": draft.case_digest,
                "ingredients_count": len(draft.ingredients),
                "ingredients": [i.model_dump(mode="json") for i in draft.ingredients],
                "product_name": draft.product_name,
                "note": "Initial revision",
            }
        ]

    _DRAFTS_STORE[session_id] = draft

    # Evaluate SCCS real-time status for draft
    sccs_res = evaluate_toxicology_mos(draft.ingredients, draft.exposure_scenario)
    inci_res = evaluate_inci_compliance(draft.ingredients)

    returned_proposal = next(
        (p for p in reversed(list(_PROPOSALS_STORE.values())) if p.session_id == session_id and p.status == ProposalStatusEnum.RETURNED and p.product_name == draft.product_name),
        None,
    )

    history_list = hist_store.get(draft.product_name, [])

    return {
        "draft": draft.model_dump(mode="json"),
        "sccs_evaluation": sccs_res.model_dump(mode="json"),
        "inci_evaluation": inci_res.model_dump(mode="json"),
        "returned_proposal": returned_proposal.model_dump(mode="json") if returned_proposal else None,
        "history": history_list,
    }


@router.post("/formulations/draft", response_model=Dict[str, Any])
async def update_formulation_draft(
    req: UpdateDraftRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_formulator),
) -> Dict[str, Any]:
    """
    Update formulation ingredients or exposure scenario for specific product.
    Increments per-product revision += 1, invalidates previous checkpoints via Saga.
    """
    tenant_id, actor = auth_context
    session_id = actor.sub

    if len(req.ingredients) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formulation exceeds maximum allowed limit of 50 ingredients (got {len(req.ingredients)}).",
        )

    prod_store = _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})
    existing_for_prod = prod_store.get(req.product_name) or _DRAFTS_STORE.get(session_id)
    new_rev = (existing_for_prod.revision + 1) if existing_for_prod else 1

    default_scenario = ExposureScenario(
        product_type="face_serum",
        daily_applied_amount_g=0.8,
        retention_factor=1.0,
        body_weight_kg=60.0,
    )
    exp_scen = req.exposure_scenario or (existing_for_prod.exposure_scenario if existing_for_prod else default_scenario)

    target_draft = FormulationDraft(
        draft_id=f"draft-{session_id}-{uuid.uuid4().hex[:4]}",
        session_id=session_id,
        product_name=req.product_name,
        revision=new_rev,
        ingredients=req.ingredients,
        exposure_scenario=exp_scen,
        status=FormulationStatusEnum.DRAFT,
        latest_verifier_result=None,
    )
    target_draft.compute_case_digest()

    # Execute atomic-style Invalidation Saga
    saved_draft = execute_governance_invalidation_saga(
        tenant_id=tenant_id,
        session_id=session_id,
        product_name=req.product_name,
        target_draft=target_draft,
    )

    sccs_res = evaluate_toxicology_mos(saved_draft.ingredients, saved_draft.exposure_scenario)
    inci_res = evaluate_inci_compliance(saved_draft.ingredients)
    hist_list = _REVISION_HISTORY_STORE.get(session_id, {}).get(req.product_name, [])

    return {
        "status": "updated",
        "revision": saved_draft.revision,
        "case_digest": saved_draft.case_digest,
        "draft": saved_draft.model_dump(mode="json"),
        "sccs_evaluation": sccs_res.model_dump(mode="json"),
        "inci_evaluation": inci_res.model_dump(mode="json"),
        "history": hist_list,
    }


@router.post("/formulations/rollback", response_model=Dict[str, Any])
async def rollback_formulation_draft(
    req: RollbackDraftRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_formulator),
) -> Dict[str, Any]:
    """Reverts the draft for a product to a specific historical revision via Saga invalidation."""
    tenant_id, actor = auth_context
    session_id = actor.sub

    prod_store = _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})
    hist_store = _REVISION_HISTORY_STORE.setdefault(session_id, {})
    history = hist_store.get(req.product_name, [])

    target_snapshot = next((s for s in history if s["revision"] == req.target_revision), None)
    if not target_snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historical revision {req.target_revision} for product '{req.product_name}' not found.",
        )

    cur_draft = prod_store.get(req.product_name)
    new_rev = (cur_draft.revision + 1) if cur_draft else (req.target_revision + 1)
    restored_items = [FormulaItem.model_validate(item) for item in target_snapshot["ingredients"]]

    target_draft = FormulationDraft(
        draft_id=f"draft-{session_id}-{uuid.uuid4().hex[:4]}",
        session_id=session_id,
        product_name=req.product_name,
        revision=new_rev,
        ingredients=restored_items,
        exposure_scenario=cur_draft.exposure_scenario if cur_draft else ExposureScenario(
            product_type="face_serum",
            daily_applied_amount_g=0.8,
            retention_factor=1.0,
            body_weight_kg=60.0,
        ),
        status=FormulationStatusEnum.DRAFT,
    )
    target_draft.compute_case_digest()

    saved_draft = execute_governance_invalidation_saga(
        tenant_id=tenant_id,
        session_id=session_id,
        product_name=req.product_name,
        target_draft=target_draft,
    )

    sccs_res = evaluate_toxicology_mos(saved_draft.ingredients, saved_draft.exposure_scenario)
    inci_res = evaluate_inci_compliance(saved_draft.ingredients)
    hist_list = _REVISION_HISTORY_STORE.get(session_id, {}).get(req.product_name, [])

    return {
        "status": "rolled_back",
        "restored_from_revision": req.target_revision,
        "new_revision": saved_draft.revision,
        "draft": saved_draft.model_dump(mode="json"),
        "sccs_evaluation": sccs_res.model_dump(mode="json"),
        "inci_evaluation": inci_res.model_dump(mode="json"),
        "history": hist_list,
    }


@router.post("/formulations/render-export", response_model=Dict[str, Any])
async def render_formulation_export(
    req: RenderDraftExportRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """
    Live ProDocuX Multi-Format Renderer for Active Formulation Draft.
    Strictly uses DraftRenderSpec to ensure visible watermarks and neutral claims.
    """
    tenant_id, actor = auth_context
    session_id = actor.sub

    prod_store = _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})
    if req.product_name:
        if req.product_name not in prod_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product draft '{req.product_name}' not found in active session workspace.",
            )
        draft = prod_store[req.product_name]
    else:
        draft = _DRAFTS_STORE.get(session_id)
        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active draft found in session.",
            )

    fmt = req.format.lower().lstrip(".")
    if fmt not in RENDER_FORMAT_ALLOWLIST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Available: {list(RENDER_FORMAT_ALLOWLIST.keys())}",
        )

    ingredients_to_use = req.ingredients or draft.ingredients
    ingredients_list = [i.model_dump(mode="json") for i in ingredients_to_use]
    sccs_res = evaluate_toxicology_mos(ingredients_to_use, draft.exposure_scenario)
    sccs_summary = sccs_res.model_dump(mode="json")

    # Construct clean DraftRenderSpec (strictly excludes approved_by and compliance certificates)
    draft_spec = DraftRenderSpec(
        document_status="draft",
        approval_status="pending_review" if draft.status == FormulationStatusEnum.PROPOSAL_PENDING_REVIEW else "not_submitted",
        product_name=req.product_name or draft.product_name,
        revision=draft.revision,
        case_digest=draft.case_digest,
        watermark="DRAFT WORKING COPY — NOT APPROVED — NOT A COMPLIANCE CERTIFICATE",
        generated_at=datetime.now(timezone.utc).isoformat(),
        ingredients=ingredients_list,
        sccs_summary=sccs_summary,
    )

    bundle_spec = map_draft_to_render_bundle(draft_spec)
    prodocux_requests = map_bundle_to_prodocux_render_requests(bundle_spec)

    render_req = prodocux_requests.get(fmt)
    if not render_req:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Available: {list(prodocux_requests.keys())}",
        )

    # Invoke ProDocuX Live Kernel
    render_res = intake_adapter.render_artifact(render_req)

    content_b64 = render_res.get("content_b64")
    claimed_sha = render_res.get("sha256")
    size_bytes = render_res.get("size_bytes")

    if not content_b64 or not claimed_sha or size_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: Missing mandatory delivery fields.",
        )

    try:
        raw_out = base64.b64decode(content_b64, validate=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: Invalid strict base64 payload.",
        )

    allow_spec = RENDER_FORMAT_ALLOWLIST[fmt]
    if len(raw_out) == 0 or len(raw_out) > allow_spec["max_bytes"] or len(raw_out) != size_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: Output size out of bounds.",
        )

    computed_sha = hashlib.sha256(raw_out).hexdigest()
    if computed_sha != claimed_sha:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: SHA-256 fingerprint mismatch.",
        )

    if allow_spec["magic"] and not raw_out.startswith(allow_spec["magic"]):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: Invalid magic signature for output format.",
        )

    claimed_mime = render_res.get("media_type") or render_res.get("mime")
    if not claimed_mime or claimed_mime.lower().split(";")[0].strip() != allow_spec["mime"].lower():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ProDocuX render integrity failure: Mismatched or missing MIME type in output.",
        )

    if fmt == "csv":
        if b"\x00" in raw_out:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="ProDocuX render integrity failure: Prohibited NUL bytes in CSV output.",
            )
        try:
            raw_out.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="ProDocuX render integrity failure: Non-UTF-8 encoding in CSV output.",
            )

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", req.product_name or draft.product_name).lower()
    fn = f"draft_{clean_name}_rev{draft.revision}.{fmt}"

    return {
        "status": "rendered",
        "format": fmt,
        "filename": fn,
        "media_type": allow_spec["mime"],
        "content_b64": content_b64,
        "sha256": claimed_sha,
        "size_bytes": size_bytes,
        "render_engine": "ProDocuX Live Kernel v0.3.0",
    }


# ---------------------------------------------------------------------------
# 3. Two-Tier 5-Format Semantic Import Preview
# ---------------------------------------------------------------------------

class ParsePreviewRequest(BaseModel):
    scenario_key: Optional[str] = None  # retinol, peptide, day_cream, phenoxy_excess, mercury
    content_blocks_contract: Optional[ProDocuXContentBlocksContract] = None
    filename: Optional[str] = None
    content_b64: Optional[str] = None


@router.post("/formulations/parse-preview", response_model=Dict[str, Any])
async def parse_import_preview(
    req: ParsePreviewRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_formulator),
) -> Dict[str, Any]:
    """
    Two-tier import parser: ProDocuX content blocks -> Fleet Cosmetics Normalizer.
    Returns normalized candidate ingredients with confidence and source locations for confirmation.
    Protected by mandatory Formulator session authentication, strict base64 decoding, and adapter-level container preflight.
    """
    tenant_id, actor = auth_context

    if req.content_b64 and req.filename:
        if len(req.content_b64) > MAX_BASE64_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Base64 payload length ({len(req.content_b64)} chars) exceeds maximum allowed {MAX_BASE64_LENGTH} chars.",
            )

        try:
            raw_bytes = base64.b64decode(req.content_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid strict base64 payload.")

        fmt = (req.filename.split(".")[-1]).lower() if "." in req.filename else "unknown"
        try:
            validate_document_preflight(fmt, raw_bytes, req.filename)
        except DocumentPreflightError:
            logger.warning(
                "document_preflight_failed format=%s error_code=%s",
                fmt,
                "DOCUMENT_PREFLIGHT_REJECTED",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document preflight validation failed.",
            )

        extracted = intake_adapter.extract_content_blocks(req.filename, raw_bytes)
        candidates = normalize_content_blocks(extracted)
        doc_id = extracted.get("document_id") or f"doc-{req.filename}"
        doc_sha = extracted.get("source_sha256") or compute_data_sha256(raw_bytes)

        # Audit parse event
        get_audit_log().append_audit_event(
            AuditEvent(
                tenant_id=tenant_id,
                run_id=actor.sub,
                actor_id=actor.sub,
                event_type=AuditEventTypeEnum.INTAKE_EXTRACTED,
                payload={
                    "action": "document_parse_preview",
                    "filename": req.filename,
                    "format": fmt,
                    "source_sha256": doc_sha,
                    "candidates_count": len(candidates),
                },
            )
        )

        return {
            "status": "preview_ready",
            "document_id": doc_id,
            "format": fmt,
            "source_sha256": doc_sha,
            "candidates_count": len(candidates),
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "raw_blocks": extracted.get("blocks", []),
        }

    # 5 Preset G1 Synthetic Content Block Scenarios
    scenario_blocks_map = {
        "retinol": ProDocuXContentBlocksContract(
            document_id="doc-sds-retinol",
            source_sha256="54014b35a9dbbc8b742570250f89fc60736bfa3df7f1b6a84f3004aeae361837",
            format="pdf",
            blocks=[
                ContentBlockItem(block_id="b1", block_type="table_cell", text="Aqua: 78.5%", source_locator="Page 1, Section 3.2, Row 1", confidence=0.99),
                ContentBlockItem(block_id="b2", block_type="table_cell", text="Glycerin: 5.0%", source_locator="Page 1, Section 3.2, Row 2", confidence=0.98),
                ContentBlockItem(block_id="b3", block_type="table_cell", text="Retinol: 0.05%", source_locator="Page 1, Section 3.2, Row 3", confidence=0.98),
                ContentBlockItem(block_id="b4", block_type="table_cell", text="Phenoxyethanol: 0.8%", source_locator="Page 1, Section 3.2, Row 4", confidence=0.97),
            ],
        ),
        "peptide": ProDocuXContentBlocksContract(
            document_id="doc-coa-peptide",
            source_sha256="e0b82ec354ff14df9ffecda2d6c1b3f9ffbcda2d6c1b3f9ffbcda2d6c1b3f9ff",
            format="docx",
            blocks=[
                ContentBlockItem(block_id="b1", block_type="paragraph", text="Aqua: 95.0%", source_locator="Section 2.1, Paragraph 3", confidence=0.98),
                ContentBlockItem(block_id="b2", block_type="paragraph", text="Palmitoyl Tripeptide-38: 2.0%", source_locator="Section 2.1, Paragraph 4", confidence=0.95),
                ContentBlockItem(block_id="b3", block_type="paragraph", text="Phenoxyethanol: 0.5%", source_locator="Section 2.1, Paragraph 5", confidence=0.96),
            ],
        ),
        "day_cream": ProDocuXContentBlocksContract(
            document_id="doc-csv-daycream",
            source_sha256="3829adba69c23458cb2589d8450246fe9b16424fc8acd2ba69c23458cb2589d8",
            format="csv",
            blocks=[
                ContentBlockItem(block_id="b1", block_type="table_cell", text="Aqua: 90.0%", source_locator="Row 2, Column 2", confidence=1.0),
                ContentBlockItem(block_id="b2", block_type="table_cell", text="Glycerin: 5.0%", source_locator="Row 3, Column 2", confidence=1.0),
                ContentBlockItem(block_id="b3", block_type="table_cell", text="Tocopherol: 0.5%", source_locator="Row 4, Column 2", confidence=0.99),
                ContentBlockItem(block_id="b4", block_type="table_cell", text="Phenoxyethanol: 0.7%", source_locator="Row 5, Column 2", confidence=0.99),
            ],
        ),
        "phenoxy_excess": ProDocuXContentBlocksContract(
            document_id="doc-xlsx-phenoxy",
            source_sha256="61cff57ec7938165234dd895177dccade7ac1a5f61cff57ec7938165234dd895",
            format="xlsx",
            blocks=[
                ContentBlockItem(block_id="b1", block_type="table_cell", text="Aqua: 90.0%", source_locator="Sheet1!B2", confidence=0.99),
                ContentBlockItem(block_id="b2", block_type="table_cell", text="Phenoxyethanol: 2.5%", source_locator="Sheet1!B3", confidence=0.98),
            ],
        ),
        "mercury": ProDocuXContentBlocksContract(
            document_id="doc-pptx-mercury",
            source_sha256="7439976743997674399767439976743997674399767439976743997674399767",
            format="pptx",
            blocks=[
                ContentBlockItem(block_id="b1", block_type="slide_text", text="Aqua: 88.0%", source_locator="Slide 3, Bullet 1", confidence=0.95),
                ContentBlockItem(block_id="b2", block_type="slide_text", text="Mercury: 2.0%", source_locator="Slide 3, Bullet 2", confidence=0.95),
            ],
        ),
    }

    contract = req.content_blocks_contract
    if not contract:
        key = req.scenario_key or "retinol"
        contract = scenario_blocks_map.get(key, scenario_blocks_map["retinol"])

    candidates = normalize_content_blocks(contract)

    return {
        "status": "preview_ready",
        "document_id": contract.document_id,
        "format": contract.format,
        "source_sha256": contract.source_sha256,
        "candidates_count": len(candidates),
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "raw_blocks": [b.model_dump(mode="json") for b in contract.blocks],
    }


# ---------------------------------------------------------------------------
# 4. Formal Gate Submission & Product Proposal
# ---------------------------------------------------------------------------

@router.post("/formulations/submit-proposal", response_model=Dict[str, Any])
async def submit_product_proposal(
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_formulator),
) -> Dict[str, Any]:
    """
    Formulator submits formulation draft to formal regulatory gate.
    - Blocks hard regulatory violations (Annex II prohibited / severe safety hazard).
    - If PASS or REVIEW: compiles PDX execution plan and creates ProductProposal.
    """
    tenant_id, actor = auth_context
    session_id = actor.sub
    draft = _DRAFTS_STORE.get(session_id)
    if not draft or not draft.ingredients:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Draft has no ingredients.")

    # 1. Run deterministic verifiers
    inci_res = evaluate_inci_compliance(draft.ingredients)
    sccs_res = evaluate_toxicology_mos(draft.ingredients, draft.exposure_scenario)

    gate_decision = GateDecisionEnum.PASS
    reasons = []

    if inci_res.status == VerifierStatusEnum.FAIL:
        gate_decision = GateDecisionEnum.FAIL
        reasons.append(f"INCI Violation: {inci_res.details.get('violation') or ', '.join(inci_res.reason_codes)}")
    elif sccs_res.status == VerifierStatusEnum.FAIL:
        gate_decision = GateDecisionEnum.FAIL
        reasons.append(f"Toxicology Safety Violation: {sccs_res.details.get('violation') or ', '.join(sccs_res.reason_codes)}")
    elif inci_res.status == VerifierStatusEnum.REVIEW or sccs_res.status == VerifierStatusEnum.REVIEW:
        gate_decision = GateDecisionEnum.REVIEW
        if sccs_res.status == VerifierStatusEnum.REVIEW:
            reasons.append(f"Toxicology Review Needed: {sccs_res.details.get('missing_studies') or ', '.join(sccs_res.reason_codes)}")
        if inci_res.status == VerifierStatusEnum.REVIEW:
            reasons.append(f"INCI Review Needed: {inci_res.details.get('review_needed') or ', '.join(inci_res.reason_codes)}")

    if gate_decision == GateDecisionEnum.FAIL:
        draft.status = FormulationStatusEnum.BLOCKED
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "FORMULATION_GATE_REJECTED",
                "gate_decision": gate_decision.value,
                "reasons": reasons,
                "message": "Formulation violates EU cosmetics safety criteria. Submission blocked.",
            },
        )

    # 2. Compile PDX Execution Plan with Human Gate Checkpoint
    proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
    case_payload = {
        "case_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "product_name": draft.product_name,
        "jurisdiction": "EU",
        "formula": [item.model_dump(mode="json") for item in draft.ingredients],
        "exposure_scenario": draft.exposure_scenario.model_dump(mode="json"),
        "supplier_documents": [],
    }

    checkpoint_store = get_checkpoint_store()
    resume_context_store = get_resume_context_store()

    # Step-by-step orchestrator execution up to Human Gate
    orchestrator_inst = get_orchestrator()
    if hasattr(orchestrator_inst, "compile_execution_plan"):
        plan = orchestrator_inst.compile_execution_plan(case_payload)
    else:
        plan = {}

    if hasattr(orchestrator_inst, "execute_plan"):
        pdx_exec_res = orchestrator_inst.execute_plan(plan, case_payload)
    elif hasattr(orchestrator_inst, "compile_and_run"):
        pdx_exec_res = orchestrator_inst.compile_and_run(case_payload)
        plan = pdx_exec_res.get("plan", plan)
    else:
        pdx_exec_res = {}

    if pdx_exec_res.get("status") in ("suspended_at_checkpoint", "awaiting_approval") and "checkpoint" in pdx_exec_res:
        raw_chk = pdx_exec_res["checkpoint"]
        checkpoint = PDXWorkflowCheckpoint.model_validate(raw_chk)
        checkpoint_id = checkpoint.checkpoint_id
        case_digest = checkpoint.subject_digest
        plan_digest = checkpoint.plan_digest
        checkpoint_store.save_checkpoint(tenant_id, checkpoint)

        raw_req = pdx_exec_res.get("approval_request")
        if not raw_req:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDX execution suspended at checkpoint but missing required approval_request.",
            )
        approval_req = PDXApprovalRequest.model_validate(raw_req)
        req_uuid_str = str(approval_req.approval_request_id)
        checkpoint_store.save_approval_request(tenant_id, approval_req)

    elif FLEET_ENV == "demo":
        checkpoint_id = f"chk-{session_id}-{proposal_id}"
        case_digest = compute_data_sha256(case_payload)
        plan_digest = compute_data_sha256(plan)
        evidence_digests = {
            "sccs_evaluation.json": compute_data_sha256(sccs_res.model_dump(mode="json")),
            "inci_evaluation.json": compute_data_sha256(inci_res.model_dump(mode="json")),
        }
        checkpoint = PDXWorkflowCheckpoint(
            checkpoint_id=checkpoint_id,
            run_id=session_id,
            subject_digest=case_digest,
            plan_digest=plan_digest,
            completed_step_ids=["step_verify_inci_compliance", "step_verify_toxicology_mos"],
            pending_step_ids=["step_human_regulatory_approval", "step_assemble_pif_manifest"],
            evidence_digests=evidence_digests,
            status=CheckpointStatusEnum.PENDING,
        )
        checkpoint_store.save_checkpoint(tenant_id, checkpoint)
        req_uuid = uuid.uuid4()
        req_uuid_str = str(req_uuid)
        approval_req = PDXApprovalRequest(
            approval_request_id=req_uuid,
            checkpoint_id=checkpoint_id,
            required_role="product_manager",
            summary=f"Human regulatory compliance review and toxicological rationale sign-off required for {draft.product_name} (Status: REVIEW).",
            status=ApprovalRequestStatusEnum.PENDING,
        )
        checkpoint_store.save_approval_request(tenant_id, approval_req)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDX execution did not reach a pending regulatory approval checkpoint and approval request.",
        )

    # Save resume context in store for LivePDXCoreOrchestrator and lease management
    if resume_context_store:
        plan_ident = ArtifactStorageIdentity(
            uri=f"artifact://{tenant_id}/plans/{session_id}.json",
            sha256=plan_digest,
            size_bytes=64,
            media_type="application/json",
        )
        case_ident = ArtifactStorageIdentity(
            uri=f"artifact://{tenant_id}/cases/{session_id}.json",
            sha256=case_digest,
            size_bytes=64,
            media_type="application/json",
        )
        ctx_record = ExecutionContextRecord(
            tenant_id=tenant_id,
            run_id=session_id,
            checkpoint_id=checkpoint_id,
            case_digest=case_digest,
            case_storage_identity=case_ident,
            plan_digest=plan_digest,
            plan_storage_identity=plan_ident,
            plan_summary=PlanSummary(
                request_id=f"req-plan-{proposal_id}",
                schema_version="pdx_execution_plan_v1",
                step_count=len(plan.get("steps", [])),
                step_ids=[s.get("id", "") for s in plan.get("steps", [])],
                has_approval_step=True,
                product_name=draft.product_name,
                jurisdiction="EU",
            ),
            approval_request=approval_req,
            evidence_digests=checkpoint.evidence_digests,
        )
        resume_context_store.save_context(ctx_record)

    # Create Proposal Record
    proposal = ProductProposal(
        proposal_id=proposal_id,
        tenant_id=tenant_id,
        session_id=session_id,
        draft_id=draft.draft_id,
        revision=draft.revision,
        product_name=draft.product_name,
        case_digest=case_digest,
        plan_digest=plan_digest,
        checkpoint_id=checkpoint_id,
        approval_request_id=req_uuid_str,
        gate_decision=gate_decision,
        gate_reasons=reasons,
        ingredients_summary=[item.model_dump(mode="json") for item in draft.ingredients],
        sccs_evaluation_summary=sccs_res.model_dump(mode="json"),
        status=ProposalStatusEnum.PENDING_REVIEW,
    )
    draft.case_digest = case_digest
    _PRODUCT_DRAFTS_STORE.setdefault(session_id, {})[draft.product_name] = draft
    _DRAFTS_STORE[session_id] = draft
    _PROPOSALS_STORE[proposal_id] = proposal
    draft.status = FormulationStatusEnum.PROPOSAL_PENDING_REVIEW

    # Audit event
    get_audit_log().append_audit_event(
        AuditEvent(
            tenant_id=tenant_id,
            run_id=session_id,
            actor_id=actor.sub,
            event_type=AuditEventTypeEnum.CHECKPOINT_CREATED,
            payload={
                "action": "proposal_submitted",
                "proposal_id": proposal_id,
                "revision": draft.revision,
                "gate_decision": gate_decision.value,
                "checkpoint_id": checkpoint_id,
                "approval_request_id": req_uuid_str,
            },
        )
    )

    return {
        "status": "proposal_created",
        "proposal_id": proposal_id,
        "gate_decision": gate_decision.value,
        "gate_reasons": reasons,
        "proposal": proposal.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# 5. Product Manager Proposal Inbox & Decisions
# ---------------------------------------------------------------------------

@router.get("/proposals/inbox", response_model=List[Dict[str, Any]])
async def list_proposals_inbox(
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_product_manager),
) -> List[Dict[str, Any]]:
    """List pending and historical proposals for Product Manager review."""
    tenant_id, _ = auth_context
    return [
        p.model_dump(mode="json")
        for p in reversed(list(_PROPOSALS_STORE.values()))
        if p.tenant_id == tenant_id
    ]


class ManagerDecisionRequest(BaseModel):
    decision: str  # approved or returned
    rationale: Optional[str] = None
    return_comments: Optional[str] = None


@router.post("/proposals/{proposal_id}/decide", response_model=Dict[str, Any])
async def manager_decide_proposal(
    proposal_id: str,
    req: ManagerDecisionRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(require_product_manager),
) -> Dict[str, Any]:
    """
    Product Manager decisions via formal ApprovalWorkflowService and Lease-Fenced PDX Orchestrator Resume:
    - 'approved': Validates 3-way digests, acquires resume lease, executes PDX resume, atomically publishes canonical PIF
                  to ArtifactStore with immutable approved_at, updates outbox/projections, and returns immutable ApprovedProductRecord.
    - 'returned': Returns proposal with comments to Formulator for Revision N+1, cancelling checkpoint and notifying PDX orchestrator.
    """
    tenant_id, actor = auth_context
    proposal = _PROPOSALS_STORE.get(proposal_id)
    if not proposal or proposal.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")

    # Idempotent return if already approved
    if proposal.status == ProposalStatusEnum.APPROVED:
        approved_rec = _APPROVED_PRODUCTS_STORE.get(proposal.product_name)
        if approved_rec:
            return approved_rec.model_dump(mode="json")

    # 6-Way Authoritative Binding Validation
    # 1. Proposal status must be PENDING_REVIEW (SUPERSEDED -> 409)
    if proposal.status != ProposalStatusEnum.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal is not pending review ({proposal.status.value}).",
        )

    # 2. Active Draft Check (draft_id, revision, case_digest must match active draft -> 412)
    active_draft = _PRODUCT_DRAFTS_STORE.get(proposal.session_id, {}).get(proposal.product_name) or _DRAFTS_STORE.get(proposal.session_id)
    if not active_draft:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Precondition Failed: Active draft for product '{proposal.product_name}' not found.",
        )
    if (
        proposal.draft_id != active_draft.draft_id
        or proposal.revision != active_draft.revision
        or proposal.case_digest != active_draft.case_digest
    ):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Proposal revision/digest does not match the active draft state.",
        )

    # 3. Mandatory Checkpoint and Approval Request presence check (missing -> 412)
    if not proposal.checkpoint_id or not proposal.approval_request_id:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Proposal missing mandatory approval_request_id or checkpoint_id binding.",
        )

    # 4. Checkpoint Store Record Check (status must be PENDING, digests must match -> 412)
    checkpoint_store = get_checkpoint_store()
    checkpoint = checkpoint_store.get_checkpoint(tenant_id, proposal.checkpoint_id)
    if not checkpoint:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Precondition Failed: PDX Checkpoint '{proposal.checkpoint_id}' not found.",
        )
    if checkpoint.status != CheckpointStatusEnum.PENDING:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Precondition Failed: Checkpoint status is '{checkpoint.status.value}', expected 'pending'.",
        )
    if checkpoint.subject_digest != proposal.case_digest or checkpoint.plan_digest != proposal.plan_digest:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Checkpoint digest binding mismatch with proposal.",
        )

    # 5. Approval Request Check (appr_req must exist and match approval_request_id -> 412)
    appr_req = checkpoint_store.get_approval_request(tenant_id, proposal.checkpoint_id)
    if not appr_req or str(appr_req.approval_request_id) != str(proposal.approval_request_id):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition Failed: Approval request binding mismatch.",
        )

    approval_service = get_approval_workflow_service()
    artifact_store = get_artifact_store()
    resume_store = get_resume_context_store()
    orchestrator_inst = get_orchestrator()

    if req.decision == "returned":
        # 1. Process decision through governance service
        appr_record, pdx_decision = approval_service.process_approval_decision(
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            approval_request_id=proposal.approval_request_id or "",
            actor=actor,
            decision=ApprovalDecisionEnum.REJECTED,
            idempotency_key=f"proposal-{proposal.proposal_id}-returned",
            case_digest=proposal.case_digest,
            plan_digest=proposal.plan_digest,
            evidence_digests=checkpoint.evidence_digests,
            reason=req.return_comments or "Returned by Product Manager for formula optimization.",
        )

        # 2. Update checkpoint in store to CANCELLED and notify orchestrator
        checkpoint_store.update_checkpoint_status(tenant_id, proposal.checkpoint_id, CheckpointStatusEnum.CANCELLED)
        try:
            orchestrator_inst.resume_with_decision(checkpoint, pdx_decision)
        except Exception:
            pass  # Rejection recorded in ledger and checkpoint

        proposal.status = ProposalStatusEnum.RETURNED
        proposal.return_comments = req.return_comments or "Returned by Product Manager for formula optimization."
        proposal.decided_at = datetime.now(timezone.utc).isoformat()

        # Unlock draft for editing
        draft = _DRAFTS_STORE.get(proposal.session_id)
        if draft:
            draft.status = FormulationStatusEnum.CHANGES_REQUIRED

        return {"status": "returned", "proposal": proposal.model_dump(mode="json")}

    elif req.decision == "approved":
        if proposal.gate_decision == GateDecisionEnum.REVIEW and not req.rationale:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager rationale is required when approving a proposal with REVIEW status.",
            )

        # 1. Process approval decision through governance service (verifies 3-way digest and idempotency)
        appr_record, pdx_decision = approval_service.process_approval_decision(
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            approval_request_id=proposal.approval_request_id or "",
            actor=actor,
            decision=ApprovalDecisionEnum.APPROVED,
            idempotency_key=f"proposal-{proposal.proposal_id}-approved",
            case_digest=proposal.case_digest,
            plan_digest=proposal.plan_digest,
            evidence_digests=checkpoint.evidence_digests,
            reason=req.rationale or "Approved by Product Manager.",
        )

        ctx = resume_store.get_context(tenant_id, proposal.checkpoint_id)

        # Crash recovery path: if context is already COMPLETED
        if ctx and ctx.status == FleetExecutionStatus.COMPLETED:
            approved_at_iso = appr_record.decided_at
            canonical_pif = {
                "tenant_id": tenant_id,
                "session_id": proposal.session_id,
                "proposal_id": proposal.proposal_id,
                "product_name": proposal.product_name,
                "revision": proposal.revision,
                "case_digest": proposal.case_digest,
                "plan_digest": proposal.plan_digest,
                "ingredients": proposal.ingredients_summary,
                "sccs_summary": proposal.sccs_evaluation_summary,
                "pdx_manifest_digest": ctx.result_identity.sha256 if ctx.result_identity else None,
                "pdx_artifact_uri": ctx.result_identity.uri if ctx.result_identity else None,
                "approved_by": actor.sub,
                "approved_at": approved_at_iso,
            }
            canonical_pif_bytes = canonical_json_dumps(canonical_pif).encode("utf-8")
            art_sha = hashlib.sha256(canonical_pif_bytes).hexdigest()
            art_storage = ArtifactStorageIdentity(
                artifact_id=f"art-prod-{proposal.proposal_id}",
                uri=f"artifact://{tenant_id}/dossiers/{proposal.proposal_id}/finalized_pif_record.json",
                sha256=art_sha,
                size_bytes=len(canonical_pif_bytes),
                media_type="application/json",
            )
            put_result = artifact_store.put_if_absent(art_storage, canonical_pif_bytes, art_sha)
            if put_result.status == PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST:
                get_audit_log().append_audit_event(
                    AuditEvent(
                        tenant_id=tenant_id,
                        run_id=proposal.session_id,
                        actor_id=actor.sub,
                        event_type=AuditEventTypeEnum.VERIFICATION_FAILED,
                        payload={
                            "action": "product_publication_blocked",
                            "proposal_id": proposal.proposal_id,
                            "checkpoint_id": proposal.checkpoint_id,
                            "error": "ARTIFACT_CONFLICT_BLOCKED",
                            "detail": "Storage contains conflicting artifact digest; ApprovedProductRecord withheld.",
                        },
                    )
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Artifact storage conflict: an artifact with a conflicting digest already exists during completed recovery (publication blocked).",
                )

            # Replay checkpoint projection synchronization
            checkpoint_store.update_checkpoint_status(tenant_id, proposal.checkpoint_id, CheckpointStatusEnum.RESUMED)

            existing_prod = next(
                (p for p in _APPROVED_PRODUCTS_STORE.values() if p.proposal_id == proposal.proposal_id and p.tenant_id == tenant_id),
                None,
            )
            if existing_prod:
                product_id = existing_prod.product_id
                approved_product = existing_prod
            else:
                product_id = f"prod-{uuid.uuid4().hex[:8]}"
                approved_product = ApprovedProductRecord(
                    product_id=product_id,
                    tenant_id=tenant_id,
                    session_id=proposal.session_id,
                    proposal_id=proposal.proposal_id,
                    revision=proposal.revision,
                    product_name=proposal.product_name,
                    case_digest=proposal.case_digest,
                    plan_digest=proposal.plan_digest,
                    checkpoint_id=proposal.checkpoint_id,
                    artifact_identity=art_storage,
                    approval_metadata={
                        "approved_by": actor.sub,
                        "approved_at": approved_at_iso,
                        "rationale": req.rationale or "Approved by Product Manager.",
                        "sha256_checksum": art_sha,
                        "pdx_artifact_uri": ctx.result_identity.uri if ctx.result_identity else None,
                        "pdx_manifest_sha256": ctx.result_identity.sha256 if ctx.result_identity else None,
                    },
                )
                _APPROVED_PRODUCTS_STORE[product_id] = approved_product

            proposal.status = ProposalStatusEnum.APPROVED
            proposal.manager_rationale = req.rationale
            proposal.decided_at = approved_at_iso

            draft = _DRAFTS_STORE.get(proposal.session_id)
            if draft:
                draft.status = FormulationStatusEnum.DRAFT

            return {
                "status": "finalized",
                "product_id": product_id,
                "artifact_identity": art_storage.model_dump(mode="json"),
                "approved_product": approved_product.model_dump(mode="json"),
            }

        # 2. Handle Lease Fencing & State Machine
        cur_version = ctx.version if ctx else 1
        lease_id = None

        try:
            ctx, lease_id = resume_store.acquire_resume_lease(
                tenant_id=tenant_id,
                checkpoint_id=proposal.checkpoint_id,
                expected_version=cur_version,
                lease_owner=actor.sub,
                lease_duration_seconds=60,
            )
            cur_version = ctx.version
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Checkpoint lease concurrency conflict: Unable to acquire resume lease.",
            ) from exc

        # 3. Execute PDX resume first to obtain authentic PDX execution outputs
        try:
            resume_result = orchestrator_inst.resume_with_decision(checkpoint, pdx_decision)
            if resume_result.get("status") not in ("completed", "success"):
                raise RuntimeError(f"PDX plan resume non-terminal status: {resume_result.get('status')}")

            raw_pdx_ident = resume_result.get("artifact_identity")
            if not raw_pdx_ident or not isinstance(raw_pdx_ident, dict):
                raise RuntimeError("PDX resume result missing required artifact_identity.")

            pdx_result_ident = ArtifactStorageIdentity.model_validate(raw_pdx_ident)

            # Strict validation: manifest_sha256 and artifact_uri MUST be present and match pdx_result_ident
            manifest_sha = resume_result.get("manifest_sha256")
            if not manifest_sha or not isinstance(manifest_sha, str) or len(manifest_sha) != 64:
                raise RuntimeError(f"PDX resume result missing or invalid manifest_sha256: {manifest_sha}")
            if pdx_result_ident.sha256 != manifest_sha:
                raise RuntimeError(f"PDX artifact identity SHA-256 mismatch: {pdx_result_ident.sha256} != {manifest_sha}")

            artifact_uri = resume_result.get("artifact_uri")
            if not artifact_uri or not isinstance(artifact_uri, str) or not artifact_uri.startswith("artifact://"):
                raise RuntimeError(f"PDX resume result missing or invalid artifact_uri: {artifact_uri}")
            if pdx_result_ident.uri != artifact_uri:
                raise RuntimeError(f"PDX artifact identity URI mismatch: {pdx_result_ident.uri} != {artifact_uri}")

        except Exception as exc:
            # Mark resume failed in state machine (retryable), keeping checkpoint pending
            try:
                resume_store.mark_resume_failed(
                    tenant_id=tenant_id,
                    checkpoint_id=proposal.checkpoint_id,
                    expected_version=cur_version,
                    lease_id=lease_id,
                    safe_error_code="RESUME_EXECUTION_ERROR",
                    request_id=proposal.approval_request_id,
                    is_retryable=True,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Resume execution error: Transient processing error (state is retryable).",
            ) from exc

        # 4. Construct canonical finalized PIF record using IMMUTABLE decided_at from appr_record
        approved_at_iso = appr_record.decided_at

        canonical_pif = {
            "tenant_id": tenant_id,
            "session_id": proposal.session_id,
            "proposal_id": proposal.proposal_id,
            "product_name": proposal.product_name,
            "revision": proposal.revision,
            "case_digest": proposal.case_digest,
            "plan_digest": proposal.plan_digest,
            "ingredients": proposal.ingredients_summary,
            "sccs_summary": proposal.sccs_evaluation_summary,
            "pdx_manifest_digest": resume_result.get("manifest_sha256"),
            "pdx_artifact_uri": resume_result.get("artifact_uri"),
            "approved_by": actor.sub,
            "approved_at": approved_at_iso,
        }
        canonical_pif_bytes = canonical_json_dumps(canonical_pif).encode("utf-8")
        art_sha = hashlib.sha256(canonical_pif_bytes).hexdigest()
        art_storage = ArtifactStorageIdentity(
            artifact_id=f"art-prod-{proposal.proposal_id}",
            uri=f"artifact://{tenant_id}/dossiers/{proposal.proposal_id}/finalized_pif_record.json",
            sha256=art_sha,
            size_bytes=len(canonical_pif_bytes),
            media_type="application/json",
        )

        # 5. Atomically write canonical PIF record to host-injected ArtifactStore with conflict checking
        put_result = artifact_store.put_if_absent(art_storage, canonical_pif_bytes, art_sha)
        if put_result.status == PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST:
            try:
                resume_store.mark_resume_failed(
                    tenant_id=tenant_id,
                    checkpoint_id=proposal.checkpoint_id,
                    expected_version=cur_version,
                    lease_id=lease_id,
                    safe_error_code="ARTIFACT_CONFLICT_BLOCKED",
                    request_id=proposal.approval_request_id,
                    is_retryable=False,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Artifact storage conflict: an artifact with a conflicting digest already exists.",
            )

        # 6. Mark completed in resume store using authentic PDX result identity & update checkpoint status
        try:
            resume_store.mark_resume_completed(
                tenant_id=tenant_id,
                checkpoint_id=proposal.checkpoint_id,
                expected_version=cur_version,
                lease_id=lease_id,
                result_identity=pdx_result_ident,
            )
            checkpoint_store.update_checkpoint_status(tenant_id, proposal.checkpoint_id, CheckpointStatusEnum.RESUMED)
        except Exception as exc:
            try:
                resume_store.mark_resume_failed(
                    tenant_id=tenant_id,
                    checkpoint_id=proposal.checkpoint_id,
                    expected_version=cur_version,
                    lease_id=lease_id,
                    safe_error_code="RESUME_COMPLETION_ERROR",
                    request_id=proposal.approval_request_id,
                    is_retryable=True,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Resume execution error: Transient processing error (state is retryable).",
            ) from exc

        # 7. Create immutable ApprovedProductRecord upon complete success
        product_id = f"prod-{uuid.uuid4().hex[:8]}"
        approved_product = ApprovedProductRecord(
            product_id=product_id,
            tenant_id=tenant_id,
            session_id=proposal.session_id,
            proposal_id=proposal.proposal_id,
            revision=proposal.revision,
            product_name=proposal.product_name,
            case_digest=proposal.case_digest,
            plan_digest=proposal.plan_digest,
            checkpoint_id=proposal.checkpoint_id,
            artifact_identity=art_storage,
            approval_metadata={
                "approved_by": actor.sub,
                "approved_at": approved_at_iso,
                "rationale": req.rationale or "Approved by Product Manager.",
                "sha256_checksum": art_sha,
                "pdx_artifact_uri": resume_result.get("artifact_uri"),
                "pdx_manifest_sha256": resume_result.get("manifest_sha256"),
            },
        )
        _APPROVED_PRODUCTS_STORE[product_id] = approved_product

        proposal.status = ProposalStatusEnum.APPROVED
        proposal.manager_rationale = req.rationale
        proposal.decided_at = approved_at_iso

        # Update draft status
        draft = _DRAFTS_STORE.get(proposal.session_id)
        if draft:
            draft.status = FormulationStatusEnum.DRAFT

        return {
            "status": "finalized",
            "product_id": product_id,
            "artifact_identity": art_storage.model_dump(mode="json"),
            "approved_product": approved_product.model_dump(mode="json"),
        }

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid decision '{req.decision}'.")


# ---------------------------------------------------------------------------
# 6. Approved Products & Export Bundle Spec Endpoint (Tenant-Isolated)
# ---------------------------------------------------------------------------

@router.get("/products/approved", response_model=List[Dict[str, Any]])
async def list_approved_products(
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> List[Dict[str, Any]]:
    """List finalized immutable approved products for the authenticated tenant."""
    tenant_id, _ = auth_context
    return [
        p.model_dump(mode="json")
        for p in reversed(list(_APPROVED_PRODUCTS_STORE.values()))
        if p.tenant_id == tenant_id
    ]


@router.get("/products/{product_id}/export-bundle", response_model=Dict[str, Any])
async def get_product_export_bundle(
    product_id: str,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """
    Generate the neutral 5-format render bundle spec for an ApprovedProductRecord.
    Enforces strict tenant isolation (fail-closed 404) and returns prodocux_render_requests.
    """
    tenant_id, _ = auth_context
    product = _APPROVED_PRODUCTS_STORE.get(product_id)
    if not product or product.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approved product not found.")

    proposal = _PROPOSALS_STORE.get(product.proposal_id)
    ingredients = proposal.ingredients_summary if proposal else []
    sccs_summary = proposal.sccs_evaluation_summary if proposal else {}

    bundle_spec = map_approved_product_to_render_bundle(product, ingredients, sccs_summary)
    prodocux_requests = map_bundle_to_prodocux_render_requests(bundle_spec)
    return {
        "status": "spec_ready",
        "product_id": product_id,
        "sha256_checksum": product.artifact_identity.sha256,
        "bundle_spec": bundle_spec,
        "prodocux_render_requests": prodocux_requests,
    }


class RenderArtifactRequest(BaseModel):
    format: str = Field(description="Render format: pdf, docx, csv, xlsx, pptx")


@router.post("/products/{product_id}/render-artifact", response_model=Dict[str, Any])
async def render_product_artifact(
    product_id: str,
    req: RenderArtifactRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Dict[str, Any]:
    """
    Render a specific format binary artifact via ProDocuX POST /v1/render/artifact with tenant validation (fail-closed 404).
    """
    tenant_id, _ = auth_context
    product = _APPROVED_PRODUCTS_STORE.get(product_id)
    if not product or product.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approved product not found.")

    fmt = req.format.lower().lstrip(".")
    proposal = _PROPOSALS_STORE.get(product.proposal_id)
    ingredients = proposal.ingredients_summary if proposal else []
    sccs_summary = proposal.sccs_evaluation_summary if proposal else {}

    bundle_spec = map_approved_product_to_render_bundle(product, ingredients, sccs_summary)
    prodocux_requests = map_bundle_to_prodocux_render_requests(bundle_spec)

    render_req = prodocux_requests.get(fmt)
    if not render_req:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported or missing render request for format '{fmt}'. Available: {list(prodocux_requests.keys())}",
        )

    render_res = intake_adapter.render_artifact(render_req)
    return {
        "status": "rendered",
        "product_id": product_id,
        "format": fmt,
        "result": render_res,
    }
