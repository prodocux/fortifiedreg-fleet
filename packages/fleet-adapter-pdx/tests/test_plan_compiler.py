"""
Unit Tests for PDX Plan Compiler.
Validates that compiled plans conform strictly to upstream execution_plan.v1.schema.json.
"""
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_governance_core.models.case import DossierCase

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
FIXTURES_DIR = ROOT_DIR / "fixtures"
SCHEMA_PATH = ROOT_DIR / "schemas" / "upstream_snapshots" / "pdx" / "execution_plan.v1.schema.json"

def test_compile_case_to_valid_pdx_plan():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw_case)

    plan = compile_case_to_pdx_plan(case, request_id="req-test-pif-001")
    
    # Must be valid per upstream execution_plan_v1 schema
    validator.validate(plan)

    assert plan["schema_version"] == "pdx_execution_plan_v1"
    assert len(plan["steps"]) >= 4
    step_kinds = [s["kind"] for s in plan["steps"]]
    assert "verify" in step_kinds
    assert "approval" in step_kinds
    assert "transform" in step_kinds
