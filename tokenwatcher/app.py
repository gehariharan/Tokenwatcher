from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import Sequence

from .config import Config
from .providers import ClaudeProvider, CodexProvider
from .providers.base import ProviderResult, ProviderStatus, pending_result

log = logging.getLogger("tokenwatcher")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_providers(cfg: Config) -> list:
    out = []
    if cfg.providers.get("codex") and cfg.providers["codex"].enabled:
        out.append(CodexProvider())
    if cfg.providers.get("claude") and cfg.providers["claude"].enabled:
        out.append(ClaudeProvider())
    return out


def _fetch_providers(providers: list, include_on_demand: bool) -> list[ProviderResult]:
    results: list[ProviderResult] = []
    for p in providers:
        if getattr(p, "on_demand_only", False) and not include_on_demand:
            results.append(pending_result(p.name))
            continue
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="with --once: also fetch on-demand providers (Claude)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = Config.load()
    providers = _build_providers(cfg)

    if not providers:
        print("No providers enabled in config.", file=sys.stderr)
        return 2

    if args.once:
        results = _fetch_providers(providers, include_on_demand=args.all)
        _print_results(results, as_json=args.json)
        has_any_ok = any(r.status is ProviderStatus.OK for r in results)
        return 0 if has_any_ok else 1

    from .tray import TrayApp

    app = TrayApp(
        fetch_fn=lambda include_on_demand: _fetch_providers(
            providers, include_on_demand=include_on_demand
        ),
        refresh_seconds=cfg.refresh_seconds,
    )
    app.run()
    return 0
