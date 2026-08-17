"""
Intake Port Definition.
Defines abstract interface for document extraction adapters.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

class IntakePort(ABC):
    @abstractmethod
    def extract_pages(self, document_filename: str, document_bytes: bytes, max_pages: int = 50) -> Dict[str, Any]:
        """Extract text and metadata from input document."""
        pass
