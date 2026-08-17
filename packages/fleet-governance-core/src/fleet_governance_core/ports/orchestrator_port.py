"""
Execution Orchestrator Port Definition.
Defines abstract interface for compiling, dispatching, and resuming execution plans with PDX.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
from fleet_governance_core.models.approval import PDXApprovalDecision, PDXWorkflowCheckpoint

class ExecutionOrchestratorPort(ABC):
    @abstractmethod
    def compile_execution_plan(self, case_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Compile a domain case into a deterministic PDX execution plan."""
        pass

    @abstractmethod
    def execute_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a plan up to an approval checkpoint or completion."""
        pass

    @abstractmethod
    def resume_with_decision(self, checkpoint: PDXWorkflowCheckpoint, decision: PDXApprovalDecision) -> Dict[str, Any]:
        """Resume an awaiting checkpoint with a signed approval decision."""
        pass
