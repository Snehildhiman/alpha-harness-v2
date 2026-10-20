"""The governor: each running task's yield, and cores re-dealt toward the best."""

from fastapi import APIRouter

from ..governor import deal, yields
from ..schemas import Out
from .deps import State

router = APIRouter(prefix="/api/governor", tags=["governor"])


class TaskYieldRow(Out):
    study_id: int
    name: str
    cores: int
    passing: int
    refused: int
    #: Share of judged Alphas that pass; ``None`` before any are judged.
    rate: float | None
    #: Cores a deal would give it now (a fresh draw, so it moves a little each time).
    suggested: int


class GovernorStatus(Out):
    enabled: bool
    tasks: list[TaskYieldRow]
    #: The last re-deal: study id → [before, after].
    last: dict[int, tuple[int, int]]


@router.get("")
async def status(state: State) -> GovernorStatus:
    found = await yields(state.optimizer, state.catalog)
    suggested = deal(found, state.governor.rng)
    return GovernorStatus(
        enabled=state.governor.enabled,
        tasks=[
            TaskYieldRow(
                study_id=y.study_id,
                name=y.name,
                cores=y.cores,
                passing=y.passing,
                refused=y.refused,
                rate=y.rate,
                suggested=suggested.get(y.study_id, y.cores),
            )
            for y in found
        ],
        last=state.governor.last,
    )


@router.post("/rebalance")
async def rebalance(state: State) -> dict[int, tuple[int, int]]:
    """Re-deal the running tasks' cores by yield now, whether or not it runs by itself."""
    return await state.governor.rebalance()
