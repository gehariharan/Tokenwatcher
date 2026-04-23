# TokenWatcher

A native Windows system-tray app that shows your **OpenAI Codex** and **Claude** usage/limits at a glance — without WSL, without installing a CLI, without pasting a token.

It reads your existing browser session cookies (Chrome/Edge/Brave/Firefox), calls the same web-dashboard endpoints the official sites use, and renders your plan utilization and reset times in a tray popup.

Inspired by [steipete/CodexBar](https://github.com/steipete/CodexBar) (macOS), reimplemented natively for Windows in Python.

## Requirements

- Windows 10/11
- Python 3.10+ (if running from source). Tested with `scoop install python`.
- You are **already logged in** to `chatgpt.com` and/or `claude.ai` in one of: Chrome, Edge, Brave, or Firefox.

## Quick start

```powershell
cd C:\Users\gehar\Documents\Github\TokenWatcher
.\install.bat
.\run.bat
```

A tray icon will appear. Click it to see your Codex and Claude utilization. Right-click for options.

## Configuration

TokenWatcher reads `%USERPROFILE%\.tokenwatcher\config.json`. Default config is created on first run. Edit to:

- Enable/disable providers
- Choose which browser to read cookies from (`auto` tries them in priority order)
- Change the refresh interval
- Pin a specific Codex workspace / Claude organization

Example:

```json
{
  "refresh_seconds": 300,
  "browser": "auto",
  "providers": {
    "codex": { "enabled": true },
    "claude": { "enabled": true }
  }
}
```

## How it works (security notes)

- Cookies are read **locally** from your browser's encrypted cookie store (DPAPI on Windows). They are not sent anywhere except to the provider's own domain (`chatgpt.com`, `claude.ai`).
- TokenWatcher never stores credentials of its own — no keychain entries, no persisted tokens.
- The browser must not be running a conflicting profile-lock for cookie reads to succeed on some systems; if you see decryption failures, close the browser once and retry.

## Roadmap

- Package as a single `.exe` via PyInstaller (+ optional MSIX)
- Per-provider history chart in a small popup window
- Notifications when a rate window crosses a threshold
- Additional providers (Copilot, Cursor) only if trivially fetchable

## License

MIT
