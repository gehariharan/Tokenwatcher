from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import Sequence

from .config import Config
from .providers import ClaudeProvider, CodexProvider
from .providers.base import ProviderResult, ProviderStatus

log = logging.getLogger("tokenwatcher")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_providers(cfg: Config) -> list:
    out = []
    if cfg.providers.get("codex") and cfg.providers["codex"].enabled:
        out.append(CodexProvider(browser=cfg.browser))
    if cfg.providers.get("claude") and cfg.providers["claude"].enabled:
        out.append(ClaudeProvider(browser=cfg.browser))
    return out


def _fetch_all(providers: list) -> list[ProviderResult]:
    results: list[ProviderResult] = []
    for p in providers:
        try:
            results.append(p.fetch())
        except Exception as e:  # noqa: BLE001
            log.exception("provider %s failed", p.name)
            results.append(
                ProviderResult(
                    name=p.name,
                    status=ProviderStatus.ERROR,
                    error=str(e),
                )
            )
    return results


def _print_results(results: list[ProviderResult], as_json: bool) -> None:
    if as_json:
        payload = [_result_to_dict(r) for r in results]
        print(json.dumps(payload, indent=2, default=str))
        return
    for r in results:
        print(r.summary_line())
        for w in r.windows:
            reset = w.resets_at.isoformat() if w.resets_at else "—"
            pct = f"{w.used_percent:.1f}%" if w.used_percent is not None else "—"
            print(f"    {w.label}: {pct}   resets_at={reset}")
        if r.credits_balance:
            print(f"    {r.credits_balance}")
        if r.error and r.status is not ProviderStatus.OK:
            print(f"    error: {r.error}")


def _result_to_dict(r: ProviderResult) -> dict:
    d = asdict(r)
    d["status"] = r.status.value
    return d


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="tokenwatcher")
    parser.add_argument("--once", action="store_true", help="fetch once and print, no tray")
    parser.add_argument("--json", action="store_true", help="with --once: print JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = Config.load()
    providers = _build_providers(cfg)

    if not providers:
        print("No providers enabled in config.", file=sys.stderr)
        return 2

    if args.once:
        results = _fetch_all(providers)
        _print_results(results, as_json=args.json)
        has_any_ok = any(r.status is ProviderStatus.OK for r in results)
        return 0 if has_any_ok else 1

    from .tray import TrayApp

    app = TrayApp(
        fetch_all=lambda: _fetch_all(providers),
        refresh_seconds=cfg.refresh_seconds,
    )
    app.run()
    return 0
