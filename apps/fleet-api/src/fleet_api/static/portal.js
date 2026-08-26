/**
 * FortifiedReg Fleet v0.4.0 — PWA & Role-Based Autonomous Compliance Client.
 * Implements strict CSP compliance (0 inline styles), single-identity dual-role session,
 * event-driven component telemetry, two-tier import preview, and proposal governance.
 * Pure AST DOM node building — ZERO innerHTML for untrusted/dynamic data.
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
  selectedProposal: null,
  deferredInstallPrompt: null,
  samplesCache: null,
  pendingScenarioKey: null,
  pendingPreviewFormat: null
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
// 1. Markdown AST Node Renderer (Zero innerHTML)
// ---------------------------------------------------------------------------

function appendFormattedText(parentEl, text) {
  if (!text) return;
  const regex = /(\*\*.*?\*\*|\*.*?\*|`.*?`)/g;
  const parts = text.split(regex);

  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      const strong = document.createElement('strong');
      strong.textContent = part.slice(2, -2);
      parentEl.appendChild(strong);
    } else if (part.startsWith('*') && part.endsWith('*') && part.length >= 2) {
      const em = document.createElement('em');
      em.textContent = part.slice(1, -1);
      parentEl.appendChild(em);
    } else if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      const code = document.createElement('code');
      code.textContent = part.slice(1, -1);
      parentEl.appendChild(code);
    } else {
      parentEl.appendChild(document.createTextNode(part));
    }
  }
}

function renderMarkdownToNode(text) {
  const container = document.createElement('div');
  if (!text) return container;

  const lines = text.split('\n');
  let currentList = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      currentList = null;
      continue;
    }

    if (trimmed.startsWith('* ') || trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
      if (!currentList) {
        currentList = document.createElement('ul');
        currentList.className = 'chat-bullet-list';
        container.appendChild(currentList);
      }
      const li = document.createElement('li');
      appendFormattedText(li, trimmed.slice(2));
      currentList.appendChild(li);
      continue;
    }

    currentList = null;

    if (trimmed.startsWith('### ')) {
      const h = document.createElement('div');
      h.className = 'font-bold text-sm text-cyan mt-05 mb-025';
      appendFormattedText(h, trimmed.slice(4));
      container.appendChild(h);
      continue;
    }
    if (trimmed.startsWith('## ') || trimmed.startsWith('# ')) {
      const h = document.createElement('div');
      h.className = 'font-bold text-base text-cyan mt-05 mb-025';
      appendFormattedText(h, trimmed.replace(/^#+\s*/, ''));
      container.appendChild(h);
      continue;
    }

    const p = document.createElement('p');
    p.className = 'mb-05';
    appendFormattedText(p, line);
    container.appendChild(p);
  }

  return container;
}

// ---------------------------------------------------------------------------
// 2. PWA & Service Worker Initialization
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
// 3. Telemetry Status Helper (Event-Driven Only)
// ---------------------------------------------------------------------------

function setTelemetryStatus(nodeId, statusText, badgeClass) {
  const statusEl = document.querySelector('#' + nodeId + ' .node-status');
  if (!statusEl) return;
  statusEl.textContent = statusText;
  statusEl.className = 'node-status badge ' + badgeClass;
}

// ---------------------------------------------------------------------------
// 4. Session & Timer Management
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
    labelEl.textContent = 'Session #' + shortId;
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
    if (timerEl) timerEl.textContent = mm + ':' + ss;
  }, 1000);
}

async function restartSession() {
  if (STATE.timerInterval) clearInterval(STATE.timerInterval);
  STATE.draft = null;
  STATE.selectedProposalId = null;

  try {
    const res = await fetch('/v1/demo/session/restart', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(STATE.token ? { 'Authorization': 'Bearer ' + STATE.token } : {})
      },
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
// 5. Role Switching (Single Identity Simulation)
// ---------------------------------------------------------------------------

async function switchRole(role) {
  STATE.actingRole = role;

  const btnFormulator = document.getElementById('btn-role-formulator');
  const btnManager = document.getElementById('btn-role-manager');
  const viewFormulator = document.getElementById('view-formulator');
  const viewManager = document.getElementById('view-manager');

  if (btnFormulator) btnFormulator.classList.toggle('active', role === 'formulator');
  if (btnManager) btnManager.classList.toggle('active', role === 'product_manager');

  if (viewFormulator) viewFormulator.classList.toggle('active', role === 'formulator');
  if (viewManager) viewManager.classList.toggle('active', role === 'product_manager');

  if (STATE.token) {
    try {
      await fetch('/v1/demo/session/role', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + STATE.token
        },
        body: JSON.stringify({ acting_role: role })
      });
    } catch (e) {
      console.warn('Role switch notification failed:', e);
    }
  }

  if (role === 'product_manager') {
    loadProposalsInbox();
  }
}

// ---------------------------------------------------------------------------
// 6. Formulation Management & SCCS Diagnostics
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

async function loadDraft(customProductName = null) {
  if (!STATE.token) return;
  try {
    const url = customProductName ? '/v1/formulations/draft?product_name=' + encodeURIComponent(customProductName) : '/v1/formulations/draft';
    const res = await fetch(url, {
      headers: { 'Authorization': 'Bearer ' + STATE.token }
    });
    if (!res.ok) return;
    const data = await res.json();
    STATE.draft = data.draft;

    const returnedBanner = document.getElementById('banner-returned-proposal');
    const returnedComments = document.getElementById('returned-proposal-comments');
    const btnLoadReturned = document.getElementById('btn-load-returned-draft');

    if (data.returned_proposal && returnedBanner) {
      returnedBanner.classList.remove('hidden');
      if (returnedComments) {
        returnedComments.textContent = 'Comments: ' + (data.returned_proposal.return_comments || 'Manager requested formula revision.');
      }
      if (btnLoadReturned) {
        btnLoadReturned.onclick = () => loadReturnedProposalToDraft(data.returned_proposal);
      }
    } else if (returnedBanner) {
      returnedBanner.classList.add('hidden');
    }

    renderFormulationTable();
    renderDiagnostics(data.sccs_evaluation, data.inci_evaluation);
    renderRevisionHistory(data.history);
    await loadAssistantSuggestions();
  } catch (err) {
    console.error('Failed to load draft:', err);
  }
}

