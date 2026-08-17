"""
Unit Tests for FakePDXOrchestrator.
"""
import json
from pathlib import Path
from fleet_adapter_pdx.orchestrator import FakePDXOrchestrator
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    PDXApprovalDecision,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.hashing import compute_data_sha256

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"

def test_orchestrator_execution_to_approval_checkpoint():
    orchestrator = FakePDXOrchestrator()

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    plan = orchestrator.compile_execution_plan(raw_case)

    res = orchestrator.execute_plan(plan, case_payload=raw_case)

    assert res["status"] == "awaiting_approval"
    chk_data = res["checkpoint"]
    assert chk_data["status"] == "pending"
    assert "step_verify_inci_compliance" in chk_data["completed_step_ids"]
    assert "step_verify_toxicology_mos" in chk_data["completed_step_ids"]
    assert "step_human_regulatory_approval" in chk_data["pending_step_ids"]

def test_orchestrator_early_stop_on_toxicology_fail():
    orchestrator = FakePDXOrchestrator()

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_toxicology_fail.json").read_text(encoding="utf-8"))["data"]
    plan = orchestrator.compile_execution_plan(raw_case)

    res = orchestrator.execute_plan(plan, case_payload=raw_case)

    assert res["status"] == "failed"
    assert res["failed_step"] == "step_verify_inci_compliance"  # Phenoxyethanol exceeded

def test_orchestrator_blocked_on_review_state():
    orchestrator = FakePDXOrchestrator()

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_missing_data.json").read_text(encoding="utf-8"))["data"]
    plan = orchestrator.compile_execution_plan(raw_case)

    res = orchestrator.execute_plan(plan, case_payload=raw_case)

    # Must block on review without proceeding to approval
    assert res["status"] == "blocked_review"
    assert res["review_step"] == "step_verify_toxicology_mos"
    assert res["verifier_result"]["status"] == "review"
    assert "MISSING_NOAEL_EVIDENCE" in res["verifier_result"]["reason_codes"]

def test_orchestrator_resume_with_approved_decision():
    orchestrator = FakePDXOrchestrator()

    raw_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    case_digest = compute_data_sha256(raw_case)

    checkpoint = PDXWorkflowCheckpoint(
        checkpoint_id="chk-step-human_approval-001",
        run_id="run-test-001",
        subject_digest=case_digest,
        plan_digest="b" * 64,
        completed_step_ids=["step_extract_docs", "step_verify_inci", "step_verify_mos"],
        pending_step_ids=["step_human_approval"],
        evidence_digests={},
    )

    decision = PDXApprovalDecision(
        decision_id="55555555-5555-4555-8555-555555555555",
        approval_request_id="44444444-4444-4444-8444-444444444444",
        checkpoint_id=checkpoint.checkpoint_id,
        idempotency_key="idemp-001",
        actor_id="usr-cso",
        decision=ApprovalDecisionEnum.APPROVED,
        reason="Approved by CSO",
        subject_digest=case_digest,
        plan_digest="b" * 64,
    )

    resume_res = orchestrator.resume_with_decision(checkpoint, decision)
    assert resume_res["status"] == "completed"
    assert "final_manifest" in resume_res
    assert resume_res["final_manifest"]["status"] == "FINALIZED_COMPLIANT"
