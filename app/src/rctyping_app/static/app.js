// rc-typing Client Application Logic

let currentSession = null;
let currentPassage = null;
let keyEvents = [];
let typedChars = [];
let isTestActive = false;
let startTime = null;
let liveInterval = null;
let latestCertificate = null;

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

  setupVerifierTab();
});

// --- Tab Navigation ---
function setupTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const tabId = `tab-${btn.dataset.tab}`;
      document.getElementById(tabId).classList.add('active');

      if (btn.dataset.tab === 'stats') loadStats();
      if (btn.dataset.tab === 'settings') loadSettings();
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

function resetTestState() {
  isTestActive = false;
  startTime = null;
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
  // Shortcut Tab + Enter for restart
  if (e.key === 'Tab') {
    e.preventDefault();
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
  if (liveInterval) clearInterval(liveInterval);
  isTestActive = false;

  focusHint.innerText = 'Submitting keystroke log for mathematical verification...';

  try {
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
      Integrity: ${p.integrity.toUpperCase()}
    </span>
    <span class="status-badge badge-published" style="margin-left: 0.5rem;">
      Registry: ${result.registry_status.toUpperCase()}
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
    <tr><td><strong>Status</strong></td><td>${report.status}</td></tr>
    <tr><td><strong>Subject Name</strong></td><td>${p.subject || '-'} <em>(self-asserted)</em></td></tr>
    <tr><td><strong>Category</strong></td><td>${p.category || '-'} ${p.language ? `(${p.language})` : ''}</td></tr>
    <tr><td><strong>Net Speed</strong></td><td><strong>${m.net_wpm ?? '-'} WPM</strong></td></tr>
    <tr><td><strong>Accuracy</strong></td><td>${m.accuracy ? (m.accuracy * 100).toFixed(1) + '%' : '-'}</td></tr>
    <tr><td><strong>Consistency</strong></td><td>${m.consistency ? Math.round(m.consistency * 100) + '%' : '-'}</td></tr>
    <tr><td><strong>Duration</strong></td><td>${m.duration_ms ? (m.duration_ms / 1000).toFixed(1) + 's' : '-'}</td></tr>
    <tr><td><strong>Integrity Heuristic</strong></td><td>${p.integrity || '-'}</td></tr>
    <tr><td><strong>Certificate ID</strong></td><td><code>${p.cert_id || '-'}</code></td></tr>
    <tr><td><strong>Issuer Key ID</strong></td><td><code>${p.issuer_id || '-'}</code></td></tr>
    <tr><td><strong>Details</strong></td><td>${report.details}</td></tr>
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
          <td><strong>${catLabel}</strong></td>
          <td>${s.tests_completed}</td>
          <td><span style="color: var(--accent); font-weight: 600;">${s.best_net_wpm} WPM</span></td>
          <td>${s.avg_net_wpm} WPM</td>
          <td>${(s.avg_accuracy * 100).toFixed(1)}%</td>
        </tr>
      `;
    }

    container.innerHTML = `
      <div style="margin-bottom: 1rem;"><strong>Total Verified Certificates:</strong> ${data.total_certificates}</div>
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
    container.innerHTML = `<p style="color: var(--error);">Error loading stats: ${err.message}</p>`;
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
