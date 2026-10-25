"""What the consultant chooses on the Settings screen, kept in ``harness.db``.

Every choice has a default, so an install that never opens Settings runs as the app does
out of the box.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select

from . import updates
from .brain.schemas import CheckResult
from .db.models import Preference
from .schemas import Out
from .themes import DEFAULT_THEMES, ThemeRule
from .vault import yields

#: The October entry the first calendar guessed before BRAIN's announcement.
LEGACY_THEME = "D1 Power Pool Oct`26 (analyst, model, news)"

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
    #: Screened-out points teach the search the models' estimate (steering) instead of
    #: being dropped. Off: the search learns only from BRAIN's results.
    screen_steer: bool = True
    #: Every 30 minutes, re-deal the cores the running tasks hold toward the tasks whose
    #: recent Alphas pass most often. Off: every task keeps the cores it was given.
    auto_balance_cores: bool = False
    #: Every half hour, queue the transplants the models like best, up to a daily budget of
    #: simulations. Off: transplants run only when you queue them.
    autopilot: bool = False
    autopilot_daily: int = Field(default=100, ge=10, le=2000)
    #: A backup when the last is this many days old; 0 turns the schedule off.
    auto_backup_days: Literal[0, 1, 7] = 7
    #: Lowest chance of passing every check a transplant needs to be queued.
    autopilot_min_chance: float = Field(default=0.4, ge=0.1, le=0.9)
    autopilot_cores: int = Field(default=2, ge=1, le=8)
    #: Region-agnostic universe the autopilot promotes families into; empty: it does not.
    autopilot_ra_universe: str = Field(default="", max_length=64)
    #: Read research feeds (arXiv quantitative finance, and any added below) twice a day.
    research: bool = True
    #: Atom or RSS feeds read beside arXiv's.
    research_feeds: list[str] = Field(default_factory=list, max_length=20)
    #: The Power Pool theme calendar, as BRAIN publishes it: the Current Theme tab tests
    #: Alphas against whichever rule is running today.
    power_pool_themes: list[ThemeRule] = Field(
        default_factory=lambda: [r.model_copy() for r in DEFAULT_THEMES], max_length=60
    )

    @field_validator("power_pool_themes")
    @classmethod
    def _announced(cls, rules: list[ThemeRule]) -> list[ThemeRule]:
        """A calendar saved with the first, guessed October entry gets BRAIN's announced
        rules instead (the dates and the PV1 rule were wrong), and the regular turnover
        theme if it is missing. A user's own entries are kept as they are."""
        names = {r.name for r in rules}
        if LEGACY_THEME not in names:
            return rules
        kept = [r for r in rules if r.name != LEGACY_THEME]
        have = {r.name for r in kept}
        return kept + [r.model_copy() for r in DEFAULT_THEMES if r.name not in have]

    #: Names of the built-in themes this calendar has been given, so a theme announced after
    #: the calendar was first saved still arrives, and one the user removed stays removed.
    themes_offered: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _newly_announced(self) -> Preferences:
        """Built-in themes the saved calendar has never been offered, and that have not ended,
        are added to it; every built-in name then counts as offered."""
        offered = set(self.themes_offered)
        have = {r.name for r in self.power_pool_themes}
        today = datetime.now().astimezone().date()
        self.power_pool_themes = self.power_pool_themes + [
            r.model_copy()
            for r in DEFAULT_THEMES
            if r.name not in offered and r.name not in have and r.end >= today
        ]
        self.themes_offered = sorted(offered | {r.name for r in DEFAULT_THEMES})
        return self


async def load(db: Database) -> Preferences:
    """Every choice, defaults filled in. Rows a newer build wrote are ignored."""
    async with db.session() as session:
        rows = await session.scalars(select(Preference))
        found = Preferences.model_validate({row.key: row.value for row in rows})
    theme_floors(found.power_pool_themes)
    return found


def theme_floors(rules: list[ThemeRule]) -> None:
    """Hand the check reader the sub-regions a Power Pool theme running today holds to a
    Sharpe floor, so their misses read as FAIL while it runs (see ``strict_sub_region``)."""
    today = datetime.now().astimezone().date()
    yields.set_theme_areas(
        frozenset(
            area.upper()
            for r in rules
            if r.power_pool and r.start <= today <= r.end
            for area in r.sub_region_sharpe
        )
    )


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
    state.optimizer.screen_steer = preferences.screen_steer
    state.governor.enabled = preferences.auto_balance_cores
    state.autopilot.configure(
        enabled=preferences.autopilot,
        daily=preferences.autopilot_daily,
        min_chance=preferences.autopilot_min_chance,
        cores=preferences.autopilot_cores,
        ra_universe=preferences.autopilot_ra_universe,
    )
    state.research.configure(enabled=preferences.research, feeds=preferences.research_feeds)
    state.daily_sync.configure(
        enabled=preferences.daily_sync,
        hour=preferences.daily_sync_hour,
        ra_every_days=preferences.ra_sync_days,
    )
