from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ProviderStatus(Enum):
    OK = "ok"
    NOT_LOGGED_IN = "not_logged_in"
    ERROR = "error"


@dataclass
class RateWindow:
    label: str                   # e.g. "5h", "7d", "session", "weekly"
    used_percent: float | None   # 0..100
    resets_at: datetime | None   # UTC


@dataclass
class ProviderResult:
    name: str                             # "codex" | "claude"
    status: ProviderStatus
    plan: str | None = None               # e.g. "plus", "pro", "team"
    account_label: str | None = None      # e.g. email or org name
    windows: list[RateWindow] = field(default_factory=list)
    credits_balance: str | None = None    # human-readable, e.g. "$12.34"
    error: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def summary_line(self) -> str:
        if self.status is ProviderStatus.NOT_LOGGED_IN:
            return f"{self.name}: not signed in"
        if self.status is ProviderStatus.ERROR:
            return f"{self.name}: error — {self.error or 'unknown'}"
        parts: list[str] = []
        if self.plan:
            parts.append(self.plan)
        for w in self.windows:
            if w.used_percent is None:
                continue
            parts.append(f"{w.label} {w.used_percent:.0f}%")
        if self.credits_balance:
            parts.append(self.credits_balance)
        return f"{self.name}: " + (", ".join(parts) if parts else "no data")


def pending_result(name: str) -> ProviderResult:
    """Placeholder result shown before an on-demand provider has been fetched."""
    return ProviderResult(
        name=name,
        status=ProviderStatus.ERROR,
        error="click Refresh to load",
    )
