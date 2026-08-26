"""
JWT Service for FortifiedReg Fleet API.
Handles token creation, verification, and decoding with zero circular dependencies.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import jwt
from fastapi import HTTPException, status

FLEET_JWT_SECRET = os.environ.get("FLEET_JWT_SECRET") or secrets.token_hex(32)
FLEET_JWT_ALGORITHM = "HS256"
FLEET_JWT_ISSUER = "fortifiedreg-fleet"
TOKEN_EXPIRATION_MINUTES = 120


def create_access_token(
    tenant_id: str = "tenant-demo",
    sub: str = "",
    roles: Optional[List[str]] = None,
    email: Optional[str] = None,
    expires_in_seconds: Optional[int] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
    acting_role: Optional[str] = None,
    session_id: Optional[str] = None,
    jti: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    custom_claims: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> str:
    """Issue a cryptographically signed HMAC-SHA256 JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    elif expires_in_seconds is not None:
        expire = now + timedelta(seconds=expires_in_seconds)
    else:
        expire = now + timedelta(minutes=TOKEN_EXPIRATION_MINUTES)

    actual_roles = roles if roles is not None else ["demo_evaluator"]

    payload: Dict[str, Any] = {
        "iss": FLEET_JWT_ISSUER,
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": actual_roles,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti or secrets.token_hex(16),
    }
    if email:
        payload["email"] = email
    if session_id:
        payload["session_id"] = session_id
    if acting_role:
        payload["acting_role"] = acting_role

    if extra_claims:
        payload.update(extra_claims)
    if custom_claims:
        payload.update(custom_claims)
    if kwargs:
        payload.update(kwargs)

    secret = os.environ.get("FLEET_JWT_SECRET") or FLEET_JWT_SECRET
    return jwt.encode(payload, secret, algorithm=FLEET_JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and cryptographically verify a JWT access token."""
    secret = os.environ.get("FLEET_JWT_SECRET") or FLEET_JWT_SECRET
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[FLEET_JWT_ALGORITHM],
            options={"verify_signature": True, "require": ["exp", "iss", "sub", "tenant_id", "roles"]},
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
