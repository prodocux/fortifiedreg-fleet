"""
PDX Execution Plan Compiler (v0.3.0).
Compiles a domain DossierCase into a valid pdx_execution_plan_v1 plan.
"""
from pathlib import Path
from typing import Any, Dict, List
from fleet_governance_core.models.case import DossierCase

FORMAT_TOOL_MAP = {
    ".pdf": "prodocux.extract_pages",
    ".docx": "prodocux.profile_document",
    ".csv": "prodocux.profile_table",
    ".xlsx": "prodocux.profile_workbook",
    ".pptx": "prodocux.profile_presentation",
}

def compile_case_to_pdx_plan(case: DossierCase, request_id: str | None = None) -> Dict[str, Any]:
    """Compile a DossierCase into a deterministic pdx_execution_plan_v1 dictionary."""
    actual_request_id = request_id or f"run-pif-{case.case_id}"
    steps: List[Dict[str, Any]] = []

    # 1. Document Extraction Steps (one per supplier document if present, dynamically mapping format from authoritative doc.filename to tool)
    extract_step_ids: List[str] = []
    for i, doc in enumerate(case.supplier_documents):
        step_id = f"step_extract_doc_{i}_{doc.doc_id}"
        fn = doc.filename
        ext = Path(fn).suffix.casefold()

        if ext not in FORMAT_TOOL_MAP:
            raise ValueError(
                f"Unsupported document format '{ext}' for document '{doc.doc_id}' ({fn}). "
                f"Compiler fail-closed: supported formats are {sorted(FORMAT_TOOL_MAP.keys())}."
            )

        tool_name = FORMAT_TOOL_MAP[ext]

        steps.append({
            "id": step_id,
            "kind": "tool",
            "name": f"Extract supplier document {doc.doc_id}",
            "tool": tool_name,
            "inputs": {
                "document_id": doc.doc_id,
                "document_filename": fn,
                "sha256": doc.sha256,
            },
            "outputs": [f"text_{doc.doc_id}"],
        })
        extract_step_ids.append(step_id)

    # 2. INCI Compliance Verification Step
    inci_step_id = "step_verify_inci_compliance"
    steps.append({
        "id": inci_step_id,
        "kind": "verify",
        "name": "Verify formulation against EU Annex II and Annex V restrictions",
        "depends_on": extract_step_ids if extract_step_ids else None,
        "verification": [
            {
                "id": "chk_inci_annex_compliance",
                "check": "verifier-cosmetics-inci-compliance",
                "fail_action": "stop",
            }
        ],
    })

    # 3. Toxicology MoS Verification Step
    tox_step_id = "step_verify_toxicology_mos"
    steps.append({
        "id": tox_step_id,
        "kind": "verify",
        "name": "Evaluate toxicological Margin of Safety against SCCS 12th Notes of Guidance",
        "depends_on": [inci_step_id],
        "verification": [
            {
                "id": "chk_mos_threshold",
                "check": "verifier-cosmetics-toxicology-mos",
                "fail_action": "stop",
            }
        ],
    })

    # 4. Human Approval Step
    approval_step_id = "step_human_regulatory_approval"
    steps.append({
        "id": approval_step_id,
        "kind": "approval",
        "name": "Chief Safety Officer final dossier review & authorization",
        "depends_on": [tox_step_id],
        "policies": {
            "approval_required": True,
            "timeout_seconds": 86400,
            "max_retries": 0,
        },
    })

    # 5. Finalized PIF Dossier Transform Step
    steps.append({
        "id": "step_assemble_pif_manifest",
        "kind": "transform",
        "name": "Assemble checksummed finalized PIF dossier artifact",
        "depends_on": [approval_step_id],
        "transform": "pdx.assemble_manifest",
        "inputs": {
            "product_name": case.product_name,
            "jurisdiction": case.jurisdiction.value,
        },
        "outputs": ["pif_manifest.json", "pif_dossier.pdf"],
    })

    # Clean out None depends_on for schema purity
    for s in steps:
        if s.get("depends_on") is None:
            s.pop("depends_on", None)

    plan = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": actual_request_id,
        "producer": {
            "type": "fleet_compiler",
            "name": "fleet-adapter-pdx",
        },
        "intent": {
            "summary": f"Compile and verify PIF compliance dossier for {case.product_name}",
            "product_name": case.product_name,
            "jurisdiction": case.jurisdiction.value,
        },
        "steps": steps,
        "policies": {
            "timeout_seconds": 300,
            "max_retries": 0,
            "default_approval_required": True,
        },
    }

    return plan
