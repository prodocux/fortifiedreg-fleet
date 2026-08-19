"""
JWT Authentication & Role-Based Access Control (RBAC) Module.
Enforces fail-closed token validation, environment-gated secret management, and sanitized error responses.
"""
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from fleet_governance_core.models.approval import AuthenticatedActor

from fleet_api.config import (
    FLEET_ENV,
    FLEET_JWT_SECRET,
    FLEET_JWT_ALGORITHM,
    FLEET_JWT_ISSUER,
)

bearer_scheme = HTTPBearer(auto_error=False)

def create_access_token(
    tenant_id: str,
    sub: str,
    roles: List[str],
    email: Optional[str] = None,
    expires_in_seconds: int = 3600,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a signed JWT access token."""
    now = int(time.time())
    payload: Dict[str, Any] = {
        "iss": FLEET_JWT_ISSUER,
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": roles,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if email:
        payload["email"] = email
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, FLEET_JWT_SECRET, algorithm=FLEET_JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and verify JWT token signature and claims."""
    try:
        payload = jwt.decode(
            token,
            FLEET_JWT_SECRET,
            algorithms=[FLEET_JWT_ALGORITHM],
            issuer=FLEET_JWT_ISSUER,
            options={"require": ["exp", "iss", "sub", "tenant_id", "roles"]},
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

def get_current_actor_and_tenant(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> tuple[str, AuthenticatedActor]:
    """Extract tenant_id and AuthenticatedActor strictly from verified JWT token."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_access_token(auth.credentials)
    tenant_id = claims["tenant_id"]
    actor = AuthenticatedActor(
        sub=claims["sub"],
        email=claims.get("email"),
        roles=claims.get("roles", []),
    )
    return tenant_id, actor

def require_roles(allowed_roles: List[str]):
    """FastAPI dependency for verifying that the authenticated actor possesses one of the required roles."""
    def role_checker(
        identity: tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
    ) -> tuple[str, AuthenticatedActor]:
        tenant_id, actor = identity
        if not any(r in allowed_roles for r in actor.roles):
            # Sanitized error message: do not leak internal role matrix or actor details
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Insufficient privileges for this operation.",
            )
        return tenant_id, actor

    return role_checker
