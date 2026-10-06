"""Shared Playwright plumbing: an isolated event loop per browser job, a concurrency cap, a health probe."""

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

from ai_service.app.core.config import settings

T = TypeVar("T")

_browser_slots = threading.BoundedSemaphore(settings.browser_max_concurrency)


def run_isolated(coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a Playwright coroutine on a fresh event loop in the current (worker) thread.

    Playwright launches the browser as a subprocess, which on Windows needs a Proactor loop; the server's
    loop may not be one, so browser work never runs on it directly.
    """
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    with _browser_slots:
        try:
            return loop.run_until_complete(coro_factory())
        finally:
            loop.close()


async def in_browser_thread(coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return await asyncio.to_thread(run_isolated, coro_factory)


_HEALTH_TTL_SECONDS = 600
_health_cache: tuple[float, dict[str, Any]] | None = None


async def browser_health() -> dict[str, Any]:
    """Whether Chromium is installed for Playwright. Cached, since the probe starts the driver."""
    global _health_cache
    if _health_cache is None or time.monotonic() - _health_cache[0] > _HEALTH_TTL_SECONDS:
        _health_cache = (time.monotonic(), await asyncio.to_thread(_probe))
    return _health_cache[1]


def _probe() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            executable = pw.chromium.executable_path
    except Exception as exc:
        return {"ok": False, "detail": f"Playwright unavailable: {exc}"}
    if Path(executable).exists():
        return {"ok": True, "detail": "Chromium installed"}
    return {"ok": False, "detail": "Chromium is not installed: run python -m playwright install chromium"}
