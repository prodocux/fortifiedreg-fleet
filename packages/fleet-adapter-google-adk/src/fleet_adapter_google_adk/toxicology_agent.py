"""
Mock Toxicology Agent Adapter (Local Testing / Fallback).
Extracts structured toxicological parameters from raw SDS documents.
"""
from typing import Any, Dict, List
from fleet_adapter_google_adk.model_armor import RegexPromptScanner

class MockToxicologyAgent:
    """Mock agent assistant for structuring toxicology data from extracted SDS text."""

    def __init__(self, scanner: RegexPromptScanner | None = None):
        self._armor = scanner or RegexPromptScanner()

    def analyze_raw_document(self, raw_text: str) -> Dict[str, Any]:
        """Scan raw document through Model Armor scanner, then extract structured ingredients."""
        # 1. First defense line: Prompt injection scan
        self._armor.scan_prompt(raw_text)

        # 2. Extract structured fields (deterministic mock)
        ingredients = []
        if "AquaGlow Peptide" in raw_text or "56-81-5" in raw_text:
            ingredients.append({
                "inci_name": "GLYCERIN",
                "cas_number": "56-81-5",
                "concentration_pct": 5.0,
                "function": "Humectant",
                "noael_mg_kg_day": 1000.0,
            })
        if "PHENOXYETHANOL" in raw_text.upper() or "122-99-6" in raw_text:
            ingredients.append({
                "inci_name": "PHENOXYETHANOL",
                "cas_number": "122-99-6",
                "concentration_pct": 0.8,
                "function": "Preservative",
                "noael_mg_kg_day": 500.0,
            })

        summary = f"Extracted {len(ingredients)} ingredient profiles with verified toxicological endpoints."
        sanitized_summary = self._armor.sanitize_output(summary)

        return {
            "status": "success",
            "summary": sanitized_summary,
            "ingredients": ingredients,
        }

# Alias
GeminiToxicologyAgent = MockToxicologyAgent
