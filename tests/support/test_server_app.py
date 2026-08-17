"""
Test Support Uvicorn entrypoint for failure injection testing.
Injects FailOnceArtifactStore only when TEST_FAIL_ONCE_TRIGGER_FILE is provided.
"""
import os
from pathlib import Path

from fleet_api.main import app
import fleet_api.deps as deps
from tests.support.fail_once_store import FailOnceArtifactStore

trigger_path = os.getenv("TEST_FAIL_ONCE_TRIGGER_FILE")
if trigger_path:
    deps.artifact_store = FailOnceArtifactStore(deps.FLEET_ARTIFACTS_DIR, trigger_path)
    deps.artifact_resolver = deps.LocalVerifiedArtifactResolver(deps.artifact_store)
    if deps.PDX_MODE == "live":
        deps.orchestrator = deps.LivePDXCoreOrchestrator(
            approval_ledger=deps.shared_approval_ledger,
            verifier_bridge=deps.verifier_bridge,
            intake_adapter=deps.intake_adapter,
            document_resolver=deps.document_resolver,
            resume_context_store=deps.resume_context_store,
            artifact_store=deps.artifact_store,
        )
    else:
        deps.orchestrator = deps.FakePDXOrchestrator(
            verifier_bridge=deps.verifier_bridge,
            artifact_store=deps.artifact_store,
        )
