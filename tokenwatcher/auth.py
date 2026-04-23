"""Read OAuth credentials the Codex and Claude Code CLIs persist on disk.

This module does not refresh tokens. Both CLIs refresh their own tokens on use,
so the expected workflow is: actively using the CLI keeps its credential file
fresh, and TokenWatcher is a read-only observer.

If tokens are expired, TokenWatcher reports a clear error and suggests running
the relevant CLI once to refresh.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CODEX_AUTH_PATH = Path(os.path.expandvars(r"%USERPROFILE%")) / ".codex" / "auth.json"
CLAUDE_CREDS_PATH = (
    Path(os.path.expandvars(r"%USERPROFILE%")) / ".claude" / ".credentials.json"
)


@dataclass
class CodexAuth:
    access_token: str
    id_token: str | None
    refresh_token: str | None
    account_id: str | None
    last_refresh: datetime | None
    openai_api_key: str | None

    @property
    def id_token_claims(self) -> dict:
        if not self.id_token:
            return {}
        return _decode_jwt_claims(self.id_token)


@dataclass
class ClaudeAuth:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    subscription_type: str | None
    rate_limit_tier: str | None
    scopes: list[str]

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at


class AuthError(Exception):
    pass


class AuthMissing(AuthError):
    """Raised when the credential file is absent."""


def load_codex_auth(path: Path = CODEX_AUTH_PATH) -> CodexAuth:
    if not path.exists():
        raise AuthMissing(
            f"{path} not found. Run the `codex` CLI once to sign in."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise AuthError(f"Cannot read {path}: {e}") from e

    tokens = raw.get("tokens") or {}
    access = tokens.get("access_token")
    if not access:
        raise AuthError(f"{path} is missing tokens.access_token")

    last_refresh_raw = raw.get("last_refresh")
    last_refresh: datetime | None = None
    if isinstance(last_refresh_raw, str):
        try:
            last_refresh = datetime.fromisoformat(
                last_refresh_raw.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            pass

    return CodexAuth(
        access_token=access,
        id_token=tokens.get("id_token"),
        refresh_token=tokens.get("refresh_token"),
        account_id=tokens.get("account_id"),
        last_refresh=last_refresh,
        openai_api_key=raw.get("OPENAI_API_KEY"),
    )


def load_claude_auth(path: Path = CLAUDE_CREDS_PATH) -> ClaudeAuth:
    if not path.exists():
        raise AuthMissing(
            f"{path} not found. Run `claude /login` once to sign in."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise AuthError(f"Cannot read {path}: {e}") from e

    oauth = raw.get("claudeAiOauth") or {}
    access = oauth.get("accessToken")
    if not access:
        raise AuthError(f"{path} is missing claudeAiOauth.accessToken")

    exp_ms = oauth.get("expiresAt")
    expires_at: datetime | None = None
    if isinstance(exp_ms, (int, float)):
        try:
            expires_at = datetime.fromtimestamp(exp_ms / 1000, tz=timezone.utc)
        except (OSError, ValueError):
            pass

    scopes = oauth.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []

    return ClaudeAuth(
        access_token=access,
        refresh_token=oauth.get("refreshToken"),
        expires_at=expires_at,
        subscription_type=oauth.get("subscriptionType"),
        rate_limit_tier=oauth.get("rateLimitTier"),
        scopes=scopes,
    )


def _decode_jwt_claims(token: str) -> dict:
    try:
        _, payload, _ = token.split(".")
    except ValueError:
        return {}
    padded = payload + "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return {}
