"""The type tabs: every stored Alpha, judged by its own type's rules.

Tabs: regular, region-agnostic (one row per family), Power Pool, current-theme Power Pool and
SuperAlpha, each split into submitted, submittable, pending (BRAIN still has checks to run)
and refused. See :mod:`alpha_harness.separation` for the rules.

The whole vault is judged at once (about a second for 50k Alphas) and kept until the vault
changes, so paging and switching tabs cost nothing.
"""

import asyncio
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from ..schemas import Out
from ..separation import Judged, Kind, Verdict, in_tab, judge_all, summary
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


async def _judged(state: State) -> list[Judged]:
    """The whole vault, judged; recomputed only when the vault changed."""
    marker = await state.catalog.query("SELECT count(*) AS n, max(fetched_at) AS t FROM alpha")
    key = (marker[0]["n"], str(marker[0]["t"])) if marker else None
    async with _lock:
        if _cache["key"] != key:
            rows = await state.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608 - constant
            _cache["judged"] = await asyncio.to_thread(judge_all, rows)
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


class TabPage(Out):
    total: int
    rows: list[TabRow]


class Summary(Out):
    #: tab -> verdict -> count. Current-theme Alphas also count under Power Pool.
    counts: dict[str, dict[str, int]]
    alphas: int


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
    )


@router.get("/summary")
async def get_summary(state: State) -> Summary:
    judged = await _judged(state)
    return Summary(counts=summary(judged), alphas=len(judged))


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
