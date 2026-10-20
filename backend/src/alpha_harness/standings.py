"""Competition standings over time.

BRAIN shows your rank in an ongoing competition only as it is now. Reading it every few hours
and keeping each reading turns that into a line: whether the Alphas you submitted this week
moved you, and how fast the board around you moves. Only your own standing is read, through
the same endpoint the Competitions screen uses; nobody else's data is fetched.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from .db.models import CompetitionStanding

if TYPE_CHECKING:
    from collections.abc import Callable

    from .brain.endpoints import BrainEndpoints
    from .db.sqlite import Database

log = structlog.get_logger(__name__)

#: A new reading at most this often per competition; ranks move over days, not minutes.
MIN_GAP = timedelta(hours=1)
#: Seconds between background readings.
EVERY_SECONDS = 6 * 3600.0
#: Readings returned per competition.
HISTORY = 120


def when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def ongoing(c: dict[str, Any], now: datetime) -> bool:
    start, end = when(c.get("startDate")), when(c.get("endDate"))
    return start is not None and end is not None and start <= now <= end


async def record(db: Database, boards: dict[str, dict[str, Any]]) -> int:
    """Keep one reading per competition, unless the last is younger than ``MIN_GAP`` and
    says the same. Returns readings kept."""
    now = datetime.now(UTC)
    kept = 0
    async with db.session() as session:
        for cid, board in boards.items():
            rank, alphas = board.get("rank"), board.get("alphas")
            if rank is None and alphas is None:
                continue
            last = await session.scalar(
                select(CompetitionStanding)
                .where(CompetitionStanding.competition_id == cid)
                .order_by(CompetitionStanding.at.desc())
                .limit(1)
            )
            if last is not None and now - last.at < MIN_GAP:
                same = (last.rank, last.alphas) == (rank, alphas)
                if same:
                    continue
                last.rank, last.alphas, last.at = rank, alphas, now
            else:
                session.add(
                    CompetitionStanding(competition_id=cid, at=now, rank=rank, alphas=alphas)
                )
            kept += 1
        await session.commit()
    return kept


async def history(db: Database, ids: list[str]) -> dict[str, list[CompetitionStanding]]:
    """Competition id → its readings, oldest first."""
    out: dict[str, list[CompetitionStanding]] = {}
    async with db.session() as session:
        for cid in ids:
            rows = (
                await session.scalars(
                    select(CompetitionStanding)
                    .where(CompetitionStanding.competition_id == cid)
                    .order_by(CompetitionStanding.at.desc())
                    .limit(HISTORY)
                )
            ).all()
            out[cid] = list(reversed(rows))
    return out


async def read_boards(endpoints: BrainEndpoints, listed: list[dict[str, Any]]) -> dict[str, Any]:
    """Competition id → BRAIN's leaderboard entry for you, for every ongoing one."""
    now = datetime.now(UTC)
    live = [c for c in listed if ongoing(c, now)]
    details = await asyncio.gather(
        *(endpoints.competition(str(c["id"])) for c in live), return_exceptions=True
    )
    boards: dict[str, Any] = {}
    for c, d in zip(live, details, strict=True):
        if isinstance(d, BaseException):
            log.warning("competitions.detail_failed", competition=c.get("id"), error=str(d))
        elif isinstance(d.get("leaderboard"), dict):
            boards[str(d.get("id") or c["id"])] = d["leaderboard"]
    return boards


class Standings:
    """Reads your standing in every ongoing competition every few hours."""

    def __init__(
        self, db: Database, endpoints: BrainEndpoints, signed_in: Callable[[], bool]
    ) -> None:
        self.db = db
        self.endpoints = endpoints
        self.signed_in = signed_in
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="standings")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(EVERY_SECONDS)
            if not self.signed_in():
                continue
            try:
                listed = await self.endpoints.competitions()
                await record(self.db, await read_boards(self.endpoints, listed))
            # BRAIN being away for a while must not end the schedule.
            except Exception:
                log.warning("standings.failed", exc_info=True)
