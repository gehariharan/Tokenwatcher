#!/usr/bin/env python3
"""Standalone Claude usage fetcher / session manager.

Usage:
  claude_fetch.py --fetch              Print JSON usage to stdout
  claude_fetch.py --login [--timeout N]  Run Edge CDP login, save sessionKey
  claude_fetch.py --clear              Delete stored sessionKey
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import time
from ctypes import POINTER, byref, c_char, c_void_p, wintypes
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(os.path.expandvars(r"%USERPROFILE%")) / ".tokenwatcher"
SESSION_PATH = CONFIG_DIR / "claude_session.dat"
STATS_CACHE_PATH = Path(os.path.expandvars(r"%USERPROFILE%")) / ".claude" / "stats-cache.json"
CLAUDE_CREDS_PATH = Path(os.path.expandvars(r"%USERPROFILE%")) / ".claude" / ".credentials.json"
EDGE_PROFILE_DIR = CONFIG_DIR / "edge-profile"

BASE_URL = "https://claude.ai/api"
CLAUDE_DOMAIN = "claude.ai"


# ── DPAPI ─────────────────────────────────────────────────────────────────────

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32

_crypt32.CryptProtectData.argtypes = [
    POINTER(_DataBlob), wintypes.LPCWSTR, POINTER(_DataBlob),
    c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL

_crypt32.CryptUnprotectData.argtypes = [
    POINTER(_DataBlob), POINTER(wintypes.LPWSTR), POINTER(_DataBlob),
    c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL

_kernel32.LocalFree.argtypes = [c_void_p]
_kernel32.LocalFree.restype = c_void_p


def _make_blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    b = _DataBlob()
    b.cbData = len(data)
    b.pbData = ctypes.cast(buf, POINTER(c_char))
    b._buf = buf
    return b


def _read_blob(b: _DataBlob) -> bytes:
    if not b.pbData:
        return b""
    out = ctypes.string_at(b.pbData, b.cbData)
    _kernel32.LocalFree(b.pbData)
    return out


def _dpapi_protect(data: bytes) -> bytes:
    in_b, out_b = _make_blob(data), _DataBlob()
    if not _crypt32.CryptProtectData(byref(in_b), None, None, None, None, 0, byref(out_b)):
        raise OSError(f"CryptProtectData failed ({ctypes.GetLastError()})")
    return _read_blob(out_b)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_b, out_b = _make_blob(data), _DataBlob()
    if not _crypt32.CryptUnprotectData(byref(in_b), None, None, None, None, 0, byref(out_b)):
        raise OSError(f"CryptUnprotectData failed ({ctypes.GetLastError()})")
    return _read_blob(out_b)


def save_session_key(value: str) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_bytes(_dpapi_protect(value.encode("utf-8")))


def load_session_key() -> str | None:
    if not SESSION_PATH.exists():
        return None
    try:
        return _dpapi_unprotect(SESSION_PATH.read_bytes()).decode("utf-8")
    except OSError:
        return None


def clear_session_key() -> None:
    try:
        SESSION_PATH.unlink()
    except FileNotFoundError:
        pass


# ── Edge CDP login ─────────────────────────────────────────────────────────────

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    from shutil import which
    hit = which("msedge")
    if hit:
        return hit
    raise RuntimeError("Microsoft Edge not found. Install it from https://www.microsoft.com/edge")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_login(timeout_seconds: int = 600) -> dict:
    import requests as _req
    import websocket as _ws

    EDGE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    edge = _find_edge()

    args = [
        edge,
        f"--remote-debugging-port={port}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
        f"--user-data-dir={EDGE_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--app=https://claude.ai/login",
    ]
    proc = subprocess.Popen(args)
    try:
        _wait_port(port, _req, timeout=15)
        session_key = _poll_session_key(port, timeout_seconds, _req, _ws)
        if session_key is None:
            return {"success": False, "error": "Timed out waiting for claude.ai sign-in. Try again."}
        save_session_key(session_key)
        return {"success": True, "error": None}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        _close_edge(port, proc, _req, _ws)


def _wait_port(port, _req, timeout):
    start = time.time()
    while time.time() - start < timeout:
        try:
            _req.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"Edge did not expose debug port {port} within {timeout}s")


def _poll_session_key(port, timeout_s, _req, _ws) -> str | None:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            targets = _req.get(f"http://127.0.0.1:{port}/json", timeout=2).json()
        except Exception:
            time.sleep(1)
            continue

        claude_targets = [
            t for t in targets
            if isinstance(t, dict)
            and t.get("type") in ("page", "webview", "app")
            and CLAUDE_DOMAIN in (t.get("url") or "")
            and t.get("webSocketDebuggerUrl")
        ]
        if not claude_targets:
            claude_targets = [
                t for t in targets
                if isinstance(t, dict) and t.get("type") == "page" and t.get("webSocketDebuggerUrl")
            ]

        for target in claude_targets:
            try:
                cookies = _cdp_cookies(target["webSocketDebuggerUrl"], _ws)
            except Exception:
                continue
            sk = cookies.get("sessionKey")
            if sk:
                return sk
        time.sleep(2)
    return None


def _cdp_cookies(ws_url: str, _ws) -> dict[str, str]:
    ws = _ws.create_connection(ws_url, timeout=8)
    ws.settimeout(8)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        result = None
        for _ in range(10):
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            if msg.get("id") == 1:
                result = msg.get("result") or {}
                break
    finally:
        try:
            ws.close()
        except Exception:
            pass
    if result is None:
        return {}
    out: dict[str, str] = {}
    for c in result.get("cookies", []) or []:
        domain = (c.get("domain") or "").lstrip(".")
        if domain.endswith(CLAUDE_DOMAIN) and c.get("name"):
            out[c["name"]] = c.get("value", "")
    return out


def _close_edge(port, proc, _req, _ws):
    try:
        ver = _req.get(f"http://127.0.0.1:{port}/json/version", timeout=2).json()
        bws = ver.get("webSocketDebuggerUrl")
    except Exception:
        bws = None

    if bws:
        try:
            ws = _ws.create_connection(bws, timeout=3)
            try:
                ws.send(json.dumps({"id": 99, "method": "Browser.close"}))
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        proc.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=5)
    except Exception:
        pass


# ── Claude plan info from .credentials.json ───────────────────────────────────

def _load_plan_info() -> tuple[str | None, str | None]:
    try:
        raw = json.loads(CLAUDE_CREDS_PATH.read_text(encoding="utf-8"))
        oauth = raw.get("claudeAiOauth") or {}
        return oauth.get("subscriptionType"), oauth.get("rateLimitTier")
    except Exception:
        return None, None


def _fmt_plan(plan, tier) -> str | None:
    parts = [p for p in (plan, tier) if p]
    return " · ".join(parts) if parts else None


# ── HTTP fetch via curl_cffi ───────────────────────────────────────────────────

def do_fetch() -> dict:
    plan, tier = _load_plan_info()

    session_key = load_session_key()
    if session_key:
        live = _fetch_live(session_key, plan, tier)
        if live is not None:
            return live

    return _fetch_historical(plan, tier, has_cookie=bool(session_key))


def _fetch_live(session_key: str, plan, tier) -> dict | None:
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return None

    cookies = {"sessionKey": session_key}
    headers = {"Accept": "application/json"}

    def get(url):
        r = cr.get(url, headers=headers, cookies=cookies,
                   impersonate="chrome131", timeout=20)
        r.raise_for_status()
        return r.json()

    try:
        orgs = get(f"{BASE_URL}/organizations")
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (401, 403):
            return None
        return _err(str(e), plan, tier)

    org = _pick_org(orgs)
    if not org:
        return _err("No chat-capable org on this account", plan, tier)

    org_id = org["uuid"]
    email = None
    try:
        acct = get(f"{BASE_URL}/account")
        email = acct.get("email_address")
    except Exception:
        pass

    try:
        usage = get(f"{BASE_URL}/organizations/{org_id}/usage")
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (401, 403):
            return None
        return _err(str(e), plan, tier)

    spend = None
    try:
        spend = get(f"{BASE_URL}/organizations/{org_id}/overage_spend_limit")
    except Exception:
        pass

    return _parse_live(usage, spend, plan, tier, email or org.get("name"))


def _pick_org(orgs) -> dict | None:
    if not isinstance(orgs, list) or not orgs:
        return None
    for o in orgs:
        if "chat" in (o.get("capabilities") or []):
            return o
    return orgs[0]


def _parse_iso(s) -> str | None:
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def _parse_live(usage, spend, plan, tier, account) -> dict:
    windows = []
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
        windows.append({
            "label": label,
            "used_percent": float(util) if util is not None else None,
            "resets_at": _parse_iso(w.get("resets_at")),
        })

    credits_balance = None
    if isinstance(spend, dict) and spend.get("is_enabled"):
        limit_c = spend.get("monthly_credit_limit") or 0
        used_c  = spend.get("used_credits") or 0
        cur = spend.get("currency") or "USD"
        sym = "$" if cur == "USD" else f"{cur} "
        credits_balance = f"{sym}{used_c/100:.2f} / {sym}{limit_c/100:.2f}"

    return {
        "status": "ok",
        "plan": _fmt_plan(plan, tier),
        "account_label": account,
        "windows": windows,
        "credits_balance": credits_balance,
        "error": None,
    }


def _fetch_historical(plan, tier, has_cookie: bool) -> dict:
    if not STATS_CACHE_PATH.exists():
        return {
            "status": "not_logged_in",
            "plan": _fmt_plan(plan, tier),
            "account_label": None,
            "windows": [],
            "credits_balance": None,
            "error": (
                "Session expired — click Sign in to Claude"
                if has_cookie
                else "Click Sign in to Claude to load live limits"
            ),
        }

    try:
        raw = json.loads(STATS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return _err(f"stats-cache.json: {e}", plan, tier)

    return _parse_historical(raw, plan, tier, has_cookie)


def _parse_historical(raw, plan, tier, has_cookie) -> dict:
    daily_activity = raw.get("dailyActivity") or []
    daily_tokens   = raw.get("dailyModelTokens") or []

    today_str      = date.today().isoformat()
    seven_ago      = (date.today() - timedelta(days=6)).isoformat()

    today_act   = _by_date(daily_activity, today_str)
    today_tok   = _by_date(daily_tokens, today_str)
    week_act    = _sum_activity(daily_activity, seven_ago)
    week_tokens = _sum_tokens(daily_tokens, seven_ago)

    windows = []

    if today_act:
        windows.append({
            "label": f"today · {today_act.get('messageCount',0):,} msgs, {today_act.get('sessionCount',0)} sessions",
            "used_percent": None, "resets_at": None,
        })

    if today_tok:
        tok_map = today_tok.get("tokensByModel") or {}
        if tok_map:
            pretty = ", ".join(
                f"{_pretty_model(m)} {_pretty_tokens(n)}"
                for m, n in sorted(tok_map.items(), key=lambda kv: -kv[1])[:3]
            )
            windows.append({"label": f"today tokens · {pretty}", "used_percent": None, "resets_at": None})

    if week_act["messageCount"] > 0:
        windows.append({
            "label": f"7d · {week_act['messageCount']:,} msgs, {week_act['sessionCount']} sessions",
            "used_percent": None, "resets_at": None,
        })

    if week_tokens:
        total = sum(week_tokens.values())
        top = sorted(week_tokens.items(), key=lambda kv: -kv[1])[:2]
        pretty = ", ".join(f"{_pretty_model(m)} {_pretty_tokens(n)}" for m, n in top)
        windows.append({
            "label": f"7d tokens · {_pretty_tokens(total)} ({pretty})",
            "used_percent": None, "resets_at": None,
        })

    err = None
    status = "ok"
    account_label = "local activity (sign in for live limits)"
    if has_cookie:
        err = "Live fetch failed — try Sign in to Claude"
        status = "not_logged_in"

    return {
        "status": status,
        "plan": _fmt_plan(plan, tier),
        "account_label": account_label,
        "windows": windows,
        "credits_balance": None,
        "error": err,
    }


def _by_date(items, target):
    for it in items:
        if isinstance(it, dict) and it.get("date") == target:
            return it
    return None


def _sum_activity(items, since):
    t = {"messageCount": 0, "sessionCount": 0}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("date"), str) and it["date"] >= since:
            for k in t:
                t[k] += int(it.get(k) or 0)
    return t


def _sum_tokens(items, since):
    out: dict[str, int] = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("date"), str) and it["date"] >= since:
            for m, n in (it.get("tokensByModel") or {}).items():
                out[m] = out.get(m, 0) + int(n or 0)
    return out


def _pretty_tokens(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}k"
    return str(n)


def _pretty_model(full):
    parts = full.split("-")
    for i, p in enumerate(parts):
        if p in ("opus", "sonnet", "haiku"):
            digits = [q for q in parts[i+1:i+3] if q.isdigit()]
            if len(digits) == 2:
                return f"{p.capitalize()} {digits[0]}.{digits[1]}"
            return p.capitalize()
    return full


def _err(msg, plan, tier) -> dict:
    return {
        "status": "error",
        "plan": _fmt_plan(plan, tier),
        "account_label": None,
        "windows": [],
        "credits_balance": None,
        "error": msg,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Claude usage fetcher")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch",  action="store_true", help="Fetch usage and print JSON")
    group.add_argument("--login",  action="store_true", help="Run Edge login flow")
    group.add_argument("--clear",  action="store_true", help="Delete stored session")
    parser.add_argument("--timeout", type=int, default=600, help="Login timeout seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    if args.fetch:
        print(json.dumps(do_fetch()))
    elif args.login:
        print(json.dumps(run_login(args.timeout)))
    elif args.clear:
        clear_session_key()
        print(json.dumps({"success": True}))


if __name__ == "__main__":
    main()
