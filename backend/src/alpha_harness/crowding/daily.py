"""The daily catalog sync: keeps the crowding history growing without anyone pressing Sync.

Once a day, from a chosen hour of the local morning, every ordinary market is downloaded.
The region-agnostic market (region ``ALL``) is far slower — BRAIN serves it fifty fields at a
time, about ten minutes per universe — so it runs every ``ra_every_days`` days instead, after
the ordinary markets are done for the day.

"Done for the day" is read from the crowding history itself: a market has been synced today
when today's snapshot holds it. That survives restarts with no bookkeeping of its own, and a
sync the user starts by hand counts the same as one started here.
"""

import asyncio
import contextlib
from datetime import date, datetime
from typing import TYPE_CHECKING

import structlog

from ..brain.schemas import REGION_AGNOSTIC_REGION

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..catalog.sync import CatalogSync, SyncTarget
    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

#: Seconds between looks. A sync is hours apart, so a ten-minute look is prompt enough.
CHECK_SECONDS = 600.0


class DailySync:
    """Starts the day's catalog download when it is due."""

    def __init__(
        self,
        sync: CatalogSync,
        catalog: Catalog,
        *,
        markets: Callable[[], Awaitable[list[SyncTarget]]],
        signed_in: Callable[[], bool],
        operators: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        self.sync = sync
        self.catalog = catalog
        self._markets = markets
        self._signed_in = signed_in
        #: Re-reads the account's operators, once a day, so a new one is used the day it appears.
        self._operators = operators
        self.operators_day: date | None = None
        #: Settings: on/off, the local hour from which the day's sync may start, and how many
        #: days apart the region-agnostic market is downloaded (0: never automatically).
        self.enabled = True
        self.hour = 6
        self.ra_every_days = 3
        self._task: asyncio.Task[None] | None = None

    def configure(self, *, enabled: bool, hour: int, ra_every_days: int) -> None:
        self.enabled = enabled
        self.hour = hour
        self.ra_every_days = ra_every_days

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="daily-catalog-sync")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            # One failed look must not end the schedule.
            except Exception:
                log.warning("daily_sync.tick_failed", exc_info=True)
            await asyncio.sleep(CHECK_SECONDS)

    async def last_synced(self) -> tuple[date | None, date | None]:
        """The latest snapshot day of the ordinary markets and of the region-agnostic one."""
        rows = await self.catalog.query(
            "SELECT region = ? AS agnostic, max(snapshot_date) AS d "
            "FROM dataset_snapshot GROUP BY ALL",
            [REGION_AGNOSTIC_REGION],
        )
        ordinary = next((r["d"] for r in rows if not r["agnostic"]), None)
        agnostic = next((r["d"] for r in rows if r["agnostic"]), None)
        return ordinary, agnostic

    async def tick(self, now: datetime | None = None) -> str | None:
        """Start whatever is due. Returns ``"ordinary"``, ``"agnostic"`` or ``None``."""
        now = now or datetime.now().astimezone()
        if not self.enabled or now.hour < self.hour or self.sync.running() or not self._signed_in():
            return None
        today = now.date()
        if self._operators is not None and self.operators_day != today:
            self.operators_day = today
            try:
                await self._operators()
                log.info("daily_sync.operators_refreshed")
            # BRAIN being away costs only today's refresh; the cached list stays in use.
            except Exception:
                log.warning("daily_sync.operators_failed", exc_info=True)
        ordinary_day, agnostic_day = await self.last_synced()

        if ordinary_day is None or ordinary_day < today:
            targets = [t for t in await self._markets() if t.region != REGION_AGNOSTIC_REGION]
            if targets:
                log.info("daily_sync.start", kind="ordinary", markets=len(targets))
                await self.sync.start_all(targets)
                return "ordinary"
            return None

        if self.ra_every_days > 0 and (
            agnostic_day is None or (today - agnostic_day).days >= self.ra_every_days
        ):
            targets = [t for t in await self._markets() if t.region == REGION_AGNOSTIC_REGION]
            if targets:
                log.info("daily_sync.start", kind="agnostic", markets=len(targets))
                await self.sync.start_all(targets)
                return "agnostic"
        return None
