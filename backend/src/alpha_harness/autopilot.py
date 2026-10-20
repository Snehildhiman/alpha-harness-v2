"""Autopilot: queue promotions and the transplants the models like best, while you are away.

Off until Settings turn it on, because it spends simulations. When on, every half hour it
looks at the transplant plan (Repair → Transplants) and, if its last task has finished, queues
the best ones whose chance of passing every check is at least the chosen minimum, up to the
day's budget. With a region-agnostic universe chosen, expressions that already pass in two
markets are promoted to region-agnostic families first. Each runs as an ordinary task on the
Tasks screen, so it can be paused or stopped there like any other. Every result feeds the
models, so the next round ranks better, and an expression that comes to pass in two markets
is promoted on a later round.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select

from .db.models import Study, StudyStatus

if TYPE_CHECKING:
    from collections.abc import Callable

log = structlog.get_logger(__name__)

#: Seconds between looks.
EVERY_SECONDS = 1800.0
#: Simulations in one autopilot task; small, so a poor round costs little.
PER_TASK = 20
#: How the autopilot's tasks are told apart from yours.
NAME = "Autopilot"
_UNFINISHED = (StudyStatus.IDLE, StudyStatus.QUEUED, StudyStatus.RUNNING, StudyStatus.PAUSED)


class Autopilot:
    def __init__(self, state: Any, signed_in: Callable[[], bool]) -> None:
        self.state = state
        self.signed_in = signed_in
        #: Settings.
        self.enabled = False
        self.daily = 100
        self.min_chance = 0.4
        self.cores = 2
        #: The region-agnostic universe families are promoted into; empty: no promotions.
        self.ra_universe = ""
        self.last: str | None = None
        self._task: asyncio.Task[None] | None = None

    def configure(
        self, *, enabled: bool, daily: int, min_chance: float, cores: int, ra_universe: str = ""
    ) -> None:
        self.enabled, self.daily, self.min_chance, self.cores = enabled, daily, min_chance, cores
        self.ra_universe = ra_universe

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="autopilot")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(EVERY_SECONDS)
            if not (self.enabled and self.signed_in()):
                continue
            try:
                self.last = await self.tick()
            # One bad round must not end the loop.
            except Exception:
                log.warning("autopilot.failed", exc_info=True)

    async def spent(self) -> tuple[int, bool]:
        """Simulations the autopilot queued in the last 24 hours, and whether one of its
        tasks is still unfinished."""
        since = datetime.now(UTC) - timedelta(hours=24)
        async with self.state.db.session() as session:
            used = await session.scalar(
                select(func.coalesce(func.sum(Study.max_trials), 0)).where(
                    Study.template_name.like(f"{NAME}%"), Study.created_at >= since
                )
            )
            open_ = await session.scalar(
                select(func.count()).where(
                    Study.template_name.like(f"{NAME}%"), Study.status.in_(_UNFINISHED)
                )
            )
        return int(used or 0), bool(open_)

    async def tick(self) -> str:
        """One round. Returns what it did, for the status line."""
        # Late: the API module imports the app state, which imports this.
        from .api.repair import add_promotions, add_transplants, promotion_rows, transplant_rows

        used, busy = await self.spent()
        if busy:
            return "Waiting for its last task to finish."
        room = min(PER_TASK, self.daily - used)
        if room <= 0:
            return f"Today's budget of {self.daily} simulations is spent."
        if self.cores > self.state.engine.slots:
            return f"The engine has {self.state.engine.slots} slots; lower the autopilot's cores."
        # Region-agnostic families first: they are the type that pays most, and these have
        # already passed as regular Alphas in two markets.
        if self.ra_universe:
            for delay in (1, 0):
                found, families = await promotion_rows(self.state, delay)
                if families and self.ra_universe in found.universes.get(delay, []):
                    chosen = families[:room]
                    added = await add_promotions(
                        self.state,
                        chosen,
                        universe=self.ra_universe,
                        delay=delay,
                        cores=self.cores,
                        name=f"{NAME} · {len(chosen)} RA families",
                        run=True,
                    )
                    log.info("autopilot.queued", task=added.name, simulations=len(chosen))
                    return f"Queued {len(chosen)} region-agnostic families."
        plan, rows = await transplant_rows(self.state, room, None)
        if not plan.ranked:
            return "Waiting for the models to be trained."
        chosen = [t for t, r in rows if (r.p_all or 0.0) >= self.min_chance][:room]
        if not chosen:
            return f"No transplant has a {self.min_chance:.0%} chance of passing."
        added = await add_transplants(
            self.state,
            chosen,
            cores=self.cores,
            name=f"{NAME} · {len(chosen)} transplants",
            run=True,
        )
        log.info("autopilot.queued", task=added.name, simulations=len(chosen))
        return f"Queued {len(chosen)} transplants."
