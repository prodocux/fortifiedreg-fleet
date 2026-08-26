"""
Workflow v0.4.0 Domain Models for FortifiedReg Fleet.
Defines Session, Formulation Drafts with Revision Invalidation,
Product Proposals, and Immutable Approved Product Records.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fleet_governance_core.models.case import ExposureScenario, FormulaItem
from fleet_governance_core.models.hashing import canonical_json_dumps, compute_data_sha256
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum


class ActingRoleEnum(str, Enum):
    FORMULATOR = "formulator"
    PRODUCT_MANAGER = "product_manager"


class FormulationStatusEnum(str, Enum):
    DRAFT = "draft"
    GATE_RUNNING = "gate_running"
    BLOCKED = "blocked"
    CHANGES_REQUIRED = "changes_required"
    PROPOSAL_PENDING_REVIEW = "proposal_pending_review"


class ProposalStatusEnum(str, Enum):
    PENDING_REVIEW = "pending_review"
    RETURNED = "returned"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class GovernanceInvalidationRecord(BaseModel):
    """Tracks atomic-style recoverable Saga invalidation of earlier proposals and checkpoints."""
    invalidation_id: str = Field(default_factory=lambda: f"inv-{uuid.uuid4().hex[:8]}")
    idempotency_key: str
    tenant_id: str = "tenant-demo"
    session_id: str
    product_name: str
    source_revision: int
    source_digest: str
    target_revision: int
    target_digest: str
    target_draft_payload: Dict[str, Any] = Field(default_factory=dict)
    step_proposals_superseded: bool = False
    step_checkpoints_cancelled: bool = False
    step_resume_invalidated: bool = False
    step_audit_emitted: bool = False
    step_draft_persisted: bool = False
    status: str = "in_progress"  # in_progress, completed, failed
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None


class GateDecisionEnum(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class DemoSession(BaseModel):
    """Single-identity demo session with dual-role acting simulation."""
    session_id: str
    sub: str
    tenant_id: str = "tenant-demo"
    roles: List[str] = Field(default_factory=lambda: ["demo_evaluator"])
    allowed_demo_roles: List[str] = Field(default_factory=lambda: ["formulator", "product_manager"])
    acting_role: ActingRoleEnum = ActingRoleEnum.FORMULATOR
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str
    is_active: bool = True


class FormulationDraft(BaseModel):
    """Formulation draft state with strict revision invalidation tracking."""
    draft_id: str
    tenant_id: str = "tenant-demo"
    session_id: str
    product_name: str = "Retinol Night Renewal Serum"
    revision: int = 1
    ingredients: List[FormulaItem] = Field(default_factory=list)
    exposure_scenario: ExposureScenario = Field(
        default_factory=lambda: ExposureScenario(
            product_type="face_serum",
            daily_applied_amount_g=0.8,
            retention_factor=1.0,
            body_weight_kg=60.0,
        )
    )
    case_digest: str = ""
    status: FormulationStatusEnum = FormulationStatusEnum.DRAFT
    latest_verifier_result: Optional[VerifierResult] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_case_digest(self) -> str:
        """Compute authoritative canonical case digest for this revision."""
        payload = {
            "draft_id": self.draft_id,
            "revision": self.revision,
            "product_name": self.product_name,
            "ingredients": [item.model_dump(mode="json") for item in sorted(self.ingredients, key=lambda x: x.inci_name)],
            "exposure_scenario": self.exposure_scenario.model_dump(mode="json"),
        }
        self.case_digest = compute_data_sha256(canonical_json_dumps(payload).encode("utf-8"))
        return self.case_digest


class ProductProposal(BaseModel):
    """Submitted regulatory product proposal waiting for Product Manager decision."""
    proposal_id: str
    tenant_id: str = "tenant-demo"
    session_id: str
    draft_id: str
    revision: int
    product_name: str
    case_digest: str
    plan_digest: str
    checkpoint_id: Optional[str] = None
    approval_request_id: Optional[str] = None
    gate_decision: GateDecisionEnum
    gate_reasons: List[str] = Field(default_factory=list)
    ingredients_summary: List[Dict[str, Any]] = Field(default_factory=list)
    sccs_evaluation_summary: Dict[str, Any] = Field(default_factory=dict)
    manager_rationale: Optional[str] = None
    return_comments: Optional[str] = None
    status: ProposalStatusEnum = ProposalStatusEnum.PENDING_REVIEW
    submitted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decided_at: Optional[str] = None


class ApprovedProductRecord(BaseModel):
    """Immutable finalized product record approved by Product Manager HitL decision."""
    product_id: str
    tenant_id: str = "tenant-demo"
    session_id: str
    proposal_id: str
    revision: int
    product_name: str
    case_digest: str
    plan_digest: str
    checkpoint_id: str
    artifact_identity: ArtifactStorageIdentity
    approval_metadata: Dict[str, Any] = Field(default_factory=dict)
    finalized_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_immutable: bool = True


class ContentBlockItem(BaseModel):
    """Universal ProDocuX content block item for two-tier import."""
    block_id: str
    block_type: str = "table_cell"  # paragraph, table_cell, slide_text
    text: str
    source_locator: str
    confidence: float = 1.0


class ProDocuXContentBlocksContract(BaseModel):
    """G1 Content blocks schema output from ProDocuX."""
    contract_version: str = "1.0.0"
    document_id: str
    source_sha256: str
    format: str  # pdf, docx, csv, xlsx, pptx
    blocks: List[ContentBlockItem] = Field(default_factory=list)
