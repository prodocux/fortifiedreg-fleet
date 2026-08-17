#!/usr/bin/env python3
"""
Generate G1 Synthetic Contract Fixtures with Exact Canonical data_sha256,
Proper Provenance Metadata (upstream_snapshot vs proposed_g1 vs fleet_owned),
and Clean Directory Initialization.
"""
import hashlib
import json
import shutil
from pathlib import Path

PDX_COMMIT = "93ec3514261bf89e9cb88b79f524e3fbc5ef4402"
FLEET_COMMIT = "UNCOMMITTED_G1_DRAFT"


PRODOCUX_REPO = "prodocux/prodocux"
PDX_REPO = "prodocux/pdx-artifact-engine"
FLEET_REPO = "prodocux/fortifiedreg-fleet"

def canonical_hash(data: dict) -> str:
    canonical_json = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

def make_upstream_snapshot_fixture(schema_id: str, version: str, data: dict, upstream_repo: str, commit_sha: str, source_path: str, source_blob_sha256: str, snapshot_mode: str = "byte_exact") -> dict:
    return {
        "_metadata": {
            "contract_status": "upstream_snapshot",
            "schema_id": schema_id,
            "schema_version": version,
            "upstream_repo": upstream_repo,
            "source_commit": commit_sha,
            "source_path": source_path,
            "source_blob_sha256": source_blob_sha256,
            "snapshot_mode": snapshot_mode,
            "data_sha256": canonical_hash(data),
            "synthetic_data_declaration": "This fixture contains 100% synthetic fictitious cosmetic brand, formula, and supplier data created solely for automated testing."
        },
        "data": data
    }

def make_proposed_contract_fixture(schema_id: str, version: str, data: dict, target_owner: str, target_gate: str) -> dict:
    return {
        "_metadata": {
            "contract_status": "proposed_g1",
            "schema_id": schema_id,
            "schema_version": version,
            "target_owner": target_owner,
            "target_gate": target_gate,
            "source_commit": None,
            "data_sha256": canonical_hash(data),
            "synthetic_data_declaration": "This fixture contains 100% synthetic fictitious cosmetic brand, formula, and supplier data created solely for automated testing."
        },
        "data": data
    }

def make_fleet_owned_fixture(schema_id: str, version: str, data: dict) -> dict:
    return {
        "_metadata": {
            "contract_status": "fleet_owned",
            "schema_id": schema_id,
            "schema_version": version,
            "upstream_repo": FLEET_REPO,
            "source_commit": FLEET_COMMIT,
            "data_sha256": canonical_hash(data),
            "synthetic_data_declaration": "This fixture contains 100% synthetic fictitious cosmetic brand, formula, and supplier data created solely for automated testing."
        },
        "data": data
    }

