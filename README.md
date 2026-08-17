# FortifiedReg Fleet (v0.3.0)

*Governed dossier production for regulated products*

Autonomous Multi-Agent Enterprise Regulatory Compliance Fleet with Human-in-the-Loop Cryptographic Verification.

## Overview
FortifiedReg Fleet is an enterprise-grade regulatory intelligence and compliance platform designed for regulated products compliance automation.

It automates European Union Regulation (EC) No 1223/2009 cosmetics Product Information File (PIF) compliance verification, toxicological Margin of Safety (MoS) evaluation according to SCCS 12th Notes of Guidance, raw material multi-format document extraction via ProDocuX HTTP Intake Adapter across 5 formats (PDF, DOCX, CSV, XLSX, PPTX), and deterministic execution orchestration via PDX Artifact Engine Core integration.

## Architecture Layers
- `packages/fleet-governance-core`: Pure domain models, abstract ports, 3-way cryptographic digest verification, lease fencing, and opaque tenant storage key derivation.
- `packages/fleet-domain-cosmetics`: Pure toxicology calculators (SED, MoS), INCI restriction verifiers (Annex II/V), and supplier document audits.
- `packages/fleet-adapter-pdx`: Live PDX Core adapter integrating with `pdx-artifact-core 0.2.0a2` (pin `55a9293...`), persistent `ApprovalLedger`, and allowlisted host transform dispatcher.
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

# Full Workspace Regression Suite (240+ tests)
pytest -v
```
