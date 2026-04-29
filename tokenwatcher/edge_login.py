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
        # Chromium ≥ rejects CDP WebSocket upgrades whose Origin header isn't
        # explicitly allowlisted; without this we get 403s on every request.
        f"--remote-allow-origins=http://127.0.0.1:{port}",
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
    last_log_at = 0.0
    while time.time() - start < timeout_s:
        try:
            targets = requests.get(f"http://127.0.0.1:{port}/json", timeout=2).json()
        except (requests.RequestException, ValueError) as e:
            log.debug("targets fetch failed: %s", e)
            time.sleep(1)
            continue

        # Log target URLs once every ~10s so the user/dev can see what Edge has open.
        if time.time() - last_log_at > 10:
            urls = [t.get("url") for t in targets if isinstance(t, dict)]
            log.debug("Edge targets (%d): %s", len(urls), urls)
            last_log_at = time.time()

        # Try ANY page or app-type target (Edge --app= mode is sometimes type=page,
        # sometimes type=webview, depending on version). Filter by URL match.
        claude_targets = [
            t
            for t in targets
            if isinstance(t, dict)
            and t.get("type") in ("page", "webview", "app")
            and CLAUDE_DOMAIN_SUFFIX in (t.get("url") or "")
            and t.get("webSocketDebuggerUrl")
        ]

        # If no targets matched by URL, also try ANY page target — claude.ai may be
        # showing a redirect URL temporarily (e.g. cloudflare check).
        if not claude_targets:
            claude_targets = [
                t
                for t in targets
                if isinstance(t, dict)
                and t.get("type") == "page"
                and t.get("webSocketDebuggerUrl")
            ]

        for target in claude_targets:
            ws_url = target["webSocketDebuggerUrl"]
            try:
                cookies = _get_cookies_via_cdp(ws_url)
            except Exception as e:  # noqa: BLE001
                log.debug("CDP cookie fetch failed for %s: %s", target.get("url"), e)
                continue
            log.debug(
                "cookies seen on %s: %s",
                target.get("url"),
                sorted(cookies.keys()),
            )
            session_key = cookies.get("sessionKey")
            if session_key:
                log.info(
                    "Captured sessionKey (len=%d) from %s", len(session_key), target.get("url")
                )
                return session_key
        time.sleep(2)
    return None


def _get_cookies_via_cdp(ws_url: str) -> dict[str, str]:
    """Send Network.getAllCookies and return cookies for any *.claude.ai domain.

    CDP responses can be interleaved with events. We loop on recv() until we
    see a frame whose id matches our request, with a hard cap of 10 frames
    so a misbehaving connection can't hang us.
    """
    request_id = 1
    ws = websocket.create_connection(ws_url, timeout=8)
    ws.settimeout(8)
    try:
        ws.send(json.dumps({"id": request_id, "method": "Network.getAllCookies"}))
        result: dict | None = None
        for _ in range(10):
            try:
                msg = json.loads(ws.recv())
            except Exception:  # noqa: BLE001
                break
            if msg.get("id") == request_id:
                result = msg.get("result") or {}
                break
        if result is None:
            raise RuntimeError("no CDP response to Network.getAllCookies")
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    cookies = result.get("cookies", []) or []
    out: dict[str, str] = {}
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if domain.endswith(CLAUDE_DOMAIN_SUFFIX) and c.get("name"):
            out[c["name"]] = c.get("value", "")
    return out
