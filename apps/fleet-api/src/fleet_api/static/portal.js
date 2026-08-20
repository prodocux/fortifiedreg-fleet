/**
 * FortifiedReg Fleet v0.3.2 — Portal JavaScript Client (ES Module)
 * Strictly fail-closed: zero synthetic fallbacks, zero client-side mock tokens/digests.
 * 100% CSP compliant: zero inline style mutations, zero style attributes.
 */

// ── Global State ──
let SESSION = null;
let SAMPLES = null;
let STATE = {
    scenario: 'retinol',
    caseId: null,
    caseDigest: null,
    plan: null,
    planDigest: null,
    execution: null,
    checkpoint: null,
    approvalRequest: null,
    approvalDecision: null,
    registeredDocs: {},
    runId: null
};

const SCENARIO_CONFIGS = {
    retinol: {
        name: 'Retinol Night Serum',
        expected: 'PASS',
        description: 'Standard facial serum with Retinol (0.05%) and Phenoxyethanol (0.8%). MoS > 100.',
        formula: [
            { inci_name: 'Aqua', concentration_pct: 78.5 },
            { inci_name: 'Glycerin', concentration_pct: 5.0, cas_number: '56-81-5', noael_mg_kg_day: 10000.0 },
            { inci_name: 'Retinol', concentration_pct: 0.05, cas_number: '68-26-8', noael_mg_kg_day: 2.0 },
            { inci_name: 'Phenoxyethanol', concentration_pct: 0.8, cas_number: '122-99-6', noael_mg_kg_day: 500.0 }
        ]
    },
    peptide: {
        name: 'Active Peptide Eye Cream',
        expected: 'REVIEW',
        description: 'Novel peptide formulation missing authoritative 90-day oral toxicity NOAEL study.',
        formula: [
            { inci_name: 'Aqua', concentration_pct: 95.0 },
            { inci_name: 'Palmitoyl Tripeptide-38', concentration_pct: 2.0, cas_number: '1447824-23-8' },
            { inci_name: 'Phenoxyethanol', concentration_pct: 0.5, cas_number: '122-99-6', noael_mg_kg_day: 500.0 }
        ]
    },
    mercury: {
        name: 'Mercury Bleaching Cream',
        expected: 'FAIL',
        description: 'Contains Mercury (2.0%), strictly prohibited under EU Annex II entry #221.',
        formula: [
            { inci_name: 'Aqua', concentration_pct: 88.0 },
            { inci_name: 'Mercury', concentration_pct: 2.0, cas_number: '7439-97-6', noael_mg_kg_day: 0.01 }
        ]
    }
};

const FORMAT_DOC_TYPES = {
    pdf: 'SDS',
    docx: 'COA',
    csv: 'COA',
    xlsx: 'COA',
    pptx: 'COA'
};

// ── HTTP Helper (Fail-Closed) ──
async function fetchApi(url, options = {}) {
    const headers = options.headers || {};
    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
    }
    if (SESSION && SESSION.token && !headers['Authorization']) {
        headers['Authorization'] = 'Bearer ' + SESSION.token;
    }
    options.headers = headers;

    const response = await fetch(url, options);
    const text = await response.text();
    let data = null;
    try {
        data = JSON.parse(text);
    } catch (e) {
        data = null;
    }
    return {
        ok: response.ok,
        status: response.status,
        data,
        rawText: text,
        headers: response.headers
    };
}

// ── Initialization ──
document.addEventListener('DOMContentLoaded', async () => {
    setupTabNavigation();
    setupScenarioCards();
    setupActionButtons();
    await loadSamples();
    await checkDeploymentTruth();
    await acquireDemoSession();
});

// ── Tab Navigation ──
function setupTabNavigation() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.getAttribute('data-view');
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            const sec = document.getElementById(target);
            if (sec) sec.classList.add('active');
        });
    });
}

