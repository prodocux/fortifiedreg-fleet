"""
Fleet Adapter PDX Package (v0.3.0).
Provides LivePDXCoreOrchestrator (integrating with pdx_artifact_core) and FakePDXOrchestrator.
"""
from fleet_adapter_pdx.orchestrator import (
    FakePDXOrchestrator,
    LivePDXCoreOrchestrator,
)
from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_adapter_pdx.verifier_bridge import PDXVerifierBridge

__version__ = "0.4.0"
__all__ = [
    "compile_case_to_pdx_plan",
    "PDXVerifierBridge",
    "LivePDXCoreOrchestrator",
    "FakePDXOrchestrator",
]
