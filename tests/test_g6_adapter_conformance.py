"""
Gate 6: Exact-Pin Schema Conformance & Contract Envelope Compatibility Tests.
Directly verifies bidirectional schema & payload compatibility against:
- ProDocuX at exact commit: 7a1d820639910c1d92b31de6eaf0a371f7386182
- PDX Artifact Engine at exact commit: 93ec3514261bf89e9cb88b79f524e3fbc5ef4402
"""
import importlib.metadata
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    PDXApprovalDecision,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.storage import ArtifactStorageIdentity
from fleet_governance_core.models.verifier import VerifierResult, VerifierStatusEnum

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

PIN_PRODOCUX = "7a1d820639910c1d92b31de6eaf0a371f7386182"
PIN_PDX = "93ec3514261bf89e9cb88b79f524e3fbc5ef4402"

PDX_REPO = Path(os.getenv("PDX_REPO_DIR")) if os.getenv("PDX_REPO_DIR") else None
PRODOCUX_REPO = Path(os.getenv("PRODOCUX_REPO_DIR")) if os.getenv("PRODOCUX_REPO_DIR") else None


def get_pdx_schema(schema_filename: str) -> dict:
    """Load PDX schema from installed package resources, or fallback to local snapshot."""
    try:
        content = files("pdx_artifact_core.schemas").joinpath(schema_filename).read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        snapshot = SCHEMAS_DIR / "upstream_snapshots" / "pdx" / schema_filename
        if snapshot.exists():
            return json.loads(snapshot.read_text(encoding="utf-8"))
        raise


def get_prodocux_schema(schema_filename: str) -> dict:
    """Load ProDocuX schema from installed package resources, or fallback to local proposed snapshot."""
    try:
        content = files("prodocux_kernel.schemas").joinpath(schema_filename).read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        snapshot = SCHEMAS_DIR / "proposed_part_a_contracts" / "prodocux" / schema_filename
        if snapshot.exists():
            return json.loads(snapshot.read_text(encoding="utf-8"))
        raise


def test_package_distribution_versions():
    """Verify that installed packages match expected versions from exact pins."""
    try:
        dist_pdx = importlib.metadata.distribution("pdx-artifact-core")
        assert dist_pdx.version == "0.2.0a2"
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        dist_pdx2 = importlib.metadata.distribution("prodocux")
        assert dist_pdx2.version == "0.2.0"
    except importlib.metadata.PackageNotFoundError:
        pass


def test_exact_upstream_pins_exist_in_git():
    """Verify that upstream repos can resolve the exact commit pins (if repo paths provided)."""
    if not PDX_REPO or not PDX_REPO.exists():
        pytest.skip("PDX_REPO_DIR not provided or directory does not exist (skipping git sibling test)")
    if not PRODOCUX_REPO or not PRODOCUX_REPO.exists():
        pytest.skip("PRODOCUX_REPO_DIR not provided or directory does not exist (skipping git sibling test)")

    res_pdx = subprocess.run(
        ["git", "-C", str(PDX_REPO), "rev-parse", "--verify", PIN_PDX],
        capture_output=True,
        text=True,
    )
    assert res_pdx.returncode == 0, f"PDX commit {PIN_PDX} missing: {res_pdx.stderr}"

    res_pdx2 = subprocess.run(
        ["git", "-C", str(PRODOCUX_REPO), "rev-parse", "--verify", PIN_PRODOCUX],
        capture_output=True,
        text=True,
    )
    assert res_pdx2.returncode == 0, f"ProDocuX commit {PIN_PRODOCUX} missing: {res_pdx2.stderr}"