// ── Top Truth Bar & Health Probes ──
async function checkDeploymentTruth() {
    try {
        const verRes = await fetchApi('/v1/version');
        if (verRes.ok && verRes.data) {
            const v = verRes.data;
            setText('truth-version', v.fleet_version || '0.3.2');
            setText('truth-revision', v.cloud_run_revision || 'local');
            setText('truth-commit', v.fleet_commit ? v.fleet_commit.substring(0, 7) : 'unknown');
            setText('truth-pdx', v.pdx_core_pin ? v.pdx_core_pin.substring(0, 7) : 'unknown');
            setText('truth-prodocux', v.prodocux_pin ? v.prodocux_pin.substring(0, 7) : 'unknown');
        }

        const readyRes = await fetchApi('/v1/ready');
        const alertBanner = document.getElementById('demo-blocked-banner');
        const elReady = document.getElementById('truth-ready');

        if (readyRes.ok && readyRes.data && readyRes.data.status === 'ready') {
            setText('truth-ready', 'READY (200)');
            if (elReady) {
                elReady.classList.remove('ready-fail');
                elReady.classList.add('ready-pass');
            }
            if (alertBanner) alertBanner.classList.remove('visible');
        } else {
            setText('truth-ready', 'DEGRADED (' + readyRes.status + ')');
            if (elReady) {
                elReady.classList.remove('ready-pass');
                elReady.classList.add('ready-fail');
            }
            if (alertBanner) {
                alertBanner.textContent = 'DEMO BLOCKED: Upstream dependencies are unavailable (HTTP ' + readyRes.status + ').';
                alertBanner.classList.add('visible');
            }
        }
    } catch (err) {
        setText('truth-ready', 'UNAVAILABLE');
    }
}

// ── Load Golden Samples ──
async function loadSamples() {
    try {
        const res = await fetch('/static/samples.json');
        if (res.ok) {
            SAMPLES = await res.json();
            renderSampleCards();
        }
    } catch (e) {
        console.error('Failed to load golden samples:', e);
    }
}

function renderSampleCards() {
    if (!SAMPLES) return;
    const grid = document.getElementById('golden-intake-grid');
    if (!grid) return;
    grid.innerHTML = '';

    for (const [fmt, sample] of Object.entries(SAMPLES)) {
        const card = document.createElement('div');
        card.className = 'select-card';
        card.id = 'intake-card-' + fmt;
        card.innerHTML = `
            <div class="flex-between mb-05">
                <span class="badge badge-blue">${fmt.toUpperCase()}</span>
                <span id="status-${fmt}" class="badge badge-review">PENDING</span>
            </div>
            <div class="font-bold text-base mb-025">${escapeHtml(sample.fn || fmt)}</div>
            <div class="text-xs text-muted font-mono mb-05">
                SHA: ${sample.sha256 ? sample.sha256.substring(0, 12) + '...' : '—'}
            </div>
            <div id="profile-${fmt}" class="text-xs text-secondary min-h-12">
                ${escapeHtml(sample.type || 'Document')}
            </div>
        `;
        grid.appendChild(card);
    }
}

// ── Session Acquisition ──
async function acquireDemoSession(persona = 'formulator') {
    try {
        const res = await fetchApi('/v1/demo/session', {
            method: 'POST',
            body: { persona }
        });
        if (res.ok && res.data && res.data.access_token) {
            SESSION = {
                token: res.data.access_token,
                sub: res.data.sub,
                persona: res.data.persona,
                expires_at: res.data.expires_at
            };
            const chip = document.getElementById('session-chip');
            if (chip) {
                chip.classList.add('visible');
                chip.textContent = '🔬 ' + (res.data.persona_label || persona) + ' · ' + res.data.sub;
            }
        }
    } catch (e) {
        console.error('Session acquisition error:', e);
    }
}

// ── Step 1: Scenario Setup ──
function setupScenarioCards() {
    document.querySelectorAll('.scenario-option').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.scenario-option').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            STATE.scenario = card.getAttribute('data-scenario');
            resetSubsequentSteps();
        });
    });
}

