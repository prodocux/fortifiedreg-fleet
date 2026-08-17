"""
Gate 6: Exact-Pin Schema Conformance & Contract Envelope Compatibility Tests.
Directly verifies bidirectional schema & payload compatibility against:
- ProDocuX at exact commit: 7a1d820639910c1d92b31de6eaf0a371f7386182
- PDX Artifact Engine at exact commit: 93ec3514261bf89e9cb88b79f524e3fbc5ef4402
"""
import json
import subprocess
from pathlib import Path
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

PRODOCUX_REPO = Path("D:/ProDocuX/prodocux")
PDX_REPO = Path("D:/ProDocuX/pdx-artifact-engine")
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

PIN_PRODOCUX = "7a1d820639910c1d92b31de6eaf0a371f7386182"
PIN_PDX = "93ec3514261bf89e9cb88b79f524e3fbc5ef4402"

def git_show_file(repo: Path, commit: str, rel_path: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{rel_path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout

def test_exact_upstream_pins_exist_in_git():
    """Verify that both upstream repos can resolve the exact commit pins."""
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
    """Verify that our plan compiler outputs plans conforming to upstream execution_plan.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/execution_plan.v1.schema.json"
    )
    schema = json.loads(schema_str)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case = DossierCase.model_validate(raw_case)
    compiled_plan = compile_case_to_pdx_plan(case)

    validator.validate(compiled_plan)

def test_pdx_approval_request_conformance_against_upstream_schema():
    """Verify that PDXApprovalRequest model conforms to upstream approval_request.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/approval_request.v1.schema.json"
    )
    schema = json.loads(schema_str)
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
    """Verify that PDXApprovalDecision model conforms to upstream approval_decision.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/approval_decision.v1.schema.json"
    )
    schema = json.loads(schema_str)
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
    """Verify that PDXWorkflowCheckpoint model conforms to upstream workflow_checkpoint.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/workflow_checkpoint.v1.schema.json"
    )
    schema = json.loads(schema_str)
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
    """Verify that VerifierResult model conforms to upstream verifier_result.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/verifier_result.v1.schema.json"
    )
    schema = json.loads(schema_str)
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
    """Verify that ArtifactStorageIdentity conforms to upstream artifact_storage_identity.v1.schema.json."""
    schema_str = git_show_file(
        PDX_REPO, PIN_PDX, "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/artifact_storage_identity.v1.schema.json"
    )
    schema = json.loads(schema_str)
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
    """Verify that C1 intake request fixture conforms to upstream prodocux intake_request_v1.json."""
    schema_str = git_show_file(
        PRODOCUX_REPO, PIN_PRODOCUX, "prodocux_kernel/schemas/intake_request_v1.json"
    )
    schema = json.loads(schema_str)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    c1_req = json.loads((FIXTURES_DIR / "c1_intake_request_sample.json").read_text(encoding="utf-8"))["data"]
    validator.validate(c1_req)

def test_prodocux_intake_response_conformance_against_upstream_schema():
    """Verify that C1 intake response fixture conforms to upstream prodocux intake_response_v1.json."""
    schema_str = git_show_file(
        PRODOCUX_REPO, PIN_PRODOCUX, "prodocux_kernel/schemas/intake_response_v1.json"
    )
    schema = json.loads(schema_str)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    c1_resp = json.loads((FIXTURES_DIR / "c1_intake_response_sample.json").read_text(encoding="utf-8"))["data"]
    validator.validate(c1_resp)

def test_prodocux_capabilities_conformance_against_upstream_schema():
    """Verify that prodocux_intake_capabilities_v1 matches upstream capabilities schema."""
    schema_str = git_show_file(
        PRODOCUX_REPO, PIN_PRODOCUX, "prodocux_kernel/schemas/prodocux_intake_capabilities_v1.json"
    )
    schema = json.loads(schema_str)
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
