"""The governor: cores go to the tasks that turn simulations into submittable Alphas.

The day's allowance is the scarce thing, and a core spent on a task that finds nothing is a
share of it gone. Every task's *yield* is read off its recent results — the share of its
Alphas BRAIN has judged that pass every check their type answers to — and, when Settings turn
it on, the cores the running tasks hold between them are re-dealt toward the higher yields.

Dealing is Thompson sampling: each task's yield is a Beta distribution over what its results
show, and each core goes to whichever task draws highest. A task with few results draws
widely and still gets tried; one with many results gets what it has earned. Every running task
keeps at least one core, and the total never changes, so the account's eight cores are never
over-committed and a task the consultant gave cores to is never starved outright.
"""

import asyncio
import contextlib
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from .db.duck import AMONG, packed
from .db.models import Study, StudyStatus, Trial, TrialState
from .labs.params import TASK_SAMPLERS, task_params
from .labs.scheduler import cores_of, resize_task
from .separation import Verdict, judge

if TYPE_CHECKING:
    from .db.duck import Catalog
    from .labs.study import Optimizer

log = structlog.get_logger(__name__)

#: Recent results per task the yield is read over.
WINDOW = 300
#: Seconds between re-deals. Cores move at a task's next round, so faster gains nothing.
EVERY_SECONDS = 1800.0
#: Draws per core when dealing, so one lucky draw does not move a core.
DRAWS = 25

PASSING = frozenset({Verdict.SUBMITTABLE, Verdict.RECHECK, Verdict.SUBMITTED})


@dataclass(frozen=True, slots=True)
class TaskYield:
    study_id: int
    name: str
    task: str
    cores: int
    passing: int
    refused: int

    @property
    def judged(self) -> int:
        return self.passing + self.refused

    @property
    def rate(self) -> float | None:
        return self.passing / self.judged if self.judged else None


def deal(yields: list[TaskYield], rng: random.Random) -> dict[int, int]:
    """Study id → cores: the same total, at least one each, the rest by Thompson draws."""
    if not yields:
        return {}
    total = sum(y.cores for y in yields)
    out = {y.study_id: 1 for y in yields}
    for _ in range(max(0, total - len(yields))):
        wins = dict.fromkeys(out, 0)
        for _ in range(DRAWS):
            best = max(yields, key=lambda y: rng.betavariate(1 + y.passing, 1 + y.refused))
            wins[best.study_id] += 1
        out[max(wins, key=lambda k: wins[k])] += 1
    return out


async def yields(optimizer: Optimizer, catalog: Catalog) -> list[TaskYield]:
    """Every running research task's recent yield."""
    async with optimizer.db.session() as session:
        running = (
            await session.scalars(
                select(Study).where(
                    Study.sampler.in_(TASK_SAMPLERS), Study.status == StudyStatus.RUNNING
                )
            )
        ).all()
        recent: dict[int, list[str]] = {}
        for row in running:
            recent[row.id] = [
                str(a)
                for a in (
                    await session.scalars(
                        select(Trial.alpha_id)
                        .where(
                            Trial.study_id == row.id,
                            Trial.state == TrialState.COMPLETE,
                            Trial.alpha_id.is_not(None),
                        )
                        .order_by(Trial.id.desc())
                        .limit(WINDOW)
                    )
                ).all()
            ]
    ids = sorted({a for alphas in recent.values() for a in alphas})
    stored: dict[str, dict[str, Any]] = {}
    if ids:
        stored = {
            str(r["alpha_id"]): r
            for r in await catalog.query(
                "SELECT alpha_id, sim_type, status, checks, classifications, simulation_mode "  # noqa: S608
                f"FROM alpha WHERE alpha_id IN {AMONG}",
                [packed(ids)],
            )
        }
    out: list[TaskYield] = []
    for row in running:
        if task_params(row).stopping:
            continue
        passing = refused = 0
        for alpha_id in recent.get(row.id, []):
            found = stored.get(alpha_id)
            if found is None:
                continue
            verdict = judge(found).verdict
            if verdict in PASSING:
                passing += 1
            elif verdict == Verdict.REFUSED:
                refused += 1
        out.append(
            TaskYield(
                study_id=row.id,
                name=row.label or row.name,
                task=row.task,
                cores=cores_of(row),
                passing=passing,
                refused=refused,
            )
        )
    return out


class Governor:
    def __init__(self, optimizer: Optimizer, catalog: Catalog) -> None:
        self.optimizer = optimizer
        self.catalog = catalog
        #: Settings: re-deal cores by yield. Off by default: it overrides the cores chosen.
        self.enabled = False
        self.last: dict[int, tuple[int, int]] = {}
        self._task: asyncio.Task[None] | None = None
        #: The draws every deal takes, kept so the API's suggestion and a deal share a stream.
        self.rng = random.Random()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="governor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(EVERY_SECONDS)
            if not self.enabled:
                continue
            try:
                await self.rebalance()
            # One failed deal must not end the loop.
            except Exception:
                log.warning("governor.failed", exc_info=True)

    async def rebalance(self) -> dict[int, tuple[int, int]]:
        """Re-deal the running tasks' cores. Returns study id → (before, after) for changes."""
        found = await yields(self.optimizer, self.catalog)
        if len(found) < 2:
            return {}
        target = deal(found, self.rng)
        changes = {
            y.study_id: (y.cores, target[y.study_id])
            for y in found
            if target[y.study_id] != y.cores
        }
        # Shrink first, so the cores a grower asks for are free when it asks.
        for study_id, (_, after) in sorted(changes.items(), key=lambda c: c[1][1] - c[1][0]):
            row = await self.optimizer.get(study_id)
            if row is None:
                continue
            refused = await resize_task(self.optimizer, row, after, None)
            if refused is not None:
                log.info("governor.no_room", study_id=study_id, wanted=after, free=refused)
        self.last = changes
        if changes:
            log.info("governor.dealt", changes=changes)
        return changes
