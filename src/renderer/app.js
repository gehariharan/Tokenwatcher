'use strict';

let settings = { watch_codex: true, watch_claude: true };

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  settings = await window.api.getSettings();
  applySettings();
  bindUI();

  window.api.onPanelOpened(() => fetchAll());
  fetchAll();
});

function bindUI() {
  document.getElementById('refresh-btn').addEventListener('click', fetchAll);
  document.getElementById('settings-btn').addEventListener('click', openSettings);
  document.getElementById('back-btn').addEventListener('click', closeSettings);
  document.getElementById('watch-codex').addEventListener('change', onToggleChange);
  document.getElementById('watch-claude').addEventListener('change', onToggleChange);

  // Tell main when the cursor is inside the panel so it keeps the panel open
  // while we're using it. We use mouseenter/mouseleave (not over/out) so child
  // elements don't trigger spurious leaves.
  document.documentElement.addEventListener('mouseenter', () => window.api.panelMouseEnter());
  document.documentElement.addEventListener('mouseleave', () => window.api.panelMouseLeave());
}

// ── Settings ──────────────────────────────────────────────────────────────────

function openSettings() {
  document.getElementById('watch-codex').checked = settings.watch_codex;
  document.getElementById('watch-claude').checked = settings.watch_claude;
  document.getElementById('main-view').classList.add('hidden');
  document.getElementById('settings-view').classList.remove('hidden');
}

function closeSettings() {
  document.getElementById('settings-view').classList.add('hidden');
  document.getElementById('main-view').classList.remove('hidden');
}

async function onToggleChange() {
  settings.watch_codex = document.getElementById('watch-codex').checked;
  settings.watch_claude = document.getElementById('watch-claude').checked;
  await window.api.saveSettings(settings);
  applySettings();
  fetchAll();
}

function applySettings() {
  document.getElementById('codex-card').style.display = settings.watch_codex ? '' : 'none';
  document.getElementById('claude-card').style.display = settings.watch_claude ? '' : 'none';
}

// ── Fetch ─────────────────────────────────────────────────────────────────────

async function fetchAll() {
  if (settings.watch_codex) setBody('codex', '<p class="loading-text">Loading…</p>');
  if (settings.watch_claude) setBody('claude', '<p class="loading-text">Loading…</p>');

  const data = await window.api.fetchUsage();

  if (settings.watch_codex) renderProvider('codex', data.codex);
  if (settings.watch_claude) renderProvider('claude', data.claude);

  const now = new Date();
  document.getElementById('last-updated').textContent =
    `Updated ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderProvider(id, result) {
  if (!result) {
    setBody(id, '<p class="error-msg">No data returned.</p>');
    setBadge(id, '');
    return;
  }

  if (result.status === 'ok') {
    setBadge(id, 'ok');
    setBody(id, buildOkBody(result));
  } else if (result.status === 'not_logged_in') {
    setBadge(id, 'warn');
    if (id === 'claude') {
      setBody(id, buildClaudeSignInBody(result.error));
    } else {
      setBody(id, `
        <p class="error-msg">${esc(result.error)}</p>
        <p class="error-msg" style="color:var(--muted)">Run <code style="font-family:monospace">codex</code> in a terminal once to refresh.</p>
      `);
    }
  } else {
    setBadge(id, 'error');
    setBody(id, `<p class="error-msg">${esc(result.error || 'Unknown error')}</p>`);
  }
}

function buildOkBody(result) {
  let html = '';

  if (result.plan || result.account_label) {
    html += '<div class="plan-row">';
    if (result.plan) {
      html += `<span class="plan-tag" title="${esc(result.plan)}">${esc(result.plan)}</span>`;
    }
    if (result.account_label) {
      html += `<span class="account-label" title="${esc(result.account_label)}">${esc(result.account_label)}</span>`;
    }
    html += '</div>';
  }

  for (const w of (result.windows || [])) {
    html += buildWindow(w);
  }

  if (result.credits_balance) {
    html += `<p class="credits-line">${esc(result.credits_balance)}</p>`;
  }

  return html || '<p class="error-msg">No usage data available.</p>';
}

function buildWindow(w) {
  const pct = w.used_percent;
  if (pct == null) {
    return `<div class="rate-window"><p class="window-text-only">${esc(w.label)}</p></div>`;
  }

  const tier = pct >= 90 ? 'crit' : pct >= 70 ? 'warn' : 'ok';
  const fillClass = `fill-${tier}`;
  const pctClass = `pct-${tier}`;
  const resetHtml = w.resets_at ? buildResetTime(w.resets_at) : '';

  return `
    <div class="rate-window">
      <div class="window-row">
        <span class="window-label">${esc(w.label)}</span>
        <span class="window-pct ${pctClass}">${pct.toFixed(1)}%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill ${fillClass}" style="width:${Math.min(pct, 100)}%"></div>
      </div>
      ${resetHtml}
    </div>
  `;
}

function buildResetTime(isoString) {
  const d = new Date(isoString);
  const diff = d - Date.now();
  if (diff <= 0) return '';

  const hours = Math.floor(diff / 3600000);

  // For windows >24h away, "resets in 145h 18m" is useless — show absolute date/time.
  if (hours >= 24) {
    const opts = { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
    return `<div class="reset-time">resets ${d.toLocaleString(undefined, opts)}</div>`;
  }

  const totalMins = Math.floor(diff / 60000);
  const m = totalMins % 60;
  const text = hours > 0 ? `resets in ${hours}h ${m}m` : `resets in ${m}m`;
  return `<div class="reset-time">${text}</div>`;
}

function buildClaudeSignInBody(errorText) {
  return `
    <p class="error-msg">${esc(errorText || 'Sign in to see live rate limits.')}</p>
    <button class="signin-btn" id="claude-signin-btn">Sign in to Claude</button>
  `;
}

// ── Claude sign-in flow ───────────────────────────────────────────────────────

document.addEventListener('click', async e => {
  if (e.target && e.target.id === 'claude-signin-btn') {
    startClaudeLogin();
  }
});

async function startClaudeLogin() {
  setBody('claude', '<p class="loading-text">Opening Edge browser — sign in to claude.ai…</p>');
  setBadge('claude', 'warn');

  const result = await window.api.claudeLogin();

  if (result && result.success) {
    await fetchAll();
  } else {
    const msg = (result && result.error) ? result.error : 'Login failed';
    setBody('claude', buildClaudeSignInBody(msg));
    setBadge('claude', 'warn');
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setBody(id, html) {
  document.getElementById(`${id}-body`).innerHTML = html;
}

function setBadge(id, state) {
  const el = document.getElementById(`${id}-status-badge`);
  el.className = 'status-badge';
  if (state === 'ok')    { el.classList.add('badge-ok');    el.textContent = 'Live'; }
  else if (state === 'warn')  { el.classList.add('badge-warn');  el.textContent = 'Auth'; }
  else if (state === 'error') { el.classList.add('badge-error'); el.textContent = 'Error'; }
  else                   { el.textContent = ''; }
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
