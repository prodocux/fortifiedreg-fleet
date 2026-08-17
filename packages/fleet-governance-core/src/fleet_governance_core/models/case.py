"""
Dossier Case Domain Models.
Implements the canonical dossier_case_v1 schema.
"""
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class JurisdictionEnum(str, Enum):
    EU = "EU"
    TW = "TW"
    US = "US"
    GLOBAL = "GLOBAL"

class DocumentTypeEnum(str, Enum):
    SDS = "SDS"
    COA = "COA"
    IFRA_CERT = "IFRA_CERT"
    GMP_CERT = "GMP_CERT"

class FormulaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inci_name: str = Field(min_length=1, max_length=128)
    cas_number: Optional[str] = Field(default=None, pattern=r"^[0-9]{2,7}-[0-9]{2}-[0-9]$")
    concentration_pct: float = Field(ge=0.0, le=100.0)
    function: Optional[str] = Field(default=None, max_length=64)
    noael_mg_kg_day: Optional[float] = Field(default=None, ge=0.0, le=50000.0)

class ExposureScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_type: str = Field(min_length=1, max_length=128)
    daily_applied_amount_g: float = Field(gt=0.0, le=1000.0)
    retention_factor: float = Field(ge=0.0, le=1.0)
    body_weight_kg: float = Field(gt=0.0, le=300.0)

class SupplierDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_.-]+$")
    media_type: Optional[str] = Field(default=None, max_length=128)
    doc_type: DocumentTypeEnum
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    supplier_name: str = Field(min_length=1, max_length=128)
    issue_date: Optional[str] = None
    expiry_date: str = Field(min_length=10, max_length=32)

class DossierCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    product_name: str = Field(min_length=1, max_length=256)
    jurisdiction: JurisdictionEnum
    formula: List[FormulaItem] = Field(min_length=1, max_length=200)
    exposure_scenario: ExposureScenario
    supplier_documents: List[SupplierDocument] = Field(default_factory=list, max_length=50)
