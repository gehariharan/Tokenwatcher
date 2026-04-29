'use strict';

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

function getSidecar() {
  // Packaged app: sidecar is next to app resources
  if (require('electron').app.isPackaged) {
    return { cmd: path.join(process.resourcesPath, 'claude_fetch.exe'), args: [] };
  }
  // Dev: prefer pre-built exe in resources/, fall back to running Python directly
  const devExe = path.join(__dirname, '../resources/claude_fetch.exe');
  if (fs.existsSync(devExe)) {
    return { cmd: devExe, args: [] };
  }
  const script = path.join(__dirname, '../sidecar/claude_fetch.py');
  const py = findPython();
  return { cmd: py, args: [script] };
}

function findPython() {
  const repoRoot = path.join(__dirname, '..');
  // Prefer the project venv — that's where curl_cffi / websocket-client live in dev
  const candidates = [
    path.join(repoRoot, '.venv', 'Scripts', 'python.exe'),
    path.join(repoRoot, 'venv', 'Scripts', 'python.exe'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return 'python';
}

function runSidecar(sidecarArgs, timeoutMs = 30_000) {
  return new Promise((resolve, reject) => {
    const { cmd, args } = getSidecar();
    const proc = spawn(cmd, [...args, ...sidecarArgs], { windowsHide: true });

    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', d => { stdout += d; });
    proc.stderr.on('data', d => { stderr += d; });

    const timer = setTimeout(() => {
      proc.kill();
      reject(new Error(`sidecar timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);

    proc.on('close', code => {
      clearTimeout(timer);
      const trimmed = stdout.trim();
      if (!trimmed) {
        const tail = stderr.trim().split('\n').slice(-3).join(' | ').slice(0, 400);
        reject(new Error(`sidecar exited ${code}. ${tail || 'no stderr'}`));
        return;
      }
      try {
        resolve(JSON.parse(trimmed));
      } catch {
        reject(new Error(`sidecar output not JSON (code ${code}): ${trimmed.slice(0, 200)}`));
      }
    });

    proc.on('error', err => {
      clearTimeout(timer);
      reject(new Error(`Failed to spawn sidecar (${err.code || 'ERR'}): ${err.message}`));
    });
  });
}

async function fetchClaudeUsage() {
  try {
    return await runSidecar(['--fetch'], 30_000);
  } catch (err) {
    return { status: 'error', error: err.message, windows: [] };
  }
}

async function runClaudeLogin() {
  try {
    return await runSidecar(['--login', '--timeout', '600'], 620_000);
  } catch (err) {
    return { success: false, error: err.message };
  }
}

module.exports = { fetchClaudeUsage, runClaudeLogin };
