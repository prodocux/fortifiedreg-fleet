"""
Audit Query Router.
Exposes append-only immutable audit trail for governance verification.
"""
from typing import Any, Dict, List, Tuple
from fastapi import APIRouter, Depends
from fleet_api.deps import audit_log, get_tenant_and_actor
from fleet_governance_core.models.approval import AuthenticatedActor

router = APIRouter(prefix="/v1/audit", tags=["Audit"])

@router.get("/runs/{run_id}", response_model=List[Dict[str, Any]])
def get_run_audit_trail(
    run_id: str,
    identity: Tuple[str, AuthenticatedActor] = Depends(get_tenant_and_actor),
) -> List[Dict[str, Any]]:
    """Retrieve all immutable audit events for a given workflow execution run."""
    tenant_id, _ = identity
    events = audit_log.list_events_for_run(tenant_id=tenant_id, run_id=run_id)
    return [e.model_dump(mode="json") for e in events]