function resetSubsequentSteps() {
    STATE.caseId = null;
    STATE.caseDigest = null;
    STATE.plan = null;
    STATE.execution = null;
    STATE.checkpoint = null;
    STATE.approvalRequest = null;
    STATE.approvalDecision = null;
    STATE.registeredDocs = {};
    STATE.runId = null;

    const evalBtn = document.getElementById('btn-run-eval');
    if (evalBtn) evalBtn.disabled = true;

    const evalOut = document.getElementById('eval-results-box');
    if (evalOut) {
        evalOut.classList.add('hidden');
        evalOut.classList.remove('visible');
    }

    const gateCard = document.getElementById('gate-card');
    if (gateCard) {
        gateCard.classList.add('hidden');
        gateCard.classList.remove('visible');
    }

    const finalCard = document.getElementById('final-evidence-card');
    if (finalCard) {
        finalCard.classList.add('hidden');
        finalCard.classList.remove('visible');
    }

    if (SAMPLES) {
        for (const fmt of Object.keys(SAMPLES)) {
            const st = document.getElementById('status-' + fmt);
            if (st) { st.className = 'badge badge-review'; st.textContent = 'PENDING'; }
        }
    }
}

// ── Action Buttons ──
function setupActionButtons() {
    const btnRegisterAll = document.getElementById('btn-register-all');
    if (btnRegisterAll) {
        btnRegisterAll.addEventListener('click', runEvidenceIntake);
    }

    const btnRunEval = document.getElementById('btn-run-eval');
    if (btnRunEval) {
        btnRunEval.addEventListener('click', runFleetEvaluation);
    }

    const btnApprove = document.getElementById('btn-approve-gate');
    if (btnApprove) {
        btnApprove.addEventListener('click', () => submitHumanDecision('approved'));
    }

    const btnReject = document.getElementById('btn-reject-gate');
    if (btnReject) {
        btnReject.addEventListener('click', () => submitHumanDecision('rejected'));
    }

    const btnDownloadEvidence = document.getElementById('btn-download-evidence');
    if (btnDownloadEvidence) {
        btnDownloadEvidence.addEventListener('click', downloadEvidencePackage);
    }
}

// ── Step 2: 5-Format Evidence Intake (Strict Fail-Closed, 0 Fallbacks) ──
async function runEvidenceIntake() {
    if (!SAMPLES) return;
    const btn = document.getElementById('btn-register-all');
    if (btn) btn.disabled = true;
    STATE.registeredDocs = {};

    let allSucceeded = true;

    for (const [fmt, sample] of Object.entries(SAMPLES)) {
        const st = document.getElementById('status-' + fmt);
        const pr = document.getElementById('profile-' + fmt);
        if (st) { st.className = 'badge badge-blue'; st.textContent = 'PROFILING...'; }

        // 1. Profile Document via Real API
        const docId = 'doc-' + fmt + '-' + Date.now();
        const profRes = await fetchApi('/v1/dossiers/documents/profile', {
            method: 'POST',
            body: {
                doc_id: docId,
                filename: sample.fn || (fmt + '_sample.' + fmt),
                content_b64: sample.b64
            }
        });

        if (profRes.ok && profRes.data) {
            // 2. Register Document into tenant resolver
            const regRes = await fetchApi('/v1/dossiers/documents/register', {
                method: 'POST',
                body: {
                    doc_id: docId,
                    filename: sample.fn || (fmt + '_sample.' + fmt),
                    content_b64: sample.b64
                }
            });

            // Fail closed: enforce genuine server-computed SHA-256 returned by API matching expected sample digest
            if (regRes.ok && regRes.data && regRes.data.sha256 && regRes.data.sha256 === sample.sha256) {
                STATE.registeredDocs[fmt] = {
                    doc_id: docId,
                    sha256: regRes.data.sha256,
                    filename: sample.fn || (fmt + '_sample.' + fmt),
                    fmt: fmt
                };
                if (st) { st.className = 'badge badge-pass'; st.textContent = 'VERIFIED'; }
                if (pr) {
                    const sm = profRes.data.structural_metadata || {};
                    const metric = sm.page_count ? (sm.page_count + ' pages') :
                                   sm.sheet_count ? (sm.sheet_count + ' sheets') :
                                   sm.slide_count ? (sm.slide_count + ' slides') :
                                   sm.row_count ? (sm.row_count + ' rows') :
                                   sm.paragraph_count ? (sm.paragraph_count + ' paras') : 'Structure parsed';
                    pr.textContent = metric + ' · ' + (regRes.data.size_bytes || 0) + ' B';
                }
            } else {
                allSucceeded = false;
                const errLabel = (regRes.ok && regRes.data && regRes.data.sha256 !== sample.sha256) ? 'SHA MISMATCH' : 'REG FAIL';
                if (st) { st.className = 'badge badge-fail'; st.textContent = errLabel; }
            }
        } else {
            allSucceeded = false;
            if (st) { st.className = 'badge badge-fail'; st.textContent = 'PROF FAIL'; }
        }
    }

    if (btn) btn.disabled = false;

    // Fail closed: only enable Step 3 evaluation if all 5 formats succeeded
    const evalBtn = document.getElementById('btn-run-eval');
    if (evalBtn) {
        evalBtn.disabled = !allSucceeded || (Object.keys(STATE.registeredDocs).length !== 5);
    }
}

