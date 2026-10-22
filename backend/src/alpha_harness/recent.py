"""Answers that come from BRAIN, kept a while and refreshed behind the screen.

A screen that asks BRAIN on every visit waits on BRAIN every visit, and while it waits it
holds one of the six connections a browser opens to the app: a few such waits and every click
stalls. So the last answer is returned at once, and once it is older than ``ttl`` a fresh one
is fetched in the background for the next visit. Only the first visit waits.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

from .tasks import spawn

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)


class Recent:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._values: dict[str, tuple[float, Any]] = {}
        self._refreshing: dict[str, asyncio.Task[Any]] = {}

    async def get(self, key: str, make: Callable[[], Awaitable[Any]]) -> Any:
        found = self._values.get(key)
        if found is None:
            value = await make()
            self._values[key] = (time.monotonic(), value)
            return value
        at, value = found
        busy = key in self._refreshing and not self._refreshing[key].done()
        if time.monotonic() - at > self.ttl and not busy:
            self._refreshing[key] = spawn(self._refresh(key, make), name=f"recent-{key}")
        return value

    async def _refresh(self, key: str, make: Callable[[], Awaitable[Any]]) -> None:
        try:
            self._values[key] = (time.monotonic(), await make())
        except Exception:
            log.warning("recent.refresh_failed", key=key, exc_info=True)

    def forget(self, key: str | None = None) -> None:
        if key is None:
            self._values.clear()
        else:
            self._values.pop(key, None)