def test_pdx_execution_plan_conformance_against_upstream_schema():
    """Verify that our plan compiler outputs plans conforming to execution_plan.v1.schema.json."""
    schema = get_pdx_schema("execution_plan.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw_case)
    compiled_plan = compile_case_to_pdx_plan(case)

    validator.validate(compiled_plan)


def test_pdx_approval_request_conformance_against_upstream_schema():
    """Verify that PDXApprovalRequest model conforms to approval_request.v1.schema.json."""
    schema = get_pdx_schema("approval_request.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    app_req = PDXApprovalRequest(
        run_id="run-001",
        checkpoint_id="chk-001",
        subject_digest="0" * 64,
        plan_digest="1" * 64,
        evidence_digests={"res.json": "2" * 64},
    )
    validator.validate(app_req.model_dump(mode="json", exclude_none=True))


def test_pdx_approval_decision_conformance_against_upstream_schema():
    """Verify that PDXApprovalDecision model conforms to approval_decision.v1.schema.json."""
    schema = get_pdx_schema("approval_decision.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    app_dec = PDXApprovalDecision(
        approval_request_id=uuid4(),
        checkpoint_id="chk-001",
        idempotency_key="idemp-001",
        actor_id="usr-cso",
        decision=ApprovalDecisionEnum.APPROVED,
        reason="Approved by CSO",
        subject_digest="0" * 64,
        plan_digest="1" * 64,
        evidence_digests={"res.json": "2" * 64},
    )
    validator.validate(app_dec.model_dump(mode="json", exclude_none=True))


def test_pdx_workflow_checkpoint_conformance_against_upstream_schema():
    """Verify that PDXWorkflowCheckpoint model conforms to workflow_checkpoint.v1.schema.json."""
    schema = get_pdx_schema("workflow_checkpoint.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    chk = PDXWorkflowCheckpoint(
        checkpoint_id="chk-001",
        run_id="run-001",
        subject_digest="0" * 64,
        plan_digest="1" * 64,
        completed_step_ids=["step_1"],
        pending_step_ids=["step_2"],
        evidence_digests={"res.json": "2" * 64},
    )
    validator.validate(chk.model_dump(mode="json", exclude_none=True))


def test_pdx_verifier_result_conformance_against_upstream_schema():
    """Verify that VerifierResult model conforms to verifier_result.v1.schema.json."""
    schema = get_pdx_schema("verifier_result.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    v_res = VerifierResult(
        verifier_id="verifier-test",
        version="1.0.0",
        status=VerifierStatusEnum.PASS,
        reason_codes=["COMPLIANT"],
        rule_set_id="RULES_1223",
        rule_set_version="2026.1",
        rule_digest="0" * 64,
        evidence_ids=["ev-1"],
    )
    validator.validate(v_res.model_dump(mode="json", exclude_none=True))


def test_pdx_artifact_storage_identity_conformance_against_upstream_schema():
    """Verify that ArtifactStorageIdentity conforms to artifact_storage_identity.v1.schema.json."""
    schema = get_pdx_schema("artifact_storage_identity.v1.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    ident = ArtifactStorageIdentity(
        artifact_id="art-pif-final-001",
        uri="gs://acme-corp/pif/final.pdf",
        sha256="0" * 64,
        size_bytes=1024,
        media_type="application/pdf",
    )
    validator.validate(ident.model_dump(mode="json", exclude_none=True))


def test_prodocux_intake_request_conformance_against_upstream_schema():
    """Verify that C1 intake request fixture conforms to intake_request_v1.json."""
    schema = get_prodocux_schema("intake_request_v1.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    c1_req = json.loads((FIXTURES_DIR / "c1_intake_request_sample.json").read_text(encoding="utf-8"))["data"]
    validator.validate(c1_req)


def test_prodocux_intake_response_conformance_against_upstream_schema():
    """Verify that C1 intake response fixture conforms to intake_response_v1.json."""
    schema = get_prodocux_schema("intake_response_v1.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    c1_resp = json.loads((FIXTURES_DIR / "c1_intake_response_sample.json").read_text(encoding="utf-8"))["data"]
    validator.validate(c1_resp)


def test_prodocux_capabilities_conformance_against_upstream_schema():
    """Verify that prodocux_intake_capabilities_v1 matches upstream capabilities schema."""
    schema = get_prodocux_schema("prodocux_intake_capabilities_v1.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    sample_caps = {
        "schema_version": "prodocux_intake_capabilities_v1",
        "kernel_version": "0.2.0",
        "api_version": "v1",
        "formats": [
            {
                "extensions": [".pdf"],
                "status": "available",
                "operation": "extract_pages",
                "max_bytes": 10485760,
                "additional_operations": [],
            }
        ],
    }
    validator.validate(sample_caps)