// ── Step 3: Governed Fleet Evaluation ──
async function runFleetEvaluation() {
    const config = SCENARIO_CONFIGS[STATE.scenario];
    if (!config) return;

    const evalBtn = document.getElementById('btn-run-eval');
    if (evalBtn) evalBtn.disabled = true;

    const evalBox = document.getElementById('eval-results-box');
    if (evalBox) {
        evalBox.classList.remove('hidden');
        evalBox.classList.add('visible');
        evalBox.innerHTML = '<div class="text-muted">Executing multi-agent review pipeline...</div>';
    }

    // 1. Create Dossier Case strictly conforming to canonical DossierCase schema
    const caseUuid = crypto.randomUUID();
    const supplierDocs = Object.values(STATE.registeredDocs).map(d => ({
        doc_id: d.doc_id,
        filename: d.filename,
        doc_type: FORMAT_DOC_TYPES[d.fmt] || 'SDS',
        sha256: d.sha256,
        supplier_name: 'Golden Evidence Supplier',
        issue_date: '2025-01-10',
        expiry_date: '2028-01-10'
    }));

    const createRes = await fetchApi('/v1/dossiers/create', {
        method: 'POST',
        body: {
            case_id: caseUuid,
            tenant_id: 'tenant-demo',
            product_name: config.name,
            jurisdiction: 'EU',
            formula: config.formula,
            exposure_scenario: {
                product_type: 'Face serum',
                daily_applied_amount_g: 1.54,
                retention_factor: 1.0,
                body_weight_kg: 60.0
            },
            supplier_documents: supplierDocs
        }
    });

    if (!createRes.ok || !createRes.data) {
        showServerFailure(evalBox, 'Case Creation Failed', createRes);
        if (evalBtn) evalBtn.disabled = false;
        return;
    }

    STATE.caseId = caseUuid;
    STATE.caseDigest = createRes.data.case_digest;

    // 2. Compile and Run Workflow
    const runRes = await fetchApi('/v1/dossiers/' + caseUuid + '/compile-and-run', {
        method: 'POST'
    });

    if (!runRes.ok || !runRes.data) {
        showServerFailure(evalBox, 'Workflow Compilation/Run Failed', runRes);
        if (evalBtn) evalBtn.disabled = false;
        return;
    }

    // Fail closed: enforce valid plan and request_id from server
    if (!runRes.data.plan || !runRes.data.plan.request_id) {
        showServerFailure(evalBox, 'Invalid Server State: missing plan request_id', runRes);
        if (evalBtn) evalBtn.disabled = false;
        return;
    }

    STATE.plan = runRes.data.plan;
    STATE.planDigest = runRes.data.plan_digest;
    STATE.execution = runRes.data.execution;
    STATE.runId = runRes.data.plan.request_id;

    // 3. Render Verifier Results
    renderEvaluationResults(evalBox, runRes.data);

    // 4. Update Gate Card
    const execStatus = runRes.data.execution ? runRes.data.execution.status : null;
    const gateCard = document.getElementById('gate-card');
    if (gateCard) {
        gateCard.classList.remove('hidden');
        gateCard.classList.add('visible');
        if (execStatus === 'awaiting_approval') {
            const chk = runRes.data.execution.checkpoint;
            const apprReqId = runRes.data.execution.approval_request_id;

            if (!chk || !apprReqId) {
                enableGateButtons(false);
                setText('gate-blocked-reason', 'Server evidence incomplete: checkpoint or approval request ID missing.');
                return;
            }

            STATE.checkpoint = chk;
            STATE.approvalRequest = { approval_request_id: apprReqId };
            setText('gate-checkpoint-id', STATE.checkpoint.checkpoint_id);
            setText('gate-case-digest', STATE.caseDigest || '—');
            setText('gate-plan-digest', STATE.planDigest || '—');
            enableGateButtons(true);
            setText('gate-blocked-reason', '');
        } else {
            enableGateButtons(false);
            const reason = execStatus === 'failed' ? 'Governance policy blocked: formulation contains regulatory violations.' :
                           execStatus === 'review' ? 'Governance policy blocked: missing mandatory toxicology studies.' :
                           'Execution state does not permit approval (' + execStatus + ').';
            setText('gate-blocked-reason', reason);
        }
    }

    if (evalBtn) evalBtn.disabled = false;
}

