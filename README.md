# TokenWatcher

A native Windows system-tray app that shows your **OpenAI Codex** and **Claude Code** usage/limits at a glance.

Instead of scraping browser cookies (which modern Chrome/Edge lock down behind admin-only encryption), TokenWatcher reads the OAuth tokens the official CLIs already store on disk, then calls the same endpoints they do. No admin. No browser. No extra sign-in.

Inspired by [steipete/CodexBar](https://github.com/steipete/CodexBar) (macOS). This is a ground-up Windows reimplementation targeting only the two providers I actually use.

## Requirements

- Windows 10/11
- Python 3.10+ (if running from source; a single-EXE build comes later)
- You have used **either** of these at least once so their credentials exist on disk:
  - **OpenAI Codex CLI** — creates `%USERPROFILE%\.codex\auth.json`
  - **Claude Code CLI** — creates `%USERPROFILE%\.claude\.credentials.json`

If neither file exists, TokenWatcher will tell you to run the relevant CLI once to sign in.

## Quick start

```powershell
cd C:\Users\gehar\Documents\Github\TokenWatcher
.\install.bat
.\run.bat
```

A tray icon will appear. Click it to see your Codex and Claude utilization.

Want to see the fetch in the console?

```powershell
.\run-console.bat --once --verbose
```

## How it works

1. **Codex.** Reads `%USERPROFILE%\.codex\auth.json`, extracts `tokens.access_token` (a JWT issued by `auth.openai.com`), decodes the embedded `id_token` claims for plan/email, and calls `https://chatgpt.com/backend-api/wham/usage` with `Authorization: Bearer <access_token>`. Returns the primary (5h) and secondary (7d) rate windows plus credits balance when applicable.
2. **Claude.** Reads `%USERPROFILE%\.claude\.credentials.json`, extracts `claudeAiOauth.accessToken`, calls `GET https://claude.ai/api/organizations` to find the chat-capable org, then `GET /api/organizations/{id}/usage` to get 5-hour / 7-day utilization. Optionally reads `/overage_spend_limit` for Claude Extra budget.

TokenWatcher **does not refresh tokens** — the CLIs do that on their own use. If a token is expired, TokenWatcher will say so and tell you to run the CLI once. That's it.

## Configuration

`%USERPROFILE%\.tokenwatcher\config.json` (auto-created on first run):

```json
{
  "refresh_seconds": 300,
  "providers": {
    "codex":  { "enabled": true },
    "claude": { "enabled": true }
  }
}
```

## What this does NOT do

- Read your actual conversations, prompts, or history
- Send your tokens anywhere other than OpenAI/Anthropic's own domains
- Store or cache your credentials

TokenWatcher only ever makes read-only calls to the same endpoints the CLIs make, using credentials you already granted to those CLIs.

## Security notes

- The credential files are plaintext JSON on disk, owned by your user. TokenWatcher reads them but never copies or writes them.
- The only network traffic is `https://chatgpt.com/backend-api/wham/usage` and `https://claude.ai/api/...`.
- There is no telemetry.

## Roadmap

- Package as a single `.exe` via PyInstaller, optional auto-start
- Richer popup window (Tkinter) with progress bars instead of a text menu
- Graceful handling of rate-window resets with a subtle tray badge

## License

MIT
