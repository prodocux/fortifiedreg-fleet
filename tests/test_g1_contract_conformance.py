"""
G1 Contract Conformance Test Suite (Strict Provenance & Ownership Separation)
Validates:
- Complete C1-C6 Schema and Fixture Inventory (Exact match, zero unexpected files)
- Metaschema validation with Draft202012Validator
- Schema conformance for all 15 fixtures using FormatChecker
- Real Git Object & Pinned-Commit Provenance Verification (git show <commit>:<path>, git hash-object)
- Explicit metadata for proposed_g1 (target_owner, target_gate, source_commit=null)
- Fleet-owned contracts (dossier_case_v1, fleet_approval_record_v1, audit_event_v1)
- Canonical data_sha256 hashing
- Negative tests: storage identity URI rejection (dot-segments, schemes, queries), filename dot-segment rejection, extra properties rejection, digest tampering
- Positive test: Large artifact (>50MB) permitted by product-neutral PDX schema
- Full-chain approval fixture relationships (checkpoint, request, decision, persistence record)
- Generator reproducibility
"""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

import os

ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT_DIR / "schemas"
FIXTURES_DIR = ROOT_DIR / "fixtures"

PDX_REPO_DIR = Path(os.getenv("PDX_REPO_DIR")) if os.getenv("PDX_REPO_DIR") else None
PRODOCUX_REPO_DIR = Path(os.getenv("PRODOCUX_REPO_DIR")) if os.getenv("PRODOCUX_REPO_DIR") else None

PDX_COMMIT = "61cff57ec7938165234dd895177dccade7ac1a5f"
PDX_SOURCE_COMMIT = "93ec3514261bf89e9cb88b79f524e3fbc5ef4402"
FLEET_COMMIT = "af8c8a508134a774af568cf9d29c7b412268e518"
FLEET_REPO = "prodocux/fortifiedreg-fleet"


# Explicit Schema Inventory (11 Schemas)
EXPECTED_SCHEMAS = {
    # Fleet-Owned Canonical Schemas
    "dossier_case_v1": SCHEMAS_DIR / "fleet" / "dossier_case_v1.json",
    "fleet_approval_record_v1": SCHEMAS_DIR / "fleet" / "fleet_approval_record_v1.json",
    "audit_event_v1": SCHEMAS_DIR / "fleet" / "audit_event_v1.json",
    
    # Real Upstream Snapshots (Exist in pinned upstream commit)
    "execution_plan_v1": SCHEMAS_DIR / "upstream_snapshots" / "pdx" / "execution_plan.v1.schema.json",
    
    # Proposed Part A Contracts (Joint G1 freeze, pending G2-G4 implementation)
    "intake_request_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "prodocux" / "intake_request_v1.json",
    "intake_response_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "prodocux" / "intake_response_v1.json",
    "verifier_result_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "pdx" / "verifier_result_v1.json",
    "workflow_checkpoint_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "pdx" / "workflow_checkpoint_v1.json",
    "approval_request_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "pdx" / "approval_request_v1.json",
    "approval_decision_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "pdx" / "approval_decision_v1.json",
    "artifact_storage_identity_v1": SCHEMAS_DIR / "proposed_part_a_contracts" / "pdx" / "artifact_storage_identity_v1.json",
}

# Explicit Fixture to Schema Mapping (15 Fixtures)
FIXTURE_SCHEMA_MAP = {
    "c1_intake_request_sample.json": "intake_request_v1",
    "c1_intake_response_sample.json": "intake_response_v1",
    "c2_dossier_case_happy_path.json": "dossier_case_v1",
    "c2_dossier_case_toxicology_fail.json": "dossier_case_v1",
    "c2_dossier_case_missing_data.json": "dossier_case_v1",
    "c2_pdx_execution_plan_sample.json": "execution_plan_v1",
    "c3_verifier_result_pass.json": "verifier_result_v1",
    "c3_verifier_result_fail.json": "verifier_result_v1",
    "c3_verifier_result_review.json": "verifier_result_v1",
    "c4_workflow_checkpoint_sample.json": "workflow_checkpoint_v1",
    "c4_approval_request_sample.json": "approval_request_v1",
    "c4_approval_decision_sample.json": "approval_decision_v1",
    "c4_fleet_approval_record_sample.json": "fleet_approval_record_v1",
    "c5_storage_identity_sample.json": "artifact_storage_identity_v1",
    "c6_audit_event_sample.json": "audit_event_v1",
}

def compute_canonical_hash(data: dict) -> str:
    canonical_json = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

