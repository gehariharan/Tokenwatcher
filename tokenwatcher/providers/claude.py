from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..auth import AuthError, AuthMissing, load_claude_auth
from .base import ProviderResult, ProviderStatus, RateWindow

log = logging.getLogger(__name__)

BASE = "https://claude.ai/api"
ORGS_URL = f"{BASE}/organizations"
ACCOUNT_URL = f"{BASE}/account"

USER_AGENT = "TokenWatcher/0.1 (+https://github.com/) compatible"


class ClaudeProvider:
    name = "claude"
    on_demand_only = True

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def fetch(self) -> ProviderResult:
        try:
            auth = load_claude_auth()
        except AuthMissing as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.NOT_LOGGED_IN, error=str(e)
            )
        except AuthError as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.ERROR, error=str(e)
            )

        headers = {
            "Authorization": f"Bearer {auth.access_token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        session = requests.Session()
        session.headers.update(headers)

        try:
            orgs = self._get(session, ORGS_URL)
            org = _pick_org(orgs)
            if not org:
                return ProviderResult(
                    name=self.name,
                    status=ProviderStatus.ERROR,
                    plan=auth.subscription_type,
                    error="No chat-capable organization on this account",
                )
            org_id = org["uuid"]
            org_name = org.get("name")

            account_email: str | None = None
            try:
                acct = self._get(session, ACCOUNT_URL)
                account_email = acct.get("email_address")
            except requests.RequestException:
                pass

            usage = self._get(session, f"{BASE}/organizations/{org_id}/usage")
            spend: dict | None = None
            try:
                spend = self._get(
                    session, f"{BASE}/organizations/{org_id}/overage_spend_limit"
                )
            except requests.RequestException:
                pass
        except requests.HTTPError as e:
            code = e.response.status_code
            if code in (401, 403):
                return ProviderResult(
                    name=self.name,
                    status=ProviderStatus.NOT_LOGGED_IN,
                    plan=auth.subscription_type,
                    error=f"claude.ai returned {code} — run Claude Code once to refresh",
                )
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=auth.subscription_type,
                error=f"HTTP {code}",
            )
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=auth.subscription_type,
                error=str(e),
            )

        return self._parse(usage, spend, auth.subscription_type, account_email, org_name)

    def _get(self, session: requests.Session, url: str) -> dict:
        r = session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse(
        usage: dict,
        spend: dict | None,
        plan: str | None,
        email: str | None,
        org_name: str | None,
    ) -> ProviderResult:
        windows: list[RateWindow] = []
        for key, label in (
            ("five_hour", "5h"),
            ("seven_day", "7d"),
            ("seven_day_sonnet", "7d sonnet"),
            ("seven_day_opus", "7d opus"),
        ):
            w = usage.get(key)
            if not isinstance(w, dict):
                continue
            util = w.get("utilization")
            windows.append(
                RateWindow(
                    label=label,
                    used_percent=float(util) if util is not None else None,
                    resets_at=_parse_iso(w.get("resets_at")),
                )
            )

        credits_balance: str | None = None
        if isinstance(spend, dict) and spend.get("is_enabled"):
            limit_cents = spend.get("monthly_credit_limit") or 0
            used_cents = spend.get("used_credits") or 0
            cur = spend.get("currency") or "USD"
            sym = "$" if cur == "USD" else f"{cur} "
            credits_balance = (
                f"{sym}{used_cents / 100:.2f} / {sym}{limit_cents / 100:.2f}"
            )

        return ProviderResult(
            name="claude",
            status=ProviderStatus.OK,
            plan=plan,
            account_label=email or org_name,
            windows=windows,
            credits_balance=credits_balance,
        )


def _pick_org(orgs: object) -> dict | None:
    if not isinstance(orgs, list) or not orgs:
        return None
    for o in orgs:
        caps = o.get("capabilities") or []
        if "chat" in caps:
            return o
    return orgs[0]


def _parse_iso(s: object) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
