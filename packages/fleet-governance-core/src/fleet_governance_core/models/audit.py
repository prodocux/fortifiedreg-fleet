"""
Audit Event Domain Model.
Implements canonical audit_event_v1 schema.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

GOVERNANCE_AUDIT_NAMESPACE = UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")

class AuditEventTypeEnum(str, Enum):
    CASE_CREATED = "CASE_CREATED"
    INTAKE_EXTRACTED = "INTAKE_EXTRACTED"
    PLAN_COMPILED = "PLAN_COMPILED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    CHECKPOINT_INVALIDATED = "CHECKPOINT_INVALIDATED"
    SESSION_RESET = "SESSION_RESET"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_DECIDED = "APPROVAL_DECIDED"
    MEMORY_PROMOTED = "MEMORY_PROMOTED"
    SECURITY_INJECTION_BLOCKED = "SECURITY_INJECTION_BLOCKED"

class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    run_id: str = Field(min_length=1, max_length=128)
    event_type: AuditEventTypeEnum
    actor_id: str = Field(min_length=1, max_length=128)
    trace_id: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    span_id: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Union[str, int, float, bool, None]] = Field(default_factory=dict)
