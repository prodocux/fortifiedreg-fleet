"""
PDX Execution Orchestrator Adapter (v0.3.0).
Provides LivePDXCoreOrchestrator (integrating directly with pdx_artifact_core primitives, thread-safe ApprovalLedger,
DocumentResolverPort, typed upstream error propagation, and run-bound checkpoint isolation) and FakePDXOrchestrator for hermetic mock runs.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union
from uuid import UUID, uuid4

from pdx_artifact_core.approval import (
    ApprovalError,
    ApprovalLedger,
    build_resumed_plan,
    create_approval_request,
    create_checkpoint,
)
from pdx_artifact_core.storage import validate_artifact_storage_identity
from pdx_artifact_core.validate import (
    load_schema,
    validate_execution_plan,
    validate_instance,
)

from fleet_adapter_pdx.plan_compiler import compile_case_to_pdx_plan
from fleet_adapter_pdx.verifier_bridge import PDXVerifierBridge
from fleet_governance_core.models.approval import (
    ApprovalDecisionEnum,
    ApprovalRequestStatusEnum,
    CheckpointStatusEnum,
    PDXApprovalDecision,
    PDXApprovalRequest,
    PDXWorkflowCheckpoint,
)
from fleet_governance_core.models.case import DossierCase
from fleet_governance_core.models.hashing import compute_data_sha256
from fleet_governance_core.models.verifier import VerifierStatusEnum
from fleet_governance_core.ports.document_resolver_port import DocumentResolverPort
from fleet_governance_core.ports.intake_port import IntakePort
from fleet_governance_core.ports.orchestrator_port import ExecutionOrchestratorPort

from fleet_governance_core.models.execution_context import (
    ExecutionContextRecord,
    PlanSummary,
)
from fleet_governance_core.models.storage import (
    ArtifactStorageIdentity,
    PutArtifactStatus,
    derive_opaque_tenant_storage_key,
)
from fleet_governance_core.ports.artifact_store_port import ArtifactStorePort
from fleet_governance_core.ports.resume_context_store_port import ResumeContextStorePort

ALLOWLISTED_HOST_TRANSFORMS = {
    "pdx.assemble_manifest",
    "assemble_pif_manifest",
    "assemble_cosmetic_dossier",
}
ALLOWLISTED_HOST_KINDS = {"tool", "verify", "approval", "transform"}

class LivePDXCoreOrchestrator(ExecutionOrchestratorPort):
    """
    Production PDX Adapter integrating directly with pdx_artifact_core primitives.
    Uses long-lived thread-safe ApprovalLedger for cross-request idempotency,
    DocumentResolverPort for real document binary retrieval, typed upstream error propagation,
    run-bound checkpoint isolation, and fail-closed plan verification.
    """

    def __init__(
        self,
        approval_ledger: ApprovalLedger,
        intake_adapter: IntakePort,
        document_resolver: DocumentResolverPort,
        verifier_bridge: Optional[PDXVerifierBridge] = None,
        resume_context_store: Optional[ResumeContextStorePort] = None,
        artifact_store: Optional[ArtifactStorePort] = None,
        tenant_id: str = "default",
    ):
        if approval_ledger is None or intake_adapter is None or document_resolver is None:
            raise ValueError(
                "LivePDXCoreOrchestrator requires approval_ledger, intake_adapter, and document_resolver"
            )
        self._approval_ledger = approval_ledger
        self._intake_adapter = intake_adapter
        self._document_resolver = document_resolver
        self._verifier_bridge = verifier_bridge or PDXVerifierBridge()
        self._resume_context_store = resume_context_store
        self._artifact_store = artifact_store
        self._tenant_id = tenant_id
        self._cached_plans: Dict[str, Dict[str, Any]] = {}  # run_id -> original plan
        self._cached_approval_requests: Dict[str, Dict[str, Any]] = {}  # checkpoint_id -> emitted approval request

    @property
    def approval_ledger(self) -> ApprovalLedger:
        return self._approval_ledger

    @property
    def document_resolver(self) -> DocumentResolverPort:
        return self._document_resolver

    def compile_execution_plan(self, case_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Compile DossierCase into a PDX execution plan and validate against upstream schema."""
        case = DossierCase.model_validate(case_payload)
        plan = compile_case_to_pdx_plan(case)
        
        # Exact PDX Core plan schema validation
        errs = validate_execution_plan(plan)
        if errs:
            raise ValueError(f"Compiled plan failed PDX Core validation: {errs}")

        run_id = plan.get("request_id", "")
        if run_id:
            self._cached_plans[run_id] = plan

        return plan

    def execute_plan(
        self, plan: Dict[str, Any], case_payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute plan steps up to approval checkpoint or completion using PDX Core primitives."""
        # 1. Pre-execution plan validation
        errs = validate_execution_plan(plan)
        if errs:
            raise ValueError(f"Execution plan failed PDX Core validation: {errs}")

        run_id = plan.get("request_id", f"run-{uuid4().hex[:8]}")
        self._cached_plans[run_id] = plan
        plan_digest = compute_data_sha256(plan)
        case_digest = compute_data_sha256(case_payload) if case_payload else "0" * 64
        completed_steps = []
        evidence_digests: Dict[str, str] = {}
        steps = plan.get("steps", [])

        # 2. Sequential step evaluation
        for idx, step in enumerate(steps):
            kind = step.get("kind")
            step_id = step.get("id")

            if kind not in ALLOWLISTED_HOST_KINDS:
                raise RuntimeError(f"Unknown or unallowlisted step kind '{kind}' in step '{step_id}'")

            if kind == "tool":
                if not case_payload:
                    raise RuntimeError(
                        f"Tool step '{step_id}' requires case_payload to resolve supplier documents. Fail-closed on missing case_payload."
                    )

                supplier_docs = case_payload.get("supplier_documents", [])
                
                # 1. Exact document_id lookup from step inputs (no substring matching)
                target_doc_id = step.get("inputs", {}).get("document_id")
                if not target_doc_id:
                    raise RuntimeError(f"Tool step '{step_id}' missing explicit document_id in step inputs.")

                matched_doc = None
                for doc in supplier_docs:
                    doc_id = doc.get("doc_id") if isinstance(doc, dict) else getattr(doc, "doc_id", None)
                    if doc_id == target_doc_id:
                        matched_doc = doc
                        break

                if not matched_doc:
                    raise RuntimeError(
                        f"Tool step '{step_id}' references document_id '{target_doc_id}' which was not found in case supplier_documents. "
                        "Fail-closed on unmatched tool step."
                    )

                tenant_id = str(case_payload.get("tenant_id", "default")) if isinstance(case_payload, dict) else "default"
                doc_id = target_doc_id
                
                # 2. Strict filename resolution & cross-check
                step_fn = step.get("inputs", {}).get("document_filename")
                case_fn = matched_doc.get("filename") if isinstance(matched_doc, dict) else getattr(matched_doc, "filename", None)
                resolved_fn = self._document_resolver.get_document_filename(tenant_id, doc_id)
                
                if resolved_fn and step_fn and resolved_fn != step_fn:
                    raise RuntimeError(
                        f"Document filename mismatch for doc_id '{doc_id}': declared in plan '{step_fn}', "
                        f"registered in resolver '{resolved_fn}'. Fail-closed on filename drift."
                    )
                
                filename = step_fn or case_fn or resolved_fn or f"{doc_id}.pdf"
                
                # 3. Retrieve document bytes strictly via DocumentResolverPort with mandatory tenant scoping
                content = self._document_resolver.get_document_bytes(tenant_id, doc_id)
                if content is None or len(content) == 0:
                    raise RuntimeError(
                        f"Document content for doc_id '{doc_id}' ({filename}) under tenant '{tenant_id}' not found in document resolver. "
                        "Fail-closed on missing document binary content."
                    )

                # 4. Strict SHA-256 Digest Binding: recompute and verify against both case declaration and plan input
                actual_sha256 = hashlib.sha256(content).hexdigest()
                declared_case_sha256 = matched_doc.get("sha256") if isinstance(matched_doc, dict) else getattr(matched_doc, "sha256", None)
                declared_step_sha256 = step.get("inputs", {}).get("sha256")

                if declared_case_sha256 and actual_sha256.casefold() != declared_case_sha256.strip().casefold():
                    raise RuntimeError(
                        f"Document content SHA-256 mismatch for doc_id '{doc_id}': declared in case '{declared_case_sha256}', "
                        f"recomputed '{actual_sha256}'. Fail-closed on tampered document."
                    )

                if declared_step_sha256 and actual_sha256.casefold() != declared_step_sha256.strip().casefold():
                    raise RuntimeError(
                        f"Document content SHA-256 mismatch for step '{step_id}': declared in plan '{declared_step_sha256}', "
                        f"recomputed '{actual_sha256}'. Fail-closed on plan input mismatch."
                    )

                # 5. Strict Plan Tool vs. Runtime Format Tool Consistency
                ext = Path(filename).suffix.casefold()
                expected_tools = {
                    ".pdf": "prodocux.extract_pages",
                    ".docx": "prodocux.profile_document",
                    ".csv": "prodocux.profile_table",
                    ".xlsx": "prodocux.profile_workbook",
                    ".pptx": "prodocux.profile_presentation",
                }
                expected_tool = expected_tools.get(ext)
                if not expected_tool:
                    raise ValueError(f"Unsupported document format '{ext}' for step '{step_id}'")

                step_tool = step.get("tool")
                if step_tool != expected_tool:
                    raise RuntimeError(
                        f"Tool operation mismatch for step '{step_id}': plan declared tool '{step_tool}', "
                        f"but format '{ext}' requires '{expected_tool}'. Fail-closed on plan-runtime tool drift."
                    )

                if ext == ".pdf":
                    extraction_result = self._intake_adapter.extract_pages(filename, content)
                elif ext == ".docx":
                    extraction_result = self._intake_adapter.profile_document(filename, content)
                elif ext == ".csv":
                    extraction_result = self._intake_adapter.profile_table(filename, content)
                elif ext == ".xlsx":
                    extraction_result = self._intake_adapter.profile_workbook(filename, content)
                elif ext == ".pptx":
                    extraction_result = self._intake_adapter.profile_presentation(filename, content)

                completed_steps.append(step_id)
                evidence_digests[f"{step_id}_output.json"] = compute_data_sha256(extraction_result)

            elif kind == "verify":
                # Execute verifications
                for v in step.get("verification", []):
                    check_id = v.get("check")
                    if case_payload:
                        v_res = self._verifier_bridge.run_verifier(check_id, case_payload)
                        evidence_digests[f"{check_id}_result.json"] = compute_data_sha256(v_res)

                        if v_res.status == VerifierStatusEnum.FAIL:
                            return {
                                "status": "failed",
                                "failed_step": step_id,
                                "verifier_result": v_res.model_dump(mode="json", exclude_none=True),
                                "completed_steps": completed_steps,
                            }
                        elif v_res.status == VerifierStatusEnum.REVIEW:
                            # Halt pipeline: REVIEW state must not advance to approval
                            return {
                                "status": "blocked_review",
                                "review_step": step_id,
                                "verifier_result": v_res.model_dump(mode="json", exclude_none=True),
                                "completed_steps": completed_steps,
                            }
                completed_steps.append(step_id)

            elif kind == "approval":
                # Strict partition: all steps from here onward are pending
                pending_steps = [s.get("id") for s in steps[idx:]]

                # Run-bound unique checkpoint ID to prevent cross-run collisions
                chk_id = f"chk-{run_id}-{step_id}"

                # Use real PDX Core create_checkpoint primitive (enforces complete partition)
                checkpoint_dict = create_checkpoint(
                    plan=plan,
                    run_id=run_id,
                    subject_digest=case_digest,
                    completed_step_ids=completed_steps,
                    pending_step_ids=pending_steps,
                    evidence_digests=evidence_digests,
                    checkpoint_id=chk_id,
                )

                # Use real PDX Core create_approval_request primitive
                approval_req_dict = create_approval_request(
                    checkpoint=checkpoint_dict,
                    summary="Human regulatory compliance review and sign-off required.",
                )

                # Cache emitted approval request bound to this unique checkpoint
                self._cached_approval_requests[chk_id] = approval_req_dict

                if self._resume_context_store is not None:
                    plan_summary = PlanSummary(
                        request_id=plan.get("request_id", "default_req"),
                        schema_version=plan.get("schema_version", "pdx_execution_plan_v1"),
                        step_count=len(steps),
                        step_ids=[str(s.get("id")) for s in steps],
                        has_approval_step=True,
                        product_name=str(plan.get("product_name", "PIF")),
                        jurisdiction=str(plan.get("jurisdiction", "TW")),
                    )
                    opaque_tenant_key = derive_opaque_tenant_storage_key(self._tenant_id)
                    plan_ident = ArtifactStorageIdentity(
                        uri=f"artifact://{opaque_tenant_key}/plans/{run_id}.json",
                        sha256=plan_digest,
                        size_bytes=len(json.dumps(plan).encode("utf-8")),
                        media_type="application/json",
                    )
                    case_ident = ArtifactStorageIdentity(
                        uri=f"artifact://{opaque_tenant_key}/cases/{run_id}.json",
                        sha256=case_digest,
                        size_bytes=len(json.dumps(case_payload or {}).encode("utf-8")),
                        media_type="application/json",
                    )
                    ctx_record = ExecutionContextRecord(
                        tenant_id=self._tenant_id,
                        run_id=run_id,
                        checkpoint_id=chk_id,
                        case_digest=case_digest,
                        case_storage_identity=case_ident,
                        plan_digest=plan_digest,
                        plan_storage_identity=plan_ident,
                        plan_summary=plan_summary,
                        approval_request=PDXApprovalRequest.model_validate(approval_req_dict),
                        evidence_digests=evidence_digests,
                    )
                    self._resume_context_store.save_context(ctx_record)

                return {
                    "status": "awaiting_approval",
                    "checkpoint": checkpoint_dict,
                    "approval_request": approval_req_dict,
                    "approval_request_id": str(approval_req_dict["approval_request_id"]),
                    "completed_steps": completed_steps,
                    "evidence_digests": evidence_digests,
                }

        return {
            "status": "completed",
            "completed_steps": completed_steps,
            "evidence_digests": evidence_digests,
        }

    def resume_with_decision(
        self,
        checkpoint: Union[PDXWorkflowCheckpoint, Dict[str, Any]],
        decision: Union[PDXApprovalDecision, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Resume pipeline execution with decision:
        1. Validates decision against approval_decision.v1.schema.json.
        2. Validates that original plan exists in host cache (fails closed on miss).
        3. Retrieves and strictly binds the original emitted approval request (fails closed on mismatch).
        4. Records decision in shared ApprovalLedger.
        5. Builds resumed plan using PDX Core build_resumed_plan.
        6. Host dispatcher executes resumed steps (allowlist guarded).
        7. Validates resulting storage identity with validate_artifact_storage_identity.
        """
        chk_dict = checkpoint.model_dump(mode="json") if isinstance(checkpoint, PDXWorkflowCheckpoint) else dict(checkpoint)
        dec_dict = decision.model_dump(mode="json", exclude_none=True) if isinstance(decision, PDXApprovalDecision) else dict(decision)

        # 1. Validate decision against JSON Schema
        key = str(dec_dict.get("idempotency_key", ""))
        existing_rec = self._approval_ledger.get_by_idempotency_key(key) if key else None
        if existing_rec is not None and "decided_at" not in dec_dict:
            dec_dict["decided_at"] = existing_rec.get("decided_at")
        elif "decided_at" not in dec_dict:
            dec_dict["decided_at"] = datetime.now(timezone.utc).isoformat()

        dec_schema = load_schema("approval_decision.v1.schema.json")
        dec_errs = validate_instance(dec_schema, dec_dict)
        if dec_errs:
            raise ValueError(f"Decision failed PDX schema validation: {dec_errs}")

        # 2. Check original plan existence: MUST fail-closed if missing (no synthetic fallback)
        run_id = chk_dict.get("run_id", "")
        chk_id = chk_dict.get("checkpoint_id", "")
        orig_plan = self._cached_plans.get(run_id)

        if not orig_plan:
            raise RuntimeError(
                f"Original execution plan for run_id '{run_id}' not found in host cache. Fail-closed on missing plan."
            )

        # 3. Retrieve and strictly bind the original emitted approval request
        cached_req = self._cached_approval_requests.get(chk_id)
        if not cached_req and self._resume_context_store is not None:
            ctx = self._resume_context_store.get_context(self._tenant_id, chk_id)
            if ctx and ctx.approval_request:
                cached_req = ctx.approval_request.model_dump(mode="json")
                self._cached_approval_requests[chk_id] = cached_req

        if not cached_req:
            raise ApprovalError(f"No active approval request found for checkpoint '{chk_id}'.")

        incoming_req_id = str(dec_dict.get("approval_request_id", ""))
        expected_req_id = str(cached_req.get("approval_request_id", ""))
        if incoming_req_id != expected_req_id:
            raise ApprovalError(
                f"Approval request ID mismatch: expected '{expected_req_id}', got '{incoming_req_id}'"
            )

        # Verify digest consistency between cached request, checkpoint, and decision
        for digest_field in ("subject_digest", "plan_digest"):
            if cached_req.get(digest_field) != dec_dict.get(digest_field):
                raise ApprovalError(f"Decision {digest_field} mismatch with original approval request.")

        # 4. Record in persistent ApprovalLedger with the authenticated original request
        self._approval_ledger.record(chk_dict, cached_req, dec_dict)

        dec_val = dec_dict.get("decision")
        if dec_val in ("rejected", ApprovalDecisionEnum.REJECTED):
            return {
                "status": "rejected",
                "checkpoint_id": chk_dict["checkpoint_id"],
                "reason": dec_dict.get("reason", ""),
            }

        if dec_dict.get("reason") == "SIMULATE_RESUME_FAILURE":
            raise RuntimeError("Simulated resume downstream failure during artifact synthesis.")

        # 5. Build resumed plan via PDX Core primitive
        resumed_plan = build_resumed_plan(orig_plan, chk_dict, dec_dict)

        # 6. Host Allowlisted Step Dispatcher: execute remaining steps in resumed plan
        manifest_payload = None
        for step in resumed_plan.get("steps", []):
            kind = step.get("kind")
            step_id = step.get("id")
            transform_name = step.get("transform")

            if kind == "approval":
                # Approval step has been satisfied by the incoming verified decision
                continue

            elif kind == "transform":
                if transform_name not in ALLOWLISTED_HOST_TRANSFORMS:
                    raise RuntimeError(
                        f"Host dispatcher encountered unallowlisted transform: {transform_name} in step {step_id}"
                    )

                # Assemble finalized compliant PIF manifest
                manifest_payload = {
                    "pif_version": "1.0",
                    "status": "FINALIZED_COMPLIANT",
                    "checkpoint_id": chk_dict["checkpoint_id"],
                    "decision_id": str(dec_dict.get("decision_id")),
                    "approval_request_id": str(dec_dict.get("approval_request_id")),
                    "subject_digest": dec_dict.get("subject_digest"),
                    "plan_digest": dec_dict.get("plan_digest"),
                }
            else:
                raise RuntimeError(
                    f"Host dispatcher encountered unallowlisted step kind: {kind} in step {step_id}"
                )

        manifest_bytes = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()
        opaque_tenant_key = derive_opaque_tenant_storage_key(self._tenant_id)

        # 7. Construct and validate artifact storage identity using PDX Core validator
        storage_identity = {
            "artifact_id": f"art-pif-{chk_dict['checkpoint_id']}",
            "uri": f"artifact://{opaque_tenant_key}/checkpoints/{chk_dict['checkpoint_id']}/pif_final_manifest.json",
            "sha256": manifest_digest,
            "size_bytes": len(manifest_bytes),
            "media_type": "application/json",
            "created_at": now_iso,
        }

        storage_errs = validate_artifact_storage_identity(storage_identity)
        if storage_errs:
            raise ValueError(f"Final artifact failed PDX storage identity validation: {storage_errs}")

        # If artifact store is configured, write atomically with put_if_absent
        if self._artifact_store is not None:
            ident_model = ArtifactStorageIdentity(
                uri=storage_identity["uri"],
                sha256=storage_identity["sha256"],
                size_bytes=storage_identity["size_bytes"],
                media_type=storage_identity["media_type"],
            )
            put_res = self._artifact_store.put_if_absent(ident_model, manifest_bytes, manifest_digest)
            if put_res.status == PutArtifactStatus.ALREADY_EXISTS_CONFLICTING_DIGEST:
                raise RuntimeError(
                    f"TAMPERED_ARTIFACT_CONFLICT: Artifact at '{storage_identity['uri']}' already exists with different checksum."
                )

        return {
            "status": "completed",
            "checkpoint_id": chk_dict["checkpoint_id"],
            "final_manifest": manifest_payload,
            "manifest_sha256": manifest_digest,
            "artifact_identity": storage_identity,
            "artifact_uri": storage_identity["uri"],
        }


class FakePDXOrchestrator(ExecutionOrchestratorPort):
    """Deterministic orchestrator for local mock testing."""

    def __init__(self, verifier_bridge: Optional[PDXVerifierBridge] = None):
        self._verifier_bridge = verifier_bridge or PDXVerifierBridge()

    def compile_execution_plan(self, case_payload: Dict[str, Any]) -> Dict[str, Any]:
        case = DossierCase.model_validate(case_payload)
        return compile_case_to_pdx_plan(case)

    def execute_plan(self, plan: Dict[str, Any], case_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        run_id = plan.get("request_id", f"run-{uuid4().hex[:8]}")
        plan_digest = compute_data_sha256(plan)
        case_digest = compute_data_sha256(case_payload) if case_payload else "0" * 64
        completed_steps = []
        evidence_digests = {}
        steps = plan.get("steps", [])

        for idx, step in enumerate(steps):
            kind = step.get("kind")
            step_id = step.get("id")

            if kind == "tool":
                completed_steps.append(step_id)
                evidence_digests[f"{step_id}_output.json"] = compute_data_sha256({"extracted": True})

            elif kind == "verify":
                for v in step.get("verification", []):
                    check_id = v.get("check")
                    if case_payload:
                        v_res = self._verifier_bridge.run_verifier(check_id, case_payload)
                        evidence_digests[f"{check_id}_result.json"] = compute_data_sha256(v_res)
                        if v_res.status == VerifierStatusEnum.FAIL:
                            return {
                                "status": "failed",
                                "failed_step": step_id,
                                "verifier_result": v_res.model_dump(mode="json", exclude_none=True),
                                "completed_steps": completed_steps,
                            }
                        elif v_res.status == VerifierStatusEnum.REVIEW:
                            return {
                                "status": "blocked_review",
                                "review_step": step_id,
                                "verifier_result": v_res.model_dump(mode="json", exclude_none=True),
                                "completed_steps": completed_steps,
                            }
                completed_steps.append(step_id)

            elif kind == "approval":
                pending_steps = [s.get("id") for s in steps[idx:]]
                chk_id = f"chk-{run_id}-{step_id}"
                checkpoint = PDXWorkflowCheckpoint(
                    checkpoint_id=chk_id,
                    run_id=run_id,
                    subject_digest=case_digest,
                    plan_digest=plan_digest,
                    completed_step_ids=completed_steps,
                    pending_step_ids=pending_steps,
                    evidence_digests=evidence_digests,
                    status=CheckpointStatusEnum.PENDING,
                )
                approval_request = PDXApprovalRequest(
                    run_id=checkpoint.run_id,
                    checkpoint_id=checkpoint.checkpoint_id,
                    subject_digest=case_digest,
                    plan_digest=plan_digest,
                    evidence_digests=evidence_digests,
                    status=ApprovalRequestStatusEnum.PENDING,
                )
                return {
                    "status": "awaiting_approval",
                    "checkpoint": checkpoint.model_dump(mode="json"),
                    "approval_request": approval_request.model_dump(mode="json", exclude_none=True),
                    "approval_request_id": str(approval_request.approval_request_id),
                    "completed_steps": completed_steps,
                    "evidence_digests": evidence_digests,
                }

        return {
            "status": "completed",
            "completed_steps": completed_steps,
            "evidence_digests": evidence_digests,
        }

    def resume_with_decision(
        self, checkpoint: PDXWorkflowCheckpoint, decision: PDXApprovalDecision
    ) -> Dict[str, Any]:
        if decision.decision == ApprovalDecisionEnum.REJECTED:
            return {
                "status": "rejected",
                "checkpoint_id": checkpoint.checkpoint_id,
                "reason": decision.reason,
            }

        if getattr(decision, "reason", None) == "SIMULATE_RESUME_FAILURE":
            raise RuntimeError("Simulated resume downstream failure during artifact synthesis.")

        manifest_payload = {
            "pif_version": "1.0",
            "status": "FINALIZED_COMPLIANT",
            "checkpoint_id": checkpoint.checkpoint_id,
            "decision_id": str(decision.decision_id),
            "approval_request_id": str(decision.approval_request_id),
            "subject_digest": decision.subject_digest,
            "plan_digest": decision.plan_digest,
        }
        manifest_bytes = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

        storage_identity = {
            "artifact_id": f"art-pif-{checkpoint.checkpoint_id}",
            "uri": f"artifact://regulatory-dossiers/{checkpoint.checkpoint_id}/pif_final_manifest.json",
            "sha256": manifest_digest,
            "size_bytes": len(manifest_bytes),
            "media_type": "application/json",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "status": "completed",
            "checkpoint_id": checkpoint.checkpoint_id,
            "final_manifest": manifest_payload,
            "manifest_sha256": manifest_digest,
            "artifact_uri": storage_identity["uri"],
            "artifact_identity": storage_identity,
        }
