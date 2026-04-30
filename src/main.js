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
let pinned = false;             // true = opened via click; auto-close timers ignored
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

  // Any time the panel actually has focus, treat it as pinned. This covers
  // both tray-click opens and clicks landing inside the rendered UI (e.g.
  // pressing Refresh after a hover-open promotes it to a sticky session).
  panel.on('focus', () => { pinned = true; });
  panel.on('blur', () => {
    panel.hide();
    pinned = false;
  });

  setupIPC();
  setupAutoUpdate();
}

function setupAutoUpdate() {
  // Only check for updates in installed builds — dev sessions running via
  // `npm start` would otherwise try to "update" themselves to the latest
  // release and fail noisily.
  if (!app.isPackaged) return;

  const { autoUpdater } = require('electron-updater');
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  const check = () => autoUpdater.checkForUpdatesAndNotify().catch(err => {
    console.warn('autoUpdater check failed:', err && err.message);
  });

  check();                                            // on startup
  setInterval(check, 6 * 60 * 60 * 1000);             // every 6h while running
}

function clearCloseTimer() {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
}

function scheduleClose() {
  if (pinned) return;                    // pinned panels stay until outside-click
  clearCloseTimer();
  closeTimer = setTimeout(() => {
    if (panel.isVisible() && !pinned) panel.hide();
  }, HOVER_CLOSE_DELAY);
}

function showPanel() {
  // Tray hover. Transient: closes when the cursor leaves both tray and panel.
  clearCloseTimer();
  if (panel.isVisible()) return;
  pinned = false;
  placePanel();
  panel.showInactive();                   // don't steal focus from active window
  panel.webContents.send('panel-opened');
}

function togglePanel() {
  // Tray click. Either dismiss a pinned panel, or open+pin one.
  clearCloseTimer();
  if (panel.isVisible() && pinned) {
    panel.hide();
    return;
  }
  if (!panel.isVisible()) placePanel();
  panel.show();
  panel.focus();                          // triggers focus event → pinned=true
  panel.webContents.send('panel-opened');
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
