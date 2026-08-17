"""
Approval Domain Models & Contract Envelopes.
Implements the 3-way digest verification and exact 1:1 conformance with upstream PDX Core schemas.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class ApprovalDecisionEnum(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"

class CheckpointStatusEnum(str, Enum):
    """Product-neutral upstream PDX checkpoint status (strictly preserved)."""
    PENDING = "pending"
    RESUMED = "resumed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

class FleetExecutionStatus(str, Enum):
    """Fleet-owned execution lifecycle status (independent of upstream PDX enum)."""
    AWAITING_DECISION = "awaiting_decision"
    APPROVED_PENDING_RESUME = "approved_pending_resume"
    RESUME_IN_PROGRESS = "resume_in_progress"
    COMPLETED = "completed"
    RESUME_FAILED_RETRYABLE = "resume_failed_retryable"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

class ApprovalRequestStatusEnum(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

class AuthenticatedActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str = Field(min_length=1, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    roles: List[str] = Field(default_factory=list, max_length=20)

class PDXWorkflowCheckpoint(BaseModel):
    """Product-neutral workflow checkpoint (1:1 with workflow_checkpoint.v1.schema.json)."""
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    subject_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    completed_step_ids: List[str] = Field(default_factory=list)
    pending_step_ids: List[str] = Field(default_factory=list)
    evidence_digests: Dict[str, str] = Field(default_factory=dict)
    status: CheckpointStatusEnum = CheckpointStatusEnum.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PDXApprovalRequest(BaseModel):
    """Product-neutral approval request (1:1 with approval_request.v1.schema.json)."""
    model_config = ConfigDict(extra="forbid")

    approval_request_id: UUID = Field(default_factory=uuid4)
    run_id: str = Field(min_length=1, max_length=128)
    checkpoint_id: str = Field(min_length=1, max_length=128)
    subject_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digests: Dict[str, str] = Field(default_factory=dict)
    summary: Optional[str] = Field(default=None, max_length=1024)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: ApprovalRequestStatusEnum = ApprovalRequestStatusEnum.PENDING

class PDXApprovalDecision(BaseModel):
    """Product-neutral approval decision (1:1 with approval_decision.v1.schema.json)."""
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID = Field(default_factory=uuid4)
    approval_request_id: UUID
    checkpoint_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    actor_id: str = Field(min_length=1, max_length=128)
    decision: ApprovalDecisionEnum
    reason: Optional[str] = Field(default=None, max_length=1024)
    subject_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digests: Dict[str, str] = Field(default_factory=dict)
    decided_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class FleetApprovalRecord(BaseModel):
    """Fleet-owned governance persistence record capturing tenant context and authenticated actor."""
    model_config = ConfigDict(extra="forbid")

    approval_record_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    run_id: str = Field(min_length=1, max_length=128)
    checkpoint_id: str = Field(min_length=1, max_length=128)
    approval_request_id: Optional[UUID] = None
    canonical_idempotency_key: str = Field(min_length=1, max_length=256)
    authenticated_actor: AuthenticatedActor
    decision: ApprovalDecisionEnum
    reason: Optional[str] = Field(default=None, max_length=1024)
    subject_case_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digests: Dict[str, str] = Field(default_factory=dict)
    decided_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
