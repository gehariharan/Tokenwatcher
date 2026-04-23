from __future__ import annotations

import logging
from http.cookiejar import CookieJar
from typing import Callable

log = logging.getLogger(__name__)


BROWSER_PRIORITY = ("chrome", "edge", "brave", "firefox")


def _loader_for(name: str) -> Callable[..., CookieJar] | None:
    import browser_cookie3 as bc3  # type: ignore
    return {
        "chrome": bc3.chrome,
        "edge": bc3.edge,
        "brave": bc3.brave,
        "firefox": bc3.firefox,
        "opera": bc3.opera,
        "chromium": bc3.chromium,
    }.get(name.lower())


def load_cookies_for_domain(domain: str, browser: str = "auto") -> CookieJar | None:
    """Return a CookieJar containing cookies for `domain`, read from the browser's local
    encrypted store. On Windows this goes through DPAPI under the hood via browser_cookie3.

    `browser` may be "auto" (try each in priority order) or a specific name.
    Returns None if no browser yielded cookies for the domain.
    """
    candidates = BROWSER_PRIORITY if browser == "auto" else (browser,)
    last_err: Exception | None = None
    for b in candidates:
        loader = _loader_for(b)
        if loader is None:
            log.debug("no loader for browser %r", b)
            continue
        try:
            jar = loader(domain_name=domain)
        except Exception as e:
            last_err = e
            log.debug("cookie load failed for browser=%s domain=%s: %s", b, domain, e)
            continue
        if any(c.domain.endswith(domain) or domain in c.domain for c in jar):
            log.info("loaded cookies for %s from %s", domain, b)
            return jar
    if last_err is not None:
        log.warning("all browser cookie loaders failed for %s: %s", domain, last_err)
    return None


def cookie_value(jar: CookieJar, name: str, domain_hint: str | None = None) -> str | None:
    for c in jar:
        if c.name != name:
            continue
        if domain_hint and domain_hint not in (c.domain or ""):
            continue
        return c.value
    return None
