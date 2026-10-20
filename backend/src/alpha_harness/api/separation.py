"""The type tabs: every stored Alpha, judged by its own type's rules.

Tabs: regular, region-agnostic (one row per family), Power Pool, current-theme Power Pool and
SuperAlpha, each split into submitted, submittable, pending (BRAIN still has checks to run)
and refused. See :mod:`alpha_harness.separation` for the rules.

The whole vault is judged at once (about a second for 50k Alphas) and kept until the vault
changes, so paging and switching tabs cost nothing.
"""

import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from .. import preferences
from ..schemas import Out
from ..separation import (
    Judged,
    Kind,
    ThemeCheck,
    Verdict,
    in_tab,
    is_power_pool_row,
    judge_all,
    summary,
)
from ..themes import ThemeRule, check, current, fields_of
from ..vault.yields import checks_of
from .deps import State

router = APIRouter(prefix="/api/separation", tags=["separation"])

COLUMNS = (
    "alpha_id, expression, sim_type, instrument_type, region, delay, universe, neutralization, "
    "decay, truncation, sharpe, fitness, turnover, returns, drawdown, margin, long_count, "
    "short_count, status, checks, classifications, simulation_mode, date_created, train_sharpe, "
    "test_sharpe, after_cost_t10"
)

#: Figures a tab can sort by.
SortKey = Literal["sharpe", "fitness", "turnover", "returns", "margin", "date_created"]

_cache: dict[str, Any] = {"key": None, "judged": []}
_lock = asyncio.Lock()


def _today() -> date:
    return datetime.now().astimezone().date()


async def _running_theme(state: State) -> ThemeRule | None:
    rules = (await preferences.load(state.db)).power_pool_themes
    return current(rules, _today())


async def _categories(state: State, rows: list[dict[str, Any]], rule: ThemeRule) -> ThemeCheck:
    """The running theme as a check on one row, with every field's category read from the
    synced catalog once, for just the fields Power Pool Alphas use."""
    wanted: set[str] = set()
    for row in rows:
        if rule.delay is not None and row.get("delay") != rule.delay:
            continue
        if not is_power_pool_row(row, checks_of(row.get("checks"))):
            continue
        wanted.update(fields_of(row.get("expression")) or [])
    by_scope: dict[tuple[str, str, int], str] = {}
    by_field: dict[str, str] = {}
    if wanted:
        found = await state.catalog.query(
            "SELECT field_id, region, delay, any_value(category_id) AS cat "
            "FROM data_field WHERE field_id IN (SELECT unnest(?)) AND category_id IS NOT NULL "
            "GROUP BY field_id, region, delay",
            [sorted(wanted)],
        )
        for f in found:
            by_scope[(f["field_id"], f["region"], int(f["delay"]))] = f["cat"]
            by_field.setdefault(f["field_id"], f["cat"])

    def category_of(name: str, region: str, delay: int) -> str | None:
        # The field's own market first; another market's category is the same dataset's.
        return by_scope.get((name, region, delay)) or by_field.get(name)

    def theme(row: dict[str, Any]) -> tuple[bool, str]:
        return check(
            rule,
            expression=row.get("expression"),
            region=row.get("region"),
            delay=row.get("delay"),
            category_of=category_of,
        )

    return theme


async def _judged(state: State) -> list[Judged]:
    """The whole vault, judged; recomputed only when the vault, the running theme or the
    synced catalog changed."""
    marker = await state.catalog.query(
        "SELECT (SELECT count(*) FROM alpha) AS n, (SELECT max(fetched_at) FROM alpha) AS t, "
        "(SELECT max(synced_at) FROM data_field) AS c"
    )
    rule = await _running_theme(state)
    key = (
        tuple(str(v) for v in marker[0].values()) if marker else None,
        json.dumps(rule.model_dump(mode="json")) if rule else None,
    )
    async with _lock:
        if _cache["key"] != key:
            rows = await state.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608 - constant
            theme = await _categories(state, rows, rule) if rule else None
            _cache["judged"] = await asyncio.to_thread(judge_all, rows, theme)
            _cache["key"] = key
        return _cache["judged"]


def _figure(item: Judged, key: str) -> Any:
    """A row's figure; an RA family shows its best passing (else best) child's."""
    if not item.children:
        return item.row.get(key)
    passing = set(item.judgement.regions_passing)
    pool = [c for c in item.children if str(c.get("region")) in passing] or item.children
    values = [float(v) for c in pool if isinstance(v := c.get(key), int | float)]
    if not values:
        return None
    return max(values) if key != "turnover" else min(values)


