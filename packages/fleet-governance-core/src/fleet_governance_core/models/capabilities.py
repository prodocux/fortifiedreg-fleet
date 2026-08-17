"""
Capability Catalog and Tool Policy Domain Models (G5).
Defines agent capability registration, role permissions, and tool invocation boundaries.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=128)
    allowed_roles: List[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_retries: int = Field(default=0, ge=0, le=5)
    approval_required: bool = Field(default=False)
    audit_payload: bool = Field(default=True)

class AgentCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=512)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+(\.[0-9]+)?$")
    required_roles: List[str] = Field(min_length=1)
    allowed_tools: List[str] = Field(default_factory=list)
    read_only: bool = Field(default=True)

class CapabilityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str = Field(pattern=r"^[0-9]+\.[0-9]+(\.[0-9]+)?$")
    capabilities: Dict[str, AgentCapability] = Field(default_factory=dict)
    tool_policies: Dict[str, ToolPolicy] = Field(default_factory=dict)

    def validate_tool_invocation(self, capability_id: str, tool_name: str, actor_roles: List[str]) -> bool:
        """Verify whether an actor with given roles can invoke tool under capability."""
        cap = self.capabilities.get(capability_id)
        if not cap or tool_name not in cap.allowed_tools:
            return False
        
        # Check actor has at least one required role for capability
        if not any(r in cap.required_roles for r in actor_roles):
            return False

        # Check tool policy
        policy = self.tool_policies.get(tool_name)
        if policy and not any(r in policy.allowed_roles for r in actor_roles):
            return False

        return True
