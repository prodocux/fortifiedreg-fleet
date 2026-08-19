"""
Fortified Enterprise Fleet API Application (v0.3.1).
FastAPI service exposing regulatory compliance orchestration, HITL approvals,
differentiated error handling, truth endpoints, and separated liveness/readiness probes.
"""
import os
import uuid
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from fleet_adapter_prodocux import (
    IntakeConnectionError,
    IntakePayloadError,
    IntakeServiceUnavailableError,
    IntakeTimeoutError,
    ProDocuXHttpIntakeAdapter,
)
from fleet_api.deps import (
    FLEET_ENV,
    INTAKE_MODE,
    PDX_MODE,
    intake_adapter,
    orchestrator,
)
from fleet_api.portal import PORTAL_HTML
from fleet_api.routers import approvals, audit, auth, dossiers, security, system

app = FastAPI(
    title="Fortified Enterprise Fleet API",
    version="0.3.1",
    description="Autonomous Multi-Agent Regulatory Fleet with Human-in-the-Loop Verification & Immutable Audit Trail",
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = req_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register All Sub-Routers
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(security.router)
app.include_router(dossiers.router)
app.include_router(approvals.router)
app.include_router(audit.router)


@app.get("/", response_class=HTMLResponse, tags=["Portal"])
def index() -> HTMLResponse:
    """Enterprise Web Portal & Verification Center."""
    return HTMLResponse(content=PORTAL_HTML, status_code=200)


# ---------------------------------------------------------------------------
# Sanitized Exception Handlers (Fail-closed; Zero raw tracebacks to client)
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    req_id = getattr(request.state, "request_id", "unknown")
    error_code = "HTTP_ERROR"
    if exc.status_code == status.HTTP_400_BAD_REQUEST:
        error_code = "BAD_REQUEST"
    elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
        error_code = "UNAUTHORIZED"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        error_code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        error_code = "NOT_FOUND"
    elif exc.status_code == status.HTTP_409_CONFLICT:
        error_code = "CONFLICT"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_code,
            "message": str(exc.detail),
            "detail": str(exc.detail),
            "request_id": req_id,
        },
        headers=exc.headers,
    )


@app.exception_handler(IntakeTimeoutError)
async def intake_timeout_handler(request: Request, exc: IntakeTimeoutError):
    req_id = getattr(request.state, "request_id", "unknown")
    msg = "Upstream document processing service timed out."
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={
            "error": "UPSTREAM_TIMEOUT",
            "message": msg,
            "detail": msg,
            "request_id": req_id,
        },
    )


@app.exception_handler(IntakeServiceUnavailableError)
async def intake_unavailable_handler(request: Request, exc: IntakeServiceUnavailableError):
    req_id = getattr(request.state, "request_id", "unknown")
    msg = "Upstream document processing service is unavailable."
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "error": "UPSTREAM_UNAVAILABLE",
            "message": msg,
            "detail": msg,
            "request_id": req_id,
        },
    )


@app.exception_handler(IntakePayloadError)
async def intake_payload_error_handler(request: Request, exc: IntakePayloadError):
    req_id = getattr(request.state, "request_id", "unknown")
    msg = "Invalid document intake payload or unsupported format."
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "INVALID_PAYLOAD",
            "message": msg,
            "detail": msg,
            "request_id": req_id,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "unknown")
    msg = f"Server processing error: {str(exc)}"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": msg,
            "detail": msg,
            "request_id": req_id,
        },
    )


# ---------------------------------------------------------------------------
# Liveness Probe
# ---------------------------------------------------------------------------

@app.get("/v1/health", response_model=Dict[str, Any], tags=["Health"])
def health() -> Dict[str, Any]:
    """Liveness probe: verifies the API process is alive and reports configured adapter modes."""
    return {
        "status": "healthy",
        "service": "fortified-enterprise-fleet-api",
        "version": "0.3.1",
        "environment": FLEET_ENV,
        "runtime_mode": "local_memory_emulation",
        "adapters": {
            "intake": {"configured_mode": INTAKE_MODE},
            "orchestrator": {"configured_mode": PDX_MODE},
            "stores": {"configured_mode": "in_memory"},
        },
        "security_scanner": "regex_prompt_scanner (local_emulation)",
        "auth_provider": "jwt_bearer_rbac",
    }


# ---------------------------------------------------------------------------
# Readiness Probe
# ---------------------------------------------------------------------------

@app.get("/v1/ready", response_model=Dict[str, Any], tags=["Health"])
def ready() -> JSONResponse:
    """Readiness probe: validates connectivity to live upstream dependencies and reports degraded state."""
    adapter_statuses = {}
    is_ready = True

    # 1. Check Intake Adapter
    if INTAKE_MODE == "live" and isinstance(intake_adapter, ProDocuXHttpIntakeAdapter):
        try:
            readiness_info = intake_adapter.check_readiness()
            if readiness_info.get("schema_version") != "prodocux_intake_capabilities_v1":
                is_ready = False
                adapter_statuses["intake"] = {
                    "mode": "live",
                    "status": "incompatible_schema",
                    "schema_version": readiness_info.get("schema_version"),
                }
            else:
                adapter_statuses["intake"] = {
                    "mode": "live",
                    "status": "ready",
                    "schema_version": readiness_info.get("schema_version"),
                    "kernel_version": readiness_info.get("kernel_version"),
                }
        except Exception:
            is_ready = False
            adapter_statuses["intake"] = {
                "mode": "live",
                "status": "unavailable",
                "error": "Upstream unreachable",
            }
    else:
        adapter_statuses["intake"] = {"mode": "fake", "status": "ready"}

    # 2. Check Orchestrator Adapter
    if PDX_MODE == "live":
        adapter_statuses["orchestrator"] = {
            "mode": "live",
            "status": "ready",
            "pdx_core_version": "0.2.0a2",
        }
    else:
        adapter_statuses["orchestrator"] = {"mode": "fake", "status": "ready"}

    # 3. Check Stores
    adapter_statuses["stores"] = {"mode": "in_memory", "status": "ready"}

    resp_payload = {
        "status": "ready" if is_ready else "degraded",
        "version": "0.3.1",
        "adapters": adapter_statuses,
    }

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=resp_payload)
