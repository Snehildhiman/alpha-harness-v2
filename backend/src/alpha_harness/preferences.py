"""What the consultant chooses on the Settings screen, kept in ``harness.db``.

Every choice has a default, so an install that never opens Settings runs as the app does
out of the box.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import Field
from sqlalchemy import select

from . import updates
from .brain.schemas import CheckResult
from .db.models import Preference
from .schemas import Out
from .themes import DEFAULT_THEMES, ThemeRule

if TYPE_CHECKING:
    from .db.sqlite import Database
    from .state import AppState


class Preferences(Out):
    #: Lend cores no running task holds to the tasks with more work than their own cores.
    #: Off by default: a task's cores are otherwise a ceiling as well as a reservation.
    lend_idle_cores: bool = False
    #: Ask the operating system not to sleep while simulations are pending.
    keep_awake: bool = True
    #: Regions whose simulations run in BRAIN's Quick mode: the same figures and the checks
    #: that score an Alpha, without correlation, Theme or Competition. GLB by default, where a
    #: batch was measured finishing 30% sooner; a Quick Alpha that passes is then run in Full.
    quick_regions: list[str] = Field(default_factory=lambda: ["GLB"], max_length=20)
    #: Download an Alpha's daily PnL as soon as it lands, when every check that gates it reads
    #: one of ``pnl_check_results``. A series a screen asks for still downloads either way.
    pnl_download: bool = True
    #: The default is the Alphas nothing refused, which is what was downloaded before this was
    #: a choice.
    pnl_check_results: list[CheckResult] = Field(
        default_factory=lambda: [CheckResult.PASS, CheckResult.WARNING, CheckResult.PENDING]
    )
    #: Cores a lab or tool starts a new task with, until changed in its own form.
    default_cores: int = Field(default=4, ge=1, le=8)
    #: Hours between looks at GitHub for a new release; 0 looks only when asked.
    update_check_hours: Literal[0, 1, 6, 24] = 1
    #: Install a new release by itself, once nothing is simulating. Off in v2: releases come
    #: from this fork's own repository, and an update should be a deliberate choice.
    auto_update: bool = False
    #: Download the data catalog once a day, so the crowding history (alpha and user counts
    #: per dataset and field over time) keeps growing.
    daily_sync: bool = True
    #: The local hour from which the day's download may start.
    daily_sync_hour: int = Field(default=6, ge=0, le=23)
    #: Days between downloads of the slow region-agnostic market; 0 never runs it by itself.
    ra_sync_days: Literal[0, 1, 2, 3, 7] = 3
    #: How many hours a passing prod or Power Pool correlation result is trusted. Past it, the
    #: Alpha moves from Submittable to Needs re-check: the pool moves as others submit.
    correlation_fresh_hours: int = Field(default=24, ge=1, le=720)
    #: Retrain the models by themselves once enough new results or re-checks arrive; a new set
    #: replaces the old only if it does at least as well on Alphas the old never saw.
    auto_retrain: bool = True
    #: Screening in the Search and Template Labs: each round asks this many times what it
    #: simulates and sends the candidates the models rate best. 1 sends every point asked.
    screen_factor: int = Field(default=4, ge=1, le=10)
    #: Share of each screened round picked at random, so the models keep learning.
    screen_explore: float = Field(default=0.2, ge=0.0, le=0.5)
    #: Every 30 minutes, re-deal the cores the running tasks hold toward the tasks whose
    #: recent Alphas pass most often. Off: every task keeps the cores it was given.
    auto_balance_cores: bool = False
    #: Read research feeds (arXiv quantitative finance, and any added below) twice a day.
    research: bool = True
    #: Atom or RSS feeds read beside arXiv's.
    research_feeds: list[str] = Field(default_factory=list, max_length=20)
    #: The Power Pool theme calendar, as BRAIN publishes it: the Current Theme tab tests
    #: Alphas against whichever rule is running today.
    power_pool_themes: list[ThemeRule] = Field(
        default_factory=lambda: [r.model_copy() for r in DEFAULT_THEMES], max_length=60
    )


async def load(db: Database) -> Preferences:
    """Every choice, defaults filled in. Rows a newer build wrote are ignored."""
    async with db.session() as session:
        rows = await session.scalars(select(Preference))
        return Preferences.model_validate({row.key: row.value for row in rows})


async def save(db: Database, preferences: Preferences) -> None:
    async with db.session() as session:
        # Stored under the Python names, which never change with the wire's spelling.
        for key, value in preferences.model_dump(mode="json", by_alias=False).items():
            await session.merge(Preference(key=key, value=value))


def apply(state: AppState, preferences: Preferences) -> None:
    """Hand every choice to the part of the app that acts on it. Takes effect at once."""
    state.engine.lend_idle_cores = preferences.lend_idle_cores
    state.engine.set_keep_awake(preferences.keep_awake)
    state.engine.quick_regions = frozenset(preferences.quick_regions)
    state.backfill.pnl_results = (
        frozenset(preferences.pnl_check_results) if preferences.pnl_download else frozenset()
    )
    updates.check_hours = preferences.update_check_hours
    updates.auto_install = preferences.auto_update
    state.predictors.auto = preferences.auto_retrain
    state.optimizer.screen_factor = preferences.screen_factor
    state.optimizer.screen_explore = preferences.screen_explore
    state.governor.enabled = preferences.auto_balance_cores
    state.research.configure(enabled=preferences.research, feeds=preferences.research_feeds)
    state.daily_sync.configure(
        enabled=preferences.daily_sync,
        hour=preferences.daily_sync_hour,
        ra_every_days=preferences.ra_sync_days,
    )
