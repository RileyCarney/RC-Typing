// rc-typing Client Application Logic

let currentSession = null;
let currentPassage = null;
let keyEvents = [];
let typedChars = [];
let isTestActive = false;
let startTime = null;
let sessionStartPromise = null;
let liveInterval = null;
let latestCertificate = null;

function escapeHtml(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// DOM Elements
const categorySelect = document.getElementById('category-select');
const languageGroup = document.getElementById('language-group');
const languageSelect = document.getElementById('language-select');
const newPassageBtn = document.getElementById('new-passage-btn');
const typingViewport = document.getElementById('typing-viewport');
const passageTitle = document.getElementById('passage-title');
const passageLicense = document.getElementById('passage-license');
const focusHint = document.getElementById('focus-hint');
const liveWpm = document.getElementById('live-wpm');
const liveAcc = document.getElementById('live-accuracy');
const liveTime = document.getElementById('live-time');

// Modal Elements
const certModal = document.getElementById('cert-modal');
const closeModalBtn = document.getElementById('close-modal-btn');
const downloadCertBtn = document.getElementById('download-cert-btn');
const viewInVerifierBtn = document.getElementById('view-in-verifier-btn');

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupSettings();
  setupTypingThoughts();
  loadNewPassage();

  categorySelect.addEventListener('change', () => {
    languageGroup.style.display = categorySelect.value === 'code' ? 'block' : 'none';
    loadNewPassage();
  });

  languageSelect.addEventListener('change', loadNewPassage);
  newPassageBtn.addEventListener('click', loadNewPassage);

  typingViewport.addEventListener('keydown', handleKeyDown);
  typingViewport.addEventListener('keyup', handleKeyUp);
  typingViewport.addEventListener('focus', () => { focusHint.innerText = 'Listening for keystrokes...'; });
  typingViewport.addEventListener('blur', () => { if (!isTestActive) focusHint.innerText = 'Click inside or start typing to begin test'; });

  closeModalBtn.addEventListener('click', () => certModal.classList.remove('open'));
  downloadCertBtn.addEventListener('click', downloadCurrentCertificate);
  viewInVerifierBtn.addEventListener('click', openCurrentInVerifier);

  document.addEventListener('keydown', (e) => {
    const testTabActive = document.getElementById('tab-test')?.classList.contains('active');
    if (!testTabActive) return;
    if (typingViewport.contains(e.target)) return;
    if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(e.target?.tagName)) return;
    handleNewPassageShortcut(e);
  });

  setupVerifierTab();
});

// --- Tab Navigation ---
function setupTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.classList.contains('active')) return;

      document.querySelectorAll('.nav-btn').forEach(b => {
        b.classList.remove('active');
        b.removeAttribute('aria-current');
      });
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      btn.setAttribute('aria-current', 'page');
      const tabId = `tab-${btn.dataset.tab}`;
      document.getElementById(tabId).classList.add('active');

      if (btn.dataset.tab === 'thoughts') {
        loadBrain();
        document.getElementById('thought-input')?.focus();
      }
      if (btn.dataset.tab === 'settings') {
        loadSettings();
        loadStats();
      }
    });
  });
}

// --- Session & Passage Loading ---
async function loadNewPassage() {
  resetTestState();
  const category = categorySelect.value;
  const language = category === 'code' ? languageSelect.value : null;

  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, language })
    });
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    currentSession = data.session_id;
    currentPassage = data.passage;

    passageTitle.innerText = `${currentPassage.title} (${currentPassage.difficulty})`;
    passageLicense.innerText = `License: ${currentPassage.license} | ${currentPassage.source}`;

    renderPassageText(currentPassage.text);
    typingViewport.focus();
  } catch (err) {
    passageTitle.innerText = 'Error loading passage';
    console.error(err);
  }
}

function handleNewPassageShortcut(e) {
  if (e.ctrlKey && !e.altKey && !e.metaKey && e.key === 'Enter') {
    e.preventDefault();
    certModal.classList.remove('open');
    loadNewPassage();
    return true;
  }
  return false;
}

