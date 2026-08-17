"""
Verifier Registry Port Definition.
Defines abstract interface for running pluggable deterministic verifiers.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from fleet_governance_core.models.verifier import VerifierResult

class VerifierRegistryPort(ABC):
    @abstractmethod
    def run_verifier(self, verifier_id: str, payload: Dict[str, Any]) -> VerifierResult:
        """Run a registered verifier against a payload."""
        pass
