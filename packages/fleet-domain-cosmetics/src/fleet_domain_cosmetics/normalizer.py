"""
Cosmetics Normalizer (v0.4.0).
Normalizes ProDocuX content blocks / Kernel text_items into structured FormulaItem candidates
with source locations, confidence scores, and safety warnings.
"""
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from fleet_governance_core.models.case import FormulaItem
from fleet_governance_core.models.workflow_v4 import ContentBlockItem, ProDocuXContentBlocksContract


class NormalizedIngredientCandidate(BaseModel):
    """Normalized candidate ingredient extracted from content blocks."""
    inci_name: str
    concentration_pct: float
    cas_number: Optional[str] = None
    noael_mg_kg_day: Optional[float] = None
    source_location: str
    confidence: float = 1.0
    warnings: List[str] = Field(default_factory=list)

    def to_formula_item(self) -> FormulaItem:
        return FormulaItem(
            inci_name=self.inci_name,
            concentration_pct=self.concentration_pct,
            cas_number=self.cas_number,
            noael_mg_kg_day=self.noael_mg_kg_day,
        )


KNOWN_NOAEL_MAP: Dict[str, Tuple[Optional[str], Optional[float]]] = {
    "retinol": ("68-26-8", 2.0),
    "phenoxyethanol": ("122-99-6", 500.0),
    "glycerin": ("56-81-5", 1000.0),
    "aqua": ("7732-18-5", None),
    "water": ("7732-18-5", None),
    "tocopherol": ("59-02-9", 500.0),
    "palmitoyl tripeptide-38": ("1447824-23-8", None),  # Novel peptide missing NOAEL
    "mercury": ("7439-97-6", 0.01),  # Annex II prohibited
}


def normalize_content_blocks(
    contract_or_payload: Union[ProDocuXContentBlocksContract, Dict[str, Any]],
) -> List[NormalizedIngredientCandidate]:
    """
    Deterministically parses ProDocuX universal content blocks or Kernel text_items
    into normalized cosmetics ingredients.
    Does not depend on external LLM; uses robust pattern matching and reference cosmetics nomenclature.
    """
    raw_blocks: List[Tuple[str, str, float]] = []  # (text, source_locator, confidence)

    # 1. Flatten from ProDocuXContentBlocksContract or dict
    if isinstance(contract_or_payload, ProDocuXContentBlocksContract):
        for block in contract_or_payload.blocks:
            raw_blocks.append((block.text, block.source_locator, block.confidence))
    elif isinstance(contract_or_payload, dict):
        # A) Check Kernel 'text_items' list
        if "text_items" in contract_or_payload and isinstance(contract_or_payload["text_items"], list):
            for i, item in enumerate(contract_or_payload["text_items"]):
                if isinstance(item, str):
                    raw_blocks.append((item, f"Item #{i + 1}", 1.0))
                elif isinstance(item, dict):
                    txt = item.get("text") or item.get("value") or ""
                    loc = item.get("source_locator") or item.get("locator") or f"Item #{i + 1}"
                    conf = float(item.get("confidence", 1.0))
                    raw_blocks.append((txt, loc, conf))

        # B) Check nested 'content' or direct 'blocks'
        blocks_source = contract_or_payload.get("blocks")
        if not blocks_source and "content" in contract_or_payload and isinstance(contract_or_payload["content"], dict):
            blocks_source = contract_or_payload["content"].get("blocks")

        if blocks_source and isinstance(blocks_source, list):
            for i, b in enumerate(blocks_source):
                if isinstance(b, dict):
                    b_id = b.get("id", f"block_{i + 1}")
                    b_type = b.get("type", "")

                    if "text" in b and isinstance(b["text"], str):
                        raw_blocks.append((b["text"], b.get("source_locator", b_id), float(b.get("confidence", 1.0))))

                    if "paragraphs" in b and isinstance(b["paragraphs"], list):
                        for p_idx, p in enumerate(b["paragraphs"]):
                            if isinstance(p, str):
                                raw_blocks.append((p, f"{b_id}, Para #{p_idx + 1}", float(b.get("confidence", 1.0))))

                    if "table" in b and isinstance(b["table"], dict):
                        for r_idx, row in enumerate(b["table"].get("rows", [])):
                            if isinstance(row, list):
                                row_str = ": ".join(str(c) for c in row if c)
                                raw_blocks.append((row_str, f"{b_id}, Row #{r_idx + 1}", float(b.get("confidence", 1.0))))

                    if "pairs" in b and isinstance(b["pairs"], list):
                        for pair in b["pairs"]:
                            if isinstance(pair, dict):
                                pair_str = f"{pair.get('label', '')}: {pair.get('value', '')}"
                                raw_blocks.append((pair_str, f"{b_id}, Pair", float(b.get("confidence", 1.0))))

                elif isinstance(b, str):
                    raw_blocks.append((b, f"Block #{i + 1}", 1.0))

    candidates: List[NormalizedIngredientCandidate] = []
    seen_names = set()

    for text, locator, confidence in raw_blocks:
        text_clean = text.strip()
        if not text_clean:
            continue

        # Pattern: Name followed by percentage (e.g. "Retinol 0.05%", "Aqua: 78.5%", "Phenoxyethanol = 0.8%")
        match = re.search(r"([A-Za-z0-9\-\s\(\),]+?)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*%", text_clean)
        if match:
            raw_name = match.group(1).strip().strip(":,()").title()
            pct_val = float(match.group(2))

            clean_key = raw_name.lower().strip()
            if clean_key in seen_names:
                continue
            seen_names.add(clean_key)

            cas, noael = KNOWN_NOAEL_MAP.get(clean_key, (None, None))
            warnings = []
            if "mercury" in clean_key:
                warnings.append("EU Annex II Entry #221 strictly prohibited substance.")
            elif clean_key == "phenoxyethanol" and pct_val > 1.0:
                warnings.append(f"Concentration {pct_val}% exceeds EU Annex V limit (1.0%).")
            elif "tripeptide" in clean_key and noael is None:
                warnings.append("Novel cosmetic peptide: Missing 90-day subchronic oral NOAEL study.")

            candidates.append(
                NormalizedIngredientCandidate(
                    inci_name=raw_name,
                    concentration_pct=pct_val,
                    cas_number=cas,
                    noael_mg_kg_day=noael,
                    source_location=locator,
                    confidence=confidence,
                    warnings=warnings,
                )
            )

    return candidates