function renderRevisionHistory(historyList) {
  const selectEl = document.getElementById('select-revision-history');
  const btnRollback = document.getElementById('btn-rollback-revision');
  if (!selectEl) return;

  selectEl.replaceChildren();
  const curRev = STATE.draft ? STATE.draft.revision : 1;

  if (!historyList || historyList.length === 0) {
    const opt = document.createElement('option');
    opt.value = String(curRev);
    opt.textContent = '📜 Rev ' + curRev + ' (Current)';
    selectEl.appendChild(opt);
    if (btnRollback) btnRollback.classList.add('hidden');
    return;
  }

  const sorted = [...historyList].sort((a, b) => b.revision - a.revision);
  sorted.forEach((item) => {
    const opt = document.createElement('option');
    opt.value = String(item.revision);
    const isCur = item.revision === curRev;
    const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    opt.textContent = '📜 Rev ' + item.revision + ' ' + (isCur ? '(Current)' : '(' + (timeStr || item.note || 'Saved') + ')');
    if (isCur) opt.selected = true;
    selectEl.appendChild(opt);
  });

  if (btnRollback) btnRollback.classList.add('hidden');
}

function handleRevisionSelectChange(e) {
  const targetRev = parseInt(e.target.value, 10);
  const btnRollback = document.getElementById('btn-rollback-revision');
  const curRev = STATE.draft ? STATE.draft.revision : 1;

  if (targetRev === curRev) {
    if (btnRollback) btnRollback.classList.add('hidden');
    return;
  }

  if (btnRollback) {
    btnRollback.classList.remove('hidden');
    btnRollback.textContent = '↩️ Rollback to Rev ' + targetRev;
  }
}

async function rollbackToSelectedRevision() {
  const selectEl = document.getElementById('select-revision-history');
  if (!selectEl || !STATE.draft) return;
  const targetRev = parseInt(selectEl.value, 10);
  if (!targetRev || targetRev === STATE.draft.revision) return;

  try {
    const res = await fetch('/v1/formulations/rollback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + STATE.token
      },
      body: JSON.stringify({
        product_name: STATE.draft.product_name,
        target_revision: targetRev
      })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    STATE.draft = data.draft;

    renderFormulationTable();
    renderDiagnostics(data.sccs_evaluation, data.inci_evaluation);
    renderRevisionHistory(data.history);
    alert('↩️ Successfully restored formulation from Revision ' + targetRev + '! New active Revision is ' + data.new_revision + '.');
  } catch (err) {
    console.error('Rollback failed:', err);
    alert('Rollback failed: ' + err.message);
  }
}

function loadReturnedProposalToDraft(proposal) {
  if (!proposal || !STATE.draft) return;
  STATE.draft.ingredients = (proposal.ingredients_summary || []).map(i => ({
    inci_name: i.inci_name,
    concentration_pct: i.concentration_pct,
    cas_number: i.cas_number,
    noael_mg_kg_day: i.noael_mg_kg_day
  }));
  STATE.draft.revision = (proposal.revision || 1) + 1;
  const returnedBanner = document.getElementById('banner-returned-proposal');
  if (returnedBanner) returnedBanner.classList.add('hidden');
  renderFormulationTable();
  saveDraft();
  alert('✏️ Loaded returned formula as Revision ' + STATE.draft.revision + '. You can now adjust concentrations, balance to 100%, and re-submit to Manager Gate.');
}

