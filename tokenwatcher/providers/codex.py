from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..cookies import cookie_value, load_cookies_for_domain
from .base import ProviderResult, ProviderStatus, RateWindow

log = logging.getLogger(__name__)

CHATGPT_DOMAIN = "chatgpt.com"
SESSION_URL = "https://chatgpt.com/api/auth/session"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 TokenWatcher/0.1"
)


class CodexProvider:
    name = "codex"

    def __init__(self, browser: str = "auto", timeout: float = 20.0) -> None:
        self.browser = browser
        self.timeout = timeout

    def fetch(self) -> ProviderResult:
        jar = load_cookies_for_domain(CHATGPT_DOMAIN, browser=self.browser)
        if jar is None:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                error="No chatgpt.com cookies found in any supported browser",
            )
        if cookie_value(jar, SESSION_COOKIE_NAME, CHATGPT_DOMAIN) is None:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                error=f"Missing cookie {SESSION_COOKIE_NAME} — sign in to chatgpt.com",
            )

        session = requests.Session()
        session.cookies = jar  # type: ignore[assignment]
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

        try:
            access_token, email = self._exchange_session(session)
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name, status=ProviderStatus.ERROR, error=f"session fetch: {e}"
            )
        if not access_token:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                error="Session cookie present but no accessToken returned (expired?)",
            )

        try:
            data = self._fetch_usage(session, access_token)
        except requests.HTTPError as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                account_label=email,
                error=f"wham/usage {e.response.status_code}",
            )
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                account_label=email,
                error=f"wham/usage: {e}",
            )

        return self._parse(data, email)

    def _exchange_session(self, session: requests.Session) -> tuple[str | None, str | None]:
        r = session.get(SESSION_URL, timeout=self.timeout)
        r.raise_for_status()
        if not r.text.strip():
            return None, None
        j = r.json()
        token = j.get("accessToken")
        user = j.get("user") or {}
        email = user.get("email")
        return token, email

    def _fetch_usage(self, session: requests.Session, access_token: str) -> dict:
        r = session.get(
            USAGE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse(data: dict, email: str | None) -> ProviderResult:
        plan = data.get("plan_type")
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
            else:
                bal = credits.get("balance")
                if bal is not None:
                    credits_balance = f"credits: {bal}"
        return ProviderResult(
            name="codex",
            status=ProviderStatus.OK,
            plan=plan,
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