function renderEvaluationResults(container, data) {
    const exec = data.execution || {};
    const verifier = (exec.verifier_results && exec.verifier_results[0]) || {};
    const status = (verifier.status || exec.status || 'unknown').toLowerCase();

    const badgeClass = status === 'pass' ? 'badge-pass' : status === 'review' ? 'badge-review' : 'badge-fail';
    const statusLabel = status.toUpperCase();

    let mosRows = '';
    const details = verifier.substance_evaluations || [];
    for (const sub of details) {
        const mosVal = sub.margin_of_safety ? sub.margin_of_safety.toFixed(1) : (sub.noael_mg_kg_day ? 'N/A' : 'Missing NOAEL');
        const verdictBadge = sub.status === 'pass' ? '<span class="badge badge-pass">PASS</span>' :
                             sub.status === 'review' ? '<span class="badge badge-review">REVIEW</span>' :
                             '<span class="badge badge-fail">FAIL</span>';
        mosRows += `
            <tr>
                <td><strong>${escapeHtml(sub.inci_name)}</strong></td>
                <td>${sub.concentration_pct}%</td>
                <td>${sub.sed_mg_kg_bw_day ? sub.sed_mg_kg_bw_day.toFixed(6) : '—'}</td>
                <td>${sub.noael_mg_kg_day || '—'}</td>
                <td class="font-mono font-bold">${mosVal}</td>
                <td>${verdictBadge}</td>
            </tr>
        `;
    }

    container.innerHTML = `
        <div class="flex-between mb-1">
            <div class="text-lg font-extrabold">Fleet Review Verdict: <span class="badge ${badgeClass}">${statusLabel}</span></div>
            <div class="text-xs text-muted font-mono">Plan SHA: ${escapeHtml(data.plan_digest ? data.plan_digest.substring(0, 16) : '—')}...</div>
        </div>
        ${details.length > 0 ? `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>INCI Name</th>
                        <th>Conc %</th>
                        <th>SED (mg/kg/d)</th>
                        <th>NOAEL</th>
                        <th>Margin of Safety</th>
                        <th>Verdict</th>
                    </tr>
                </thead>
                <tbody>
                    ${mosRows}
                </tbody>
            </table>
        ` : ''}
    `;
}