function resetTestState() {
  isTestActive = false;
  startTime = null;
  sessionStartPromise = null;
  keyEvents = [];
  typedChars = [];
  if (liveInterval) clearInterval(liveInterval);
  liveWpm.innerText = '0';
  liveAcc.innerText = '100%';
  liveTime.innerText = '0.0s';
}

function renderPassageText(text) {
  typingViewport.innerHTML = '';
  for (let i = 0; i < text.length; i++) {
    const span = document.createElement('span');
    span.classList.add('char');
    span.innerText = text[i];
    if (i === 0) span.classList.add('current');
    typingViewport.appendChild(span);
  }
}

// --- Keystroke Handling ---
function handleKeyDown(e) {
  if (!currentPassage) return;

  // Shortcut Ctrl + Enter for new passage
  if (handleNewPassageShortcut(e)) {
    return;
  }

  // Ignore navigation or modifier-only keys
  if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(e.key)) {
    return;
  }

  const now = performance.now();
  if (!isTestActive) {
    isTestActive = true;
    startTime = now;
    liveInterval = setInterval(updateLiveStats, 100);
    if (currentSession) {
      sessionStartPromise = fetch(`/api/sessions/${currentSession}/start`, { method: 'POST' }).catch(() => {});
    }
  }

  const offsetMs = Math.round(now - startTime);
  keyEvents.push({
    t_ms: offsetMs,
    key: e.key,
    type: 'keydown',
    is_trusted: e.isTrusted
  });

  const targetText = currentPassage.text;
  const charElements = typingViewport.querySelectorAll('.char');

  if (e.key === 'Backspace') {
    e.preventDefault();
    if (typedChars.length > 0) {
      const idx = typedChars.length - 1;
      typedChars.pop();
      charElements[idx].className = 'char current';
      if (idx + 1 < charElements.length) charElements[idx + 1].classList.remove('current');
    }
    return;
  }

  // Handle character entry
  let charToAdd = null;
  if (e.key === 'Enter') {
    e.preventDefault();
    charToAdd = '\n';
  } else if (e.key === 'Tab') {
    charToAdd = '    ';
  } else if (e.key.length === 1) {
    charToAdd = e.key;
  }

  if (charToAdd !== null) {
    e.preventDefault();
    for (let c of charToAdd) {
      const idx = typedChars.length;
      if (idx < targetText.length) {
        typedChars.push(c);
        charElements[idx].classList.remove('current');
        if (c === targetText[idx]) {
          charElements[idx].classList.add('correct');
        } else {
          charElements[idx].classList.add('incorrect');
        }
        if (idx + 1 < charElements.length) {
          charElements[idx + 1].classList.add('current');
        }
      }
    }
  }

  // Check completion
  if (typedChars.length >= targetText.length) {
    finishTest();
  }
}

function handleKeyUp(e) {
  if (!isTestActive) return;
  if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(e.key)) return;
  const now = performance.now();
  const offsetMs = Math.round(now - startTime);
  keyEvents.push({
    t_ms: offsetMs,
    key: e.key,
    type: 'keyup',
    is_trusted: e.isTrusted
  });
}

function updateLiveStats() {
  if (!startTime || !currentPassage) return;
  const elapsedSec = (performance.now() - startTime) / 1000;
  liveTime.innerText = `${elapsedSec.toFixed(1)}s`;

  let correct = 0;
  for (let i = 0; i < typedChars.length; i++) {
    if (typedChars[i] === currentPassage.text[i]) correct++;
  }

  const minutes = Math.max(0.001, elapsedSec / 60);
  const wpm = Math.round((correct / 5) / minutes);
  const accuracy = typedChars.length > 0 ? Math.round((correct / typedChars.length) * 100) : 100;

  liveWpm.innerText = wpm;
  liveAcc.innerText = `${accuracy}%`;
}

