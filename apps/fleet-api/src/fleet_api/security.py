"""
JWT Authentication & Role-Based Access Control (RBAC) Module.
Enforces fail-closed token validation, active session verification, and server-side role policies.
"""
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fleet_api.config import FLEET_ENV
from fleet_api.jwt_service import (
    FLEET_JWT_SECRET,
    FLEET_JWT_ALGORITHM,
    FLEET_JWT_ISSUER,
    create_access_token,
    decode_access_token,
)
from fleet_api.session_security import validate_session
from fleet_governance_core.models.approval import AuthenticatedActor
from fleet_governance_core.models.workflow_v4 import ActingRoleEnum

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_actor_and_tenant(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Tuple[str, AuthenticatedActor]:
    """Extract tenant_id and AuthenticatedActor strictly from verified, active JWT session."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_id, actor, session = validate_session(f"Bearer {auth.credentials}")
    return tenant_id, actor


get_tenant_and_actor = get_current_actor_and_tenant


def require_acting_role(required_role: ActingRoleEnum):
    """FastAPI dependency for verifying that the caller's active session possesses the required acting role."""
    def role_checker(
        auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> Tuple[str, AuthenticatedActor]:
        if not auth or not auth.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant_id, actor, session = validate_session(
            f"Bearer {auth.credentials}",
            required_role=required_role,
        )
        return tenant_id, actor

    return role_checker


require_formulator = require_acting_role(ActingRoleEnum.FORMULATOR)
require_product_manager = require_acting_role(ActingRoleEnum.PRODUCT_MANAGER)


def require_roles(allowed_roles: List[str]):
    """FastAPI dependency for verifying that the authenticated actor possesses one of the required roles."""
    def role_checker(
        identity: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
    ) -> Tuple[str, AuthenticatedActor]:
        tenant_id, actor = identity
        if not any(r in allowed_roles for r in actor.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Insufficient privileges for this operation.",
            )
        return tenant_id, actor

    return role_checker


def get_optional_tenant_and_actor(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Tuple[str, AuthenticatedActor]:
    """Extract tenant_id and AuthenticatedActor if provided, otherwise default to tenant-demo."""
    if not auth or not auth.credentials:
        return "tenant-demo", AuthenticatedActor(sub="demo-formulator", email="formulator@demo.fortifiedreg.com", roles=["demo_evaluator"])
    claims = decode_access_token(auth.credentials)
    tenant_id = claims["tenant_id"]
    actor = AuthenticatedActor(
        sub=claims["sub"],
        email=claims.get("email"),
        roles=claims.get("roles", []),
    )
    return tenant_id, actor
