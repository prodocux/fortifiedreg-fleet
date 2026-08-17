"""
Execution Context, Plan Summary, and Outbox Models (v0.3.0).
Provides strong-typed representations for durable resume context,
atomic lease fencing, and projection outbox synchronization.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from fleet_governance_core.models.approval import (
    FleetExecutionStatus,
    PDXApprovalRequest,
)
from fleet_governance_core.models.storage import ArtifactStorageIdentity

class PlanSummary(BaseModel):
    """
    Descriptive, non-authoritative summary of execution plan metadata.
    Strictly forbidden from storing raw document bytes, prompts, or sensitive payloads.
    """
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(pattern=r"^pdx_execution_plan_v1$")
    step_count: int = Field(ge=1, le=100)
    step_ids: List[str] = Field(max_length=100)
    has_approval_step: bool
    product_name: str = Field(min_length=1, max_length=255)
    jurisdiction: str = Field(min_length=2, max_length=16)

class ProjectionOutboxRecord(BaseModel):
    """
    Durable outbox record for asynchronous, idempotent PDX checkpoint projection synchronization.
    """
    model_config = ConfigDict(extra="forbid")

    outbox_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    checkpoint_id: str = Field(min_length=1, max_length=128)
    target_pdx_status: str = Field(pattern=r"^(resumed|cancelled)$")
    created_at: str
    processed_at: Optional[str] = None
    attempt_count: int = 0

class ExecutionContextRecord(BaseModel):
    """
    Durable execution context record stored by host.
    Holds opaque references and deterministic digests without inlining sensitive case payloads.
    """
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    checkpoint_id: str = Field(min_length=1, max_length=128)
    case_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_storage_identity: Optional[ArtifactStorageIdentity] = None
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_storage_identity: Optional[ArtifactStorageIdentity] = None
    plan_summary: PlanSummary
    approval_request: Optional[PDXApprovalRequest] = None
    evidence_digests: Dict[str, str] = Field(default_factory=dict)
    document_storage_identities: Dict[str, ArtifactStorageIdentity] = Field(default_factory=dict)
    status: FleetExecutionStatus = FleetExecutionStatus.AWAITING_DECISION
    version: int = 1
    lease_id: Optional[str] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    attempt_count: int = 0
    result_identity: Optional[ArtifactStorageIdentity] = None
    last_error: Optional[Dict[str, Any]] = None