// --- Finish Test & Submit ---
async function finishTest() {
  updateLiveStats();
  if (liveInterval) clearInterval(liveInterval);
  isTestActive = false;

  focusHint.innerText = 'Submitting keystroke log for mathematical verification...';

  try {
    if (sessionStartPromise) await sessionStartPromise;
    const res = await fetch(`/api/sessions/${currentSession}/finish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        events: keyEvents,
        subject_name: document.getElementById('setting-default-name')?.value || 'Anonymous Typist'
      })
    });

    if (!res.ok) throw new Error(await res.text());

    const result = await res.json();
    liveWpm.innerText = Math.round(result.metrics.net_wpm);
    liveAcc.innerText = `${(result.metrics.accuracy * 100).toFixed(1)}%`;
    liveTime.innerText = `${(result.metrics.duration_ms / 1000).toFixed(1)}s`;
    latestCertificate = result.certificate;
    showCertificateModal(result);
  } catch (err) {
    focusHint.innerText = `Error issuing certificate: ${err.message}`;
    console.error(err);
  }
}

function showCertificateModal(result) {
  const p = result.certificate.payload;
  document.getElementById('cert-val-subject').innerText = p.subject;
  document.getElementById('cert-val-cat').innerText = p.language ? `${p.category} (${p.language})` : p.category;
  document.getElementById('cert-val-netwpm').innerText = `${p.metrics.net_wpm} WPM`;
  document.getElementById('cert-val-acc').innerText = `${(p.metrics.accuracy * 100).toFixed(1)}%`;
  document.getElementById('cert-val-consistency').innerText = `${Math.round(p.metrics.consistency * 100)}%`;
  document.getElementById('cert-val-duration').innerText = `${(p.metrics.duration_ms / 1000).toFixed(1)}s`;
  document.getElementById('cert-val-id').innerText = p.cert_id;
  document.getElementById('cert-val-issuer').innerText = p.issuer_id;

  const badgeBox = document.getElementById('modal-status-badge');
  badgeBox.innerHTML = `
    <span class="status-badge ${p.integrity === 'clean' ? 'badge-clean' : 'badge-flagged'}">
      Integrity: ${escapeHtml(String(p.integrity || '').toUpperCase())}
    </span>
    <span class="status-badge badge-published" style="margin-left: 0.5rem;">
      Registry: ${escapeHtml(String(result.registry_status || '').toUpperCase())}
    </span>
  `;

  certModal.classList.add('open');
}

function downloadCurrentCertificate() {
  if (!latestCertificate) return;
  const str = JSON.stringify(latestCertificate, null, 2);
  const blob = new Blob([str], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `rc-certificate-${latestCertificate.payload.cert_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function openCurrentInVerifier() {
  if (!latestCertificate) return;
  certModal.classList.remove('open');
  document.querySelector('[data-tab="verify"]').click();
  document.getElementById('cert-json-input').value = JSON.stringify(latestCertificate, null, 2);
  document.getElementById('run-verify-btn').click();
}

// --- Verifier Tab ---
function setupVerifierTab() {
  const fileInput = document.getElementById('cert-file-input');
  const uploadBtn = document.getElementById('upload-cert-btn');
  const verifyBtn = document.getElementById('run-verify-btn');
  const textarea = document.getElementById('cert-json-input');

  uploadBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (ev) => { textarea.value = ev.target.result; };
      reader.readAsText(file);
    }
  });

  verifyBtn.addEventListener('click', async () => {
    const raw = textarea.value.trim();
    if (!raw) return;

    let envelope;
    try {
      envelope = JSON.parse(raw);
    } catch (err) {
      alert('Invalid JSON: ' + err.message);
      return;
    }

    try {
      const res = await fetch('/api/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(envelope)
      });
      if (!res.ok) {
        const errText = await res.text();
        alert(`Verification failed (HTTP ${res.status}): ${errText}`);
        return;
      }
      const data = await res.json();
      displayVerificationReport(data, envelope);
    } catch (err) {
      alert('Verification error: ' + err.message);
    }
  });
}

