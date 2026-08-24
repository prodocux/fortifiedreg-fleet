"""
Fleet Domain Cosmetics Package.
"""
from fleet_domain_cosmetics.mos_calculator import (
    calculate_sed,
    calculate_mos,
    evaluate_toxicology_mos,
)
from fleet_domain_cosmetics.inci_verifier import evaluate_inci_compliance
from fleet_domain_cosmetics.document_verifier import evaluate_supplier_documents

from fleet_domain_cosmetics.normalizer import (
    NormalizedIngredientCandidate,
    normalize_content_blocks,
)
from fleet_domain_cosmetics.export_spec_mapper import (
    map_approved_product_to_render_bundle,
    map_bundle_to_prodocux_render_requests,
)

__version__ = "0.4.0"
__all__ = [
    "calculate_sed",
    "calculate_mos",
    "evaluate_toxicology_mos",
    "evaluate_inci_compliance",
    "evaluate_supplier_documents",
    "NormalizedIngredientCandidate",
    "normalize_content_blocks",
    "map_approved_product_to_render_bundle",
    "map_bundle_to_prodocux_render_requests",
]
