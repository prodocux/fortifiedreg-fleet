"""
Authentication and Dev-Token Router.
Exposes development token generation endpoint strictly for local testing and prototype UI.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from fleet_api.security import FLEET_ENV, create_access_token

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

class DevTokenRequest(BaseModel):
    tenant_id: str = Field(default="tenant-acme-corp")
    sub: str = Field(default="usr-cso-steven-wu")
    roles: List[str] = Field(default_factory=lambda: ["safety_assessor", "approver", "cso"])
    email: Optional[str] = Field(default="cso@acme.com")

@router.post("/dev-token", response_model=Dict[str, Any])
def generate_dev_token(body: DevTokenRequest = DevTokenRequest()) -> Dict[str, Any]:
    """Generate a development JWT token. Available ONLY when FLEET_ENV is test, local, or dev."""
    if FLEET_ENV not in ("test", "local", "dev"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev token endpoint is disabled in non-development environments.",
        )

    token = create_access_token(
        tenant_id=body.tenant_id,
        sub=body.sub,
        roles=body.roles,
        email=body.email,
        expires_in_seconds=86400,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "tenant_id": body.tenant_id,
        "sub": body.sub,
        "roles": body.roles,
    }
