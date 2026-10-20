"""The autopilot: what it has spent today, what it last did, and a round on demand."""

from fastapi import APIRouter

from ..schemas import Out
from .deps import State

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


class AutopilotStatus(Out):
    enabled: bool
    daily: int
    #: Simulations it queued in the last 24 hours.
    used: int
    #: One of its tasks is still unfinished, so it waits.
    busy: bool
    #: What its last round did.
    last: str | None


@router.get("")
async def status(state: State) -> AutopilotStatus:
    used, busy = await state.autopilot.spent()
    pilot = state.autopilot
    return AutopilotStatus(
        enabled=pilot.enabled, daily=pilot.daily, used=used, busy=busy, last=pilot.last
    )


@router.post("/run")
async def run_now(state: State) -> AutopilotStatus:
    """One round now, whether or not Settings turn it on (pressing the button is the choice)."""
    state.autopilot.last = await state.autopilot.tick()
    return await status(state)