def test_inventory_exactness():
    """Verify exact count and presence of all schemas and fixtures with no extras."""
    actual_fixtures = {f.name for f in FIXTURES_DIR.glob("*.json")}
    expected_fixtures = set(FIXTURE_SCHEMA_MAP.keys())
    assert actual_fixtures == expected_fixtures, (
        f"Fixture inventory mismatch. Extra: {actual_fixtures - expected_fixtures}, Missing: {expected_fixtures - actual_fixtures}"
    )
    
    actual_schemas = {p.resolve() for p in SCHEMAS_DIR.rglob("*.json")}
    expected_schema_paths = {p.resolve() for p in EXPECTED_SCHEMAS.values()}
    assert actual_schemas == expected_schema_paths, (
        f"Schema inventory mismatch. Extra: {actual_schemas - expected_schema_paths}, Missing: {expected_schema_paths - actual_schemas}"
    )

@pytest.mark.parametrize("schema_key,schema_path", EXPECTED_SCHEMAS.items())
def test_schema_metaschema_validity(schema_key: str, schema_path: Path):
    """Ensure all JSON schemas are valid Draft 2020-12 schemas."""
    schema_content = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema_content)

@pytest.mark.parametrize("fixture_name,schema_key", FIXTURE_SCHEMA_MAP.items())
def test_fixture_conformance_and_format_check(fixture_name: str, schema_key: str):
    """Validate each fixture against its corresponding schema with strict format checking."""
    fixture_path = FIXTURES_DIR / fixture_name
    fixture_doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    
    assert "_metadata" in fixture_doc, f"Missing _metadata in {fixture_name}"
    assert "data" in fixture_doc, f"Missing data in {fixture_name}"
    
    schema_path = EXPECTED_SCHEMAS[schema_key]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(instance=fixture_doc["data"])

@pytest.mark.parametrize("fixture_name", FIXTURE_SCHEMA_MAP.keys())
def test_fixture_hash_integrity_and_provenance(fixture_name: str):
    """Validate canonical data_sha256 calculation and authentic provenance metadata."""
    fixture_path = FIXTURES_DIR / fixture_name
    fixture_doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    meta = fixture_doc["_metadata"]
    
    # 1. Canonical Hash Integrity
    expected_hash = compute_canonical_hash(fixture_doc["data"])
    assert meta["data_sha256"] == expected_hash, (
        f"Hash mismatch in {fixture_name}: expected {expected_hash}, got {meta['data_sha256']}"
    )
    
    # 2. Strict Provenance Category Checking
    status = meta["contract_status"]
    if status == "upstream_snapshot":
        assert meta["upstream_repo"] == "prodocux/pdx-artifact-engine"
        assert meta["source_commit"] in (PDX_SOURCE_COMMIT, PDX_COMMIT)
        assert meta["snapshot_mode"] == "byte_exact"
        source_rel_path = meta["source_path"]
        expected_blob_sha = meta["source_blob_sha256"]
        
        # Verify local snapshot file hash matches declared blob sha
        snapshot_file = EXPECTED_SCHEMAS[FIXTURE_SCHEMA_MAP[fixture_name]]
        assert hashlib.sha256(snapshot_file.read_bytes()).hexdigest() == expected_blob_sha
        
        # Verify snapshot directly against git object database if PDX_REPO_DIR provided
        if PDX_REPO_DIR and PDX_REPO_DIR.exists():
            git_show_cmd = ["git", "show", f"{meta['source_commit']}:{source_rel_path}"]
            git_res = subprocess.run(git_show_cmd, cwd=str(PDX_REPO_DIR), capture_output=True, check=True)
            assert hashlib.sha256(git_res.stdout).hexdigest() == expected_blob_sha, "Git show bytes do not match expected blob SHA!"
            
            # Verify git hash-object
            git_hash_res = subprocess.run(["git", "hash-object", str(snapshot_file)], capture_output=True, text=True, check=True)
            assert git_hash_res.stdout.strip() == "d1f97632194ea55658a7e136f0a1c3df0ce30e09"
            
        # Verify against installed package resources (fail-closed)
        from importlib.resources import files
        pkg_schema = files("pdx_artifact_core.schemas").joinpath(Path(source_rel_path).name)
        assert pkg_schema.is_file(), f"Installed pdx_artifact_core package resource missing: {source_rel_path}"
        assert hashlib.sha256(pkg_schema.read_bytes()).hexdigest() == expected_blob_sha, (
            f"Installed package schema hash mismatch for {source_rel_path}!"
        )
            
    elif status == "proposed_g1":
        assert meta["source_commit"] is None, "Proposed contracts must have source_commit=None"
        assert meta["target_owner"] in ["prodocux/prodocux", "prodocux/pdx-artifact-engine"]
        assert meta["target_gate"] in ["G2", "G3", "G4", "G5"]
        
    elif status == "fleet_owned":
        assert meta["upstream_repo"] == FLEET_REPO
        assert meta["source_commit"] == FLEET_COMMIT
    else:
        pytest.fail(f"Unknown contract_status '{status}' in fixture {fixture_name}")