def main():
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
    
    # 1. Clean existing fixtures to avoid stale files
    if fixtures_dir.exists():
        shutil.rmtree(fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. C1 Intake Request Sample (Proposed Part A - ProDocuX / G2)
    c1_req_data = {
        "document_filename": "synthetic_sds_aquaglow_peptide.pdf",
        "document_b64": "JVBERi0xLjQKJcTl8uXrp/Og0MTGCjQgMCBvYmoKPDwKL0ZpbHRlciAvRmxhdGVEZWNvZGUKL0xlbmd0aCAxMC4uLgo=",
        "max_pages": 50
    }
    (fixtures_dir / "c1_intake_request_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("intake_request_v1", "1.0.0", c1_req_data, PRODOCUX_REPO, "G2"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 2. C1 Intake Response Sample (Proposed Part A - ProDocuX / G2)
    c1_resp_data = {
        "status": "success",
        "source_sha256": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "page_count": 3,
        "pages": [
            {"page_number": 1, "text": "SYNTHETIC RAW MATERIAL SAFETY DATA SHEET\nProduct: AquaGlow Peptide\nSupplier: BioSynthetics Ltd\nCAS: 56-81-5", "ocr_required": False},
            {"page_number": 2, "text": "SECTION 9: Physical and Chemical Properties\nPurity: 99.5%\nHeavy metals: < 10 ppm", "ocr_required": False},
            {"page_number": 3, "text": "SECTION 11: Toxicological Information\nNOAEL (oral, rat): 1000 mg/kg bw/day\nSkin irritation: Non-irritant", "ocr_required": False}
        ],
        "truncation": {"truncated": False, "total_characters": 350}
    }
    (fixtures_dir / "c1_intake_response_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("intake_response_v1", "1.0.0", c1_resp_data, PRODOCUX_REPO, "G2"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 3. C2 Dossier Case Happy Path (Fleet Owned)
    c2_happy = {
        "case_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "tenant-acme-corp",
        "product_name": "Synthetic Radiant Face Cream",
        "jurisdiction": "EU",
        "formula": [
            {"inci_name": "AQUA", "cas_number": "7732-18-5", "concentration_pct": 75.0, "function": "Solvent", "noael_mg_kg_day": 2000.0},
            {"inci_name": "GLYCERIN", "cas_number": "56-81-5", "concentration_pct": 5.0, "function": "Humectant", "noael_mg_kg_day": 1000.0},
            {"inci_name": "NIACINAMIDE", "cas_number": "98-92-0", "concentration_pct": 2.0, "function": "Skin Conditioning", "noael_mg_kg_day": 800.0},
            {"inci_name": "PHENOXYETHANOL", "cas_number": "122-99-6", "concentration_pct": 0.8, "function": "Preservative", "noael_mg_kg_day": 500.0}
        ],
        "exposure_scenario": {
            "product_type": "Face Cream (Leave-on)",
            "daily_applied_amount_g": 1.54,
            "retention_factor": 1.0,
            "body_weight_kg": 60.0
        },
        "supplier_documents": [
            {
                "doc_id": "doc-sds-001",
                "filename": "doc-sds-001.pdf",
                "doc_type": "SDS",
                "sha256": "b1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
                "supplier_name": "BioSynthetics Ltd",
                "issue_date": "2025-01-10",
                "expiry_date": "2028-01-10"
            }
        ]
    }
    (fixtures_dir / "c2_dossier_case_happy_path.json").write_text(
        json.dumps(make_fleet_owned_fixture("dossier_case_v1", "1.1.0", c2_happy), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 4. C2 Dossier Case Toxicology Fail (Fleet Owned)
    c2_tox_fail = {
        "case_id": "22222222-2222-4222-8222-222222222222",
        "tenant_id": "tenant-acme-corp",
        "product_name": "Synthetic Overdose Preservative Serum",
        "jurisdiction": "EU",
        "formula": [
            {"inci_name": "AQUA", "cas_number": "7732-18-5", "concentration_pct": 97.5, "function": "Solvent", "noael_mg_kg_day": 2000.0},
            {"inci_name": "PHENOXYETHANOL", "cas_number": "122-99-6", "concentration_pct": 2.5, "function": "Preservative", "noael_mg_kg_day": 50.0}
        ],
        "exposure_scenario": {
            "product_type": "Face Cream (Leave-on)",
            "daily_applied_amount_g": 1.54,
            "retention_factor": 1.0,
            "body_weight_kg": 60.0
        },
        "supplier_documents": []
    }
    (fixtures_dir / "c2_dossier_case_toxicology_fail.json").write_text(
        json.dumps(make_fleet_owned_fixture("dossier_case_v1", "1.1.0", c2_tox_fail), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 5. C2 Dossier Case Missing Data (Fleet Owned)
    c2_missing = {
        "case_id": "33333333-3333-4333-8333-333333333333",
        "tenant_id": "tenant-acme-corp",
        "product_name": "Synthetic Unverified Peptide Essence",
        "jurisdiction": "EU",
        "formula": [
            {"inci_name": "AQUA", "cas_number": "7732-18-5", "concentration_pct": 98.0, "function": "Solvent", "noael_mg_kg_day": 2000.0},
            {"inci_name": "COPPER TRIPEPTIDE-1", "cas_number": "89030-95-5", "concentration_pct": 2.0, "function": "Active"}
        ],
        "exposure_scenario": {
            "product_type": "Face Cream (Leave-on)",
            "daily_applied_amount_g": 1.54,
            "retention_factor": 1.0,
            "body_weight_kg": 60.0
        },
        "supplier_documents": []
    }
    (fixtures_dir / "c2_dossier_case_missing_data.json").write_text(
        json.dumps(make_fleet_owned_fixture("dossier_case_v1", "1.1.0", c2_missing), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 6. C2 PDX Execution Plan Conformance Sample (Real Upstream Snapshot from PDX)
    c2_pdx_plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "req-pif-compile-001",
        "producer": {
            "type": "fleet_compiler",
            "name": "fleet-adapter-pdx"
        },
        "intent": {
            "summary": "Compile and verify cosmetics PIF dossier"
        },
        "steps": [
            {
                "id": "step_extract_sds",
                "kind": "tool",
                "tool": "prodocux.extract_pages",
                "inputs": {
                    "document_filename": "sds.pdf"
                },
                "outputs": ["sds_text"]
            },
            {
                "id": "step_verify_toxicology",
                "kind": "verify",
                "depends_on": ["step_extract_sds"],
                "verification": [
                    {
                        "id": "chk_mos_threshold",
                        "check": "verifier-cosmetics-toxicology-mos",
                        "fail_action": "stop"
                    }
                ]
            },
            {
                "id": "step_human_approval",
                "kind": "approval",
                "depends_on": ["step_verify_toxicology"]
            }
        ],
        "policies": {
            "timeout_seconds": 300,
            "max_retries": 0,
            "default_approval_required": True
        }
    }
    (fixtures_dir / "c2_pdx_execution_plan_sample.json").write_text(
        json.dumps(make_upstream_snapshot_fixture(
            "execution_plan_v1",
            "1.0.0",
            c2_pdx_plan,
            PDX_REPO,
            PDX_COMMIT,
            "packages/pdx_artifact_core/src/pdx_artifact_core/schemas/execution_plan.v1.schema.json",
            "fff3e94c92a69e64987e29db7a9e18d215895c05a882caf3691c7987c0a4b37d",
            "byte_exact"
        ), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 7. C3 Verifier Result Pass (Proposed Part A - PDX / G3)
    c3_pass = {
        "verifier_id": "verifier-cosmetics-toxicology-mos",
        "version": "1.0.0",
        "status": "pass",
        "reason_codes": ["MOS_ABOVE_THRESHOLD_100", "CONCENTRATION_WITHIN_LIMITS"],
        "rule_set_id": "EU_COSMETICS_REG_1223_2009",
        "rule_set_version": "2025.1",
        "rule_digest": "c1c2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "evidence_ids": ["doc-sds-001"],
        "details": {
            "minimum_mos": 2435.0,
            "threshold": 100.0
        },
        "timestamp": "2026-08-13T09:00:00Z"
    }
    (fixtures_dir / "c3_verifier_result_pass.json").write_text(
        json.dumps(make_proposed_contract_fixture("verifier_result_v1", "1.0.0", c3_pass, PDX_REPO, "G3"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 8. C3 Verifier Result Fail (Proposed Part A - PDX / G3)
    c3_fail = {
        "verifier_id": "verifier-cosmetics-toxicology-mos",
        "version": "1.0.0",
        "status": "fail",
        "reason_codes": ["MOS_BELOW_THRESHOLD_100", "ANNEX_V_CONCENTRATION_EXCEEDED"],
        "rule_set_id": "EU_COSMETICS_REG_1223_2009",
        "rule_set_version": "2025.1",
        "rule_digest": "c1c2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "evidence_ids": [],
        "details": {
            "minimum_mos": 77.9,
            "threshold": 100.0
        },
        "timestamp": "2026-08-13T09:00:00Z"
    }
    (fixtures_dir / "c3_verifier_result_fail.json").write_text(
        json.dumps(make_proposed_contract_fixture("verifier_result_v1", "1.0.0", c3_fail, PDX_REPO, "G3"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 9. C3 Verifier Result Review (Proposed Part A - PDX / G3)
    c3_review = {
        "verifier_id": "verifier-cosmetics-toxicology-mos",
        "version": "1.0.0",
        "status": "review",
        "reason_codes": ["MISSING_NOAEL_EVIDENCE"],
        "rule_set_id": "EU_COSMETICS_REG_1223_2009",
        "rule_set_version": "2025.1",
        "rule_digest": "c1c2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "evidence_ids": [],
        "details": {
            "missing_field": "COPPER TRIPEPTIDE-1.noael_mg_kg_day"
        },
        "timestamp": "2026-08-13T09:00:00Z"
    }
    (fixtures_dir / "c3_verifier_result_review.json").write_text(
        json.dumps(make_proposed_contract_fixture("verifier_result_v1", "1.0.0", c3_review, PDX_REPO, "G3"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 10. C4 Workflow Checkpoint Sample (Proposed Part A - PDX / G4, product-neutral subject_digest)
    c4_checkpoint = {
        "checkpoint_id": "chk-step-verify-final-001",
        "run_id": "run-pif-20260813-001",
        "subject_digest": canonical_hash(c2_happy),
        "plan_digest": canonical_hash(c2_pdx_plan),
        "completed_step_ids": ["step_extract_sds", "step_verify_toxicology"],
        "pending_step_ids": ["step_human_approval"],
        "evidence_digests": {
            "dossier_summary.json": "e1e2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "safety_assessment_report.pdf": "f1f2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        },
        "status": "pending",
        "created_at": "2026-08-13T09:04:00Z"
    }
    (fixtures_dir / "c4_workflow_checkpoint_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("workflow_checkpoint_v1", "1.0.0", c4_checkpoint, PDX_REPO, "G4"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 11. C4 Approval Request Sample (Proposed Part A - PDX / G4, product-neutral subject_digest)
    c4_req = {
        "approval_request_id": "44444444-4444-4444-8444-444444444444",
        "run_id": "run-pif-20260813-001",
        "checkpoint_id": "chk-step-verify-final-001",
        "subject_digest": canonical_hash(c2_happy),
        "plan_digest": canonical_hash(c2_pdx_plan),
        "evidence_digests": {
            "dossier_summary.json": "e1e2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "safety_assessment_report.pdf": "f1f2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        },
        "summary": "Formula verification passed. Ready for Chief Safety Officer final review.",
        "created_at": "2026-08-13T09:05:00Z",
        "status": "pending"
    }
    (fixtures_dir / "c4_approval_request_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("approval_request_v1", "1.0.0", c4_req, PDX_REPO, "G4"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 12. C4 Approval Decision Sample (Proposed Part A - PDX / G4, product-neutral subject_digest & idempotency_key)
    c4_pdx_decision = {
        "decision_id": "55555555-5555-4555-8555-555555555555",
        "approval_request_id": "44444444-4444-4444-8444-444444444444",
        "checkpoint_id": "chk-step-verify-final-001",
        "idempotency_key": "idemp-key-999",
        "actor_id": "usr-chief-safety-officer",
        "decision": "approved",
        "reason": "All toxicology parameters verified against EU SCCS Notes of Guidance 12th revision.",
        "subject_digest": canonical_hash(c2_happy),
        "plan_digest": canonical_hash(c2_pdx_plan),
        "evidence_digests": {
            "dossier_summary.json": "e1e2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "safety_assessment_report.pdf": "f1f2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        },
        "decided_at": "2026-08-13T09:10:00Z"
    }
    (fixtures_dir / "c4_approval_decision_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("approval_decision_v1", "1.0.0", c4_pdx_decision, PDX_REPO, "G4"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 13. C4 Fleet Approval Record Sample (Fleet Owned Persistence Record)
    c4_fleet_record = {
        "approval_record_id": "77777777-7777-4777-8777-777777777777",
        "tenant_id": "tenant-acme-corp",
        "run_id": "run-pif-20260813-001",
        "checkpoint_id": "chk-step-verify-final-001",
        "canonical_idempotency_key": "tenant-acme-corp:chk-step-verify-final-001:usr-chief-safety-officer:idemp-key-999",
        "authenticated_actor": {
            "sub": "usr-chief-safety-officer",
            "email": "cso@acme-corp.com",
            "roles": ["regulatory_officer", "approver"]
        },
        "decision": "approved",
        "reason": "All toxicology parameters verified against EU SCCS Notes of Guidance 12th revision.",
        "subject_case_digest": canonical_hash(c2_happy),
        "plan_digest": canonical_hash(c2_pdx_plan),
        "evidence_digests": {
            "dossier_summary.json": "e1e2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "safety_assessment_report.pdf": "f1f2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        },
        "decided_at": "2026-08-13T09:10:00Z"
    }
    (fixtures_dir / "c4_fleet_approval_record_sample.json").write_text(
        json.dumps(make_fleet_owned_fixture("fleet_approval_record_v1", "1.0.0", c4_fleet_record), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 14. C5 Storage Identity Sample (Proposed Part A - PDX / G3, gs:// or artifact://)
    c5_data = {
        "artifact_id": "art-safety-assessment-dossier-001",
        "uri": "gs://acme-corp-dossiers/2026/08/pif_final_radiant_face_cream.pdf",
        "sha256": "f1f2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "size_bytes": 1048576,
        "media_type": "application/pdf",
        "created_at": "2026-08-13T09:12:00Z"
    }
    (fixtures_dir / "c5_storage_identity_sample.json").write_text(
        json.dumps(make_proposed_contract_fixture("artifact_storage_identity_v1", "1.0.0", c5_data, PDX_REPO, "G3"), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 15. C6 Audit Event Sample (Fleet Owned)
    c6_data = {
        "event_id": "66666666-6666-4666-8666-666666666666",
        "tenant_id": "tenant-acme-corp",
        "run_id": "run-pif-20260813-001",
        "event_type": "APPROVAL_DECIDED",
        "actor_id": "usr-chief-safety-officer",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "span_id": "00f067aa0ba902b7",
        "timestamp": "2026-08-13T09:10:01Z",
        "payload": {
            "decision": "approved",
            "checkpoint_id": "chk-step-verify-final-001",
            "idempotency_key": "tenant-acme-corp:chk-step-verify-final-001:usr-chief-safety-officer:idemp-key-999"
        }
    }
    (fixtures_dir / "c6_audit_event_sample.json").write_text(
        json.dumps(make_fleet_owned_fixture("audit_event_v1", "1.0.0", c6_data), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Generated 15 G1 synthetic fixtures in {fixtures_dir}")

if __name__ == "__main__":
    main()
