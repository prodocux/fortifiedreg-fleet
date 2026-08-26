# FortifiedReg Fleet (v0.4.0)

*Governed dossier production for regulated products*

Autonomous Multi-Agent Enterprise Regulatory Compliance Fleet with Human-in-the-Loop Cryptographic Verification.

## Overview
FortifiedReg Fleet is an enterprise-grade regulatory intelligence and compliance platform designed for regulated products compliance automation.

It automates European Union Regulation (EC) No 1223/2009 cosmetics Product Information File (PIF) compliance verification, toxicological Margin of Safety (MoS) evaluation according to SCCS 12th Notes of Guidance, raw material multi-format document extraction via ProDocuX HTTP Intake Adapter across 5 formats (PDF, DOCX, CSV, XLSX, PPTX), and deterministic execution orchestration via PDX Artifact Engine Core integration.

## Architecture Layers
- `packages/fleet-governance-core`: Pure domain models, abstract ports, 3-way cryptographic digest verification, lease fencing, and opaque tenant storage key derivation.
- `packages/fleet-domain-cosmetics`: Pure toxicology calculators (SED, MoS), INCI restriction verifiers (Annex II/V), and supplier document audits.
- `packages/fleet-adapter-pdx`: Live PDX Core adapter integrating with `pdx-artifact-core 0.2.0a2` (pin `61cff57...`), persistent `ApprovalLedger`, and allowlisted host transform dispatcher.
- `packages/fleet-adapter-prodocux`: Production ProDocuX HTTP Intake Adapter supporting 5 document formats (PDF, DOCX, CSV, XLSX, PPTX) with exact format boundaries, retry backoff, and sanitized error mapping.
- `packages/fleet-adapter-local`: Local file-backed and SQLite ACID persistence adapters, atomic non-overwriting process-crash-recoverable artifact publishing, and 4-stage verified artifact content resolver.
- `packages/fleet-adapter-gcp`: Thread-safe in-memory stores and cloud persistence ports.
- `packages/fleet-adapter-google-adk`: Google Model Armor security scanner and structured toxicology agent.
- `apps/fleet-api`: FastAPI REST backend with fail-closed JWT auth, RBAC, separated `/v1/health` (liveness) and `/v1/ready` (readiness) probes, single-transaction atomic approval decisions, and immutable audit logging.

## Conformance & Verification Suites
```bash
# G1: Canonical Contract Conformance & Synthetic Fixtures (79 tests)
pytest tests/test_g1_contract_conformance.py -v

# G6: Exact-Pin Schema Conformance against Upstream Git Trees (9 tests)
pytest tests/test_g6_adapter_conformance.py -v

# G6A: ProDocuX HTTP Intake In-Process Conformance across 5 Formats (23 tests)
pytest tests/test_g6a_prodocux_inprocess_conformance.py -v

# G6A: ProDocuX Live HTTP Endpoint Harness (Environment-conditioned, reports SKIPPED (NOT RUN) if unset)
pytest tests/test_g6a_prodocux_live_conformance.py -v

# G6B: PDX Core Primitives & Persistent Ledger Conformance (5 tests)
pytest tests/test_g6b_pdx_core_conformance.py -v

# G7: Lifecycle Conformance, SQLite ACID, Lease Fencing & Crash-Safe Storage (12 tests)
pytest tests/test_g7_lifecycle_conformance.py -v

# B8: Host Subprocess & Docker Container Integration Gates
pytest tests/test_b8_production_deployment_gate.py tests/test_b8_docker_deployment_gate.py -v

# B9: Docker Production Live-Adapter Integration Gate
pytest tests/test_b9_docker_production_live_gate.py -v

# B10: Google Cloud Run Remote Deployment Gate
pytest tests/test_b10_cloud_run_remote_gate.py -v

# Full Workspace Regression Suite (120+ tests)
pytest -v
```

## Google Cloud Run Deployment & Spin-up Guide

FortifiedReg Fleet is packaged for serverless deployment on **Google Cloud Run**, utilizing **Google Artifact Registry**, **Google Cloud Secret Manager**, and **Google Model Armor** guardrails.

### 1. Prerequisites
- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed and authenticated.
- A Google Cloud Project with Billing enabled.

### 2. One-Click Deployment
Set your Project ID and execute the automated deployment script:

```bash
# Set your GCP Project ID
export GCP_PROJECT_ID="your-gcp-project-id"

# Run automated Cloud Run deployment (Linux / macOS / Cloud Shell)
bash deploy/cloudrun/deploy.sh
```

Or on Windows (PowerShell):
```powershell
$env:GCP_PROJECT_ID = "your-gcp-project-id"
.\deploy\cloudrun\deploy.ps1
```

The script automatically:
1. Enables required Google Cloud APIs (`run`, `artifactregistry`, `secretmanager`, `cloudbuild`, `logging`).
2. Creates an Artifact Registry repository (`fortifiedreg`).
3. Generates and stores secure keys in Google Secret Manager (`fleet-jwt-secret`).
4. Builds the OCI revision-pinned container image via Cloud Build.
5. Deploys to Cloud Run with scale-to-zero configuration (`--min-instances 0`) to avoid unnecessary cloud costs.
6. Prints the live HTTPS URL (`https://fortifiedreg-fleet-<hash>-<region>.a.run.app`) and runs a health probe.

### 3. Remote Verification Suite
To run the automated compliance suite against your live Cloud Run deployment:
```bash
FLEET_REMOTE_URL="https://fortifiedreg-fleet-<hash>-<region>.a.run.app" pytest -v tests/test_b10_cloud_run_remote_gate.py
```

### 4. Zero-Cost Teardown
When demo recording is completed, teardown all deployed resources with a single command:
```bash
bash deploy/cloudrun/destroy.sh
```

