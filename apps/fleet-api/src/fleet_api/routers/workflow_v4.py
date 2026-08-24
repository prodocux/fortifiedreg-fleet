"""
Workflow v0.4.0 Router for FortifiedReg Fleet.
Exposes Session Lifecycle, Formulation Draft with Revision Invalidation,
Two-tier 5-Format Import Preview, Proposal Submission Gate, Manager Decisions,
and Approved Product Record Export Bundle.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from fleet_api.deps import (
    FLEET_ENV,
    get_approval_store,
    get_approval_workflow_service,
    get_artifact_store,
    get_audit_log,
    get_checkpoint_store,
    get_orchestrator,
    get_resume_context_store,
    get_tenant_and_actor,
    intake_adapter,
    orchestrator,
)
from fleet_api.security import create_access_token
from fleet_domain_cosmetics.inci_verifier import evaluate_inci_compliance
from fleet_domain_cosmetics.mos_calculator import evaluate_toxicology_mos
from fleet_domain_cosmetics.normalizer import (
    NormalizedIngredientCandidate,
    normalize_content_blocks,
)
from fleet_domain_cosmetics.export_spec_mapper import (
    map_approved_product_to_render_bundle,
    map_bundle_to_prodocux_render_requests,
)
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    AuthenticatedActor,
    CheckpointStatusEnum,
    FleetApprovalRecord,
    PDXApprovalDecision,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.audit import AuditEvent, AuditEventTypeEnum
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
    ProDocuXContentBlocksContract,
    ProductProposal,
    ProposalStatusEnum,
)

router = APIRouter(prefix="/v1", tags=["Workflow v0.4.0"])

# Ephemeral in-memory store for session, draft, proposal, and approved product states
_SESSIONS_STORE: Dict[str, DemoSession] = {}
_DRAFTS_STORE: Dict[str, FormulationDraft] = {}
_PROPOSALS_STORE: Dict[str, ProductProposal] = {}
_APPROVED_PRODUCTS_STORE: Dict[str, ApprovedProductRecord] = {}


# ---------------------------------------------------------------------------
# 1. Session Management (Single Identity with Dual-Role Acting)
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    acting_role: Optional[ActingRoleEnum] = ActingRoleEnum.FORMULATOR


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
        "Production requires external IdP / SSO RBAC with segregation of duties."
    )


@router.post("/demo/session", response_model=SessionResponse)
async def create_demo_session(req: Optional[CreateSessionRequest] = None) -> SessionResponse:
    """Issue a 15-minute demo session token with dual-role acting simulation."""
    acting_role = req.acting_role if req else ActingRoleEnum.FORMULATOR
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    sub = f"demo-session-{uuid.uuid4().hex[:12]}"
    exp_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    exp_iso = exp_time.isoformat()

    session_obj = DemoSession(
        session_id=session_id,
        sub=sub,
        acting_role=acting_role,
        expires_at=exp_iso,
    )
    _SESSIONS_STORE[session_id] = session_obj
    _SESSIONS_STORE[sub] = session_obj

    # Initialize default draft
    draft_id = f"draft-{session_id}"
    init_draft = FormulationDraft(
        draft_id=draft_id,
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
    init_draft.compute_case_digest()
    _DRAFTS_STORE[session_id] = init_draft
    _DRAFTS_STORE[sub] = init_draft

    token = create_access_token(
        tenant_id="tenant-demo",
        sub=sub,
        roles=["demo_evaluator"],
        expires_in_seconds=900,
        extra_claims={
            "session_id": session_id,
            "allowed_demo_roles": ["formulator", "product_manager"],
            "acting_role": acting_role.value,
        },
    )

    return SessionResponse(
        token=token,
        access_token=token,
        session_id=session_id,
        sub=sub,
        tenant_id="tenant-demo",
        acting_role=acting_role,
        allowed_demo_roles=["formulator", "product_manager"],
        expires_at=exp_iso,
    )


@router.post("/demo/session/restart", response_model=SessionResponse)
async def restart_demo_session(req: Optional[CreateSessionRequest] = None) -> SessionResponse:
    """Terminates existing session and restarts a clean demo session from revision 1."""
    return await create_demo_session(req)


# ---------------------------------------------------------------------------
# 2. Formulation Management with Revision Invalidation
# ---------------------------------------------------------------------------

class UpdateDraftRequest(BaseModel):
    product_name: str
    ingredients: List[FormulaItem]
    exposure_scenario: Optional[ExposureScenario] = None
    acting_role: ActingRoleEnum = ActingRoleEnum.FORMULATOR


@router.get("/formulations/draft", response_model=Dict[str, Any])
async def get_formulation_draft(auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor)) -> Dict[str, Any]:
    """Retrieve current formulation draft for the active session."""
    tenant_id, actor = auth_context
    session_id = actor.sub
    draft = _DRAFTS_STORE.get(session_id)
    if not draft:
        # Create on the fly if needed
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

    # Evaluate SCCS real-time status for draft
    sccs_res = evaluate_toxicology_mos(draft.ingredients, draft.exposure_scenario)
    inci_res = evaluate_inci_compliance(draft.ingredients)

    return {
        "draft": draft.model_dump(mode="json"),
        "sccs_evaluation": sccs_res.model_dump(mode="json"),
        "inci_evaluation": inci_res.model_dump(mode="json"),
    }


@router.post("/formulations/draft", response_model=Dict[str, Any])
async def update_formulation_draft(
    req: UpdateDraftRequest,
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> Dict[str, Any]:
    """
    Update formulation ingredients or exposure scenario.
    Increments revision += 1, invalidates previous verifier results & checkpoints.
    """
    tenant_id, actor = auth_context
    session_id = actor.sub

    existing = _DRAFTS_STORE.get(session_id)
    new_rev = (existing.revision + 1) if existing else 1

    draft = FormulationDraft(
        draft_id=f"draft-{session_id}",
        session_id=session_id,
        product_name=req.product_name,
        revision=new_rev,
        ingredients=req.ingredients,
        exposure_scenario=req.exposure_scenario or (existing.exposure_scenario if existing else ExposureScenario(
            product_type="face_serum",
            daily_applied_amount_g=0.8,
            retention_factor=1.0,
            body_weight_kg=60.0,
        )),
        status=FormulationStatusEnum.DRAFT,
        latest_verifier_result=None,  # Strictly invalidated
    )
    draft.compute_case_digest()
    _DRAFTS_STORE[session_id] = draft

    # Audit event for revision increment
    audit_log = get_audit_log()
    audit_log.append_audit_event(
        AuditEvent(
            tenant_id=tenant_id,
            run_id=session_id,
            actor_id=actor.sub,
            event_type=AuditEventTypeEnum.CASE_CREATED,
            payload={
                "action": "formulation_draft_updated",
                "revision": new_rev,
                "case_digest": draft.case_digest,
                "acting_role": req.acting_role.value,
            },
        )
    )

    sccs_res = evaluate_toxicology_mos(draft.ingredients, draft.exposure_scenario)
    inci_res = evaluate_inci_compliance(draft.ingredients)

    return {
        "status": "updated",
        "revision": new_rev,
        "case_digest": draft.case_digest,
        "draft": draft.model_dump(mode="json"),
        "sccs_evaluation": sccs_res.model_dump(mode="json"),
        "inci_evaluation": inci_res.model_dump(mode="json"),
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
async def parse_import_preview(req: ParsePreviewRequest) -> Dict[str, Any]:
    """
    Two-tier import parser: ProDocuX content blocks -> Fleet Cosmetics Normalizer.
    Returns normalized candidate ingredients with confidence and source locations for confirmation.
    Supports either pre-set scenario keys, explicit content blocks contracts, or live uploaded files.
    """
    if req.content_b64 and req.filename:
        import base64
        try:
            raw_bytes = base64.b64decode(req.content_b64)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 payload.")

        extracted = intake_adapter.extract_content_blocks(req.filename, raw_bytes)
        candidates = normalize_content_blocks(extracted)
        doc_id = extracted.get("document_id") or f"doc-{req.filename}"
        doc_sha = extracted.get("source_sha256") or compute_data_sha256(raw_bytes)
        fmt = (req.filename.split(".")[-1]).lower() if "." in req.filename else "unknown"

        return {
            "status": "preview_ready",
            "document_id": doc_id,
            "format": fmt,
            "source_sha256": doc_sha,
            "candidates_count": len(candidates),
            "candidates": [c.model_dump(mode="json") for c in candidates],
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
    }


# ---------------------------------------------------------------------------
# 4. Formal Gate Submission & Product Proposal
# ---------------------------------------------------------------------------

@router.post("/formulations/submit-proposal", response_model=Dict[str, Any])
async def submit_product_proposal(
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
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
                "gate_decision": "FAIL",
                "message": "Submission hard blocked by Regulatory Gate.",
                "reasons": reasons,
            },
        )

    # 2. Compile PDX Plan & Checkpoint with Approval Request
    case_digest = draft.compute_case_digest()
    plan_digest = compute_data_sha256(f"pdx-plan-{draft.draft_id}-rev{draft.revision}-{case_digest}".encode("utf-8"))
    checkpoint_id = f"chk-{uuid.uuid4().hex[:12]}"
    proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
    req_uuid = uuid.uuid4()
    req_uuid_str = str(req_uuid)

    checkpoint_store = get_checkpoint_store()
    checkpoint = PDXWorkflowCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id=session_id,
        status=CheckpointStatusEnum.PENDING,
        subject_digest=case_digest,
        plan_digest=plan_digest,
        evidence_digests={"sccs_digest": sccs_res.rule_digest},
    )
    checkpoint_store.save_checkpoint(tenant_id, checkpoint)

    approval_request = PDXApprovalRequest(
        approval_request_id=req_uuid,
        checkpoint_id=checkpoint_id,
        run_id=session_id,
        subject_digest=case_digest,
        plan_digest=plan_digest,
        evidence_digests={"sccs_digest": sccs_res.rule_digest},
        summary="Regulatory safety dossier PIF approval request",
    )
    checkpoint_store.save_approval_request(tenant_id, approval_request)

    # Save resume context in store for LivePDXCoreOrchestrator if present
    resume_context_store = get_resume_context_store()
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
                step_count=3,
                step_ids=["step_verify_toxicology", "step_human_approval", "step_assemble_pif"],
                has_approval_step=True,
                product_name=draft.product_name,
                jurisdiction="EU",
            ),
            approval_request=approval_request,
            evidence_digests={"sccs_digest": sccs_res.rule_digest},
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
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
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
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> Dict[str, Any]:
    """
    Product Manager decisions via formal ApprovalWorkflowService and PDX Orchestrator Resume:
    - 'approved': Validates 3-way digests, records approval decision, resumes PDX execution plan,
                  atomically publishes canonical PIF to ArtifactStore with conflict checking,
                  and returns immutable ApprovedProductRecord.
    - 'returned': Returns proposal with comments to Formulator for Revision N+1 and notifies PDX orchestrator.
    """
    tenant_id, actor = auth_context
    proposal = _PROPOSALS_STORE.get(proposal_id)
    if not proposal or proposal.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")

    if proposal.status != ProposalStatusEnum.PENDING_REVIEW:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Proposal already decided ({proposal.status}).")

    checkpoint_store = get_checkpoint_store()
    approval_service = get_approval_workflow_service()
    artifact_store = get_artifact_store()
    orchestrator = get_orchestrator()

    checkpoint = checkpoint_store.get_checkpoint(tenant_id, proposal.checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Checkpoint '{proposal.checkpoint_id}' not found.")

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

        # 2. Inform PDX orchestrator of termination
        try:
            orchestrator.resume_with_decision(checkpoint, pdx_decision)
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

        # 2. Resume PDX execution plan via Orchestrator
        try:
            resume_result = orchestrator.resume_with_decision(checkpoint, pdx_decision)
        except Exception as e:
            # If resume fails, fail-closed without creating finalized ApprovedProductRecord
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"PDX execution resume failed: {str(e)}",
            )

        if resume_result.get("status") not in ("completed", "success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"PDX execution resume did not complete successfully. Status: {resume_result.get('status')}",
            )

        # 3. Transition checkpoint to RESUMED in checkpoint store upon successful resume
        checkpoint.status = CheckpointStatusEnum.RESUMED
        checkpoint_store.save_checkpoint(tenant_id, checkpoint)

        # 4. Construct canonical finalized PIF record
        approved_at_iso = datetime.now(timezone.utc).isoformat()
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Artifact storage conflict: an artifact with a conflicting digest already exists at {art_storage.uri}",
            )

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
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
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
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
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
    auth_context: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
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
