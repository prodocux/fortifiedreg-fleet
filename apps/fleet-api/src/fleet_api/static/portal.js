/**
 * FortifiedReg Fleet v0.4.0 — PWA & Role-Based Autonomous Compliance Client.
 * Implements strict CSP compliance (0 inline styles), single-identity dual-role session,
 * event-driven component telemetry, two-tier import preview, and proposal governance.
 */

// Global Application State
const STATE = {
  token: null,
  sessionId: null,
  sub: null,
  actingRole: 'formulator',
  expiresAt: null,
  timerInterval: null,
  draft: null,
  pendingPreviewCandidates: [],
  selectedProposalId: null,
  deferredInstallPrompt: null
};

// Standard Cosmetic Ingredient Knowledge Database for Auto-complete
const INGREDIENT_DATABASE = [
  { inci: "Aqua", cas: "7732-18-5", noael: null, defaultPct: 70.0 },
  { inci: "Glycerin", cas: "56-81-5", noael: 1000.0, defaultPct: 5.0 },
  { inci: "Retinol", cas: "68-26-8", noael: 2.0, defaultPct: 0.05 },
  { inci: "Phenoxyethanol", cas: "122-99-6", noael: 500.0, defaultPct: 0.8 },
  { inci: "Niacinamide", cas: "98-92-0", noael: 50.0, defaultPct: 2.0 },
  { inci: "Sodium Hyaluronate", cas: "9067-32-7", noael: 1000.0, defaultPct: 0.2 },
  { inci: "Palmitoyl Tripeptide-38", cas: "1447824-23-8", noael: null, defaultPct: 2.0 },
  { inci: "Rosa Damascena Flower Water", cas: "90106-38-0", noael: 1000.0, defaultPct: 10.0 },
  { inci: "Phenethyl Alcohol", cas: "60-12-8", noael: 500.0, defaultPct: 0.3 },
  { inci: "Tocopherol", cas: "59-02-9", noael: 500.0, defaultPct: 0.5 },
  { inci: "Ascorbyl Glucoside", cas: "129499-78-1", noael: 1000.0, defaultPct: 2.0 },
  { inci: "Panthenol", cas: "81-13-0", noael: 1000.0, defaultPct: 1.0 },
  { inci: "Allantoin", cas: "97-59-6", noael: 1000.0, defaultPct: 0.2 },
  { inci: "Squalane", cas: "111-01-3", noael: 1000.0, defaultPct: 3.0 },
  { inci: "Ceramide NP", cas: "100403-19-8", noael: 1000.0, defaultPct: 0.1 },
  { inci: "Salicylic Acid", cas: "69-72-7", noael: 50.0, defaultPct: 1.0 },
  { inci: "Linalool", cas: "78-70-6", noael: 117.0, defaultPct: 0.005 },
  { inci: "Geraniol", cas: "106-24-1", noael: 100.0, defaultPct: 0.003 },
  { inci: "Mercury", cas: "7439-97-6", noael: 0.01, defaultPct: 1.0 }
];

// ---------------------------------------------------------------------------
// 1. PWA & Service Worker Initialization
// ---------------------------------------------------------------------------

function initPWA() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/service-worker.js?v=0.4.1').then((reg) => {
        reg.update();
      }).catch((err) => {
        console.warn('ServiceWorker registration error:', err);
      });
    });
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    STATE.deferredInstallPrompt = e;
    const installBtn = document.getElementById('btn-install-pwa');
    if (installBtn) installBtn.classList.remove('hidden');
  });

  const installBtn = document.getElementById('btn-install-pwa');
  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (STATE.deferredInstallPrompt) {
        STATE.deferredInstallPrompt.prompt();
        const { outcome } = await STATE.deferredInstallPrompt.userChoice;
        if (outcome === 'accepted') {
          installBtn.classList.add('hidden');
        }
        STATE.deferredInstallPrompt = null;
      }
    });
  }

  window.addEventListener('online', () => {
    const banner = document.getElementById('offline-banner');
    if (banner) banner.classList.add('hidden');
  });

  window.addEventListener('offline', () => {
    const banner = document.getElementById('offline-banner');
    if (banner) banner.classList.remove('hidden');
    setTelemetryStatus('node-prodocux-intake', 'OFFLINE', 'badge-fail');
    setTelemetryStatus('node-cosmetics-engine', 'OFFLINE', 'badge-fail');
    setTelemetryStatus('node-gemini-assistant', 'OFFLINE', 'badge-fail');
    setTelemetryStatus('node-pdx-orchestrator', 'OFFLINE', 'badge-fail');
  });
}


// ---------------------------------------------------------------------------
// 2. Telemetry Status Helper (Event-Driven Only)
// ---------------------------------------------------------------------------

function setTelemetryStatus(nodeId, statusText, badgeClass) {
  const statusEl = document.querySelector(`#${nodeId} .node-status`);
  if (!statusEl) return;
  statusEl.textContent = statusText;
  statusEl.className = `node-status badge ${badgeClass}`;
}


// ---------------------------------------------------------------------------
// 3. Session & Timer Management
// ---------------------------------------------------------------------------

