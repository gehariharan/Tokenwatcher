'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const AUTH_PATH = path.join(os.homedir(), '.codex', 'auth.json');
const USAGE_URL = 'https://chatgpt.com/backend-api/wham/usage';

function decodeJwtClaims(token) {
  if (!token) return {};
  try {
    const [, payload] = token.split('.');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    return JSON.parse(Buffer.from(padded, 'base64url').toString('utf8'));
  } catch {
    return {};
  }
}

async function fetchCodexUsage() {
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(AUTH_PATH, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') {
      return {
        status: 'not_logged_in',
        error: 'No auth.json found — run the codex CLI once to sign in',
        windows: [],
      };
    }
    return { status: 'error', error: `Cannot read auth.json: ${err.message}`, windows: [] };
  }

  const tokens = raw.tokens || {};
  const accessToken = tokens.access_token;
  if (!accessToken) {
    return { status: 'error', error: 'auth.json is missing tokens.access_token', windows: [] };
  }

  const claims = decodeJwtClaims(tokens.id_token);
  const email = claims.email || null;
  const plan = claims.chatgpt_plan_type || null;
  const accountId = tokens.account_id || claims.chatgpt_account_id || null;

  const headers = {
    Authorization: `Bearer ${accessToken}`,
    Accept: 'application/json',
    'User-Agent': 'TokenWatcher/0.1',
  };
  if (accountId) headers['ChatGPT-Account-Id'] = accountId;

  let resp;
  try {
    resp = await fetch(USAGE_URL, { headers });
  } catch (err) {
    return { status: 'error', error: `Network error: ${err.message}`, plan, account_label: email, windows: [] };
  }

  if (resp.status === 401 || resp.status === 403) {
    return {
      status: 'not_logged_in',
      error: 'Access token rejected — run `codex` once to refresh',
      plan,
      account_label: email,
      windows: [],
    };
  }

  if (!resp.ok) {
    return { status: 'error', error: `HTTP ${resp.status}`, plan, account_label: email, windows: [] };
  }

  let data;
  try {
    data = await resp.json();
  } catch {
    return { status: 'error', error: 'Invalid JSON response', plan, account_label: email, windows: [] };
  }

  return parseCodexData(data, plan, email);
}

function parseCodexData(data, plan, email) {
  const windows = [];
  const rl = data.rate_limit || {};

  for (const [key, label] of [['primary_window', '5h'], ['secondary_window', '7d']]) {
    const w = rl[key];
    if (!w || typeof w !== 'object') continue;
    windows.push({
      label,
      used_percent: w.used_percent != null ? parseFloat(w.used_percent) : null,
      resets_at: w.reset_at ? new Date(w.reset_at * 1000).toISOString() : null,
    });
  }

  let credits_balance = null;
  const cr = data.credits || {};
  if (cr.has_credits) {
    credits_balance = cr.unlimited ? 'unlimited credits'
      : cr.balance != null ? `credits: ${cr.balance}` : null;
  }

  return {
    status: 'ok',
    plan: plan || data.plan_type || null,
    account_label: email,
    windows,
    credits_balance,
    error: null,
  };
}

module.exports = { fetchCodexUsage };
