"""Competitions: what BRAIN is running, and where you stand in each.

BRAIN lists every competition with your status in it, but your rank only comes with one
competition at a time, so only the ongoing ones are read in full. Every reading is kept
(``standings.py``), so the screen can show how your rank moved.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from ..schemas import Out
from ..standings import history, ongoing, read_boards, record, when
from .deps import State

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


class CompetitionStanding(Out):
    rank: int | None
    alphas: int | None


class StandingPoint(Out):
    at: datetime
    rank: int | None
    alphas: int | None


class Competition(Out):
    id: str
    name: str
    #: BRAIN's word for your place in it, e.g. ``ACCEPTED`` or ``EXCLUDED``.
    status: str
    enrolled: bool
    ongoing: bool
    scoring: str | None
    start_date: str | None
    end_date: str | None
    sign_up_end_date: str | None
    faq: str | None
    #: Only for an ongoing competition you are enrolled in.
    standing: CompetitionStanding | None
    #: Your earlier readings, oldest first (ongoing competitions only).
    history: list[StandingPoint]


class Competitions(Out):
    competitions: list[Competition]


@router.get("")
async def competitions(state: State) -> Competitions:
    listed = await state.endpoints.competitions()
    now = datetime.now(UTC)
    # One competition BRAIN will not show (restricted, or a passing error) costs only its rank,
    # not the page.
    boards = await read_boards(state.endpoints, listed)
    await record(state.db, boards)
    past_readings = await history(state.db, [str(c["id"]) for c in listed if ongoing(c, now)])

    def row(c: dict[str, Any]) -> Competition:
        cid = str(c["id"])
        board = boards.get(cid)
        return Competition(
            id=cid,
            name=str(c.get("name") or cid),
            status=str(c.get("status") or ""),
            enrolled=c.get("signUpDate") is not None,
            ongoing=ongoing(c, now),
            scoring=c.get("scoring"),
            start_date=c.get("startDate"),
            end_date=c.get("endDate"),
            sign_up_end_date=c.get("signUpEndDate"),
            faq=c.get("faq"),
            standing=CompetitionStanding(rank=board.get("rank"), alphas=board.get("alphas"))
            if isinstance(board, dict)
            else None,
            history=[
                StandingPoint(at=p.at, rank=p.rank, alphas=p.alphas)
                for p in past_readings.get(cid, [])
            ],
        )

    rows = [row(c) for c in listed]

    # Ongoing first, soonest to end; then the rest, most recent first. By the moment, not the
    # text: BRAIN's offsets change with daylight saving, and text sorts ignore them.
    def ends(r: Competition) -> datetime:
        return when(r.end_date) or datetime.min.replace(tzinfo=UTC)

    live = sorted((r for r in rows if r.ongoing), key=ends)
    past = sorted((r for r in rows if not r.ongoing), key=ends, reverse=True)
    return Competitions(competitions=live + past)