async function initSession(actingRole = 'formulator') {
  try {
    const res = await fetch('/v1/demo/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acting_role: actingRole })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    STATE.token = data.token;
    STATE.sessionId = data.session_id;
    STATE.sub = data.sub;
    STATE.actingRole = data.acting_role;
    STATE.expiresAt = new Date(data.expires_at).getTime();

    updateSessionChip();
    startSessionTimer();
    await loadDraft();
  } catch (err) {
    console.error('Failed to initialize demo session:', err);
  }
}

function updateSessionChip() {
  const labelEl = document.getElementById('session-label');
  if (labelEl) {
    const shortId = STATE.sessionId ? STATE.sessionId.slice(-6).toUpperCase() : 'INIT';
    labelEl.textContent = `Session #${shortId}`;
  }
}

function startSessionTimer() {
  if (STATE.timerInterval) clearInterval(STATE.timerInterval);

  const timerEl = document.getElementById('session-timer');
  STATE.timerInterval = setInterval(() => {
    if (!STATE.expiresAt) return;
    const now = Date.now();
    const remainingMs = STATE.expiresAt - now;

    if (remainingMs <= 0) {
      clearInterval(STATE.timerInterval);
      if (timerEl) timerEl.textContent = 'EXPIRED';
      alert('Demo Session has expired. Please click [Restart Demo Session] to generate a fresh workspace.');
      return;
    }

    const totalSec = Math.floor(remainingMs / 1000);
    const mm = String(Math.floor(totalSec / 60)).padStart(2, '0');
    const ss = String(totalSec % 60).padStart(2, '0');
    if (timerEl) timerEl.textContent = `${mm}:${ss}`;
  }, 1000);
}

async function restartSession() {
  if (STATE.timerInterval) clearInterval(STATE.timerInterval);
  STATE.draft = null;
  STATE.selectedProposalId = null;

  try {
    const res = await fetch('/v1/demo/session/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acting_role: 'formulator' })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    STATE.token = data.token;
    STATE.sessionId = data.session_id;
    STATE.sub = data.sub;
    STATE.actingRole = 'formulator';
    STATE.expiresAt = new Date(data.expires_at).getTime();

    updateSessionChip();
    startSessionTimer();
    switchRole('formulator');
    await loadDraft();

    // Reset telemetry nodes to IDLE
    setTelemetryStatus('node-prodocux-intake', 'IDLE', 'badge-idle');
    setTelemetryStatus('node-cosmetics-engine', 'IDLE', 'badge-idle');
    setTelemetryStatus('node-gemini-assistant', 'IDLE', 'badge-idle');
    setTelemetryStatus('node-pdx-orchestrator', 'IDLE', 'badge-idle');
    setTelemetryStatus('node-manager-gate', 'IDLE', 'badge-idle');
    setTelemetryStatus('node-prodocux-render', 'IDLE', 'badge-idle');
  } catch (err) {
    console.error('Failed to restart session:', err);
  }
}


// ---------------------------------------------------------------------------
// 4. Role Switching (Single Identity Simulation)
// ---------------------------------------------------------------------------

function switchRole(role) {
  STATE.actingRole = role;

  const btnFormulator = document.getElementById('btn-role-formulator');
  const btnManager = document.getElementById('btn-role-manager');
  const viewFormulator = document.getElementById('view-formulator');
  const viewManager = document.getElementById('view-manager');
  const viewExport = document.getElementById('view-export');

  if (role === 'formulator') {
    btnFormulator.classList.add('active');
    btnManager.classList.remove('active');
    viewFormulator.classList.add('active');
    viewManager.classList.remove('active');
    if (viewExport) viewExport.classList.remove('active');
  } else {
    btnManager.classList.add('active');
    btnFormulator.classList.remove('active');
    viewManager.classList.add('active');
    viewFormulator.classList.remove('active');
    if (viewExport) viewExport.classList.remove('active');
    loadProposalsInbox();
  }
}


// ---------------------------------------------------------------------------
// 5. Formulation Management & SCCS Diagnostics
// ---------------------------------------------------------------------------

function collectIngredientsFromTable() {
  const tbody = document.getElementById('tbody-ingredients');
  if (!tbody) return STATE.draft ? STATE.draft.ingredients : [];

  const rows = tbody.querySelectorAll('tr');
  const ingredients = [];
  rows.forEach((tr) => {
    const nameInput = tr.querySelector('[data-field="inci_name"]');
    const concInput = tr.querySelector('[data-field="concentration_pct"]');
    const casInput = tr.querySelector('[data-field="cas_number"]');
    const noaelInput = tr.querySelector('[data-field="noael_mg_kg_day"]');

    if (nameInput && concInput) {
      const name = nameInput.value.trim();
      if (name) {
        ingredients.push({
          inci_name: name,
          concentration_pct: parseFloat(concInput.value) || 0,
          cas_number: casInput ? casInput.value.trim() : '',
          noael_mg_kg_day: (noaelInput && noaelInput.value.trim() !== '') ? parseFloat(noaelInput.value) : null
        });
      }
    }
  });
  return ingredients;
}

async function loadDraft() {
  if (!STATE.token) return;
  try {
    const res = await fetch('/v1/formulations/draft', {
      headers: { 'Authorization': `Bearer ${STATE.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    STATE.draft = data.draft;

    renderFormulationTable();
    renderDiagnostics(data.sccs_evaluation, data.inci_evaluation);
    await loadAssistantSuggestions();
  } catch (err) {
    console.error('Failed to load draft:', err);
  }
}

function renderFormulationTable() {
  if (!STATE.draft) return;
  const tbody = document.getElementById('tbody-ingredients');
  const nameInput = document.getElementById('input-product-name');
  const revBadge = document.getElementById('draft-revision-badge');
  const digestBadge = document.getElementById('draft-digest-badge');

  if (nameInput) nameInput.value = STATE.draft.product_name || '';
  if (revBadge) revBadge.textContent = `Revision: ${STATE.draft.revision}`;
  if (digestBadge) digestBadge.textContent = `Case SHA: ${STATE.draft.case_digest.slice(0, 12)}...`;

  if (!tbody) return;
  tbody.innerHTML = '';

  STATE.draft.ingredients.forEach((item, index) => {
    const tr = document.createElement('tr');

    tr.innerHTML = `
      <td><input type="text" list="ingredient-library-datalist" class="table-input input-inci" data-field="inci_name" data-index="${index}" value="${item.inci_name}" placeholder="Type INCI or select..."></td>
      <td><input type="number" step="0.01" class="table-input input-pct" data-field="concentration_pct" data-index="${index}" value="${item.concentration_pct}"></td>
      <td><input type="text" class="table-input input-cas" data-field="cas_number" data-index="${index}" value="${item.cas_number || ''}" placeholder="CAS No."></td>
      <td><input type="number" step="0.1" class="table-input input-noael" data-field="noael_mg_kg_day" data-index="${index}" value="${item.noael_mg_kg_day ?? ''}" placeholder="NOAEL"></td>
      <td class="text-center"><button type="button" class="btn btn-danger btn-sm btn-del-row" data-index="${index}">🗑️</button></td>
    `;
    tbody.appendChild(tr);
  });

  // Bind change and input events with smart database auto-fill
  tbody.querySelectorAll('.table-input').forEach((input) => {
    const updateMem = (e) => {
      const idx = parseInt(e.target.dataset.index, 10);
      const field = e.target.dataset.field;
      let val = e.target.value;

      if (field === 'concentration_pct') val = parseFloat(val) || 0;
      if (field === 'noael_mg_kg_day') val = (val && val.trim() !== '') ? parseFloat(val) : null;

      if (STATE.draft && STATE.draft.ingredients[idx]) {
        STATE.draft.ingredients[idx][field] = val;

        // Auto-complete CAS and NOAEL if exact/fuzzy INCI match found in database
        if (field === 'inci_name' && val) {
          const match = INGREDIENT_DATABASE.find(
            (db) => db.inci.toLowerCase() === val.trim().toLowerCase()
          );
          if (match) {
            const tr = e.target.closest('tr');
            if (match.cas && (!STATE.draft.ingredients[idx].cas_number || STATE.draft.ingredients[idx].cas_number === '')) {
              STATE.draft.ingredients[idx].cas_number = match.cas;
              if (tr) {
                const casInput = tr.querySelector('.input-cas');
                if (casInput) casInput.value = match.cas;
              }
            }
            if (match.noael != null && STATE.draft.ingredients[idx].noael_mg_kg_day == null) {
              STATE.draft.ingredients[idx].noael_mg_kg_day = match.noael;
              if (tr) {
                const noaelInput = tr.querySelector('.input-noael');
                if (noaelInput) noaelInput.value = match.noael;
              }
            }
          }
        }
      }
    };
    input.addEventListener('change', updateMem);
    input.addEventListener('input', updateMem);
  });

  tbody.querySelectorAll('.btn-del-row').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      STATE.draft.ingredients = collectIngredientsFromTable();
      const idx = parseInt(e.target.dataset.index, 10);
      STATE.draft.ingredients.splice(idx, 1);
      renderFormulationTable();
      saveDraft();
    });
  });
}

function addIngredientRow() {
  if (!STATE.draft) return;
  STATE.draft.ingredients = collectIngredientsFromTable();
  STATE.draft.ingredients.push({
    inci_name: '',
    concentration_pct: 1.0,
    cas_number: '',
    noael_mg_kg_day: null
  });
  renderFormulationTable();
}

function addQuickIngredient(inci, cas, noael, pct) {
  if (!STATE.draft) return;
  STATE.draft.ingredients = collectIngredientsFromTable();
  
  // Check if already present
  const existing = STATE.draft.ingredients.find(i => i.inci_name.toLowerCase() === inci.toLowerCase());
  if (existing) {
    existing.concentration_pct = pct;
    existing.cas_number = cas;
    existing.noael_mg_kg_day = noael;
  } else {
    STATE.draft.ingredients.push({
      inci_name: inci,
      concentration_pct: pct,
      cas_number: cas,
      noael_mg_kg_day: noael
    });
  }
  renderFormulationTable();
  saveDraft();
}

async function saveDraft() {
  if (!STATE.token || !STATE.draft) return;
  const nameInput = document.getElementById('input-product-name');
  if (nameInput) STATE.draft.product_name = nameInput.value.trim();

  STATE.draft.ingredients = collectIngredientsFromTable();

  const saveBtn = document.getElementById('btn-save-draft');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '💾 Saving & Analyzing...';
  }

  setTelemetryStatus('node-cosmetics-engine', 'EVALUATING', 'badge-running');

  try {
    const res = await fetch('/v1/formulations/draft', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${STATE.token}`
      },
      body: JSON.stringify({
        product_name: STATE.draft.product_name,
        ingredients: STATE.draft.ingredients,
        exposure_scenario: STATE.draft.exposure_scenario,
        acting_role: STATE.actingRole
      })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    STATE.draft = data.draft;

    renderFormulationTable();
    renderDiagnostics(data.sccs_evaluation, data.inci_evaluation);
    await loadAssistantSuggestions();

    const isPass = (data.sccs_evaluation?.status || '').toLowerCase() === 'pass' &&
                   (data.inci_evaluation?.status || '').toLowerCase() === 'pass';
    setTelemetryStatus('node-cosmetics-engine', isPass ? 'PASSED' : 'REVIEW/FAIL', isPass ? 'badge-pass' : 'badge-review');

    if (saveBtn) {
      saveBtn.textContent = '✅ Saved & Analyzed!';
      setTimeout(() => {
        saveBtn.textContent = '💾 Save & Re-analyze Formulation';
        saveBtn.disabled = false;
      }, 1500);
    }
  } catch (err) {
    console.error('Failed to save draft:', err);
    setTelemetryStatus('node-cosmetics-engine', 'ERROR', 'badge-fail');
    if (saveBtn) {
      saveBtn.textContent = '❌ Save Failed';
      setTimeout(() => {
        saveBtn.textContent = '💾 Save & Re-analyze Formulation';
        saveBtn.disabled = false;
      }, 2000);
    }
  }
}

function renderDiagnostics(sccs, inci) {
  const scoreEl = document.getElementById('compliance-score');
  const mosList = document.getElementById('sidebar-mos-list');
  const gateIndicator = document.getElementById('gate-indicator');
  const gateDesc = document.getElementById('gate-desc');

  if (mosList) {
    mosList.innerHTML = '';
    const substances = sccs?.substance_evaluations || [];
    substances.forEach((s) => {
      const div = document.createElement('div');
      div.className = 'mos-item flex-between';
      const mosVal = s.margin_of_safety != null ? Math.round(s.margin_of_safety) : 'N/A';
      const stLower = (s.status || '').toLowerCase();
      const badgeClass = stLower === 'pass' ? 'badge-pass' : (stLower === 'review' ? 'badge-review' : 'badge-fail');
      div.innerHTML = `
        <span><strong>${s.inci_name}</strong> (${s.concentration_pct}%)</span>
        <span class="badge ${badgeClass}">
          MoS: ${mosVal}
        </span>
      `;
      mosList.appendChild(div);
    });
  }

  // Update Gate Status Box with strict case-insensitive status handling
  if (gateIndicator && gateDesc) {
    const ingredients = STATE.draft ? STATE.draft.ingredients : [];
    const hasMercury = ingredients.some(i => (i.inci_name || '').toLowerCase().includes('mercury'));
    const hasExcessPreservative = ingredients.some(i => (i.inci_name || '').toLowerCase() === 'phenoxyethanol' && i.concentration_pct > 1.0);

    const sccsSt = (sccs?.status || '').toLowerCase();
    const inciSt = (inci?.status || '').toLowerCase();

    if (hasMercury || hasExcessPreservative || sccsSt === 'fail' || inciSt === 'fail') {
      gateIndicator.textContent = 'BLOCKED (FAIL)';
      gateIndicator.className = 'gate-status-indicator badge-fail';
      gateDesc.textContent = 'Formulation contains prohibited substances (Annex II) or preservative limits exceeded (Annex V); submission blocked.';
    } else if (sccsSt === 'review' || inciSt === 'review') {
      gateIndicator.textContent = 'REVIEW NEEDED';
      gateIndicator.className = 'gate-status-indicator badge-review';
      gateDesc.textContent = 'Some ingredients lack toxicology NOAEL studies; manager approval rationale required.';
    } else {
      gateIndicator.textContent = 'READY (PASS)';
      gateIndicator.className = 'gate-status-indicator badge-pass';
      gateDesc.textContent = 'Formulation is fully compliant; all ingredients MoS ≥ 100.';
    }
  }
}


// ---------------------------------------------------------------------------
// 6. AI Copilot Suggestions & Interactive Dialogue
// ---------------------------------------------------------------------------

async function loadAssistantSuggestions() {
  if (!STATE.token || !STATE.draft) return;
  setTelemetryStatus('node-gemini-assistant', 'ANALYZING', 'badge-running');

  try {
    const res = await fetch('/v1/assistant/suggestions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${STATE.token}`
      },
      body: JSON.stringify({
        product_name: STATE.draft.product_name,
        ingredients: STATE.draft.ingredients,
        exposure_scenario: STATE.draft.exposure_scenario
      })
    });

    if (!res.ok) return;
    const data = await res.json();

    const scoreEl = document.getElementById('compliance-score');
    if (scoreEl) scoreEl.textContent = data.overall_compliance_score;

    const listEl = document.getElementById('sidebar-suggestions-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    data.suggestions.forEach((s) => {
      const card = document.createElement('div');
      card.className = `suggestion-card ${s.severity === 'high' ? 'severity-high' : ''}`;

      let btnHtml = '';
      if (s.proposed_patch && s.action_label) {
        btnHtml = `<button type="button" class="btn btn-secondary btn-sm btn-apply-patch mt-05">${s.action_label}</button>`;
      }

      card.innerHTML = `
        <div class="suggestion-title">${s.title}</div>
        <div class="suggestion-msg">${s.message}</div>
        <div class="suggestion-citation">📜 ${s.rule_citation}</div>
        ${btnHtml}
      `;

      if (s.proposed_patch) {
        const patchBtn = card.querySelector('.btn-apply-patch');
        if (patchBtn) {
          patchBtn.addEventListener('click', () => applySuggestionPatch(s.proposed_patch));
        }
      }

      listEl.appendChild(card);
    });

    setTelemetryStatus('node-gemini-assistant', 'READY', 'badge-pass');
  } catch (err) {
    console.error('Failed to load assistant suggestions:', err);
    setTelemetryStatus('node-gemini-assistant', 'UNAVAILABLE', 'badge-review');
  }
}

function applySuggestionPatch(patch) {
  if (!STATE.draft) return;
  STATE.draft.ingredients = collectIngredientsFromTable();

  if (patch.remove_inci) {
    STATE.draft.ingredients = STATE.draft.ingredients.filter(
      (item) => item.inci_name.toLowerCase() !== patch.remove_inci.toLowerCase()
    );
  } else if (patch.inci_name) {
    const item = STATE.draft.ingredients.find(
      (i) => i.inci_name.toLowerCase() === patch.inci_name.toLowerCase()
    );
    if (item) {
      if (patch.concentration_pct != null) item.concentration_pct = patch.concentration_pct;
      if (patch.noael_mg_kg_day != null) item.noael_mg_kg_day = patch.noael_mg_kg_day;
    }
  }

  saveDraft();
}

async function sendChatMessage(customQuery = null) {
  if (!STATE.token) return;
  const inputEl = document.getElementById('input-chat-message');
  const query = (customQuery || (inputEl ? inputEl.value : '')).trim();
  if (!query) return;

  if (inputEl) inputEl.value = '';

  const messagesContainer = document.getElementById('chat-messages');
  if (messagesContainer) {
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble chat-user';
    userBubble.innerHTML = `
      <div class="chat-sender">🔬 Formulator</div>
      <div class="chat-text">${escapeHtml(query)}</div>
    `;
    messagesContainer.appendChild(userBubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  setTelemetryStatus('node-gemini-assistant', 'REASONING', 'badge-running');

  try {
    const res = await fetch('/v1/assistant/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${STATE.token}`
      },
      body: JSON.stringify({
        message: query,
        product_name: STATE.draft ? STATE.draft.product_name : 'Formula',
        ingredients: STATE.draft ? STATE.draft.ingredients : [],
        exposure_scenario: STATE.draft ? STATE.draft.exposure_scenario : null
      })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (messagesContainer) {
      const botBubble = document.createElement('div');
      botBubble.className = 'chat-bubble chat-bot';
      const formattedReply = formatMarkdown(data.reply);
      botBubble.innerHTML = `
        <div class="chat-sender">✨ ${data.provider}</div>
        <div class="chat-text">${formattedReply}</div>
      `;
      messagesContainer.appendChild(botBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    setTelemetryStatus('node-gemini-assistant', 'READY', 'badge-pass');
  } catch (err) {
    console.error('Failed to send chat message:', err);
    if (messagesContainer) {
      const errBubble = document.createElement('div');
      errBubble.className = 'chat-bubble chat-bot';
      errBubble.innerHTML = `
        <div class="chat-sender">⚠️ Gemini Advisor</div>
        <div class="chat-text">Unable to complete query. Please try again.</div>
      `;
      messagesContainer.appendChild(errBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    setTelemetryStatus('node-gemini-assistant', 'UNAVAILABLE', 'badge-review');
  }
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n\* /g, '<br>• ')
    .replace(/\n/g, '<br>');
}


// ---------------------------------------------------------------------------
// 7. 5-Format Preset Import Preview
// ---------------------------------------------------------------------------

async function triggerParsePreview(scenarioKey) {
  setTelemetryStatus('node-prodocux-intake', 'PARSING', 'badge-running');
  STATE.pendingScenarioKey = scenarioKey;

  try {
    const res = await fetch('/v1/formulations/parse-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_key: scenarioKey })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    STATE.pendingPreviewCandidates = data.candidates || [];

    const modal = document.getElementById('modal-import-preview');
    const tbody = document.getElementById('modal-tbody-candidates');
    const warningsEl = document.getElementById('modal-warnings');

    if (tbody) {
      tbody.innerHTML = '';
      STATE.pendingPreviewCandidates.forEach((c) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${c.inci_name}</strong></td>
          <td>${c.concentration_pct}%</td>
          <td>${c.cas_number || '—'}</td>
          <td>${c.noael_mg_kg_day ?? '—'}</td>
          <td><span class="text-xs font-mono text-muted">${c.source_location}</span></td>
          <td><span class="badge badge-info">${Math.round(c.confidence * 100)}%</span></td>
        `;
        tbody.appendChild(tr);
      });
    }

    if (warningsEl) {
      const allWarnings = STATE.pendingPreviewCandidates.flatMap((c) => c.warnings || []);
      warningsEl.textContent = allWarnings.length > 0 ? `⚠️ Warnings: ${allWarnings.join('; ')}` : '';
    }

    if (modal) modal.classList.remove('hidden');
    setTelemetryStatus('node-prodocux-intake', 'EXTRACTED', 'badge-pass');
  } catch (err) {
    console.error('Parse preview failed:', err);
    setTelemetryStatus('node-prodocux-intake', 'FAILED', 'badge-fail');
  }
}

function applyPreviewToDraft() {
  if (!STATE.draft || STATE.pendingPreviewCandidates.length === 0) return;

  const scenarioTitles = {
    retinol: 'Retinol Night Renewal Serum',
    peptide: 'Active Peptide Eye Cream',
    day_cream: 'Hydrating Day Cream',
    phenoxy_excess: 'Excess Phenoxyethanol Cream',
    mercury: 'Mercury Bleaching Cream'
  };

  if (STATE.pendingScenarioKey && scenarioTitles[STATE.pendingScenarioKey]) {
    STATE.draft.product_name = scenarioTitles[STATE.pendingScenarioKey];
    const nameInput = document.getElementById('input-product-name');
    if (nameInput) nameInput.value = STATE.draft.product_name;
  }

  STATE.draft.ingredients = STATE.pendingPreviewCandidates.map((c) => ({
    inci_name: c.inci_name,
    concentration_pct: c.concentration_pct,
    cas_number: c.cas_number,
    noael_mg_kg_day: c.noael_mg_kg_day
  }));

  const modal = document.getElementById('modal-import-preview');
  if (modal) modal.classList.add('hidden');

  renderFormulationTable();
  saveDraft();
}


// ---------------------------------------------------------------------------
// 8. Proposal Submission Gate
// ---------------------------------------------------------------------------

async function submitProposal() {
  if (!STATE.token) return;
  setTelemetryStatus('node-pdx-orchestrator', 'COMPILING', 'badge-running');

  try {
    const res = await fetch('/v1/formulations/submit-proposal', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${STATE.token}` }
    });

    if (!res.ok) {
      const errJson = await res.json();
      const reasons = errJson.detail?.reasons || [errJson.detail];
      alert(`❌ Submission Blocked:\n${reasons.join('\n')}`);
      setTelemetryStatus('node-pdx-orchestrator', 'BLOCKED', 'badge-fail');
      return;
    }

    const data = await res.json();
    alert(`✅ Proposal Submitted Successfully!\nProposal ID: ${data.proposal_id}\nGate Decision: ${data.gate_decision}\nRouted to Product Manager inbox for review.`);

    setTelemetryStatus('node-pdx-orchestrator', 'PLAN COMPILED', 'badge-pass');
    setTelemetryStatus('node-manager-gate', 'AWAITING APPROVAL', 'badge-review');

    // Switch view to manager
    switchRole('product_manager');
  } catch (err) {
    console.error('Failed to submit proposal:', err);
    setTelemetryStatus('node-pdx-orchestrator', 'ERROR', 'badge-fail');
  }
}


// ---------------------------------------------------------------------------
// 9. Product Manager Inbox & Decisions
// ---------------------------------------------------------------------------

async function loadProposalsInbox() {
  if (!STATE.token) return;
  try {
    const res = await fetch('/v1/proposals/inbox', {
      headers: { 'Authorization': `Bearer ${STATE.token}` }
    });
    if (!res.ok) return;
    const proposals = await res.json();

    const listEl = document.getElementById('inbox-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (proposals.length === 0) {
      listEl.innerHTML = '<p class="text-sm text-muted text-center py-2">No pending proposals in inbox.</p>';
      return;
    }

    proposals.forEach((p) => {
      const item = document.createElement('div');
      item.className = `inbox-item ${STATE.selectedProposalId === p.proposal_id ? 'selected' : ''}`;
      item.dataset.id = p.proposal_id;

      const badgeClass = p.status === 'approved' ? 'badge-pass' : (p.status === 'returned' ? 'badge-fail' : 'badge-review');

      item.innerHTML = `
        <div class="inbox-item-title">${p.product_name} (Rev ${p.revision})</div>
        <div class="inbox-item-meta">
          <span>${p.proposal_id}</span>
          <span class="badge ${badgeClass}">${p.status.toUpperCase()}</span>
        </div>
      `;

      item.addEventListener('click', () => showProposalDetail(p));
      listEl.appendChild(item);
    });

    // Auto-select first proposal if none selected
    if (!STATE.selectedProposalId && proposals.length > 0) {
      showProposalDetail(proposals[0]);
    }
  } catch (err) {
    console.error('Failed to load proposals inbox:', err);
  }
}

function showProposalDetail(p) {
  STATE.selectedProposalId = p.proposal_id;
  STATE.selectedProposal = p;

  document.querySelectorAll('.inbox-item').forEach((el) => {
    el.classList.toggle('selected', el.dataset.id === p.proposal_id);
  });

  const titleEl = document.getElementById('detail-product-name');
  const metaEl = document.getElementById('detail-proposal-meta');
  const gateBadgeEl = document.getElementById('detail-gate-badge');
  const bodyEl = document.getElementById('detail-body');
  const actionsBox = document.getElementById('manager-actions-box');

  if (titleEl) titleEl.textContent = `${p.product_name} (Revision ${p.revision})`;
  if (metaEl) metaEl.textContent = `Proposal ID: ${p.proposal_id} · Case SHA: ${p.case_digest.slice(0, 16)}... · Plan SHA: ${p.plan_digest.slice(0, 16)}...`;

  if (gateBadgeEl) {
    const isPass = p.gate_decision === 'PASS';
    gateBadgeEl.innerHTML = `<span class="badge ${isPass ? 'badge-pass' : 'badge-review'}">GATE: ${p.gate_decision}</span>`;
  }

  if (bodyEl) {
    let ingredientsHtml = '<table class="data-table mb-1"><thead><tr><th>INCI Name</th><th>Concentration</th><th>CAS</th><th>NOAEL</th></tr></thead><tbody>';
    p.ingredients_summary.forEach((item) => {
      ingredientsHtml += `<tr><td>${item.inci_name}</td><td>${item.concentration_pct}%</td><td>${item.cas_number || '—'}</td><td>${item.noael_mg_kg_day ?? '—'}</td></tr>`;
    });
    ingredientsHtml += '</tbody></table>';

    let reasonsHtml = '';
    if (p.gate_reasons && p.gate_reasons.length > 0) {
      reasonsHtml = `<div class="card mb-1"><div class="text-sm font-bold text-amber mb-05">📋 Gate Review Notes:</div><ul class="text-sm text-secondary">${p.gate_reasons.map((r) => `<li>${r}</li>`).join('')}</ul></div>`;
    }

    bodyEl.innerHTML = `
      ${reasonsHtml}
      <div class="text-sm font-bold text-secondary mb-05">Formulation Ingredients Summary:</div>
      ${ingredientsHtml}
    `;
  }

  if (actionsBox) {
    if (p.status === 'pending_review') {
      actionsBox.classList.remove('hidden');
    } else {
      actionsBox.classList.add('hidden');
    }
  }
}

async function sendManagerChatMessage(customQuery = null) {
  if (!STATE.token) return;
  const inputEl = document.getElementById('input-manager-chat-message');
  const query = (customQuery || (inputEl ? inputEl.value : '')).trim();
  if (!query) return;

  if (inputEl) inputEl.value = '';

  const messagesContainer = document.getElementById('manager-chat-messages');
  if (messagesContainer) {
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble chat-user';
    userBubble.innerHTML = `
      <div class="chat-sender">👔 Product Manager</div>
      <div class="chat-text">${escapeHtml(query)}</div>
    `;
    messagesContainer.appendChild(userBubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  setTelemetryStatus('node-gemini-assistant', 'REASONING', 'badge-running');

  const p = STATE.selectedProposal;
  const productName = p ? p.product_name : (STATE.draft ? STATE.draft.product_name : 'Formula');
  const ingredients = p ? p.ingredients_summary : (STATE.draft ? STATE.draft.ingredients : []);
  const gateDecision = p ? p.gate_decision : null;
  const gateReasons = p ? p.gate_reasons : null;

  try {
    const res = await fetch('/v1/assistant/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${STATE.token}`
      },
      body: JSON.stringify({
        message: query,
        product_name: productName,
        ingredients: ingredients,
        acting_role: 'product_manager',
        gate_decision: gateDecision,
        gate_reasons: gateReasons
      })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (messagesContainer) {
      const botBubble = document.createElement('div');
      botBubble.className = 'chat-bubble chat-bot';
      const formattedReply = formatMarkdown(data.reply);
      
      let insertBtnHtml = '';
      if (query.toLowerCase().includes('rationale') || query.includes('理由') || query.includes('草擬')) {
        insertBtnHtml = `<div class="mt-05"><button type="button" class="btn btn-secondary btn-sm btn-insert-rationale">📋 Insert Rationale into Input Field</button></div>`;
      }

      botBubble.innerHTML = `
        <div class="chat-sender">✨ ${data.provider}</div>
        <div class="chat-text">${formattedReply}</div>
        ${insertBtnHtml}
      `;

      if (insertBtnHtml) {
        const insBtn = botBubble.querySelector('.btn-insert-rationale');
        if (insBtn) {
          insBtn.addEventListener('click', () => {
            const ratInput = document.getElementById('input-manager-rationale');
            if (ratInput) {
              // Extract clean text from reply
              const cleanText = data.reply.replace(/<[^>]*>?/gm, '').replace(/#+\s*/g, '').slice(0, 500).trim();
              ratInput.value = cleanText;
              ratInput.focus();
            }
          });
        }
      }

      messagesContainer.appendChild(botBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    setTelemetryStatus('node-gemini-assistant', 'READY', 'badge-pass');
  } catch (err) {
    console.error('Failed to send manager chat message:', err);
    if (messagesContainer) {
      const errBubble = document.createElement('div');
      errBubble.className = 'chat-bubble chat-bot';
      errBubble.innerHTML = `
        <div class="chat-sender">⚠️ Gemini Advisor</div>
        <div class="chat-text">Unable to complete query. Please try again.</div>
      `;
      messagesContainer.appendChild(errBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    setTelemetryStatus('node-gemini-assistant', 'UNAVAILABLE', 'badge-review');
  }
}

async function decideProposal(decision) {
  if (!STATE.token || !STATE.selectedProposalId) return;

  const rationaleInput = document.getElementById('input-manager-rationale');
  const commentInput = document.getElementById('input-return-comment');
  const rationale = rationaleInput ? rationaleInput.value.trim() : '';
  const returnComments = commentInput ? commentInput.value.trim() : '';

  setTelemetryStatus('node-manager-gate', 'DECIDING', 'badge-running');

  try {
    const res = await fetch(`/v1/proposals/${STATE.selectedProposalId}/decide`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${STATE.token}`
      },
      body: JSON.stringify({
        decision: decision,
        rationale: rationale,
        return_comments: returnComments
      })
    });

    if (!res.ok) {
      const errJson = await res.json();
      alert(`Decision failed: ${errJson.detail}`);
      setTelemetryStatus('node-manager-gate', 'DECISION ERROR', 'badge-fail');
      return;
    }

    const data = await res.json();

    if (decision === 'approved') {
      alert(`🎉 Proposal Approved & Finalized!\nProduct ID: ${data.product_id}\nSHA-256 Provenance Checksum: ${data.artifact_identity.sha256}`);
      setTelemetryStatus('node-manager-gate', 'FINALIZED', 'badge-pass');
      setTelemetryStatus('node-prodocux-render', 'READY FOR EXPORT', 'badge-pass');
      await showExportCenter(data.product_id);
    } else {
      alert(`↩️ Proposal returned to Formulator for revision.\nReturn comments recorded in audit ledger.`);
      setTelemetryStatus('node-manager-gate', 'RETURNED', 'badge-review');
      await loadProposalsInbox();
    }
  } catch (err) {
    console.error('Failed to decide proposal:', err);
  }
}


// ---------------------------------------------------------------------------
// 10. Approved Product Record & 5-Format Export Center
// ---------------------------------------------------------------------------

async function showExportCenter(productId) {
  const viewFormulator = document.getElementById('view-formulator');
  const viewManager = document.getElementById('view-manager');
  const viewExport = document.getElementById('view-export');

  if (viewFormulator) viewFormulator.classList.remove('active');
  if (viewManager) viewManager.classList.remove('active');
  if (viewExport) viewExport.classList.add('active');

  try {
    const res = await fetch(`/v1/products/${productId}/export-bundle`, {
      headers: { 'Authorization': `Bearer ${STATE.token}` }
    });
    if (!res.ok) return;
    const data = await res.json();

    const listEl = document.getElementById('approved-products-list');
    if (!listEl) return;

    listEl.innerHTML = `
      <div class="card mb-15">
        <div class="flex-between mb-1">
          <div>
            <div class="text-lg font-bold">${data.bundle_spec.product_name} (Revision ${data.bundle_spec.revision})</div>
            <div class="text-xs font-mono text-muted">Product ID: ${data.product_id} · Checkpoint: ${data.bundle_spec.checkpoint_id}</div>
          </div>
          <span class="badge badge-pass">FINALIZED &amp; IMMUTABLE</span>
        </div>

        <div class="form-group mb-1">
          <label class="form-label">SHA-256 Cryptographic Checksum Fingerprint:</label>
          <input type="text" class="form-control font-mono" value="${data.sha256_checksum}" readonly>
        </div>

        <div class="text-sm font-bold text-secondary mb-075">ProDocuX 5-Format Render Specifications:</div>
        <div class="d-flex gap-075 flex-wrap">
          <button type="button" class="btn btn-secondary btn-export" data-fmt="pdf">⬇️ Download PDF Safety Summary</button>
          <button type="button" class="btn btn-secondary btn-export" data-fmt="docx">⬇️ Download DOCX CoA Specification</button>
          <button type="button" class="btn btn-secondary btn-export" data-fmt="csv">⬇️ Download CSV Formulation Matrix</button>
          <button type="button" class="btn btn-secondary btn-export" data-fmt="xlsx">⬇️ Download XLSX Toxicology Model</button>
          <button type="button" class="btn btn-secondary btn-export" data-fmt="pptx">⬇️ Download PPTX Review Deck</button>
          <button type="button" class="btn btn-primary btn-export" data-fmt="json">⬇️ Download Complete Checksummed Evidence Package</button>
        </div>
      </div>
    `;

    listEl.querySelectorAll('.btn-export').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const fmt = e.target.dataset.fmt;
        if (fmt === 'json') {
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${data.bundle_spec.product_name.replace(/\s+/g, '_')}_evidence_package.json`;
          a.click();
          URL.revokeObjectURL(url);
          return;
        }

        try {
          setTelemetryStatus('node-prodocux-render', `RENDERING ${fmt.toUpperCase()}`, 'badge-running');
          const rRes = await fetch(`/v1/products/${productId}/render-artifact`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${STATE.token}`
            },
            body: JSON.stringify({ format: fmt })
          });

          if (!rRes.ok) {
            const err = await rRes.json();
            alert(`Render failed: ${err.detail || 'ProDocuX Render Engine Error'}`);
            setTelemetryStatus('node-prodocux-render', 'RENDER ERROR', 'badge-fail');
            return;
          }

          const rData = await rRes.json();
          setTelemetryStatus('node-prodocux-render', `${fmt.toUpperCase()} RENDERED`, 'badge-pass');

          // Download base64 payload
          const b64 = rData.result?.content_b64;
          if (b64) {
            const byteChars = atob(b64);
            const byteNums = new Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) {
              byteNums[i] = byteChars.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNums);
            const blob = new Blob([byteArray], { type: 'application/octet-stream' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${data.bundle_spec.product_name.replace(/\s+/g, '_')}_finalized.${fmt}`;
            a.click();
            URL.revokeObjectURL(url);
          } else {
            alert(`✅ ${fmt.toUpperCase()} rendered successfully! SHA-256: ${rData.result?.sha256}`);
          }
        } catch (err) {
          console.error('Failed to render artifact:', err);
          setTelemetryStatus('node-prodocux-render', 'RENDER FAILED', 'badge-fail');
        }
      });
    });
  } catch (err) {
    console.error('Failed to show export center:', err);
  }
}


// ---------------------------------------------------------------------------
// 11. Event Listeners Binding
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  initPWA();
  initSession('formulator');

  // Role Buttons
  const btnFormulator = document.getElementById('btn-role-formulator');
  const btnManager = document.getElementById('btn-role-manager');
  if (btnFormulator) btnFormulator.addEventListener('click', () => switchRole('formulator'));
  if (btnManager) btnManager.addEventListener('click', () => switchRole('product_manager'));

  // Restart Button
  const btnRestart = document.getElementById('btn-restart-demo');
  if (btnRestart) btnRestart.addEventListener('click', restartSession);

  // Preset Scenario Chips
  document.querySelectorAll('.preset-chip').forEach((chip) => {
    chip.addEventListener('click', (e) => {
      const scenarioKey = chip.dataset.scenario;
      triggerParsePreview(scenarioKey);
    });
  });

  // Modal Buttons
  const modalClose = document.getElementById('btn-modal-close');
  const modalCancel = document.getElementById('btn-modal-cancel');
  const modalApply = document.getElementById('btn-modal-apply');
  const modal = document.getElementById('modal-import-preview');

  if (modalClose) modalClose.addEventListener('click', () => modal.classList.add('hidden'));
  if (modalCancel) modalCancel.addEventListener('click', () => modal.classList.add('hidden'));
  if (modalApply) modalApply.addEventListener('click', applyPreviewToDraft);

  // Table Buttons
  const btnAdd = document.getElementById('btn-add-ingredient');
  const btnSave = document.getElementById('btn-save-draft');
  if (btnAdd) btnAdd.addEventListener('click', addIngredientRow);
  if (btnSave) btnSave.addEventListener('click', saveDraft);

  // Submit Proposal Button
  const btnSubmit = document.getElementById('btn-submit-proposal');
  if (btnSubmit) btnSubmit.addEventListener('click', submitProposal);

  // Manager Decision Buttons
  const btnAccept = document.getElementById('btn-manager-accept');
  const btnReturn = document.getElementById('btn-manager-return');
  if (btnAccept) btnAccept.addEventListener('click', () => decideProposal('approved'));
  if (btnReturn) btnReturn.addEventListener('click', () => decideProposal('returned'));

  // Gemini Copilot Interactive Chat Listeners
  const btnChatSend = document.getElementById('btn-chat-send');
  const inputChatMsg = document.getElementById('input-chat-message');
  if (btnChatSend) btnChatSend.addEventListener('click', () => sendChatMessage());
  if (inputChatMsg) {
    inputChatMsg.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }

  document.querySelectorAll('.btn-prompt-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const prompt = chip.dataset.prompt;
      if (prompt) sendChatMessage(prompt);
    });
  });

  // Manager Copilot Interactive Chat Listeners
  const btnMgrChatSend = document.getElementById('btn-manager-chat-send');
  const inputMgrChatMsg = document.getElementById('input-manager-chat-message');
  if (btnMgrChatSend) btnMgrChatSend.addEventListener('click', () => sendManagerChatMessage());
  if (inputMgrChatMsg) {
    inputMgrChatMsg.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        sendManagerChatMessage();
      }
    });
  }

  document.querySelectorAll('.btn-mgr-prompt').forEach((chip) => {
    chip.addEventListener('click', () => {
      const prompt = chip.dataset.prompt;
      if (prompt) sendManagerChatMessage(prompt);
    });
  });

  // Quick Add from Ingredient Library Buttons
  document.querySelectorAll('.btn-quick-ing').forEach((btn) => {
    btn.addEventListener('click', () => {
      const inci = btn.dataset.inci;
      const cas = btn.dataset.cas;
      const noael = btn.dataset.noael ? parseFloat(btn.dataset.noael) : null;
      const pct = btn.dataset.pct ? parseFloat(btn.dataset.pct) : 1.0;
      addQuickIngredient(inci, cas, noael, pct);
    });
  });
});
