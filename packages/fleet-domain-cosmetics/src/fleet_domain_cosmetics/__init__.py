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

__version__ = "0.1.0"
__all__ = [
    "calculate_sed",
    "calculate_mos",
    "evaluate_toxicology_mos",
    "evaluate_inci_compliance",
    "evaluate_supplier_documents",
]