def test_negative_tampered_data_fails_hash_check():
    """Verify that tampering 1 byte in data causes data_sha256 verification failure."""
    fixture_path = FIXTURES_DIR / "c2_dossier_case_happy_path.json"
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    
    tampered_data = copy.deepcopy(doc["data"])
    tampered_data["product_name"] = "Tampered Face Cream"
    
    assert compute_canonical_hash(tampered_data) != doc["_metadata"]["data_sha256"]

def test_negative_extra_properties_rejected():
    """Verify that unknown extra properties are strictly rejected by additionalProperties: false."""
    schema = json.loads(EXPECTED_SCHEMAS["dossier_case_v1"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    
    doc = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))
    bad_data = copy.deepcopy(doc["data"])
    bad_data["unknown_injected_field"] = "malicious_payload"
    
    with pytest.raises(ValidationError):
        validator.validate(bad_data)
        
    # Test in nested formula item
    bad_formula_data = copy.deepcopy(doc["data"])
    bad_formula_data["formula"][0]["injected_nested_key"] = 123
    with pytest.raises(ValidationError):
        validator.validate(bad_formula_data)

@pytest.mark.parametrize("invalid_filename", [
    ".",
    "..",
    "../evil.pdf",
    "..\\evil.pdf",
    "folder/document.pdf",
    "/absolute/path/doc.pdf",
    "C:\\Windows\\System32\\calc.exe",
    "no_extension_file",
    ".hidden_file"
])
def test_negative_intake_request_filename_rejected(invalid_filename: str):
    """Verify that dot-segments, path traversals, absolute paths, and invalid basenames are rejected."""
    schema = json.loads(EXPECTED_SCHEMAS["intake_request_v1"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    
    doc = json.loads((FIXTURES_DIR / "c1_intake_request_sample.json").read_text(encoding="utf-8"))
    bad_data = copy.deepcopy(doc["data"])
    bad_data["document_filename"] = invalid_filename
    
    with pytest.raises(ValidationError):
        validator.validate(bad_data)

@pytest.mark.parametrize("valid_uri", [
    "gs://acme-corp-dossiers/2026/08/pif_final.pdf",
    "artifact://run-pif-20260813-001/outputs/report.docx",
    "artifact://run-123/simple.txt"
])
def test_positive_storage_identity_uri_allowed(valid_uri: str):
    """Verify that product-neutral artifact:// and gs:// URIs without dot-segments are accepted."""
    schema = json.loads(EXPECTED_SCHEMAS["artifact_storage_identity_v1"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    
    doc = json.loads((FIXTURES_DIR / "c5_storage_identity_sample.json").read_text(encoding="utf-8"))
    data = copy.deepcopy(doc["data"])
    data["uri"] = valid_uri
    validator.validate(data)

def test_positive_large_artifact_size_allowed():
    """Verify that product-neutral PDX schema does not enforce Fleet-specific 50MB limit (e.g. allows 100MB+ media)."""
    schema = json.loads(EXPECTED_SCHEMAS["artifact_storage_identity_v1"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    
    doc = json.loads((FIXTURES_DIR / "c5_storage_identity_sample.json").read_text(encoding="utf-8"))
    data = copy.deepcopy(doc["data"])
    data["size_bytes"] = 104857600  # 100 MiB
    validator.validate(data)

@pytest.mark.parametrize("invalid_uri", [
    # Dot segment traversals
    "artifact://run-1/../secret",
    "artifact://run-1/a/../../secret",
    "artifact://run-1/./output.pdf",
    "gs://valid-bucket/path/../secret",
    "gs://valid-bucket/./object",
    "gs://valid-bucket/../object",
    "artifact://run-1/dir/..",
    "artifact://run-1/dir/.",
    # Non-compliant schemes & paths
    "file:///etc/passwd",
    "file://C:/Windows/System32/cmd.exe",
    "C:\\Users\\Admin\\secret.key",
    "/var/run/secrets",
    "http://insecure-domain.com/artifact.pdf",
    "https://storage.googleapis.com/bucket/doc.pdf?X-Goog-Signature=malicious_leak",
    "s3://aws-bucket/doc.pdf",
    # Query, fragment, userinfo
    "gs://bucket/path/doc.pdf#fragment",
    "gs://bucket/path/doc.pdf?query=123",
    "gs://user:pass@bucket/path/doc.pdf",
    "artifact://run-123/doc.pdf?token=leak",
    "artifact://run-123/doc.pdf#frag"
])
def test_negative_storage_identity_uri_rejected(invalid_uri: str):
    """Verify that dot-segments, non-compliant schemes, file://, Windows paths, signed URLs, queries, and fragments are rejected."""
    schema = json.loads(EXPECTED_SCHEMAS["artifact_storage_identity_v1"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    
    doc = json.loads((FIXTURES_DIR / "c5_storage_identity_sample.json").read_text(encoding="utf-8"))
    bad_data = copy.deepcopy(doc["data"])
    bad_data["uri"] = invalid_uri
    
    with pytest.raises(ValidationError):
        validator.validate(bad_data)

def test_approval_fixture_digest_relationships():
    """Verify full-chain mathematical and referential relationships across all C4 fixtures."""
    happy_case = json.loads((FIXTURES_DIR / "c2_dossier_case_happy_path.json").read_text(encoding="utf-8"))["data"]
    pdx_plan = json.loads((FIXTURES_DIR / "c2_pdx_execution_plan_sample.json").read_text(encoding="utf-8"))["data"]
    checkpoint = json.loads((FIXTURES_DIR / "c4_workflow_checkpoint_sample.json").read_text(encoding="utf-8"))["data"]
    req = json.loads((FIXTURES_DIR / "c4_approval_request_sample.json").read_text(encoding="utf-8"))["data"]
    pdx_decision = json.loads((FIXTURES_DIR / "c4_approval_decision_sample.json").read_text(encoding="utf-8"))["data"]
    fleet_record = json.loads((FIXTURES_DIR / "c4_fleet_approval_record_sample.json").read_text(encoding="utf-8"))["data"]
    
    case_hash = compute_canonical_hash(happy_case)
    plan_hash = compute_canonical_hash(pdx_plan)
    
    # 1. Subject Digest Consistency
    assert checkpoint["subject_digest"] == case_hash
    assert req["subject_digest"] == case_hash
    assert pdx_decision["subject_digest"] == case_hash
    assert fleet_record["subject_case_digest"] == case_hash
    
    # 2. Plan Digest Consistency
    assert checkpoint["plan_digest"] == plan_hash
    assert req["plan_digest"] == plan_hash
    assert pdx_decision["plan_digest"] == plan_hash
    assert fleet_record["plan_digest"] == plan_hash
    
    # 3. Evidence Digests Chain Consistency
    assert checkpoint["evidence_digests"] == req["evidence_digests"]
    assert req["evidence_digests"] == pdx_decision["evidence_digests"]
    assert pdx_decision["evidence_digests"] == fleet_record["evidence_digests"]
    
    # 4. Identity & Correlation Consistency
    assert checkpoint["checkpoint_id"] == req["checkpoint_id"] == pdx_decision["checkpoint_id"] == fleet_record["checkpoint_id"]
    assert checkpoint["run_id"] == req["run_id"] == fleet_record["run_id"]
    assert req["approval_request_id"] == pdx_decision["approval_request_id"]
    assert pdx_decision["idempotency_key"] in fleet_record["canonical_idempotency_key"]
    assert pdx_decision["actor_id"] == fleet_record["authenticated_actor"]["sub"]

def test_generator_reproducibility():
    """Verify that running generate_g1_fixtures.py produces 100% byte-identical output."""
    generator_script = ROOT_DIR / "scripts" / "generate_g1_fixtures.py"
    
    # Capture current state of all fixtures
    before_state = {f.name: f.read_bytes() for f in sorted(FIXTURES_DIR.glob("*.json"))}
    
    # Execute generator
    res = subprocess.run([sys.executable, str(generator_script)], capture_output=True, text=True, cwd=str(ROOT_DIR))
    assert res.returncode == 0, f"Generator failed: {res.stderr}"
    
    # Compare
    after_state = {f.name: f.read_bytes() for f in sorted(FIXTURES_DIR.glob("*.json"))}
    assert before_state == after_state, "Generator produced non-reproducible fixture differences!"
