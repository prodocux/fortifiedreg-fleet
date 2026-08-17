"""
Model Armor Port Definition.
Defines abstract interface for prompt injection scanning and data loss prevention.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

class ModelArmorPort(ABC):
    @abstractmethod
    def scan_prompt(self, text: str) -> Dict[str, Any]:
        """Scan input text for prompt injection, jailbreak, or malicious content. Fail-closed if unavailable."""
        pass

    @abstractmethod
    def sanitize_output(self, text: str) -> str:
        """Sanitize LLM output to prevent token or credential leakage."""
        pass