function displayVerificationReport(report, envelope) {
  const container = document.getElementById('verify-results');
  const badge = document.getElementById('verify-badge-container');
  const tbody = document.querySelector('#verify-details-table tbody');

  container.style.display = 'block';
  badge.innerHTML = report.valid
    ? `<span class="status-badge badge-clean" style="font-size: 1rem;">&#10004; VALID CRYPTOGRAPHIC SIGNATURE</span>`
    : `<span class="status-badge badge-flagged" style="font-size: 1rem;">&#10008; INVALID OR TAMPERED SIGNATURE</span>`;

  const p = envelope.payload || {};
  const m = p.metrics || {};

  tbody.innerHTML = `
    <tr><td><strong>Status</strong></td><td>${escapeHtml(report.status)}</td></tr>
    <tr><td><strong>Subject Name</strong></td><td>${escapeHtml(p.subject || '-')} <em>(self-asserted)</em></td></tr>
    <tr><td><strong>Category</strong></td><td>${escapeHtml(p.category || '-')} ${p.language ? `(${escapeHtml(p.language)})` : ''}</td></tr>
    <tr><td><strong>Net Speed</strong></td><td><strong>${escapeHtml(m.net_wpm ?? '-')} WPM</strong></td></tr>
    <tr><td><strong>Accuracy</strong></td><td>${m.accuracy != null ? escapeHtml((m.accuracy * 100).toFixed(1) + '%') : '-'}</td></tr>
    <tr><td><strong>Consistency</strong></td><td>${m.consistency != null ? escapeHtml(Math.round(m.consistency * 100) + '%') : '-'}</td></tr>
    <tr><td><strong>Duration</strong></td><td>${m.duration_ms != null ? escapeHtml((m.duration_ms / 1000).toFixed(1) + 's') : '-'}</td></tr>
    <tr><td><strong>Integrity Heuristic</strong></td><td>${escapeHtml(p.integrity || '-')}</td></tr>
    <tr><td><strong>Certificate ID</strong></td><td><code>${escapeHtml(p.cert_id || '-')}</code></td></tr>
    <tr><td><strong>Issuer Key ID</strong></td><td><code>${escapeHtml(p.issuer_id || '-')}</code></td></tr>
    <tr><td><strong>Details</strong></td><td>${escapeHtml(report.details)}</td></tr>
  `;
}

// --- Stats Tab ---
async function loadStats() {
  const container = document.getElementById('stats-container');
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();

    if (data.total_certificates === 0) {
      container.innerHTML = '<p style="color: var(--text-muted);">No completed tests yet. Take your first test in the Typing Test tab!</p>';
      return;
    }

    let rows = '';
    for (let [key, s] of Object.entries(data.by_category)) {
      const catLabel = s.language ? `${s.category} / ${s.language}` : s.category;
      rows += `
        <tr>
          <td><strong>${escapeHtml(catLabel)}</strong></td>
          <td>${escapeHtml(s.tests_completed)}</td>
          <td><span style="color: var(--accent); font-weight: 600;">${escapeHtml(s.best_net_wpm)} WPM</span></td>
          <td>${escapeHtml(s.avg_net_wpm)} WPM</td>
          <td>${escapeHtml((s.avg_accuracy * 100).toFixed(1))}%</td>
        </tr>
      `;
    }

    container.innerHTML = `
      <div style="margin-bottom: 1rem;"><strong>Total Verified Certificates:</strong> ${escapeHtml(data.total_certificates)}</div>
      <table>
        <thead>
          <tr>
            <th>Category of Thought</th>
            <th>Tests</th>
            <th>Personal Best</th>
            <th>Avg Speed</th>
            <th>Avg Accuracy</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<p style="color: var(--error);">Error loading stats: ${escapeHtml(err.message)}</p>`;
  }
}

