from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..auth import AuthError, AuthMissing, load_codex_auth
from .base import ProviderResult, ProviderStatus, RateWindow

log = logging.getLogger(__name__)

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

USER_AGENT = "TokenWatcher/0.1 (+https://github.com/) compatible"


class CodexProvider:
    name = "codex"
    on_demand_only = False

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def fetch(self) -> ProviderResult:
        try:
            auth = load_codex_auth()
        except AuthMissing as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.NOT_LOGGED_IN, error=str(e)
            )
        except AuthError as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.ERROR, error=str(e)
            )

        claims = auth.id_token_claims
        email = claims.get("email")
        plan = claims.get("chatgpt_plan_type")
        account_id = auth.account_id or claims.get("chatgpt_account_id")

        headers = {
            "Authorization": f"Bearer {auth.access_token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        try:
            r = requests.get(USAGE_URL, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=plan,
                account_label=email,
                error=f"request failed: {e}",
            )

        if r.status_code in (401, 403):
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                plan=plan,
                account_label=email,
                error="Access token rejected — run `codex` once to refresh",
            )
        if r.status_code >= 400:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=plan,
                account_label=email,
                error=f"wham/usage HTTP {r.status_code}",
            )

        try:
            data = r.json()
        except ValueError as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=plan,
                account_label=email,
                error=f"invalid JSON: {e}",
            )

        return self._parse(data, plan, email)

    @staticmethod
    def _parse(data: dict, plan: str | None, email: str | None) -> ProviderResult:
        windows: list[RateWindow] = []
        rate_limit = data.get("rate_limit") or {}
        for key, label in (("primary_window", "5h"), ("secondary_window", "7d")):
            w = rate_limit.get(key)
            if not isinstance(w, dict):
                continue
            pct = w.get("used_percent")
            reset = w.get("reset_at")
            windows.append(
                RateWindow(
                    label=label,
                    used_percent=float(pct) if pct is not None else None,
                    resets_at=_from_unix(reset),
                )
            )

        credits_balance: str | None = None
        credits = data.get("credits") or {}
        if credits.get("has_credits"):
            if credits.get("unlimited"):
                credits_balance = "unlimited credits"
            elif credits.get("balance") is not None:
                credits_balance = f"credits: {credits['balance']}"

        return ProviderResult(
            name="codex",
            status=ProviderStatus.OK,
            plan=plan or data.get("plan_type"),
            account_label=email,
            windows=windows,
            credits_balance=credits_balance,
        )


def _from_unix(ts: object) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
