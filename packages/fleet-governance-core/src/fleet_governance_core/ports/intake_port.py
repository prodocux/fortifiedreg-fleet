"""
Intake Port Definition (v0.4.0).
Defines abstract interface for document extraction and rendering adapters.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class IntakePort(ABC):
    @abstractmethod
    def extract_pages(self, document_filename: str, document_bytes: bytes, max_pages: int = 50) -> Dict[str, Any]:
        """Extract text and metadata from input document (legacy page extraction)."""
        pass

    @abstractmethod
    def extract_content_blocks(
        self, document_filename: str, document_bytes: bytes, max_pages: int = 50
    ) -> Dict[str, Any]:
        """Extract neutral universal content blocks (prodocux_content_blocks_v1 with text_items)."""
        pass

    @abstractmethod
    def render_artifact(self, render_request: Dict[str, Any]) -> Dict[str, Any]:
        """Request deterministic artifact binary rendering via prodocux_render_request_v1."""
        pass