// --- Settings Tab ---
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    document.getElementById('setting-auto-publish').checked = data.publish_to_registry;
    document.getElementById('setting-default-name').value = data.default_cert_name;
    document.getElementById('setting-registry-url').value = data.registry_url || '';
  } catch (err) {
    console.error('Error loading settings', err);
  }
}

function setupSettings() {
  const saveBtn = document.getElementById('save-settings-btn');
  const statusLbl = document.getElementById('settings-status');

  saveBtn.addEventListener('click', async () => {
    const publish = document.getElementById('setting-auto-publish').checked;
    const name = document.getElementById('setting-default-name').value;
    const registryUrl = document.getElementById('setting-registry-url').value;

    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          publish_to_registry: publish,
          default_cert_name: name,
          registry_url: registryUrl
        })
      });
      if (res.ok) {
        statusLbl.innerText = 'Settings saved successfully!';
        setTimeout(() => { statusLbl.innerText = ''; }, 3000);
      }
    } catch (err) {
      alert('Error saving settings: ' + err.message);
    }
  });
}

// --- Typing Thoughts & Brain Explorer ---
let thoughtStartTime = null;
let thoughtInterval = null;
let activeFolderId = null; // null = Brain root
let brainState = { folders: [], thoughts: [], encryption: null };
const collapsedFolders = new Set();
let draggedThoughtId = null;

function setupTypingThoughts() {
  const input = document.getElementById('thought-input');
  const pushBtn = document.getElementById('push-thought-btn');
  const createFolderBtn = document.getElementById('create-folder-btn');
  const newFolderInput = document.getElementById('new-folder-input');
  const exportZipBtn = document.getElementById('export-brain-zip-btn');
  if (!input || !pushBtn) return;

  input.addEventListener('keydown', (e) => {
    if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Tab'].includes(e.key)) {
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      pushCurrentThought();
      return;
    }
    if (!thoughtStartTime && (e.key.length === 1 || e.key === 'Backspace')) {
      startThoughtTimer();
    }
  });

  input.addEventListener('input', () => {
    if (!input.value.trim()) {
      resetThoughtComposerTimer();
    } else if (!thoughtStartTime) {
      startThoughtTimer();
    }
    updateThoughtLiveTelemetry();
  });

  pushBtn.addEventListener('click', pushCurrentThought);

  createFolderBtn?.addEventListener('click', createBrainFolder);
  newFolderInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      createBrainFolder();
    }
  });

  exportZipBtn?.addEventListener('click', () => {
    window.location.href = '/api/thoughts/export-zip';
  });
}

function startThoughtTimer() {
  thoughtStartTime = performance.now();
  if (thoughtInterval) clearInterval(thoughtInterval);
  thoughtInterval = setInterval(updateThoughtLiveTelemetry, 100);
  const hint = document.getElementById('thought-status-hint');
  if (hint) hint.innerText = 'Measuring typing speed... Press Enter to push thought';
}

function resetThoughtComposerTimer() {
  thoughtStartTime = null;
  if (thoughtInterval) {
    clearInterval(thoughtInterval);
    thoughtInterval = null;
  }
  const wpmEl = document.getElementById('thought-live-wpm');
  const timeEl = document.getElementById('thought-live-time');
  const charsEl = document.getElementById('thought-live-chars');
  if (wpmEl) wpmEl.innerText = '0';
  if (timeEl) timeEl.innerText = '0.0s';
  if (charsEl) charsEl.innerText = '0';
}

function updateThoughtLiveTelemetry() {
  const input = document.getElementById('thought-input');
  if (!input) return;
  const text = input.value;
  const charsEl = document.getElementById('thought-live-chars');
  const wpmEl = document.getElementById('thought-live-wpm');
  const timeEl = document.getElementById('thought-live-time');

  if (charsEl) charsEl.innerText = String(text.length);
  if (!thoughtStartTime) return;

  const elapsedMs = Math.max(1, performance.now() - thoughtStartTime);
  const elapsedSec = elapsedMs / 1000;
  const minutes = Math.max(0.001, elapsedSec / 60);
  const wpm = Math.round((text.length / 5) / minutes);

  if (wpmEl) wpmEl.innerText = String(wpm);
  if (timeEl) timeEl.innerText = `${elapsedSec.toFixed(1)}s`;
}

