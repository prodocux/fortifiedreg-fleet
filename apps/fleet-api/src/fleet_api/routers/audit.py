"""
Audit Query Router.
Exposes tenant-isolated, append-only audit event queries for governance verification.
"""
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fleet_api.deps import audit_log, get_tenant_and_actor
from fleet_governance_core.models.approval import AuthenticatedActor

router = APIRouter(prefix="/v1/audit", tags=["Audit"])


@router.get("/events", response_model=Dict[str, Any])
def list_tenant_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> Dict[str, Any]:
    """Retrieve all immutable audit events for the authenticated tenant.
    Tenant ID is bound strictly to the authenticated JWT token claim; caller override is forbidden.
    """
    tenant_id, _ = identity
    events = audit_log.list_all_events(tenant_id=tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "store_mode": "in_memory",
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }


@router.get("/runs/{run_id}", response_model=List[Dict[str, Any]])
def get_run_audit_trail(
    run_id: str,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> List[Dict[str, Any]]:
    """Retrieve all immutable audit events for a given workflow execution run within authenticated tenant boundary."""
    tenant_id, _ = identity
    events = audit_log.list_events_for_run(tenant_id=tenant_id, run_id=run_id)
    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit trail for run '{run_id}' not found in tenant '{tenant_id}'.",
        )
    return [e.model_dump(mode="json") for e in events]
