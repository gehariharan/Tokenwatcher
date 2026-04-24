"""Claude provider.

Primary path: use the user's claude.ai sessionKey cookie (captured via the
one-time Edge login in edge_login.py) to hit the same private API endpoints
that power the claude.ai settings/usage page. This gives real 5h / 7d window
utilization, resets, and plan info — exactly what CodexBar shows on macOS.

Fallback path: if no cookie is stored, surface local historical activity from
stats-cache.json so the tray icon shows *something* useful, and tell the user
to sign in.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from ..auth import AuthError, AuthMissing, load_claude_auth
from ..claude_session import load_session_key
from .base import ProviderResult, ProviderStatus, RateWindow

log = logging.getLogger(__name__)

STATS_CACHE_PATH = (
    Path(os.path.expandvars(r"%USERPROFILE%")) / ".claude" / "stats-cache.json"
)

BASE = "https://claude.ai/api"
ORGS_URL = f"{BASE}/organizations"
ACCOUNT_URL = f"{BASE}/account"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 TokenWatcher/0.1"
)


class ClaudeProvider:
    name = "claude"
    on_demand_only = False

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def fetch(self) -> ProviderResult:
        plan, tier = _plan_from_credentials()

        session_key = load_session_key()
        if session_key:
            live = self._fetch_live(session_key, plan, tier)
            if live is not None:
                return live
            # Cookie exists but returned 401/403 → fall through to fallback
            # and signal that re-auth is needed.

        return self._fetch_historical_fallback(plan, tier, has_cookie=bool(session_key))

    def _fetch_live(
        self, session_key: str, plan: str | None, tier: str | None
    ) -> ProviderResult | None:
        headers = {
            "Cookie": f"sessionKey={session_key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        session = requests.Session()
        session.headers.update(headers)

        try:
            orgs = self._get(session, ORGS_URL)
        except requests.HTTPError as e:
            if e.response.status_code in (401, 403):
                return None  # signal fallback
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                error=f"claude.ai HTTP {e.response.status_code}",
            )
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                error=str(e),
            )

        org = _pick_org(orgs)
        if not org:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                error="No chat-capable organization on this account",
            )
        org_id = org["uuid"]
        org_name = org.get("name")

        email: str | None = None
        try:
            acct = self._get(session, ACCOUNT_URL)
            email = acct.get("email_address")
        except requests.RequestException:
            pass

        try:
            usage = self._get(session, f"{BASE}/organizations/{org_id}/usage")
        except requests.HTTPError as e:
            if e.response.status_code in (401, 403):
                return None
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                account_label=email,
                error=f"/usage HTTP {e.response.status_code}",
            )
        except requests.RequestException as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                account_label=email,
                error=str(e),
            )

        spend: dict | None = None
        try:
            spend = self._get(
                session, f"{BASE}/organizations/{org_id}/overage_spend_limit"
            )
        except requests.RequestException:
            pass

        return _parse_live(usage, spend, plan, tier, email or org_name)

    def _get(self, session: requests.Session, url: str) -> dict:
        r = session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _fetch_historical_fallback(
        self, plan: str | None, tier: str | None, has_cookie: bool
    ) -> ProviderResult:
        if not STATS_CACHE_PATH.exists():
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.NOT_LOGGED_IN,
                plan=_fmt_plan(plan, tier),
                error=(
                    "session expired — click Sign in to Claude"
                    if has_cookie
                    else "click Sign in to Claude to load live limits"
                ),
            )
        try:
            raw = json.loads(STATS_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return ProviderResult(
                name=self.name,
                status=ProviderStatus.ERROR,
                plan=_fmt_plan(plan, tier),
                error=f"stats-cache.json: {e}",
            )
        result = _parse_historical(raw, plan, tier)
        if has_cookie:
            # Cookie was present but live call failed — nudge re-auth even in fallback.
            result.error = "live fetch failed, showing local activity — try Sign in to Claude"
            result.status = ProviderStatus.NOT_LOGGED_IN
        return result


# ---- parsing helpers --------------------------------------------------------


def _plan_from_credentials() -> tuple[str | None, str | None]:
    try:
        auth = load_claude_auth()
        return auth.subscription_type, auth.rate_limit_tier
    except (AuthMissing, AuthError):
        return None, None


def _fmt_plan(plan: str | None, tier: str | None) -> str | None:
    parts = [p for p in (plan, tier) if p]
    return " · ".join(parts) if parts else None


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


def _parse_live(
    usage: dict,
    spend: dict | None,
    plan: str | None,
    tier: str | None,
    account: str | None,
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
        credits_balance = f"{sym}{used_cents / 100:.2f} / {sym}{limit_cents / 100:.2f}"

    return ProviderResult(
        name="claude",
        status=ProviderStatus.OK,
        plan=_fmt_plan(plan, tier),
        account_label=account,
        windows=windows,
        credits_balance=credits_balance,
    )


def _parse_historical(
    raw: dict, plan: str | None, tier: str | None
) -> ProviderResult:
    daily_activity = raw.get("dailyActivity") or []
    daily_tokens = raw.get("dailyModelTokens") or []

    today_str = date.today().isoformat()
    today_activity = _find_by_date(daily_activity, today_str)
    today_tokens = _find_by_date(daily_tokens, today_str)

    seven_day_ago = (date.today() - timedelta(days=6)).isoformat()
    week_activity = _sum_activity(daily_activity, seven_day_ago)
    week_tokens_by_model = _sum_tokens(daily_tokens, seven_day_ago)

    windows: list[RateWindow] = []

    if today_activity:
        summary = (
            f"{today_activity.get('messageCount', 0):,} msgs, "
            f"{today_activity.get('sessionCount', 0)} sessions"
        )
        windows.append(
            RateWindow(label=f"today · {summary}", used_percent=None, resets_at=None)
        )

    if today_tokens:
        tokens_map = today_tokens.get("tokensByModel") or {}
        if tokens_map:
            pretty = ", ".join(
                f"{_pretty_model(m)} {_pretty_tokens(n)}"
                for m, n in sorted(tokens_map.items(), key=lambda kv: -kv[1])[:3]
            )
            windows.append(
                RateWindow(
                    label=f"today tokens · {pretty}",
                    used_percent=None,
                    resets_at=None,
                )
            )

    if week_activity["messageCount"] > 0:
        windows.append(
            RateWindow(
                label=(
                    f"7d · {week_activity['messageCount']:,} msgs, "
                    f"{week_activity['sessionCount']} sessions"
                ),
                used_percent=None,
                resets_at=None,
            )
        )

    if week_tokens_by_model:
        total = sum(week_tokens_by_model.values())
        top = sorted(week_tokens_by_model.items(), key=lambda kv: -kv[1])[:2]
        pretty = ", ".join(f"{_pretty_model(m)} {_pretty_tokens(n)}" for m, n in top)
        windows.append(
            RateWindow(
                label=f"7d tokens · {_pretty_tokens(total)} ({pretty})",
                used_percent=None,
                resets_at=None,
            )
        )

    return ProviderResult(
        name="claude",
        status=ProviderStatus.OK,
        plan=_fmt_plan(plan, tier),
        account_label="local activity (sign in for live limits)",
        windows=windows,
        credits_balance=None,
    )


def _find_by_date(items: list, target: str) -> dict | None:
    for it in items:
        if isinstance(it, dict) and it.get("date") == target:
            return it
    return None


def _sum_activity(items: list, since: str) -> dict[str, int]:
    totals = {"messageCount": 0, "sessionCount": 0, "toolCallCount": 0}
    for it in items:
        if not isinstance(it, dict):
            continue
        d = it.get("date")
        if not isinstance(d, str) or d < since:
            continue
        for k in totals:
            totals[k] += int(it.get(k) or 0)
    return totals


def _sum_tokens(items: list, since: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        d = it.get("date")
        if not isinstance(d, str) or d < since:
            continue
        for model, n in (it.get("tokensByModel") or {}).items():
            out[model] = out.get(model, 0) + int(n or 0)
    return out


def _pretty_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _pretty_model(full: str) -> str:
    parts = full.split("-")
    for i, p in enumerate(parts):
        if p in ("opus", "sonnet", "haiku"):
            version_digits = [q for q in parts[i + 1 : i + 3] if q.isdigit()]
            if len(version_digits) == 2:
                return f"{p.capitalize()} {version_digits[0]}.{version_digits[1]}"
            return p.capitalize()
    return full