async function pushCurrentThought() {
  const input = document.getElementById('thought-input');
  const filenameInput = document.getElementById('thought-filename-input');
  const hint = document.getElementById('thought-status-hint');
  if (!input) return;

  const content = input.value.trim();
  if (!content) {
    if (hint) hint.innerText = 'Type a thought before pushing.';
    return;
  }

  const durationMs = thoughtStartTime ? Math.max(50, Math.round(performance.now() - thoughtStartTime)) : 500;
  const minutes = Math.max(0.001, durationMs / 60000);
  const wpm = Math.round(((content.length / 5) / minutes) * 10) / 10;
  const customFilename = filenameInput ? filenameInput.value.trim() : '';

  try {
    const res = await fetch('/api/thoughts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        duration_ms: durationMs,
        wpm,
        folder_id: activeFolderId,
        filename: customFilename || null
      })
    });
    if (!res.ok) throw new Error(await res.text());

    const created = await res.json();
    input.value = '';
    if (filenameInput) filenameInput.value = '';
    resetThoughtComposerTimer();
    if (hint) {
      hint.innerText = `Pushed ${created.filename} (${created.wpm} WPM in ${created.total_time}) - encrypted locally.`;
    }
    await loadBrain();
    input.focus();
  } catch (err) {
    if (hint) hint.innerText = `Error saving thought: ${err.message}`;
    console.error(err);
  }
}

async function loadBrain() {
  try {
    const res = await fetch('/api/thoughts/brain');
    if (!res.ok) throw new Error(await res.text());
    brainState = await res.json();

    if (activeFolderId && !brainState.folders.some(f => f.id === activeFolderId)) {
      activeFolderId = null;
    }

    const badge = document.getElementById('brain-encryption-badge');
    if (badge && brainState.encryption) {
      badge.innerText = `${brainState.encryption.algorithm} Local Encrypted`;
    }

    renderBrainExplorer();
    renderBrainThoughts();
  } catch (err) {
    console.error('Failed to load brain', err);
  }
}

async function createBrainFolder() {
  const input = document.getElementById('new-folder-input');
  if (!input) return;
  const name = input.value.trim();
  if (!name) return;

  try {
    const res = await fetch('/api/thoughts/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        parent_id: activeFolderId
      })
    });
    if (!res.ok) throw new Error(await res.text());
    const created = await res.json();
    input.value = '';
    activeFolderId = created.id;
    await loadBrain();
  } catch (err) {
    alert('Could not create folder: ' + err.message);
  }
}

