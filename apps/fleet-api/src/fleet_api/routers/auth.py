"""
Authentication and Demo Session Router.
Provides strictly scoped ephemeral demo sessions for evaluation and controlled dev tokens.
Supports persona-aware session issuance for role-based UI walkthroughs.
"""
import json
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from fleet_api.security import FLEET_ENV, create_access_token

router = APIRouter(tags=["Auth"])

# Server-side allowlist: persona name -> sub prefix
# Client-supplied roles, tenant_id, and sub are always rejected.
# Only "persona" is accepted as a UI routing hint; it does NOT change privilege level.
ALLOWED_PERSONAS: Dict[str, Dict[str, str]] = {
    "formulator": {
        "sub_prefix": "demo-formulator",
        "label": "R&D Formulator",
        "description": "Registers product formulations and exposure scenarios",
    },
    "supplier_qa": {
        "sub_prefix": "demo-qa",
        "label": "Supplier QA Manager",
        "description": "Uploads and verifies 5-format supplier evidence documents",
    },
    "safety_assessor": {
        "sub_prefix": "demo-assessor",
        "label": "Safety Assessor",
        "description": "Triggers multi-agent SCCS toxicology evaluation and fleet orchestration",
    },
    "cso": {
        "sub_prefix": "demo-cso",
        "label": "Chief Safety Officer (CSO)",
        "description": "Reviews PIF dossiers and performs cryptographic sign-off at HitL gate",
    },
}

_FORBIDDEN_OVERRIDES = frozenset({"tenant_id", "roles", "sub", "email", "role", "permissions"})


@router.post("/v1/demo/session", response_model=Dict[str, Any])
async def create_demo_session(request: Request, response: Response) -> Dict[str, Any]:
    """Issue a strictly scoped, ephemeral 15-minute demo session token.

    Accepts an optional ``persona`` field to route the session to a specific
    role-based UI layout. All privilege-affecting fields (tenant_id, roles, sub)
    are forbidden and rejected with HTTP 400.

    Allowed personas: formulator, supplier_qa, safety_assessor, cso
    """
    persona_key = "formulator"  # safe default

    body_bytes = await request.body()
    if body_bytes.strip():
        try:
            data = json.loads(body_bytes)
            if isinstance(data, dict):
                # Reject any attempt to escalate privileges
                forbidden_keys = _FORBIDDEN_OVERRIDES & set(data.keys())
                if forbidden_keys:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Client-supplied fields are strictly forbidden on demo session: {sorted(forbidden_keys)}",
                    )
                # Accept only a persona hint
                if "persona" in data:
                    requested = str(data["persona"]).strip().lower()
                    if requested not in ALLOWED_PERSONAS:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"Unknown persona '{requested}'. "
                                f"Allowed values: {sorted(ALLOWED_PERSONAS.keys())}"
                            ),
                        )
                    persona_key = requested
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload in demo session request.",
            )

    persona_meta = ALLOWED_PERSONAS[persona_key]
    session_id = f"{persona_meta['sub_prefix']}-{uuid.uuid4().hex[:12]}"

    token = create_access_token(
        tenant_id="tenant-demo",
        sub=session_id,
        roles=["demo_evaluator"],
        email=f"{persona_key}@demo.fortifiedreg.com",
        expires_in_seconds=7200,
        extra_claims={"persona": persona_key},
    )

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 7200,
        "tenant_id": "tenant-demo",
        "sub": session_id,
        "persona": persona_key,
        "persona_label": persona_meta["label"],
        "persona_description": persona_meta["description"],
        "roles": ["demo_evaluator"],
        "mode": "persona_demo_session",
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