function enableGateButtons(enabled) {
    const btnApprove = document.getElementById('btn-approve-gate');
    const btnReject = document.getElementById('btn-reject-gate');
    if (btnApprove) btnApprove.disabled = !enabled;
    if (btnReject) btnReject.disabled = !enabled;
}

// ── Step 4: Human Decision Gate ──
async function submitHumanDecision(decision) {
    if (!STATE.checkpoint || !STATE.caseId || !STATE.approvalRequest) return;

    enableGateButtons(false);

    const payload = {
        checkpoint_id: STATE.checkpoint.checkpoint_id,
        run_id: STATE.checkpoint.run_id,
        approval_request_id: STATE.approvalRequest.approval_request_id,
        idempotency_key: 'idem-' + STATE.checkpoint.checkpoint_id + '-' + decision,
        decision: decision,
        reason: decision === 'approved' ? 'Approved by regulatory signatory.' : 'Rejected at Human-in-the-Loop gate.',
        case_digest: STATE.caseDigest,
        plan_digest: STATE.planDigest,
        evidence_digests: STATE.checkpoint.evidence_digests || {}
    };

    const res = await fetchApi('/v1/approval/decide', {
        method: 'POST',
        body: payload
    });

    if (!res.ok || !res.data) {
        const gateCard = document.getElementById('gate-card');
        showServerFailure(gateCard, 'Approval Decision Submission Failed', res);
        return;
    }

    STATE.approvalDecision = res.data;

    // ── Step 5: Finalized Certified Artifact ──
    const finalCard = document.getElementById('final-evidence-card');
    if (finalCard) {
        finalCard.classList.remove('hidden');
        finalCard.classList.add('visible');
        const art = res.data.artifact_identity || res.data.artifact_storage_identity;
        if (!art || !art.sha256) {
            showServerFailure(finalCard, 'Server Evidence Incomplete: artifact identity missing', res);
            return;
        }

        setText('art-uri', art.uri || art.artifact_uri || '—');
        setText('art-sha', art.sha256 || '—');
        setText('art-size', art.size_bytes !== undefined ? (art.size_bytes + ' B') : '—');
        setText('art-store-mode', res.data.artifact_store_mode || 'local_filesystem_ephemeral');
    }
}

// ── Step 5: Download Checksummed Evidence Package ──
async function downloadEvidencePackage() {
    if (!STATE.runId) return;
    const res = await fetchApi('/v1/evidence/runs/' + STATE.runId);
    if (res.ok && res.data) {
        const jsonStr = JSON.stringify(res.data, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'evidence_package_' + STATE.runId + '.json';
        a.click();
        URL.revokeObjectURL(url);
    } else {
        alert('Failed to retrieve evidence package (HTTP ' + res.status + ').');
    }
}

// ── Error Helper ──
function showServerFailure(container, title, res) {
    const reqId = (res.data && res.data.request_id) || 'unknown';
    const errCode = (res.data && res.data.error) || ('HTTP_' + res.status);
    const msg = (res.data && (res.data.detail || res.data.message)) || res.rawText || 'Server evidence incomplete.';

    const errDiv = document.createElement('div');
    errDiv.className = 'alert-banner visible mt-1';
    errDiv.innerHTML = `
        <strong>${escapeHtml(title)} [${escapeHtml(errCode)}]:</strong> ${escapeHtml(msg)}<br>
        <span class="text-xs font-mono">HTTP ${res.status} · Request ID: ${escapeHtml(reqId)}</span>
    `;
    container.appendChild(errDiv);
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