async function deleteBrainFolder(folderId) {
  try {
    const res = await fetch(`/api/thoughts/folders/${folderId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    if (activeFolderId === folderId) activeFolderId = null;
    await loadBrain();
  } catch (err) {
    alert('Error deleting folder: ' + err.message);
  }
}

async function moveThoughtToFolder(thoughtId, targetFolderId) {
  try {
    const payload = targetFolderId ? { folder_id: targetFolderId } : { move_to_root: true };
    const res = await fetch(`/api/thoughts/${thoughtId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(await res.text());
    await loadBrain();
  } catch (err) {
    alert('Error moving thought: ' + err.message);
  }
}

async function deleteThought(thoughtId) {
  try {
    const res = await fetch(`/api/thoughts/${thoughtId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    await loadBrain();
  } catch (err) {
    alert('Error deleting thought: ' + err.message);
  }
}

function attachFolderDropHandlers(rowEl, folderId) {
  rowEl.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    rowEl.classList.add('drag-over');
  });
  rowEl.addEventListener('dragleave', () => {
    rowEl.classList.remove('drag-over');
  });
  rowEl.addEventListener('drop', async (e) => {
    e.preventDefault();
    rowEl.classList.remove('drag-over');
    const droppedId = e.dataTransfer.getData('text/plain') || draggedThoughtId;
    if (droppedId) {
      await moveThoughtToFolder(droppedId, folderId);
      draggedThoughtId = null;
    }
  });
}

function attachThoughtDragHandlers(el, thoughtId) {
  el.setAttribute('draggable', 'true');
  el.addEventListener('dragstart', (e) => {
    draggedThoughtId = thoughtId;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', thoughtId);
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => {
    draggedThoughtId = null;
    el.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(node => node.classList.remove('drag-over'));
  });
}

function renderBrainExplorer() {
  const tree = document.getElementById('brain-explorer-tree');
  const activeLabel = document.getElementById('thought-active-folder-label');
  if (!tree) return;
  tree.innerHTML = '';

  const activeFolder = brainState.folders.find(f => f.id === activeFolderId);
  if (activeLabel) {
    activeLabel.innerText = activeFolder ? `Brain / ${activeFolder.path}` : 'Brain /';
  }

  // Root node
  const rootRow = document.createElement('div');
  rootRow.className = `tree-folder-row${activeFolderId === null ? ' active' : ''}`;
  rootRow.dataset.folderId = 'root';
  rootRow.innerHTML = `<span class="tree-folder-label"><span>&#128193;</span><span class="tree-folder-name">Brain / (Root)</span></span>`;
  rootRow.addEventListener('click', () => {
    activeFolderId = null;
    renderBrainExplorer();
    renderBrainThoughts();
  });
  attachFolderDropHandlers(rootRow, null);
  tree.appendChild(rootRow);

  const rootChildrenWrap = document.createElement('div');
  rootChildrenWrap.className = 'tree-children';
  renderFolderBranch(null, rootChildrenWrap);
  tree.appendChild(rootChildrenWrap);
}

function renderFolderBranch(parentId, container) {
  const childFolders = brainState.folders.filter(f => (f.parent_id || null) === parentId);
  for (const folder of childFolders) {
    const isCollapsed = collapsedFolders.has(folder.id);
    const row = document.createElement('div');
    row.className = `tree-folder-row${activeFolderId === folder.id ? ' active' : ''}`;
    row.dataset.folderId = folder.id;

    const label = document.createElement('span');
    label.className = 'tree-folder-label';

    const toggle = document.createElement('span');
    toggle.innerText = isCollapsed ? '▸' : '▾';
    toggle.style.cursor = 'pointer';
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (isCollapsed) collapsedFolders.delete(folder.id);
      else collapsedFolders.add(folder.id);
      renderBrainExplorer();
    });

    const icon = document.createElement('span');
    icon.innerHTML = '&#128193;';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'tree-folder-name';
    nameSpan.innerText = folder.name;

    label.append(toggle, icon, nameSpan);

    const delBtn = document.createElement('button');
    delBtn.className = 'tree-folder-delete';
    delBtn.title = 'Delete folder (thoughts move to parent)';
    delBtn.innerHTML = '&times;';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteBrainFolder(folder.id);
    });

    row.append(label, delBtn);
    row.addEventListener('click', () => {
      activeFolderId = folder.id;
      renderBrainExplorer();
      renderBrainThoughts();
    });
    attachFolderDropHandlers(row, folder.id);
    container.appendChild(row);

    if (!isCollapsed) {
      const branch = document.createElement('div');
      branch.className = 'tree-children';
      renderFolderBranch(folder.id, branch);
      container.appendChild(branch);
    }
  }

  // Render .md files directly inside parentId in explorer tree
  const folderThoughts = brainState.thoughts.filter(t => (t.folder_id || null) === parentId);
  for (const thought of folderThoughts) {
    const fileEl = document.createElement('div');
    fileEl.className = 'tree-file-item';
    fileEl.title = `${thought.filename} (${thought.wpm} WPM, ${thought.total_time})`;
    fileEl.innerHTML = `<span>&#128196;</span><span class="tree-folder-name"></span>`;
    fileEl.querySelector('.tree-folder-name').innerText = thought.filename;
    attachThoughtDragHandlers(fileEl, thought.id);
    container.appendChild(fileEl);
  }
}