function renderFormulationTable() {
  if (!STATE.draft) return;
  const tbody = document.getElementById('tbody-ingredients');
  const nameInput = document.getElementById('input-product-name');
  const revBadge = document.getElementById('draft-revision-badge');
  const digestBadge = document.getElementById('draft-digest-badge');

  if (nameInput) nameInput.value = STATE.draft.product_name || '';
  if (revBadge) revBadge.textContent = 'Revision: ' + STATE.draft.revision;
  if (digestBadge) digestBadge.textContent = 'Case SHA: ' + STATE.draft.case_digest.slice(0, 12) + '...';

  updateTotalConcentrationMeter();

  if (!tbody) return;
  tbody.replaceChildren();

  STATE.draft.ingredients.forEach((item, index) => {
    const tr = document.createElement('tr');

    const tdInci = document.createElement('td');
    const inputInci = document.createElement('input');
    inputInci.type = 'text';
    inputInci.setAttribute('list', 'ingredient-library-datalist');
    inputInci.className = 'table-input input-inci';
    inputInci.dataset.field = 'inci_name';
    inputInci.dataset.index = String(index);
    inputInci.value = item.inci_name || '';
    inputInci.placeholder = 'Type INCI or select...';
    tdInci.appendChild(inputInci);

    const tdPct = document.createElement('td');
    const inputPct = document.createElement('input');
    inputPct.type = 'number';
    inputPct.step = '0.01';
    inputPct.className = 'table-input input-pct';
    inputPct.dataset.field = 'concentration_pct';
    inputPct.dataset.index = String(index);
    inputPct.value = String(item.concentration_pct ?? 0);
    tdPct.appendChild(inputPct);

    const tdCas = document.createElement('td');
    const inputCas = document.createElement('input');
    inputCas.type = 'text';
    inputCas.className = 'table-input input-cas';
    inputCas.dataset.field = 'cas_number';
    inputCas.dataset.index = String(index);
    inputCas.value = item.cas_number || '';
    inputCas.placeholder = 'CAS No.';
    tdCas.appendChild(inputCas);

    const tdNoael = document.createElement('td');
    const inputNoael = document.createElement('input');
    inputNoael.type = 'number';
    inputNoael.step = '0.1';
    inputNoael.className = 'table-input input-noael';
    inputNoael.dataset.field = 'noael_mg_kg_day';
    inputNoael.dataset.index = String(index);
    inputNoael.value = item.noael_mg_kg_day != null ? String(item.noael_mg_kg_day) : '';
    inputNoael.placeholder = 'NOAEL';
    tdNoael.appendChild(inputNoael);

    const tdAction = document.createElement('td');
    tdAction.className = 'text-center';
    const btnDel = document.createElement('button');
    btnDel.type = 'button';
    btnDel.className = 'btn btn-danger btn-sm btn-del-row';
    btnDel.dataset.index = String(index);
    btnDel.textContent = '🗑️';
    tdAction.appendChild(btnDel);

    tr.appendChild(tdInci);
    tr.appendChild(tdPct);
    tr.appendChild(tdCas);
    tr.appendChild(tdNoael);
    tr.appendChild(tdAction);

    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('.table-input').forEach((input) => {
    const updateMem = (e) => {
      const idx = parseInt(e.target.dataset.index, 10);
      const field = e.target.dataset.field;
      let val = e.target.value;

      if (field === 'concentration_pct') val = parseFloat(val) || 0;
      if (field === 'noael_mg_kg_day') val = (val && val.trim() !== '') ? parseFloat(val) : null;

      if (STATE.draft && STATE.draft.ingredients[idx]) {
        STATE.draft.ingredients[idx][field] = val;

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
                if (noaelInput) noaelInput.value = String(match.noael);
              }
            }
          }
        }

        updateTotalConcentrationMeter();
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

function updateTotalConcentrationMeter() {
  const badge = document.getElementById('badge-total-concentration');
  const label = document.getElementById('label-balance-status');
  if (!badge || !STATE.draft) return;

  const totalPct = STATE.draft.ingredients.reduce(
    (acc, cur) => acc + (parseFloat(cur.concentration_pct) || 0),
    0
  );
  const rounded = Math.round(totalPct * 100) / 100;
  badge.textContent = rounded.toFixed(2) + '%';

  if (Math.abs(rounded - 100.0) < 0.01) {
    badge.className = 'badge badge-pass font-mono';
    if (label) {
      label.textContent = '✓ 100.00% Fully Balanced';
      label.className = 'text-xs text-emerald';
    }
  } else {
    badge.className = 'badge badge-review font-mono';
    if (label) {
      const diff = Math.round((100.0 - rounded) * 100) / 100;
      label.textContent = diff > 0 ? ('⚠️ Incomplete (Remaining: ' + diff.toFixed(2) + '%)') : ('⚠️ Exceeded (Over: ' + Math.abs(diff).toFixed(2) + '%)');
      label.className = 'text-xs text-amber';
    }
  }
}

function autoBalanceAqua() {
  if (!STATE.draft) return;
  STATE.draft.ingredients = collectIngredientsFromTable();

  let aquaItem = STATE.draft.ingredients.find(
    (i) => (i.inci_name || '').trim().toLowerCase() === 'aqua' || (i.inci_name || '').trim().toLowerCase() === 'water'
  );

  if (!aquaItem) {
    aquaItem = {
      inci_name: 'Aqua',
      concentration_pct: 0,
      cas_number: '7732-18-5',
      noael_mg_kg_day: null
    };
    STATE.draft.ingredients.unshift(aquaItem);
  }

  const otherSum = STATE.draft.ingredients
    .filter((i) => i !== aquaItem)
    .reduce((acc, cur) => acc + (parseFloat(cur.concentration_pct) || 0), 0);

  const remaining = Math.max(0, Math.round((100.0 - otherSum) * 100) / 100);
  aquaItem.concentration_pct = remaining;

  renderFormulationTable();
  saveDraft();
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
        'Authorization': 'Bearer ' + STATE.token
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
    renderRevisionHistory(data.history);
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
  const mosList = document.getElementById('sidebar-mos-list');
  const gateIndicator = document.getElementById('gate-indicator');
  const gateDesc = document.getElementById('gate-desc');

  if (mosList) {
    mosList.replaceChildren();
    const substances = sccs?.substance_evaluations || [];
    substances.forEach((s) => {
      const div = document.createElement('div');
      div.className = 'mos-item flex-between';
      const mosVal = s.margin_of_safety != null ? Math.round(s.margin_of_safety) : 'N/A';
      const stLower = (s.status || '').toLowerCase();
      const badgeClass = stLower === 'pass' ? 'badge-pass' : (stLower === 'review' ? 'badge-review' : 'badge-fail');

      const spanName = document.createElement('span');
      const strongName = document.createElement('strong');
      strongName.textContent = s.inci_name || '';
      spanName.appendChild(strongName);
      spanName.appendChild(document.createTextNode(' (' + s.concentration_pct + '%)'));

      const spanBadge = document.createElement('span');
      spanBadge.className = 'badge ' + badgeClass;
      spanBadge.textContent = 'MoS: ' + mosVal;

      div.appendChild(spanName);
      div.appendChild(spanBadge);
      mosList.appendChild(div);
    });
  }

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
// 7. AI Copilot Suggestions & Interactive Dialogue
// ---------------------------------------------------------------------------

async function loadAssistantSuggestions() {
  if (!STATE.token || !STATE.draft) return;
  setTelemetryStatus('node-gemini-assistant', 'ANALYZING', 'badge-running');

  try {
    const res = await fetch('/v1/assistant/suggestions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + STATE.token
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
    if (scoreEl) scoreEl.textContent = String(data.overall_compliance_score);

    const listEl = document.getElementById('sidebar-suggestions-list');
    if (!listEl) return;
    listEl.replaceChildren();

    data.suggestions.forEach((s) => {
      const card = document.createElement('div');
      card.className = 'suggestion-card ' + (s.severity === 'high' ? 'severity-high' : '');

      const titleEl = document.createElement('div');
      titleEl.className = 'suggestion-title';
      titleEl.textContent = s.title || '';

      const msgEl = document.createElement('div');
      msgEl.className = 'suggestion-msg';
      msgEl.textContent = s.message || '';

      const citEl = document.createElement('div');
      citEl.className = 'suggestion-citation';
      citEl.textContent = '📜 ' + (s.rule_citation || '');

      card.appendChild(titleEl);
      card.appendChild(msgEl);
      card.appendChild(citEl);

      if (s.proposed_patch && s.action_label) {
        const patchBtn = document.createElement('button');
        patchBtn.type = 'button';
        patchBtn.className = 'btn btn-secondary btn-sm btn-apply-patch mt-05';
        patchBtn.textContent = s.action_label;
        patchBtn.addEventListener('click', () => applySuggestionPatch(s.proposed_patch));
        card.appendChild(patchBtn);
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
  const btnSend = document.getElementById('btn-chat-send');
  const query = (customQuery || (inputEl ? inputEl.value : '')).trim();
  if (!query) return;

  if (inputEl) inputEl.value = '';

  const messagesContainer = document.getElementById('chat-messages');
  if (messagesContainer) {
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble chat-user';

    const senderEl = document.createElement('div');
    senderEl.className = 'chat-sender';
    senderEl.textContent = '🔬 Formulator';

    const textEl = document.createElement('div');
    textEl.className = 'chat-text';
    textEl.textContent = query;

    userBubble.appendChild(senderEl);
    userBubble.appendChild(textEl);
    messagesContainer.appendChild(userBubble);

    const thinkingBubble = document.createElement('div');
    thinkingBubble.className = 'chat-bubble chat-bot thinking-bubble';
    thinkingBubble.id = 'chat-thinking-bubble';

    const thinkSender = document.createElement('div');
    thinkSender.className = 'chat-sender';
    thinkSender.textContent = '✨ Gemini Regulatory Copilot';

    const thinkText = document.createElement('div');
    thinkText.className = 'chat-text';
    const spanSpin = document.createElement('span');
    spanSpin.className = 'spinner-pulse';
    spanSpin.textContent = '⏳';
    const emText = document.createElement('em');
    emText.textContent = ' Analyzing EU 1223/2009 Annexes & calculating toxicological MoS...';
    thinkText.appendChild(spanSpin);
    thinkText.appendChild(emText);

    thinkingBubble.appendChild(thinkSender);
    thinkingBubble.appendChild(thinkText);
    messagesContainer.appendChild(thinkingBubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  if (inputEl) inputEl.disabled = true;
  if (btnSend) btnSend.disabled = true;
  setTelemetryStatus('node-gemini-assistant', 'REASONING', 'badge-running');

  try {
    const res = await fetch('/v1/assistant/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + STATE.token
      },
      body: JSON.stringify({
        message: query,
        product_name: STATE.draft ? STATE.draft.product_name : 'Formula',
        ingredients: STATE.draft ? STATE.draft.ingredients : [],
        exposure_scenario: STATE.draft ? STATE.draft.exposure_scenario : null
      })
    });

    const tb = document.getElementById('chat-thinking-bubble');
    if (tb) tb.remove();

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (messagesContainer) {
      const botBubble = document.createElement('div');
      botBubble.className = 'chat-bubble chat-bot';

      const botSender = document.createElement('div');
      botSender.className = 'chat-sender';
      botSender.textContent = '✨ ' + (data.provider || 'Gemini Regulatory Copilot');

      const botText = document.createElement('div');
      botText.className = 'chat-text';
      botText.appendChild(renderMarkdownToNode(data.reply));

      botBubble.appendChild(botSender);
      botBubble.appendChild(botText);
      messagesContainer.appendChild(botBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    setTelemetryStatus('node-gemini-assistant', 'READY', 'badge-pass');
  } catch (err) {
    console.error('Failed to send chat message:', err);
    const tb = document.getElementById('chat-thinking-bubble');
    if (tb) tb.remove();

    if (messagesContainer) {
      const errBubble = document.createElement('div');
      errBubble.className = 'chat-bubble chat-bot';

      const errSender = document.createElement('div');
      errSender.className = 'chat-sender';
      errSender.textContent = '⚠️ Gemini Advisor';

      const errText = document.createElement('div');
      errText.className = 'chat-text';
      errText.textContent = 'Unable to complete query. Please try again.';

      errBubble.appendChild(errSender);
      errBubble.appendChild(errText);
      messagesContainer.appendChild(errBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    setTelemetryStatus('node-gemini-assistant', 'UNAVAILABLE', 'badge-review');
  } finally {
    if (inputEl) {
      inputEl.disabled = false;
      inputEl.focus();
    }
    if (btnSend) btnSend.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// 8. Sample Download & Draft Render Export
// ---------------------------------------------------------------------------

const SCENARIO_FORMAT_MAP = {
  retinol: 'pdf',
  peptide: 'docx',
  day_cream: 'csv',
  phenoxy_excess: 'xlsx',
  mercury: 'pptx'
};

async function downloadSampleFile(key) {
  try {
    if (!STATE.samplesCache) {
      const res = await fetch('/static/samples.json');
      if (!res.ok) throw new Error('Samples payload not found.');
      STATE.samplesCache = await res.json();
    }

    const fmt = (SCENARIO_FORMAT_MAP[key] || key || 'pdf').toLowerCase();
    const item = STATE.samplesCache[fmt];

    if (!item || !item.b64) {
      alert('Download sample for ' + key.toUpperCase() + ' not available.');
      return;
    }

    const byteChars = atob(item.b64);
    const byteNums = new Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i++) {
      byteNums[i] = byteChars.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNums);
    const blob = new Blob([byteArray], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = item.fn || ('sample_' + fmt + '.' + fmt);
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error('Failed to download sample file:', err);
    alert('Failed to download sample file: ' + err.message);
  }
}

async function renderDraftExport(format, customProductName = null, customIngredients = null) {
  if (!STATE.token) return;
  setTelemetryStatus('node-prodocux-render', 'RENDERING', 'badge-running');

  try {
    const prodName = customProductName || (STATE.draft ? STATE.draft.product_name : 'Formulation');
    const ings = customIngredients || collectIngredientsFromTable();

    const res = await fetch('/v1/formulations/render-export', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + STATE.token
      },
      body: JSON.stringify({
        format: format,
        product_name: prodName,
        ingredients: ings
      })
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (!data.content_b64) throw new Error('No binary payload returned from ProDocuX render engine.');

    const byteChars = atob(data.content_b64);
    const byteNums = new Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i++) {
      byteNums[i] = byteChars.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNums);
    const mimeMap = {
      pdf: 'application/pdf',
      docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      csv: 'text/csv',
      xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    };
    const blob = new Blob([byteArray], { type: mimeMap[format.toLowerCase()] || 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || ('formulation_rev' + (STATE.draft ? STATE.draft.revision : 1) + '.' + format);
    a.click();
    URL.revokeObjectURL(url);

    setTelemetryStatus('node-prodocux-render', 'RENDERED', 'badge-pass');
    alert('✓ ProDocuX Live Engine successfully rendered ' + format.toUpperCase() + '!\nFilename: ' + data.filename + '\nSHA-256: ' + data.sha256);
  } catch (err) {
    console.error('ProDocuX draft render failed:', err);
    setTelemetryStatus('node-prodocux-render', 'FAILED', 'badge-fail');
    alert('ProDocuX render failed: ' + err.message);
  }
}

async function triggerParsePreview(scenarioKey) {
  setTelemetryStatus('node-prodocux-intake', 'PARSING', 'badge-running');
  STATE.pendingScenarioKey = scenarioKey;

  try {
    const res = await fetch('/v1/formulations/parse-preview', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(STATE.token ? { 'Authorization': 'Bearer ' + STATE.token } : {})
      },
      body: JSON.stringify({ scenario_key: scenarioKey })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    STATE.pendingPreviewCandidates = data.candidates || [];
    STATE.pendingPreviewFormat = data.format || 'pdf';

    const modal = document.getElementById('modal-import-preview');
    const tbody = document.getElementById('modal-tbody-candidates');
    const warningsEl = document.getElementById('modal-warnings');

    const evSha = document.getElementById('evidence-sha256');
    const evParser = document.getElementById('evidence-parser');
    const evDocId = document.getElementById('evidence-doc-id');
    const evPre = document.getElementById('evidence-raw-blocks');

    if (evSha) evSha.textContent = data.source_sha256 || '—';
    if (evParser) evParser.textContent = 'prodocux.extract_blocks (' + (data.format || 'pdf').toUpperCase() + ' Parser)';
    if (evDocId) evDocId.textContent = data.document_id || '—';
    if (evPre) evPre.textContent = JSON.stringify(data.raw_blocks || [], null, 2);

    if (tbody) {
      tbody.replaceChildren();
      STATE.pendingPreviewCandidates.forEach((c) => {
        const tr = document.createElement('tr');

        const tdInci = document.createElement('td');
        const strongInci = document.createElement('strong');
        strongInci.textContent = c.inci_name || '';
        tdInci.appendChild(strongInci);

        const tdPct = document.createElement('td');
        tdPct.textContent = c.concentration_pct + '%';

        const tdCas = document.createElement('td');
        tdCas.textContent = c.cas_number || '—';

        const tdNoael = document.createElement('td');
        tdNoael.textContent = c.noael_mg_kg_day != null ? String(c.noael_mg_kg_day) : '—';

        const tdLoc = document.createElement('td');
        const spanLoc = document.createElement('span');
        spanLoc.className = 'text-xs font-mono text-muted';
        spanLoc.textContent = c.source_location || '';
        tdLoc.appendChild(spanLoc);

        const tdConf = document.createElement('td');
        const spanConf = document.createElement('span');
        spanConf.className = 'badge badge-info';
        spanConf.textContent = Math.round((c.confidence || 1.0) * 100) + '%';
        tdConf.appendChild(spanConf);

        tr.appendChild(tdInci);
        tr.appendChild(tdPct);
        tr.appendChild(tdCas);
        tr.appendChild(tdNoael);
        tr.appendChild(tdLoc);
        tr.appendChild(tdConf);

        tbody.appendChild(tr);
      });
    }

    if (warningsEl) {
      const allWarnings = STATE.pendingPreviewCandidates.flatMap((c) => c.warnings || []);
      warningsEl.textContent = allWarnings.length > 0 ? ('⚠️ Warnings: ' + allWarnings.join('; ')) : '';
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
    day_cream: 'Compliant Day Cream',
    phenoxy_excess: 'Excess Preservative Cream',
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
// 9. Proposal Submission Gate
// ---------------------------------------------------------------------------

async function submitProposal() {
  if (!STATE.token) return;
  setTelemetryStatus('node-pdx-orchestrator', 'COMPILING', 'badge-running');

  try {
    const res = await fetch('/v1/formulations/submit-proposal', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + STATE.token }
    });

    if (!res.ok) {
      const errJson = await res.json();
      const reasons = errJson.detail?.reasons || [errJson.detail];
      alert('❌ Submission Blocked:\n' + reasons.join('\n'));
      setTelemetryStatus('node-pdx-orchestrator', 'BLOCKED', 'badge-fail');
      return;
    }

    const data = await res.json();
    alert('✅ Proposal Submitted Successfully!\nProposal ID: ' + data.proposal_id + '\nGate Decision: ' + data.gate_decision + '\nRouted to Product Manager inbox for review.');

    setTelemetryStatus('node-pdx-orchestrator', 'PLAN COMPILED', 'badge-pass');
    setTelemetryStatus('node-manager-gate', 'AWAITING APPROVAL', 'badge-review');

    switchRole('product_manager');
  } catch (err) {
    console.error('Failed to submit proposal:', err);
    setTelemetryStatus('node-pdx-orchestrator', 'ERROR', 'badge-fail');
  }
}

// ---------------------------------------------------------------------------
// 10. Product Manager Inbox & Decisions
// ---------------------------------------------------------------------------

async function loadProposalsInbox() {
  if (!STATE.token) return;
  try {
    const res = await fetch('/v1/proposals/inbox', {
      headers: { 'Authorization': 'Bearer ' + STATE.token }
    });
    if (!res.ok) return;
    const proposals = await res.json();

    const listEl = document.getElementById('inbox-list');
    if (!listEl) return;
    listEl.replaceChildren();

    if (proposals.length === 0) {
      const p = document.createElement('p');
      p.className = 'text-sm text-muted text-center py-2';
      p.textContent = 'No pending proposals in inbox.';
      listEl.appendChild(p);
      return;
    }

    proposals.forEach((p) => {
      const item = document.createElement('div');
      item.className = 'inbox-item ' + (STATE.selectedProposalId === p.proposal_id ? 'selected' : '');
      item.dataset.id = p.proposal_id;

      const title = document.createElement('div');
      title.className = 'inbox-item-title';
      title.textContent = p.product_name + ' (Rev ' + p.revision + ')';

      const meta = document.createElement('div');
      meta.className = 'inbox-item-meta';

      const spanId = document.createElement('span');
      spanId.textContent = p.proposal_id;

      const badgeClass = p.status === 'approved' ? 'badge-pass' : (p.status === 'returned' ? 'badge-fail' : (p.status === 'superseded' ? 'badge-fail' : 'badge-review'));
      const spanBadge = document.createElement('span');
      spanBadge.className = 'badge ' + badgeClass;
      spanBadge.textContent = p.status.toUpperCase();

      meta.appendChild(spanId);
      meta.appendChild(spanBadge);

      item.appendChild(title);
      item.appendChild(meta);

      item.addEventListener('click', () => showProposalDetail(p));
      listEl.appendChild(item);
    });

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

  if (titleEl) titleEl.textContent = p.product_name + ' (Revision ' + p.revision + ')';
  if (metaEl) metaEl.textContent = 'Proposal ID: ' + p.proposal_id + ' · Case SHA: ' + p.case_digest.slice(0, 16) + '... · Plan SHA: ' + p.plan_digest.slice(0, 16) + '...';

  if (gateBadgeEl) {
    gateBadgeEl.replaceChildren();
    const isPass = p.gate_decision === 'PASS';
    const isApproved = p.status === 'approved';
    const isReturned = p.status === 'returned';
    const isSuperseded = p.status === 'superseded';
    const badgeText = isApproved ? 'APPROVED & FINALIZED' : (isReturned ? 'RETURNED' : (isSuperseded ? 'SUPERSEDED' : ('GATE: ' + p.gate_decision)));
    const badgeClass = isApproved ? 'badge-pass' : (isReturned || isSuperseded ? 'badge-fail' : (isPass ? 'badge-pass' : 'badge-review'));
    const span = document.createElement('span');
    span.className = 'badge ' + badgeClass;
    span.textContent = badgeText;
    gateBadgeEl.appendChild(span);
  }

  if (bodyEl) {
    bodyEl.replaceChildren();

    const bannerCard = document.createElement('div');
    bannerCard.className = 'card mb-1 ' + (p.status === 'approved' ? 'bg-surface border-emerald p-1' : 'bg-surface p-1');

    if (p.status === 'approved') {
      const topRow = document.createElement('div');
      topRow.className = 'flex-between align-center mb-075';
      const labelApproved = document.createElement('span');
      labelApproved.className = 'text-sm font-bold text-emerald';
      labelApproved.textContent = '✅ Finalized & Approved PIF Product Dossier';
      topRow.appendChild(labelApproved);
      bannerCard.appendChild(topRow);

      const subMeta = document.createElement('div');
      subMeta.className = 'text-xs text-muted mb-075';
      subMeta.textContent = 'Decided At: ' + (p.decided_at || '—') + ' · Rationale: ' + (p.manager_rationale || 'Standard compliance approval');
      bannerCard.appendChild(subMeta);
    }

    const catABox = document.createElement('div');
    catABox.className = 'mb-075';
    const catATitle = document.createElement('div');
    catATitle.className = 'text-xs font-bold text-cyan mb-05';
    catATitle.textContent = p.status === 'approved'
      ? '🖨️ Category A: ProDocuX 5-Format Finalized Deliverables:'
      : '🖨️ Category A: ProDocuX Pre-Review Live Render Preview:';
    catABox.appendChild(catATitle);

    const catABtns = document.createElement('div');
    catABtns.className = 'd-flex gap-05 flex-wrap';
    const formats = [
      { fmt: 'pdf', label: '📄 PDF' },
      { fmt: 'docx', label: '📝 DOCX' },
      { fmt: 'csv', label: '📊 CSV' },
      { fmt: 'xlsx', label: '📈 XLSX' },
      { fmt: 'pptx', label: '📽️ PPTX' }
    ];
    formats.forEach(({ fmt, label }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline-cyan btn-sm btn-prop-render';
      btn.textContent = label + ' ' + (p.status === 'approved' ? 'Final' : 'Preview');
      btn.addEventListener('click', () => renderDraftExport(fmt, p.product_name, p.ingredients_summary));
      catABtns.appendChild(btn);
    });
    catABox.appendChild(catABtns);
    bannerCard.appendChild(catABox);

    const catBBox = document.createElement('div');
    const catBTitle = document.createElement('div');
    catBTitle.className = 'text-xs font-bold text-secondary mb-05';
    catBTitle.textContent = '📂 Category B: Upstream 5-Format Raw Evidence Binaries:';
    catBBox.appendChild(catBTitle);

    const catBBtns = document.createElement('div');
    catBBtns.className = 'd-flex gap-05 flex-wrap';
    const samples = [
      { scen: 'retinol', label: '📄 SDS.pdf' },
      { scen: 'peptide', label: '📝 Spec.docx' },
      { scen: 'day_cream', label: '📊 Formula.csv' },
      { scen: 'phenoxy_excess', label: '📈 Tox.xlsx' },
      { scen: 'mercury', label: '📽️ Audit.pptx' }
    ];
    samples.forEach(({ scen, label }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-secondary btn-sm btn-prop-dl-sample';
      btn.textContent = label;
      btn.addEventListener('click', () => downloadSampleFile(scen));
      catBBtns.appendChild(btn);
    });
    catBBox.appendChild(catBBtns);
    bannerCard.appendChild(catBBox);

    bodyEl.appendChild(bannerCard);

    if (p.gate_reasons && p.gate_reasons.length > 0) {
      const reasonsCard = document.createElement('div');
      reasonsCard.className = 'card mb-1';
      const rTitle = document.createElement('div');
      rTitle.className = 'text-sm font-bold text-amber mb-05';
      rTitle.textContent = '📋 Gate Review Notes:';
      const rUl = document.createElement('ul');
      rUl.className = 'text-sm text-secondary';
      p.gate_reasons.forEach((r) => {
        const rLi = document.createElement('li');
        rLi.textContent = r;
        rUl.appendChild(rLi);
      });
      reasonsCard.appendChild(rTitle);
      reasonsCard.appendChild(rUl);
      bodyEl.appendChild(reasonsCard);
    }

    const ingTitle = document.createElement('div');
    ingTitle.className = 'text-sm font-bold text-secondary mb-05';
    ingTitle.textContent = 'Formulation Ingredients Summary:';
    bodyEl.appendChild(ingTitle);

    const table = document.createElement('table');
    table.className = 'data-table mb-1';
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ['INCI Name', 'Concentration', 'CAS', 'NOAEL'].forEach((hText) => {
      const th = document.createElement('th');
      th.textContent = hText;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    p.ingredients_summary.forEach((item) => {
      const row = document.createElement('tr');
      const tdName = document.createElement('td');
      tdName.textContent = item.inci_name || '';
      const tdPct = document.createElement('td');
      tdPct.textContent = item.concentration_pct + '%';
      const tdCas = document.createElement('td');
      tdCas.textContent = item.cas_number || '—';
      const tdNoael = document.createElement('td');
      tdNoael.textContent = item.noael_mg_kg_day != null ? String(item.noael_mg_kg_day) : '—';

      row.appendChild(tdName);
      row.appendChild(tdPct);
      row.appendChild(tdCas);
      row.appendChild(tdNoael);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    bodyEl.appendChild(table);
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
  const btnSend = document.getElementById('btn-manager-chat-send');
  const query = (customQuery || (inputEl ? inputEl.value : '')).trim();
  if (!query) return;

  if (inputEl) inputEl.value = '';

  const messagesContainer = document.getElementById('manager-chat-messages');
  if (messagesContainer) {
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble chat-user';

    const senderEl = document.createElement('div');
    senderEl.className = 'chat-sender';
    senderEl.textContent = '👔 Product Manager';

    const textEl = document.createElement('div');
    textEl.className = 'chat-text';
    textEl.textContent = query;

    userBubble.appendChild(senderEl);
    userBubble.appendChild(textEl);
    messagesContainer.appendChild(userBubble);

    const thinkingBubble = document.createElement('div');
    thinkingBubble.className = 'chat-bubble chat-bot thinking-bubble';
    thinkingBubble.id = 'manager-thinking-bubble';

    const thinkSender = document.createElement('div');
    thinkSender.className = 'chat-sender';
    thinkSender.textContent = '✨ Gemini Regulatory Copilot';

    const thinkText = document.createElement('div');
    thinkText.className = 'chat-text';
    const spanSpin = document.createElement('span');
    spanSpin.className = 'spinner-pulse';
    spanSpin.textContent = '⏳';
    const emText = document.createElement('em');
    emText.textContent = ' Gemini is evaluating proposal risk & drafting manager rationale...';
    thinkText.appendChild(spanSpin);
    thinkText.appendChild(emText);

    thinkingBubble.appendChild(thinkSender);
    thinkingBubble.appendChild(thinkText);
    messagesContainer.appendChild(thinkingBubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  if (inputEl) inputEl.disabled = true;
  if (btnSend) btnSend.disabled = true;
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
        'Authorization': 'Bearer ' + STATE.token
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

    const tb = document.getElementById('manager-thinking-bubble');
    if (tb) tb.remove();

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (messagesContainer) {
      const botBubble = document.createElement('div');
      botBubble.className = 'chat-bubble chat-bot';

      const botSender = document.createElement('div');
      botSender.className = 'chat-sender';
      botSender.textContent = '✨ ' + (data.provider || 'Gemini Regulatory Copilot');

      const botText = document.createElement('div');
      botText.className = 'chat-text';
      botText.appendChild(renderMarkdownToNode(data.reply));

      botBubble.appendChild(botSender);
      botBubble.appendChild(botText);

      if (query.toLowerCase().includes('rationale') || query.includes('理由') || query.includes('草擬')) {
        const insertBox = document.createElement('div');
        insertBox.className = 'mt-05';
        const insBtn = document.createElement('button');
        insBtn.type = 'button';
        insBtn.className = 'btn btn-secondary btn-sm btn-insert-rationale';
        insBtn.textContent = '📋 Insert Rationale into Input Field';
        insBtn.addEventListener('click', () => {
          const ratInput = document.getElementById('input-manager-rationale');
          if (ratInput) {
            const cleanText = data.reply.replace(/<[^>]*>?/gm, '').replace(/#+\s*/g, '').slice(0, 500).trim();
            ratInput.value = cleanText;
            ratInput.focus();
          }
        });
        insertBox.appendChild(insBtn);
        botBubble.appendChild(insertBox);
      }

      messagesContainer.appendChild(botBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    setTelemetryStatus('node-gemini-assistant', 'READY', 'badge-pass');
  } catch (err) {
    console.error('Failed to send manager chat message:', err);
    const tb = document.getElementById('manager-thinking-bubble');
    if (tb) tb.remove();

    if (messagesContainer) {
      const errBubble = document.createElement('div');
      errBubble.className = 'chat-bubble chat-bot';

      const errSender = document.createElement('div');
      errSender.className = 'chat-sender';
      errSender.textContent = '⚠️ Gemini Advisor';

      const errText = document.createElement('div');
      errText.className = 'chat-text';
      errText.textContent = 'Unable to complete query. Please try again.';

      errBubble.appendChild(errSender);
      errBubble.appendChild(errText);
      messagesContainer.appendChild(errBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    setTelemetryStatus('node-gemini-assistant', 'UNAVAILABLE', 'badge-review');
  } finally {
    if (inputEl) {
      inputEl.disabled = false;
      inputEl.focus();
    }
    if (btnSend) btnSend.disabled = false;
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
    const res = await fetch('/v1/proposals/' + STATE.selectedProposalId + '/decide', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + STATE.token
      },
      body: JSON.stringify({
        decision: decision,
        rationale: rationale,
        return_comments: returnComments
      })
    });

    if (!res.ok) {
      const errJson = await res.json();
      alert('Decision failed: ' + (errJson.detail || JSON.stringify(errJson)));
      setTelemetryStatus('node-manager-gate', 'DECISION ERROR', 'badge-fail');
      return;
    }

    const data = await res.json();

    if (decision === 'approved') {
      alert('🎉 Proposal Approved & Finalized!\nProduct ID: ' + data.product_id + '\nSHA-256 Provenance Checksum: ' + (data.artifact_identity?.sha256 || 'Verified') + '\n\nYou can now download the 5 finalized ProDocuX output files and upstream evidence binaries below.');
      setTelemetryStatus('node-manager-gate', 'FINALIZED', 'badge-pass');
      setTelemetryStatus('node-prodocux-render', 'READY FOR EXPORT', 'badge-pass');
      await loadProposalsInbox();
    } else {
      alert('↩️ Proposal returned to Formulator for revision.\nReturn comments recorded in audit ledger.');
      setTelemetryStatus('node-manager-gate', 'RETURNED', 'badge-review');
      await loadProposalsInbox();
    }
  } catch (err) {
    console.error('Failed to decide proposal:', err);
  }
}

// ---------------------------------------------------------------------------
// 11. Event Listeners Binding
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  initPWA();
  initSession('formulator');

  const btnFormulator = document.getElementById('btn-role-formulator');
  const btnManager = document.getElementById('btn-role-manager');
  if (btnFormulator) btnFormulator.addEventListener('click', () => switchRole('formulator'));
  if (btnManager) btnManager.addEventListener('click', () => switchRole('product_manager'));

  const btnRestart = document.getElementById('btn-restart-demo');
  if (btnRestart) btnRestart.addEventListener('click', restartSession);

  document.querySelectorAll('.preset-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const scenarioKey = chip.dataset.scenario;
      triggerParsePreview(scenarioKey);
    });
  });

  const modalClose = document.getElementById('btn-modal-close');
  const modalCancel = document.getElementById('btn-modal-cancel');
  const modalApply = document.getElementById('btn-modal-apply');
  const modal = document.getElementById('modal-import-preview');

  if (modalClose) modalClose.addEventListener('click', () => modal.classList.add('hidden'));
  if (modalCancel) modalCancel.addEventListener('click', () => modal.classList.add('hidden'));
  if (modalApply) modalApply.addEventListener('click', applyPreviewToDraft);

  const btnAdd = document.getElementById('btn-add-ingredient');
  const btnSave = document.getElementById('btn-save-draft');
  const btnAutoBalance = document.getElementById('btn-auto-balance-aqua');
  if (btnAdd) btnAdd.addEventListener('click', addIngredientRow);
  if (btnSave) btnSave.addEventListener('click', saveDraft);
  if (btnAutoBalance) btnAutoBalance.addEventListener('click', autoBalanceAqua);

  const selectRev = document.getElementById('select-revision-history');
  const btnRollback = document.getElementById('btn-rollback-revision');
  if (selectRev) selectRev.addEventListener('change', handleRevisionSelectChange);
  if (btnRollback) btnRollback.addEventListener('click', rollbackToSelectedRevision);

  document.querySelectorAll('.btn-draft-render').forEach((btn) => {
    btn.addEventListener('click', () => {
      const fmt = btn.dataset.renderFmt;
      if (fmt) renderDraftExport(fmt);
    });
  });

  document.querySelectorAll('.btn-dl-scenario').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const scenarioKey = btn.dataset.scenario;
      if (scenarioKey) downloadSampleFile(scenarioKey);
    });
  });

  document.querySelectorAll('.btn-dl-sample').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.scenario || btn.dataset.fmt;
      if (key) downloadSampleFile(key);
    });
  });

  const btnToggleEvidence = document.getElementById('btn-toggle-prodocux-evidence');
  const evidenceBody = document.getElementById('prodocux-evidence-body');
  if (btnToggleEvidence && evidenceBody) {
    btnToggleEvidence.addEventListener('click', () => {
      const isHidden = evidenceBody.classList.toggle('hidden');
      btnToggleEvidence.textContent = isHidden ? '🔍 Show ProDocuX Binary Extraction Evidence & Hash' : '▲ Hide Extraction Evidence';
    });
  }

  const btnModalDownloadSource = document.getElementById('btn-modal-download-source');
  if (btnModalDownloadSource) {
    btnModalDownloadSource.addEventListener('click', () => {
      downloadSampleFile(STATE.pendingScenarioKey || STATE.pendingPreviewFormat || 'pdf');
    });
  }

  const btnSubmit = document.getElementById('btn-submit-proposal');
  if (btnSubmit) btnSubmit.addEventListener('click', submitProposal);

  const btnAccept = document.getElementById('btn-manager-accept');
  const btnReturn = document.getElementById('btn-manager-return');
  if (btnAccept) btnAccept.addEventListener('click', () => decideProposal('approved'));
  if (btnReturn) btnReturn.addEventListener('click', () => decideProposal('returned'));

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
