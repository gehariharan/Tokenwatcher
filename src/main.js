'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, screen, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const { fetchCodexUsage } = require('../src-node/codex');
const { fetchClaudeUsage, runClaudeLogin } = require('../src-node/claude');
const { loadSettings, saveSettings } = require('../src-node/settings');

// Single instance lock
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

let tray = null;
let panel = null;
let closeTimer = null;
const HOVER_CLOSE_DELAY = 350;

app.whenReady().then(init);

app.on('window-all-closed', e => e.preventDefault()); // keep alive in tray

async function init() {
  app.setAppUserModelId('com.tokenwatcher.app');

  tray = new Tray(makeTrayIcon());
  tray.setToolTip('TokenWatcher');
  tray.on('mouse-enter', showPanel);
  tray.on('mouse-leave', scheduleClose);
  tray.on('click', togglePanel);          // still works for keyboard / accessibility
  tray.on('right-click', showContextMenu);

  panel = new BrowserWindow({
    width: 360,
    height: 520,
    show: false,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  panel.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  panel.on('blur', () => panel.hide());

  setupIPC();
}

function clearCloseTimer() {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
}

function scheduleClose() {
  clearCloseTimer();
  closeTimer = setTimeout(() => {
    if (panel.isVisible()) panel.hide();
  }, HOVER_CLOSE_DELAY);
}

function showPanel() {
  clearCloseTimer();
  if (panel.isVisible()) return;
  placePanel();
  panel.showInactive();                   // don't steal focus from active window
  panel.webContents.send('panel-opened');
}

function togglePanel() {
  clearCloseTimer();
  if (panel.isVisible()) {
    panel.hide();
  } else {
    placePanel();
    panel.show();
    panel.focus();
    panel.webContents.send('panel-opened');
  }
}

function placePanel() {
  const tb = tray.getBounds();
  const { workArea } = screen.getDisplayMatching(tb);
  const [w, h] = panel.getSize();

  let x = Math.round(tb.x + tb.width / 2 - w / 2);
  let y = Math.round(tb.y - h - 8);

  x = Math.max(workArea.x, Math.min(x, workArea.x + workArea.width - w));
  y = Math.max(workArea.y, Math.min(y, workArea.y + workArea.height - h));

  panel.setPosition(x, y);
}

function showContextMenu() {
  const menu = Menu.buildFromTemplate([
    { label: 'Open TokenWatcher', click: togglePanel },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]);
  tray.popUpContextMenu(menu);
}

function setupIPC() {
  ipcMain.handle('fetch-usage', async () => {
    const settings = loadSettings();
    const results = {};
    const tasks = [];

    if (settings.watch_codex) {
      tasks.push(fetchCodexUsage().then(r => { results.codex = r; }).catch(e => {
        results.codex = { status: 'error', error: e.message, windows: [] };
      }));
    }
    if (settings.watch_claude) {
      tasks.push(fetchClaudeUsage().then(r => { results.claude = r; }).catch(e => {
        results.claude = { status: 'error', error: e.message, windows: [] };
      }));
    }

    await Promise.all(tasks);
    return results;
  });

  ipcMain.handle('claude-login', async () => {
    return runClaudeLogin();
  });

  ipcMain.handle('get-settings', () => loadSettings());

  ipcMain.handle('save-settings', (_, settings) => {
    saveSettings(settings);
    return { ok: true };
  });

  ipcMain.handle('open-external', (_, url) => {
    shell.openExternal(url);
  });

  // Hover tracking from the renderer: cursor inside the panel keeps it open;
  // leaving the panel without re-entering the tray closes after a short delay.
  ipcMain.on('panel-mouse-enter', () => clearCloseTimer());
  ipcMain.on('panel-mouse-leave', () => scheduleClose());
}

// ---- Tray icon ----

function makeTrayIcon() {
  // Prefer the multi-resolution ICO so Windows picks the right size for the
  // current DPI; fall back to the 32x32 PNG if the ICO is missing.
  const candidates = [
    resolveAsset('icon.ico'),
    resolveAsset('icon-tray.png'),
    resolveAsset('icon.png'),
  ];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      const img = nativeImage.createFromPath(p);
      if (!img.isEmpty()) return img;
    }
  }
  return nativeImage.createEmpty();
}

function resolveAsset(name) {
  // In packaged builds, electron-builder copies extraResources to
  // process.resourcesPath; in dev, assets live in the repo's assets/ dir.
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'assets', name);
  }
  return path.join(__dirname, '..', 'assets', name);
}
