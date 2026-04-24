"""Edge-based one-time login flow for claude.ai.

Launches Microsoft Edge in app mode against claude.ai with a dedicated
TokenWatcher profile and remote-debugging enabled. Polls the Edge DevTools
Protocol over WebSocket until the sessionKey cookie appears, then returns it.

We use a dedicated user-data-dir so this never collides with the user's normal
Edge session and the profile's cookie jar is owned by TokenWatcher.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path

import requests
import websocket  # provided by websocket-client

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

EDGE_PROFILE_DIR = CONFIG_DIR / "edge-profile"
LOGIN_URL = "https://claude.ai/login"
CLAUDE_DOMAIN_SUFFIX = "claude.ai"


EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class LoginError(Exception):
    pass


def find_edge_path() -> str:
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    # Last resort: try PATH lookup
    from shutil import which

    hit = which("msedge")
    if hit:
        return hit
    raise LoginError(
        "Microsoft Edge not found. Install it from https://www.microsoft.com/edge."
    )


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_login(timeout_seconds: int = 600) -> str:
    """Launch Edge, wait for user to sign into claude.ai, return the sessionKey.

    Raises LoginError on timeout or failure.
    """
    EDGE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    port = _find_free_port()
    edge = find_edge_path()

    args = [
        edge,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={EDGE_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--app={LOGIN_URL}",
    ]
    log.info("Launching Edge: %s", args)
    proc = subprocess.Popen(args)
    try:
        _wait_for_debug_port(port, timeout=15)
        session_key = _poll_for_session_key(port, timeout_seconds)
        if session_key is None:
            raise LoginError(
                "Timed out waiting for claude.ai sign-in. Try again."
            )
        return session_key
    finally:
        try:
            proc.terminate()
        except OSError:
            pass


def _wait_for_debug_port(port: int, timeout: int) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return
        except requests.RequestException:
            time.sleep(0.3)
    raise LoginError(f"Edge did not expose debug port {port}")


def _poll_for_session_key(port: int, timeout_s: int) -> str | None:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            targets = requests.get(f"http://127.0.0.1:{port}/json", timeout=2).json()
        except (requests.RequestException, ValueError):
            time.sleep(1)
            continue

        claude_targets = [
            t
            for t in targets
            if isinstance(t, dict)
            and t.get("type") == "page"
            and CLAUDE_DOMAIN_SUFFIX in (t.get("url") or "")
        ]
        for target in claude_targets:
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                continue
            try:
                cookies = _get_cookies_via_cdp(ws_url)
            except Exception as e:  # noqa: BLE001
                log.debug("CDP cookie fetch failed: %s", e)
                continue
            session_key = cookies.get("sessionKey")
            if session_key:
                log.info("Captured sessionKey (%d chars)", len(session_key))
                return session_key
        time.sleep(2)
    return None


def _get_cookies_via_cdp(ws_url: str) -> dict[str, str]:
    ws = websocket.create_connection(ws_url, timeout=5)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        reply = json.loads(ws.recv())
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    cookies = reply.get("result", {}).get("cookies", []) or []
    out: dict[str, str] = {}
    for c in cookies:
        domain = c.get("domain") or ""
        if CLAUDE_DOMAIN_SUFFIX in domain and c.get("name"):
            out[c["name"]] = c.get("value", "")
    return out
