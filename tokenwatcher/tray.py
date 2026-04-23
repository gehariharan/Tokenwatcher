from __future__ import annotations

import logging
import os
import subprocess
import threading
import webbrowser
from datetime import datetime, timezone
from typing import Callable

import pystray
from pystray import Menu, MenuItem

from .config import CONFIG_PATH
from .icon import render_icon
from .providers.base import ProviderResult, ProviderStatus

log = logging.getLogger(__name__)


class TrayApp:
    def __init__(
        self,
        fetch_all: Callable[[], list[ProviderResult]],
        refresh_seconds: int,
    ) -> None:
        self._fetch_all = fetch_all
        self._refresh_seconds = max(60, int(refresh_seconds))
        self._results: list[ProviderResult] = []
        self._last_update: datetime | None = None
        self._stop = threading.Event()
        self._icon = pystray.Icon(
            name="TokenWatcher",
            icon=render_icon("TW"),
            title="TokenWatcher",
            menu=self._build_menu(),
        )

    def run(self) -> None:
        self._icon.run(setup=self._on_start)

    def _on_start(self, icon: pystray.Icon) -> None:
        icon.visible = True
        threading.Thread(target=self._refresh_loop, daemon=True).start()

    def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            self._do_refresh()
            self._stop.wait(self._refresh_seconds)

    def _do_refresh(self) -> None:
        try:
            self._results = self._fetch_all()
        except Exception as e:  # noqa: BLE001
            log.exception("fetch_all failed: %s", e)
            self._results = []
        self._last_update = datetime.now(timezone.utc)
        self._icon.menu = self._build_menu()
        self._icon.title = self._compact_title()

    def _compact_title(self) -> str:
        parts = ["TokenWatcher"]
        for r in self._results:
            if r.status is ProviderStatus.OK and r.windows:
                top = max(
                    (w.used_percent for w in r.windows if w.used_percent is not None),
                    default=None,
                )
                if top is not None:
                    parts.append(f"{r.name[:1].upper()}:{int(top)}%")
        return " | ".join(parts)

    def _build_menu(self) -> Menu:
        items: list[MenuItem] = []
        if not self._results:
            items.append(MenuItem("Loading…", None, enabled=False))
        for r in self._results:
            items.append(MenuItem(_header_line(r), None, enabled=False))
            for w in r.windows:
                items.append(MenuItem("   " + _window_line(w), None, enabled=False))
            if r.credits_balance:
                items.append(MenuItem("   " + r.credits_balance, None, enabled=False))
            if r.account_label:
                items.append(MenuItem("   " + r.account_label, None, enabled=False))
            items.append(Menu.SEPARATOR)

        last = (
            f"Updated {self._last_update.astimezone().strftime('%H:%M:%S')}"
            if self._last_update
            else "Never updated"
        )
        items.append(MenuItem(last, None, enabled=False))
        items.append(MenuItem("Refresh now", self._on_refresh_clicked))
        items.append(
            MenuItem("Open config file", lambda _i, _mi: self._open_config())
        )
        items.append(
            MenuItem(
                "Open chatgpt.com", lambda _i, _mi: webbrowser.open("https://chatgpt.com/")
            )
        )
        items.append(
            MenuItem(
                "Open claude.ai", lambda _i, _mi: webbrowser.open("https://claude.ai/")
            )
        )
        items.append(Menu.SEPARATOR)
        items.append(MenuItem("Quit", self._on_quit))
        return Menu(*items)

    def _on_refresh_clicked(self, _icon: pystray.Icon, _item: MenuItem) -> None:
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _on_quit(self, icon: pystray.Icon, _item: MenuItem) -> None:
        self._stop.set()
        icon.visible = False
        icon.stop()

    def _open_config(self) -> None:
        path = str(CONFIG_PATH)
        if not CONFIG_PATH.exists():
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError:
            subprocess.Popen(["notepad.exe", path])


def _header_line(r: ProviderResult) -> str:
    label = r.name.capitalize()
    if r.status is ProviderStatus.NOT_LOGGED_IN:
        return f"{label}: not signed in"
    if r.status is ProviderStatus.ERROR:
        return f"{label}: error"
    plan = f" ({r.plan})" if r.plan else ""
    return f"{label}{plan}"


def _window_line(w) -> str:
    pct = f"{w.used_percent:.0f}%" if w.used_percent is not None else "—"
    reset = ""
    if w.resets_at is not None:
        delta = w.resets_at - datetime.now(timezone.utc)
        reset = f"  resets in {_fmt_delta(delta)}"
    return f"{w.label}: {pct}{reset}"


def _fmt_delta(delta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        return "now"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
