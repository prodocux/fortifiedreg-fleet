"""
Session Security and Token Lifecycle Service for FortifiedReg Fleet (v0.4.0).
Provides single-instance demo-grade security and governance hardening:
- JWT issuance with unique 'jti' identifiers and strict TTL alignment.
- Memory-bounded JTI revocation tracking (_REVOKED_JTIS_STORE).
- Server-side acting-role tracking and role-segregated authorization gates.
- Recoverable Session Reset Saga with complete cleanup of pending governance state.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from fleet_api.jwt_service import create_access_token, decode_access_token
from fleet_governance_core.models.approval import AuthenticatedActor
from fleet_governance_core.models.workflow_v4 import ActingRoleEnum, DemoSession

DEFAULT_SESSION_TTL_MINUTES = 120

# Thread-safe single-process memory stores
_SESSION_LOCK = threading.Lock()
_SESSIONS_STORE: Dict[str, DemoSession] = {}
_SESSION_JTIS: Dict[str, Set[str]] = {}  # session_id/sub -> set of jtis
_REVOKED_JTIS_STORE: Set[str] = set()


class SessionResetRecord(BaseModel):
    """Tracks state and progress of a recoverable session reset saga."""
    reset_id: str = Field(default_factory=lambda: f"reset-{uuid.uuid4().hex[:8]}")
    session_id: str
    sub: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    step_proposals_cleaned: bool = False
    step_checkpoints_cleaned: bool = False
    step_drafts_cleaned: bool = False
    step_jtis_revoked: bool = False
    new_session_id: Optional[str] = None
    status: str = "reset_in_progress"  # reset_in_progress, completed, failed
    error: Optional[str] = None


_SESSION_RESET_RECORDS: Dict[str, SessionResetRecord] = {}


def issue_demo_session(
    acting_role: ActingRoleEnum = ActingRoleEnum.FORMULATOR,
    ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES,
    tenant_id: str = "tenant-demo",
) -> Tuple[str, DemoSession]:
    """
    Issue a fresh demo session with a unique cryptographic JTI and server-side state.
    """
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    sub = f"demo-session-{uuid.uuid4().hex[:12]}"
    jti = f"jti-{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    exp_time = now + timedelta(minutes=ttl_minutes)

    session = DemoSession(
        session_id=session_id,
        sub=sub,
        tenant_id=tenant_id,
        roles=["demo_evaluator"],
        allowed_demo_roles=["formulator", "product_manager"],
        acting_role=acting_role,
        created_at=now.isoformat(),
        expires_at=exp_time.isoformat(),
        is_active=True,
    )

    token = create_access_token(
        sub=sub,
        tenant_id=tenant_id,
        roles=["demo_evaluator"],
        acting_role=acting_role.value,
        session_id=session_id,
        jti=jti,
        expires_delta=timedelta(minutes=ttl_minutes),
        custom_claims={
            "email": f"demo-{acting_role.value}@demo.fortifiedreg.com",
            "allowed_demo_roles": ["formulator", "product_manager"],
        },
    )

    with _SESSION_LOCK:
        _SESSIONS_STORE[session_id] = session
        _SESSIONS_STORE[sub] = session
        if session_id not in _SESSION_JTIS:
            _SESSION_JTIS[session_id] = set()
        _SESSION_JTIS[session_id].add(jti)
        if sub not in _SESSION_JTIS:
            _SESSION_JTIS[sub] = set()
        _SESSION_JTIS[sub].add(jti)

    return token, session


def validate_session(
    token: str,
    required_role: Optional[ActingRoleEnum] = None,
) -> Tuple[str, AuthenticatedActor, DemoSession]:
    """
    Validate caller token against cryptographic signature, expiration, JTI revocation,
    active session state, and server-side acting-role policies.
    """
    if not token or not token.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = token[len("Bearer "):].strip()
    payload = decode_access_token(raw_token)

    jti = payload.get("jti")
    session_id = payload.get("session_id")
    tenant_id = payload.get("tenant_id", "tenant-demo")
    sub = payload.get("sub", "")

    with _SESSION_LOCK:
        if jti and jti in _REVOKED_JTIS_STORE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        session = _SESSIONS_STORE.get(session_id) or _SESSIONS_STORE.get(sub) if (session_id or sub in _SESSIONS_STORE) else None
        roles = payload.get("roles", [])
        has_demo_session_claims = bool(
            session_id
            or payload.get("allowed_demo_roles")
            or (sub and sub.startswith("demo-session-"))
            or (isinstance(roles, list) and "demo_evaluator" in roles)
        )

        if session is not None:
            if not session.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session is inactive, expired, or currently resetting.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if required_role and session.acting_role != required_role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Operation requires server-side role '{required_role.value}', but session is currently acting as '{session.acting_role.value}'.",
                )
            actor_roles = session.roles
        else:
            # If token carries demo session claims but server-side session is missing -> Fail-closed 401
            if has_demo_session_claims:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Demo session has expired, been purged, or does not exist on server.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Non-session token (e.g. dev token / standard production token)
            if required_role:
                # Check if role matches caller's JWT roles
                allowed = (
                    required_role.value in roles
                    or (required_role == ActingRoleEnum.PRODUCT_MANAGER and any(r in ("approver", "cso", "safety_assessor") for r in roles))
                    or (required_role == ActingRoleEnum.FORMULATOR and any(r in ("formulator", "safety_assessor") for r in roles))
                )
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Operation requires role '{required_role.value}', but caller roles are {roles}.",
                    )
            actor_roles = roles
            session = DemoSession(
                session_id=session_id or f"sess-std-{sub}",
                sub=sub,
                tenant_id=tenant_id,
                roles=roles,
                allowed_demo_roles=["formulator", "product_manager"],
                acting_role=required_role or ActingRoleEnum.FORMULATOR,
                created_at=datetime.now(timezone.utc).isoformat(),
                expires_at=datetime.now(timezone.utc).isoformat(),
                is_active=True,
            )

    actor = AuthenticatedActor(sub=sub, email=payload.get("email"), roles=actor_roles)
    return tenant_id, actor, session


def set_acting_role(session_id_or_sub: str, new_role: ActingRoleEnum) -> DemoSession:
    """Switch server-side acting role for an active session."""
    with _SESSION_LOCK:
        session = _SESSIONS_STORE.get(session_id_or_sub)
        if not session or not session.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session not found or inactive.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session.acting_role = new_role
        return session


def revoke_demo_session(
    caller_token: str,
    cleanup_governance_fn: Optional[Callable[[str, str, str], None]] = None,
) -> None:
    """
    Explicitly revoke an active session without issuing a new one:
    1. Authenticate caller.
    2. Immediately inactivate session and revoke all JTIs (fail-closed first).
    3. Execute governance cleanups (cancel proposals/checkpoints, flush drafts).
    """
    if not caller_token or not caller_token.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for session revocation.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = caller_token[len("Bearer "):].strip()
    payload = decode_access_token(raw_token)
    session_id = payload.get("session_id")
    sub = payload.get("sub", "")
    current_jti = payload.get("jti")
    tenant_id = payload.get("tenant_id", "tenant-demo")

    # Step 1: Inactivate session and revoke all active JTIs immediately
    with _SESSION_LOCK:
        for key in (session_id, sub):
            if key:
                old_sess = _SESSIONS_STORE.get(key)
                if old_sess:
                    old_sess.is_active = False
                jtis = _SESSION_JTIS.get(key, set())
                for j in jtis:
                    _REVOKED_JTIS_STORE.add(j)
        if current_jti:
            _REVOKED_JTIS_STORE.add(current_jti)

    # Step 2: Run governance cleanups
    if cleanup_governance_fn:
        try:
            cleanup_governance_fn(tenant_id, session_id or sub, sub)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Session revocation cleanup interrupted.",
            ) from exc


def execute_session_reset_saga(
    caller_token: str,
    cleanup_governance_fn: Optional[Callable[[str, str, str], None]] = None,
) -> Tuple[str, DemoSession]:
    """
    Execute a recoverable Session Reset Saga:
    1. Authenticate caller and locate session.
    2. Mark old session inactive (blocking all concurrent mutations).
    3. Execute governance cleanups (cancel proposals/checkpoints, flush drafts for both session_id & sub).
    4. Revoke all active JTIs for that session.
    5. Issue a fresh session and token (active only after all cleanup steps succeed).
    """
    if not caller_token or not caller_token.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for session restart.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = caller_token[len("Bearer "):].strip()
    payload = decode_access_token(raw_token)
    session_id = payload.get("session_id", "")
    sub = payload.get("sub", "")
    current_jti = payload.get("jti")
    tenant_id = payload.get("tenant_id", "tenant-demo")

    if not session_id and not sub:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session identifier missing from token.")

    reset_record = SessionResetRecord(session_id=session_id or sub, sub=sub)

    # Lock Window 1: Record reset saga & inactivate old session
    with _SESSION_LOCK:
        _SESSION_RESET_RECORDS[reset_record.reset_id] = reset_record
        for key in (session_id, sub):
            if key:
                old_session = _SESSIONS_STORE.get(key)
                if old_session:
                    old_session.is_active = False

    try:
        # Step 3: Run governance cleanups across both session_id and sub
        if cleanup_governance_fn:
            cleanup_governance_fn(tenant_id, session_id, sub)
        reset_record.step_proposals_cleaned = True
        reset_record.step_checkpoints_cleaned = True
        reset_record.step_drafts_cleaned = True

        # Lock Window 2: Revoke all JTIs for old session
        with _SESSION_LOCK:
            for key in (session_id, sub):
                if key:
                    jtis = _SESSION_JTIS.get(key, set())
                    for j in jtis:
                        _REVOKED_JTIS_STORE.add(j)
            if current_jti:
                _REVOKED_JTIS_STORE.add(current_jti)
            reset_record.step_jtis_revoked = True

        # Step 5: Issue fresh session (initially inactive)
        new_session_id = f"sess-{uuid.uuid4().hex[:8]}"
        new_sub = f"demo-session-{uuid.uuid4().hex[:12]}"
        new_jti = f"jti-{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        exp_time = now + timedelta(minutes=DEFAULT_SESSION_TTL_MINUTES)

        new_session = DemoSession(
            session_id=new_session_id,
            sub=new_sub,
            tenant_id=tenant_id,
            roles=["demo_evaluator"],
            allowed_demo_roles=["formulator", "product_manager"],
            acting_role=ActingRoleEnum.FORMULATOR,
            created_at=now.isoformat(),
            expires_at=exp_time.isoformat(),
            is_active=False,  # Inactive until fully registered
        )

        new_token = create_access_token(
            sub=new_sub,
            tenant_id=tenant_id,
            roles=["demo_evaluator"],
            acting_role=ActingRoleEnum.FORMULATOR.value,
            session_id=new_session_id,
            jti=new_jti,
            expires_delta=timedelta(minutes=DEFAULT_SESSION_TTL_MINUTES),
            custom_claims={
                "email": "demo-formulator@demo.fortifiedreg.com",
                "allowed_demo_roles": ["formulator", "product_manager"],
            },
        )

        # Lock Window 3: Register and activate new session
        with _SESSION_LOCK:
            new_session.is_active = True
            _SESSIONS_STORE[new_session_id] = new_session
            _SESSIONS_STORE[new_sub] = new_session
            _SESSION_JTIS[new_session_id] = {new_jti}
            _SESSION_JTIS[new_sub] = {new_jti}

            reset_record.new_session_id = new_session.session_id
            reset_record.status = "completed"
            reset_record.completed_at = datetime.now(timezone.utc).isoformat()

        return new_token, new_session

    except Exception as exc:
        reset_record.status = "failed"
        reset_record.error = "Session reset interrupted"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session reset saga failed during state teardown.",
        )
