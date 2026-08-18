"""
Authentication and Demo Session Router.
Provides strictly scoped ephemeral demo sessions for evaluation and controlled dev tokens.
"""
import json
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from fleet_api.security import FLEET_ENV, create_access_token

router = APIRouter(tags=["Auth"])

@router.post("/v1/demo/session", response_model=Dict[str, Any])
async def create_demo_session(request: Request, response: Response) -> Dict[str, Any]:
    """Issue a strictly scoped, ephemeral 15-minute demo session token.
    Client-supplied tenant, role, or subject overrides are strictly forbidden and rejected.
    """
    body_bytes = await request.body()
    if body_bytes.strip():
        try:
            data = json.loads(body_bytes)
            if isinstance(data, dict) and any(k in data for k in ("tenant_id", "roles", "sub", "email", "role", "permissions")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Client-supplied tenant_id, sub, or roles parameters are strictly forbidden on demo session.",
                )
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload in demo session request.",
            )

    session_id = f"demo-session-{uuid.uuid4().hex[:12]}"
    token = create_access_token(
        tenant_id="tenant-demo",
        sub=session_id,
        roles=["demo_evaluator"],
        email="demo-evaluator@democorp.com",
        expires_in_seconds=900,
    )

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 900,
        "tenant_id": "tenant-demo",
        "sub": session_id,
        "roles": ["demo_evaluator"],
        "mode": "demo_evaluator_session",
    }


class DevTokenRequest(BaseModel):
    tenant_id: str = Field(default="tenant-acme-corp")
    sub: str = Field(default="usr-cso-steven-wu")
    roles: List[str] = Field(default_factory=lambda: ["safety_assessor", "approver", "cso"])
    email: Optional[str] = Field(default="cso@acme.com")


@router.post("/v1/auth/dev-token", response_model=Dict[str, Any])
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
