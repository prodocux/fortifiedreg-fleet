"""
Verifier Result Domain Model.
Implements the proposed verifier_result_v1 contract.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

class VerifierStatusEnum(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"

class VerifierResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    status: VerifierStatusEnum
    reason_codes: List[str] = Field(default_factory=list, max_length=50)
    rule_set_id: str = Field(min_length=1, max_length=128)
    rule_set_version: str = Field(min_length=1, max_length=32)
    rule_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_ids: List[str] = Field(default_factory=list, max_length=50)
    details: Dict[str, Union[str, int, float, bool, None]] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
