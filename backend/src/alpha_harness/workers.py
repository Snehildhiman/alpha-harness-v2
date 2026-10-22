"""Where heavy Python work runs, and a watchdog that says when the app stalls.

Python runs one thread at a time. Work in a worker thread still takes turns with the thread
that answers the screens, so every busy worker makes each answer wait longer. A lab choosing
its next Alphas (the optimizer weighing every trial so far) is the heaviest such work and
runs all day, so it gets one thread of its own: the labs take turns on it, and however many
run, the screens compete with one of them, not all.

The watchdog is a plain thread that the event loop ticks four times a second. When a tick is
more than :data:`STALL` late, the loop is stuck in something; the watchdog notes what the
loop's thread was running then, so Health can say where the time went.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

log = structlog.get_logger(__name__)

#: The labs' planning thread: one, shared, so a dozen tasks cannot crowd out the screens.
LABS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="labs")
#: How long one task may plan in one go; it plans the rest on its next turn.
PLAN_SECONDS = 2.0
#: A loop late by this much is stalled.
STALL = 2.0
TICK = 0.25


async def in_labs[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """``fn`` on the labs' own thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(LABS, functools.partial(fn, *args, **kwargs))


class Watchdog:
    def __init__(self) -> None:
        self._beat = time.monotonic()
        self._loop_thread: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task[None] | None = None
        #: The last stalls: when, how long, and where the loop was.
        self.stalls: deque[dict[str, Any]] = deque(maxlen=20)
        #: Worst lateness seen in the last minute, in seconds.
        self._recent: deque[tuple[float, float]] = deque(maxlen=240)

    def start(self) -> None:
        self._loop_thread = threading.get_ident()
        self._task = asyncio.get_running_loop().create_task(self._ticks(), name="watchdog")
        self._thread = threading.Thread(target=self._watch, name="watchdog", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _ticks(self) -> None:
        while True:
            now = time.monotonic()
            self._recent.append((now, max(0.0, now - self._beat - TICK)))
            self._beat = now
            await asyncio.sleep(TICK)

    def _watch(self) -> None:
        reported = 0.0
        while not self._stop.wait(0.5):
            late = time.monotonic() - self._beat
            if late < STALL or self._beat == reported:
                continue
            reported = self._beat
            frames: dict[int, Any] = getattr(sys, "_current_frames")()  # noqa: B009
            frame = frames.get(self._loop_thread or -1)
            where = _ours(traceback.extract_stack(frame)) if frame is not None else []
            stall = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "seconds": round(late, 1),
                "where": where,
            }
            self.stalls.append(stall)
            log.warning("loop.stalled", seconds=round(late, 1), where=" <- ".join(where[:4]))

    def worst_last_minute(self) -> float:
        cutoff = time.monotonic() - 60
        lates = [late for at, late in self._recent if at >= cutoff]
        current = max(0.0, time.monotonic() - self._beat - TICK)
        return max([current, *lates])


def _ours(stack: traceback.StackSummary) -> list[str]:
    """The app's own frames, innermost first: where to look."""
    frames = [f for f in stack if "alpha_harness" in f.filename]
    return [f"{_short(f.filename)}:{f.lineno} {f.name}" for f in reversed(frames)][:8]


def _short(filename: str) -> str:
    return filename.rsplit("alpha_harness", 1)[-1].replace("\\", "/").lstrip("/")


watchdog = Watchdog()