function renderBrainThoughts() {
  const listEl = document.getElementById('brain-thoughts-list');
  const headingEl = document.getElementById('brain-current-path-heading');
  const countEl = document.getElementById('brain-thought-count');
  if (!listEl) return;

  const activeFolder = brainState.folders.find(f => f.id === activeFolderId);
  const visibleThoughts = activeFolderId === null
    ? brainState.thoughts
    : brainState.thoughts.filter(t => t.folder_id === activeFolderId);

  if (headingEl) {
    headingEl.innerText = activeFolder ? `Brain / ${activeFolder.path}` : 'Brain / (All Thoughts)';
  }
  if (countEl) {
    countEl.innerText = `${visibleThoughts.length} thought${visibleThoughts.length === 1 ? '' : 's'}`;
  }

  listEl.innerHTML = '';
  if (visibleThoughts.length === 0) {
    listEl.innerHTML = '<p style="color: var(--text-muted); font-size: 0.9rem;">No thoughts in this folder yet. Type above and press Enter to push one!</p>';
    return;
  }

  for (const t of visibleThoughts) {
    const card = document.createElement('div');
    card.className = 'thought-card';
    attachThoughtDragHandlers(card, t.id);

    const top = document.createElement('div');
    top.className = 'thought-card-top';

    const nameEl = document.createElement('div');
    nameEl.className = 'thought-filename';
    nameEl.innerText = t.filename;

    const metrics = document.createElement('div');
    metrics.className = 'thought-metrics';
    const wpmPill = document.createElement('span');
    wpmPill.className = 'thought-pill';
    wpmPill.innerText = `${t.wpm} WPM`;
    const timePill = document.createElement('span');
    timePill.className = 'thought-pill';
    timePill.innerText = t.total_time;
    const pathPill = document.createElement('span');
    pathPill.className = 'thought-pill';
    pathPill.innerText = `/${t.folder_path || ''}`;
    metrics.append(wpmPill, timePill, pathPill);
    top.append(nameEl, metrics);

    const body = document.createElement('div');
    body.className = 'thought-body';
    body.innerText = t.content;

    const actions = document.createElement('div');
    actions.className = 'thought-card-actions';

    const moveLabel = document.createElement('label');
    moveLabel.style.display = 'flex';
    moveLabel.style.alignItems = 'center';
    moveLabel.style.gap = '0.4rem';
    moveLabel.innerText = 'Folder:';

    const moveSelect = document.createElement('select');
    moveSelect.className = 'thought-move-select';
    const rootOpt = document.createElement('option');
    rootOpt.value = '';
    rootOpt.innerText = 'Brain / (Root)';
    if (!t.folder_id) rootOpt.selected = true;
    moveSelect.appendChild(rootOpt);

    for (const f of brainState.folders) {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.innerText = f.path;
      if (t.folder_id === f.id) opt.selected = true;
      moveSelect.appendChild(opt);
    }
    moveSelect.addEventListener('change', () => moveThoughtToFolder(t.id, moveSelect.value || null));
    moveLabel.appendChild(moveSelect);

    const btnGroup = document.createElement('div');
    btnGroup.style.display = 'flex';
    btnGroup.style.gap = '0.4rem';

    const dlBtn = document.createElement('button');
    dlBtn.className = 'btn btn-secondary btn-xs';
    dlBtn.innerText = 'Download .md';
    dlBtn.addEventListener('click', () => {
      const blob = new Blob([t.markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = t.filename;
      a.click();
      URL.revokeObjectURL(url);
    });

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger btn-xs';
    delBtn.innerText = 'Delete';
    delBtn.addEventListener('click', () => deleteThought(t.id));

    btnGroup.append(dlBtn, delBtn);
    actions.append(moveLabel, btnGroup);

    card.append(top, body, actions);
    listEl.appendChild(card);
  }
}
