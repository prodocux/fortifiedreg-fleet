"""
FastAPI Dependencies for FortifiedReg Fleet (v0.3.0).
Assembles live or fake adapters into domain services with strict environment gating.
"""
import os
from typing import Tuple
from fastapi import Depends
from pdx_artifact_core.approval import ApprovalLedger

from fleet_adapter_gcp import (
    InMemoryApprovalStore,
    InMemoryArtifactStorageAdapter,
    InMemoryAuditLog,
    InMemoryCheckpointStore,
    InMemoryMemoryStore,
    ThreadSafeDocumentResolver,
)
from fleet_adapter_local import (
    LocalArtifactStore,
    LocalVerifiedArtifactResolver,
    SQLiteResumeContextStore,
)
from fleet_adapter_google_adk import RegexPromptScanner
from fleet_adapter_pdx import (
    FakePDXOrchestrator,
    LivePDXCoreOrchestrator,
    PDXVerifierBridge,
)
from fleet_adapter_prodocux import (
    FakeProDocuXIntakeAdapter,
    ProDocuXHttpIntakeAdapter,
)
from fleet_api.security import get_current_actor_and_tenant, require_roles
from fleet_governance_core.models.approval import AuthenticatedActor
from fleet_governance_core.ports.artifact_content_resolver_port import ArtifactContentResolverPort
from fleet_governance_core.ports.artifact_store_port import ArtifactStorePort
from fleet_governance_core.ports.document_resolver_port import DocumentResolverPort
from fleet_governance_core.ports.intake_port import IntakePort
from fleet_governance_core.ports.orchestrator_port import ExecutionOrchestratorPort
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort
from fleet_governance_core.services.approval_workflow import ApprovalWorkflowService

ALLOWED_ENVS = {"production", "staging", "test", "local", "dev"}
raw_env = os.getenv("FLEET_ENV", "production")
if not raw_env or not raw_env.strip():
    raise ValueError("FLEET_ENV cannot be empty.")
FLEET_ENV = raw_env.strip().lower()
if FLEET_ENV not in ALLOWED_ENVS:
    raise ValueError(f"Invalid FLEET_ENV: '{FLEET_ENV}'. Must be one of {sorted(ALLOWED_ENVS)}.")

# In production/staging, defaults to live; in test/local/dev, defaults to fake
DEFAULT_ADAPTER_MODE = "fake" if FLEET_ENV in ("test", "local", "dev") else "live"
INTAKE_MODE = os.getenv("FLEET_INTAKE_ADAPTER", DEFAULT_ADAPTER_MODE).lower()
PDX_MODE = os.getenv("FLEET_PDX_ADAPTER", DEFAULT_ADAPTER_MODE).lower()

# 1. Validate mode allowlists (prevent silent typos from falling back)
if INTAKE_MODE not in ("live", "fake"):
    raise ValueError(f"Invalid FLEET_INTAKE_ADAPTER: '{INTAKE_MODE}'. Must be 'live' or 'fake'.")

if PDX_MODE not in ("live", "fake"):
    raise ValueError(f"Invalid FLEET_PDX_ADAPTER: '{PDX_MODE}'. Must be 'live' or 'fake'.")

# 2. Fail-closed in production / staging
if FLEET_ENV in ("production", "staging"):
    if INTAKE_MODE == "fake":
        raise RuntimeError(
            "Fail-closed: Fake intake adapter is prohibited in production/staging environment. "
            "Set FLEET_INTAKE_ADAPTER=live or use FLEET_ENV=test/local/dev."
        )
    if PDX_MODE == "fake":
        raise RuntimeError(
            "Fail-closed: Fake PDX orchestrator is prohibited in production/staging environment. "
            "Set FLEET_PDX_ADAPTER=live or use FLEET_ENV=test/local/dev."
        )

# 1. Stores & Persistence (Configurable SQLite Persistence & Local Artifact Store)
FLEET_DB_PATH = os.getenv("FLEET_DB_PATH", ":memory:")
FLEET_ARTIFACTS_DIR = os.getenv("FLEET_ARTIFACTS_DIR", "./.local_artifacts")

resume_context_store = SQLiteResumeContextStore(FLEET_DB_PATH)
approval_store = resume_context_store
checkpoint_store = resume_context_store
audit_log = InMemoryAuditLog()
storage_adapter = InMemoryArtifactStorageAdapter()
document_resolver = ThreadSafeDocumentResolver()
memory_store = InMemoryMemoryStore()
artifact_store = LocalArtifactStore(FLEET_ARTIFACTS_DIR)
artifact_resolver = LocalVerifiedArtifactResolver(artifact_store)

# 2. Shared Long-Lived Approval Ledger & Verifier Bridge
shared_approval_ledger = ApprovalLedger()
verifier_bridge = PDXVerifierBridge()

# 3. Dynamic Intake Adapter Resolution
intake_adapter: IntakePort
if INTAKE_MODE == "live":
    intake_adapter = ProDocuXHttpIntakeAdapter(is_production=(FLEET_ENV not in ("test", "local", "dev")))
else:
    intake_adapter = FakeProDocuXIntakeAdapter()

# 4. Dynamic Orchestrator Resolution
orchestrator: ExecutionOrchestratorPort
if PDX_MODE == "live":
    orchestrator = LivePDXCoreOrchestrator(
        approval_ledger=shared_approval_ledger,
        verifier_bridge=verifier_bridge,
        intake_adapter=intake_adapter,
        document_resolver=document_resolver,
        resume_context_store=resume_context_store,
        artifact_store=artifact_store,
    )
else:
    orchestrator = FakePDXOrchestrator(
        verifier_bridge=verifier_bridge,
        artifact_store=artifact_store,
    )

model_armor = RegexPromptScanner()

# 5. Core Approval Workflow Service
approval_service = ApprovalWorkflowService(
    approval_store=approval_store,
    audit_log=audit_log,
    checkpoint_store=checkpoint_store,
    resume_context_store=resume_context_store,
)

from fleet_governance_core.ports.approval_store_port import ApprovalStorePort
from fleet_governance_core.ports.audit_log_port import AuditLogPort
from fleet_governance_core.ports.checkpoint_store_port import CheckpointStorePort

def get_checkpoint_store() -> CheckpointStorePort:
    return checkpoint_store

def get_approval_store() -> ApprovalStorePort:
    return approval_store

def get_audit_log() -> AuditLogPort:
    return audit_log

def get_approval_workflow_service() -> ApprovalWorkflowService:
    return ApprovalWorkflowService(
        approval_store=approval_store,
        audit_log=audit_log,
        checkpoint_store=checkpoint_store,
        resume_context_store=resume_context_store,
    )

def get_orchestrator() -> ExecutionOrchestratorPort:
    return orchestrator

def get_document_resolver() -> DocumentResolverPort:
    return document_resolver

def get_resume_context_store() -> ResumeContextStorePort:
    return resume_context_store

def get_artifact_store() -> ArtifactStorePort:
    return artifact_store

def get_artifact_resolver() -> ArtifactContentResolverPort:
    return artifact_resolver

def get_tenant_and_actor(
    identity: Tuple[str, AuthenticatedActor] = Depends(get_current_actor_and_tenant),
) -> Tuple[str, AuthenticatedActor]:
    return identity

def get_approver_identity(
    identity: Tuple[str, AuthenticatedActor] = Depends(
        require_roles(["approver", "regulatory_approver", "safety_assessor", "cso"])
    ),
) -> Tuple[str, AuthenticatedActor]:
    return identity
