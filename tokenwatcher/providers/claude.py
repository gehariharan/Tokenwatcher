from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..cookies import cookie_value, load_cookies_for_domain
from .base import ProviderResult, ProviderStatus, RateWindow

log = logging.getLogger(__name__)

CLAUDE_DOMAIN = "claude.ai"
SESSION_COOKIE_NAME = "sessionKey"

BASE = "https://claude.ai/api"
ORGS_URL = f"{BASE}/organizations"
ACCOUNT_URL = f"{BASE}/account"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 TokenWatcher/0.1"
)


class ClaudeProvider:
    name = "claude"

    def __init__(self, browser: str = "auto", timeout: float = 20.0) -> None:
        self.browser = browser
        self.timeout = timeout

    def fetch(self) -> ProviderResult:
        jar = load_cookies_for_domain(CLAUDE_DOMAIN, browser=self.browser)
        if jar is None or cookie_value(jar, SESSION_COOKIE_NAME, CLAUDE_DOMAIN) is None:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                error="No claude.ai sessionKey cookie — sign in to claude.ai",
            )

        session = requests.Session()
        session.cookies = jar  # type: ignore[assignment]
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

        try:
            orgs = self._get(session, ORGS_URL)
            org = _pick_org(orgs)
            if not org:
                return ProviderResult(
                    name=self.name,
                    status=ProviderStatus.ERROR,
                    error="No chat-capable organization found on this account",
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
            spend = None
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
                    error=f"claude.ai returned {code} — session likely expired",
                )
            return ProviderResult(
                name=self.name, status=ProviderStatus.ERROR, error=f"HTTP {code}"
            )
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.ERROR, error=str(e)
            )

        return self._parse(usage, spend, org_name, account_email)

    def _get(self, session: requests.Session, url: str) -> dict:
        r = session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse(
        usage: dict,
        spend: dict | None,
        org_name: str | None,
        email: str | None,
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
            account_label=email or org_name,
            windows=windows,
            credits_balance=credits_balance,
        )


def _pick_org(orgs: object) -> dict | None:
    if not isinstance(orgs, list):
        return None
    for o in orgs:
        caps = o.get("capabilities") or []
        if "chat" in caps:
            return o
    return orgs[0] if orgs else None


def _parse_iso(s: object) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
