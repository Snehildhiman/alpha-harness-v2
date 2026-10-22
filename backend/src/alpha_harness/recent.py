"""Answers that come from BRAIN, kept a while and refreshed behind the screen.

A screen that asks BRAIN on every visit waits on BRAIN every visit, and while it waits it
holds one of the six connections a browser opens to the app: a few such waits and every click
stalls. So the last answer is returned at once, and once it is older than ``ttl`` a fresh one
is fetched in the background for the next visit. Only the first visit waits.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from .tasks import spawn

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)


class StillReading(Exception):
    """The first answer is still being read; ask again shortly."""


class Recent:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._values: dict[str, tuple[float, Any]] = {}
        self._refreshing: dict[str, asyncio.Task[Any]] = {}

    async def get(
        self, key: str, make: Callable[[], Awaitable[Any]], *, wait: float | None = None
    ) -> Any:
        """The last answer, at once. The first ever is waited for, at most ``wait`` seconds:
        past that :class:`StillReading` is raised while the read goes on in the background,
        so a slow BRAIN never holds one of the browser's connections for long."""
        found = self._values.get(key)
        if found is None:
            busy = self._refreshing.get(key)
            if busy is None or busy.done():
                busy = self._refreshing[key] = spawn(self._refresh(key, make), name=f"recent-{key}")
            try:
                await asyncio.wait_for(asyncio.shield(busy), wait)
            except TimeoutError as exc:
                raise StillReading(key) from exc
            if key not in self._values:
                # The read failed: say so the usual way, by trying once more in the open.
                value = await make()
                self._values[key] = (time.monotonic(), value)
            return self._values[key][1]
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


class Memo:
    """A few answers kept for ``ttl`` seconds, by any hashable key; the oldest go first.

    For screens that recompute the same answer from the same judged vault: the key carries
    the vault's identity, so a re-judged vault is a new key and never a stale answer.
    """

    def __init__(self, ttl: float, size: int = 32) -> None:
        self.ttl = ttl
        self.size = size
        self._values: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any:
        found = self._values.get(key)
        if found is None or time.monotonic() - found[0] > self.ttl:
            return None
        return found[1]

    def put(self, key: Any, value: Any) -> None:
        self._values[key] = (time.monotonic(), value)
        while len(self._values) > self.size:
            self._values.pop(next(iter(self._values)))
