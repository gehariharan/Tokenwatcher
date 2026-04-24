# TokenWatcher

A native Windows system-tray app that shows your **OpenAI Codex** and **Claude** usage/limits at a glance.

- **Codex:** reads the OpenAI Codex CLI's OAuth token from `~/.codex/auth.json` and calls the same private endpoint the CLI uses (`chatgpt.com/backend-api/wham/usage`) for live 5h / 7d window utilization.
- **Claude:** one-time sign-in through an embedded Microsoft Edge window establishes a claude.ai session; the cookie is DPAPI-encrypted and stored locally. TokenWatcher then hits claude.ai's real usage API for live window data. Falls back to historical activity (from Claude Code's `stats-cache.json`) if you haven't signed in yet.

Inspired by [steipete/CodexBar](https://github.com/steipete/CodexBar) (macOS), reimplemented from scratch for Windows to avoid WSL, browser-cookie scraping, and admin requirements.

## Requirements

- Windows 10/11 with Microsoft Edge installed (ships on Windows by default)
- Python 3.10+ (for running from source; single-EXE packaging via PyInstaller planned)
- At least one of these is useful for Codex / Claude display:
  - **OpenAI Codex CLI** has been used at least once (creates `~/.codex/auth.json`)
  - **Claude Code CLI** has been used at least once (for historical fallback); plus a claude.ai sign-in inside TokenWatcher (for live limits)

## Quick start

```powershell
cd C:\Users\gehar\Documents\Github\TokenWatcher
.\install.bat
.\run.bat
```

A tray icon appears. Click it to see Codex and Claude data. To enable live Claude window data:

- Click the tray → **Sign in to Claude…**
- Edge opens to `claude.ai/login` in app mode
- Sign in once; TokenWatcher captures the session cookie and closes the window automatically
- Next refresh shows live 5h / 7d utilization

## How Claude sign-in works

- TokenWatcher launches `msedge.exe` with a **dedicated user-data-dir** under `~/.tokenwatcher/edge-profile/` (does NOT touch your main Edge profile) and `--remote-debugging-port=<random>`.
- After you sign in, TokenWatcher reads the `sessionKey` cookie via Edge's DevTools Protocol (local WebSocket, never leaves your machine).
- The cookie is DPAPI-encrypted at `~/.tokenwatcher/claude_session.dat` — only your current Windows user can decrypt it.
- The cookie is only ever sent to `claude.ai` domains.

## Configuration

`%USERPROFILE%\.tokenwatcher\config.json`:

```json
{
  "refresh_seconds": 300,
  "providers": {
    "codex":  { "enabled": true },
    "claude": { "enabled": true }
  }
}
```

## CLI usage

```powershell
.\run-console.bat --once                 # fetch everything once, print, exit
.\run-console.bat --once --json          # JSON output
.\run-console.bat --claude-login         # launch Edge to sign into claude.ai
```

## What TokenWatcher does NOT do

- No browser-cookie scraping from your main Chrome/Edge profile (Chrome/Edge v127+ cookies are locked behind app-bound encryption that admin can't bypass — we avoid that whole class of problem).
- No telemetry.
- No storage of OpenAI / Anthropic credentials beyond the DPAPI-encrypted claude.ai session cookie.
- No sending data anywhere except to `chatgpt.com` and `claude.ai` themselves.

## License

MIT
