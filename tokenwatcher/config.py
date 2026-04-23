from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.path.expandvars(r"%USERPROFILE%")) / ".tokenwatcher"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class ProviderConfig:
    enabled: bool = True


@dataclass
class Config:
    refresh_seconds: int = 300
    browser: str = "auto"
    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {
            "codex": ProviderConfig(enabled=True),
            "claude": ProviderConfig(enabled=True),
        }
    )

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "Config":
        providers_raw = raw.get("providers", {}) or {}
        providers = {
            name: ProviderConfig(enabled=bool(v.get("enabled", True)))
            for name, v in providers_raw.items()
            if isinstance(v, dict)
        }
        for missing in ("codex", "claude"):
            providers.setdefault(missing, ProviderConfig(enabled=True))
        return cls(
            refresh_seconds=int(raw.get("refresh_seconds", 300)),
            browser=str(raw.get("browser", "auto")),
            providers=providers,
        )

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "refresh_seconds": self.refresh_seconds,
                    "browser": self.browser,
                    "providers": {k: asdict(v) for k, v in self.providers.items()},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