class Issue(Out):
    name: str
    result: str
    value: Any = None
    limit: Any = None


class TabRow(Out):
    alpha_id: str
    expression: str | None
    kind: str
    verdict: str
    region: str | None
    delay: int | None
    universe: str | None
    neutralization: str | None
    decay: int | None
    sharpe: float | None
    fitness: float | None
    turnover: float | None
    returns: float | None
    margin: float | None
    date_created: str | None
    failed: list[Issue]
    pending: list[str]
    regions_passing: list[str]
    regions_tried: list[str]
    children: list[str]
    #: Power Pool rows: how the running theme reads this Alpha.
    theme_note: str | None


class TabPage(Out):
    total: int
    rows: list[TabRow]


class RunningTheme(Out):
    name: str
    rule: str
    start: date
    end: date


class Summary(Out):
    #: tab -> verdict -> count. Current-theme Alphas also count under Power Pool.
    counts: dict[str, dict[str, int]]
    alphas: int
    #: The theme running today, from the calendar in Settings; ``None`` between themes.
    theme: RunningTheme | None


def _row(item: Judged) -> TabRow:
    j, r = item.judgement, item.row
    return TabRow(
        alpha_id=str(r.get("alpha_id")),
        expression=r.get("expression"),
        kind=j.kind.value,
        verdict=j.verdict.value,
        region=r.get("region"),
        delay=r.get("delay"),
        universe=r.get("universe"),
        neutralization=r.get("neutralization"),
        decay=r.get("decay"),
        sharpe=_figure(item, "sharpe"),
        fitness=_figure(item, "fitness"),
        turnover=_figure(item, "turnover"),
        returns=_figure(item, "returns"),
        margin=_figure(item, "margin"),
        date_created=str(r["date_created"]) if r.get("date_created") else None,
        failed=[Issue(**asdict(i)) for i in j.failed],
        pending=j.pending,
        regions_passing=j.regions_passing,
        regions_tried=j.regions_tried,
        children=[str(c.get("alpha_id")) for c in item.children],
        theme_note=j.theme_note,
    )


@router.get("/summary")
async def get_summary(state: State) -> Summary:
    judged = await _judged(state)
    rule = await _running_theme(state)
    running = (
        RunningTheme(name=rule.name, rule=rule.describe(), start=rule.start, end=rule.end)
        if rule
        else None
    )
    return Summary(counts=summary(judged), alphas=len(judged), theme=running)


@router.get("/themes")
async def get_themes(state: State) -> list[ThemeRule]:
    """The Power Pool theme calendar."""
    return (await preferences.load(state.db)).power_pool_themes


@router.put("/themes")
async def put_themes(body: list[ThemeRule], state: State) -> list[ThemeRule]:
    """Replace the theme calendar; the tabs re-judge on the next read."""
    current_prefs = await preferences.load(state.db)
    updated = current_prefs.model_copy(update={"power_pool_themes": body})
    await preferences.save(state.db, updated)
    preferences.apply(state, updated)
    return body


@router.get("/alphas")
async def tab(
    state: State,
    tab: Annotated[Kind, Query()],
    verdict: Annotated[Verdict, Query()] = Verdict.SUBMITTABLE,
    region: Annotated[str | None, Query()] = None,
    sort: Annotated[SortKey, Query()] = "sharpe",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TabPage:
    """One tab's Alphas with one verdict, best first."""
    judged = await _judged(state)
    picked = [
        item
        for item in judged
        if in_tab(item, tab)
        and item.judgement.verdict == verdict
        and (
            region is None
            or region == item.row.get("region")
            or region in item.judgement.regions_tried
        )
    ]
    descending = sort != "turnover"

    def order(item: Judged) -> tuple[bool, Any]:
        value = _figure(item, sort) if sort != "date_created" else str(item.row.get(sort) or "")
        missing = value is None
        return (
            missing,
            (-value if descending else value) if isinstance(value, int | float) else value or "",
        )

    if sort == "date_created":
        picked.sort(key=lambda i: str(i.row.get("date_created") or ""), reverse=True)
    else:
        picked.sort(key=order)
    return TabPage(total=len(picked), rows=[_row(i) for i in picked[offset : offset + limit]])
