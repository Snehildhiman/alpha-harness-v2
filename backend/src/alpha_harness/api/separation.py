"""The type tabs: every stored Alpha, judged by its own type's rules.

Tabs: regular, region-agnostic (one row per family), Power Pool, current-theme Power Pool and
SuperAlpha, each split into submitted, submittable, pending (BRAIN still has checks to run)
and refused. See :mod:`alpha_harness.separation` for the rules.

The whole vault is judged at once (about a second for 50k Alphas) and kept until the vault
changes, so paging and switching tabs cost nothing.
"""

import asyncio
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from .. import preferences
from ..crowding import crowdmap
from ..crowding.crowdmap import Floor
from ..schemas import Out
from ..separation import (
    RA_MIN_REGIONS,
    Freshness,
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
from ..vault.store import SERIES_VERSION
from ..vault.yields import checks_of
from .deps import State, refuse

router = APIRouter(prefix="/api/separation", tags=["separation"])
log = structlog.get_logger(__name__)

#: Seconds a judgement of the whole vault is served before a change re-judges it.
REJUDGE_SECONDS = 20.0
#: BRAIN's prod-correlation limit.
PROD_LIMIT = 0.7

COLUMNS = (
    "alpha_id, expression, sim_type, instrument_type, region, delay, universe, neutralization, "
    "decay, truncation, sharpe, fitness, turnover, returns, drawdown, margin, long_count, "
    "short_count, status, checks, classifications, simulation_mode, date_created, train_sharpe, "
    "test_sharpe, after_cost_t10, checks_at"
)

#: Figures a tab can sort by.
SortKey = Literal["sharpe", "fitness", "turnover", "returns", "margin", "date_created"]

_cache: dict[str, Any] = {"key": None, "judged": []}
_floors: dict[str, Any] = {}
_floor_lock = asyncio.Lock()
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


async def judge_vault(state: State, *, force: bool = False) -> list[Judged]:
    """The whole vault, judged; recomputed only when the vault, the running theme or the
    synced catalog changed."""
    marker = await state.catalog.query(
        "SELECT (SELECT count(*) FROM alpha) AS n, (SELECT max(fetched_at) FROM alpha) AS t, "
        "(SELECT max(checks_at) FROM alpha) AS k, (SELECT max(synced_at) FROM data_field) AS c"
    )
    prefs = await preferences.load(state.db)
    rule = current(prefs.power_pool_themes, _today())
    now = datetime.now(UTC).replace(tzinfo=None)
    fresh = Freshness(now=now, max_age=timedelta(hours=prefs.correlation_fresh_hours))
    key = (
        tuple(str(v) for v in marker[0].values()) if marker else None,
        json.dumps(rule.model_dump(mode="json")) if rule else None,
        # Results age by the clock, not only by writes: re-judge at least hourly.
        prefs.correlation_fresh_hours,
        now.strftime("%Y-%m-%d %H"),
    )
    async with _lock:
        # While tasks run the vault changes every few seconds; judging 50k Alphas takes a few.
        # A judgement younger than REJUDGE_SECONDS is served as it stands.
        recent = time.monotonic() - _cache.get("at", float("-inf")) < REJUDGE_SECONDS
        if _cache["key"] != key and not (recent and _cache["key"] is not None and not force):
            rows = await state.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608 - constant
            theme = await _categories(state, rows, rule) if rule else None
            _cache["judged"] = await asyncio.to_thread(judge_all, rows, theme, fresh)
            _cache["key"] = key
            _cache["at"] = time.monotonic()
        return _cache["judged"]


#: Verdicts worth a crowd floor: the ones still hoping to pass prod correlation.
_HOPEFUL = frozenset({Verdict.SUBMITTABLE, Verdict.RECHECK, Verdict.PENDING})
#: Types judged on prod correlation.
_PROD_KINDS = frozenset({Kind.REGULAR, Kind.RA, Kind.SUPER})


def _family_floor(children: list[dict[str, Any]], found: dict[str, Floor]) -> Floor:
    """An RA family needs two regions: its floor is the second-lowest of its children's."""
    known = sorted(
        (f for c in children if (f := found.get(str(c.get("alpha_id")))) and f.value is not None),
        key=lambda f: f.value if f.value is not None else 0.0,
    )
    if len(known) < RA_MIN_REGIONS:
        return Floor(None)
    return known[RA_MIN_REGIONS - 1]


async def crowd_floors(state: State, judged: list[Judged]) -> dict[str, Floor]:
    """Each hopeful prod-correlation Alpha's local floor (:mod:`.crowding.crowdmap`), by the
    id its tab row carries.

    Incremental, because results land every few seconds while tasks run: an Alpha's floor is
    worked out once and kept until its region's landmarks change (a re-check reported a new
    prod correlation, or something was submitted). Alphas whose PnL had not arrived are tried
    again once it has.
    """
    stored = await state.catalog.query(
        "SELECT count(*) AS n FROM alpha WHERE coalesce(pnl_version, series_version) = ?",
        [SERIES_VERSION],
    )
    with_series = int(stored[0]["n"]) if stored else 0
    async with _floor_lock:
        if _floors.get("judged") is judged and _floors.get("series") == with_series:
            return _floors["out"]
        if _floors.get("judged") is not judged:
            every = [r for item in judged for r in (item.row, *item.children)]
            landmarks = crowdmap.landmarks_of(every)
            wanted: dict[str, list[str]] = {}
            for item in judged:
                j = item.judgement
                if j.kind not in _PROD_KINDS or j.verdict not in _HOPEFUL:
                    continue
                for row in item.children or [item.row]:
                    region = row.get("region")
                    if region and region in landmarks:
                        wanted.setdefault(str(region), []).append(str(row.get("alpha_id")))
            _floors.update(landmarks=landmarks, wanted=wanted)
        landmarks = _floors["landmarks"]
        wanted = _floors["wanted"]
        known: dict[str, Floor] = _floors.setdefault("per_alpha", {})
        signatures: dict[str, int] = _floors.setdefault("signatures", {})
        waiting: set[str] = _floors.setdefault("no_pnl", set())
        for region, marks in landmarks.items():
            signature = hash(tuple(sorted(marks.items())))
            if signatures.get(region) != signature:
                signatures[region] = signature
                for alpha_id in wanted.get(region, []):
                    known.pop(alpha_id, None)
        # PnL that has arrived since: those Alphas are measured again.
        retry = (
            [a for ids in wanted.values() for a in ids if a in waiting]
            if _floors.get("series") != with_series
            else []
        )
        if retry:
            arrived = {
                str(r["alpha_id"])
                for r in await state.catalog.query(
                    "SELECT alpha_id FROM alpha WHERE alpha_id IN (SELECT unnest(?)) "
                    "AND coalesce(pnl_version, series_version) = ?",
                    [retry, SERIES_VERSION],
                )
            }
            for alpha_id in arrived:
                waiting.discard(alpha_id)
                known.pop(alpha_id, None)
        measured = 0
        for region, ids in wanted.items():
            todo = [a for a in dict.fromkeys(ids) if a not in known]
            if not todo:
                continue
            marks = landmarks[region]
            grid = await state.alphas.pnl_grid([*todo, *marks])
            with_pnl = set(grid[0])
            found = await asyncio.to_thread(crowdmap.floors, grid, todo, marks)
            for alpha_id in todo:
                known[alpha_id] = found.get(alpha_id, Floor(None))
                if alpha_id not in with_pnl:
                    waiting.add(alpha_id)
            measured += len(todo)
        out: dict[str, Floor] = {}
        for item in judged:
            alpha_id = str(item.row.get("alpha_id"))
            floor = (
                _family_floor(item.children, known)
                if item.children
                else known.get(alpha_id, Floor(None))
            )
            if floor.value is not None:
                out[alpha_id] = floor
        if measured:
            log.info("separation.crowd_floors", measured=measured, rows=len(out))
        _floors.update(judged=judged, series=with_series, out=out)
        return out


def figure(item: Judged, key: str) -> Any:
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
    #: When BRAIN last judged it: its last re-check, else its simulation (UTC).
    checked_at: datetime | None
    #: The lowest prod correlation it can have, worked out locally from Alphas whose prod
    #: correlation BRAIN reported (RA families: the second-best region's), and the Alpha
    #: setting it, their correlation, and that Alpha's own prod correlation.
    crowd_floor: float | None = None
    crowd_via: str | None = None
    crowd_r: float | None = None
    crowd_p: float | None = None


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


def _row(item: Judged, floors: dict[str, Floor] | None = None) -> TabRow:
    j, r = item.judgement, item.row
    floor = (floors or {}).get(str(r.get("alpha_id")))
    return TabRow(
        crowd_floor=floor.value if floor else None,
        crowd_via=floor.via if floor else None,
        crowd_r=floor.r if floor else None,
        crowd_p=floor.p if floor else None,
        alpha_id=str(r.get("alpha_id")),
        expression=r.get("expression"),
        kind=j.kind.value,
        verdict=j.verdict.value,
        region=r.get("region"),
        delay=r.get("delay"),
        universe=r.get("universe"),
        neutralization=r.get("neutralization"),
        decay=r.get("decay"),
        sharpe=figure(item, "sharpe"),
        fitness=figure(item, "fitness"),
        turnover=figure(item, "turnover"),
        returns=figure(item, "returns"),
        margin=figure(item, "margin"),
        date_created=str(r["date_created"]) if r.get("date_created") else None,
        failed=[Issue(**asdict(i)) for i in j.failed],
        pending=j.pending,
        regions_passing=j.regions_passing,
        regions_tried=j.regions_tried,
        children=[str(c.get("alpha_id")) for c in item.children],
        theme_note=j.theme_note,
        # Stored naive UTC; sent with its zone so the browser does not read it as local.
        checked_at=j.checked_at.replace(tzinfo=UTC) if j.checked_at else None,
    )


@router.get("/summary")
async def get_summary(state: State) -> Summary:
    judged = await judge_vault(state)
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
    _cache["at"] = float("-inf")  # the tabs re-judge on the next read, not after the throttle
    return body


class TabFilter(BaseModel):
    """Narrowing for a tab: settings, figures, and the data an Alpha reads."""

    model_config = ConfigDict(populate_by_name=True)

    delay: int | None = None
    universe: str | None = None
    neutralization: str | None = None
    #: An Alpha reads at least one field of this dataset / data category.
    dataset: str | None = None
    category: str | None = None
    min_sharpe: float | None = Field(default=None, alias="minSharpe")
    min_fitness: float | None = Field(default=None, alias="minFitness")
    min_turnover: float | None = Field(default=None, alias="minTurnover")
    max_turnover: float | None = Field(default=None, alias="maxTurnover")
    #: Text the expression or the Alpha id contains.
    search: str | None = None
    #: Only read from a request body (a re-check); the tab takes ``region`` on its own.
    region: str | None = None

    def keeps(self, item: Judged, data: dict[str, tuple[set[str], set[str]]]) -> bool:
        row = item.row
        for key in ("delay", "universe", "neutralization"):
            wanted = getattr(self, key)
            if wanted is not None and wanted != "" and row.get(key) != wanted:
                return False

        def above(name: str, low: float | None) -> bool:
            value = figure(item, name)
            return low is None or (value is not None and value >= low)

        if not (above("sharpe", self.min_sharpe) and above("fitness", self.min_fitness)):
            return False
        if not above("turnover", self.min_turnover):
            return False
        if self.max_turnover is not None:
            value = figure(item, "turnover")
            if value is None or value > self.max_turnover:
                return False
        if self.search:
            needle = self.search.lower()
            text = f"{row.get('alpha_id') or ''} {row.get('expression') or ''}".lower()
            if needle not in text:
                return False
        if self.dataset or self.category:
            datasets, categories = data.get(str(row.get("expression") or ""), (set(), set()))
            if self.dataset and self.dataset not in datasets:
                return False
            if self.category and self.category not in categories:
                return False
        return True


_NO_FILTER = TabFilter()
#: Expression → the datasets and data categories of its fields, kept across requests.
_data: dict[str, Any] = {"stamp": None, "fields": {}, "by_expression": {}}


async def _data_of(state: State, judged: list[Judged]) -> dict[str, tuple[set[str], set[str]]]:
    """The datasets and categories every judged Alpha's expression reads."""
    (stamp,) = await state.catalog.query(
        "SELECT count(*) AS n, max(synced_at) AS t FROM data_field"
    )
    if _data["stamp"] != tuple(stamp.values()):
        rows = await state.catalog.query(
            "SELECT field_id, any_value(dataset_id) AS d, any_value(category_id) AS c "
            "FROM data_field GROUP BY field_id"
        )
        _data.update(
            stamp=tuple(stamp.values()),
            fields={str(r["field_id"]): (r["d"], r["c"]) for r in rows},
            by_expression={},
        )
    fields: dict[str, tuple[str | None, str | None]] = _data["fields"]
    out: dict[str, tuple[set[str], set[str]]] = _data["by_expression"]
    for item in judged:
        expression = str(item.row.get("expression") or "")
        if expression in out:
            continue
        datasets: set[str] = set()
        categories: set[str] = set()
        for name in fields_of(expression) or []:
            dataset, category = fields.get(name, (None, None))
            if dataset:
                datasets.add(str(dataset))
            if category:
                categories.add(str(category))
        out[expression] = (datasets, categories)
    return out


class Facet(Out):
    value: str
    alphas: int


class TabFacets(Out):
    regions: list[Facet]
    datasets: list[Facet]
    categories: list[Facet]
    universes: list[Facet]
    neutralizations: list[Facet]


@router.get("/facets")
async def facets(
    state: State,
    tab: Annotated[Kind, Query()],
    verdict: Annotated[Verdict, Query()] = Verdict.SUBMITTABLE,
) -> TabFacets:
    """What a tab's Alphas with one verdict are split by, with counts: the filter choices."""
    judged = await judge_vault(state)
    picked = [i for i in judged if in_tab(i, tab) and i.judgement.verdict == verdict]
    data = await _data_of(state, picked)
    counts: dict[str, Counter[str]] = {k: Counter() for k in TabFacets.model_fields}
    for item in picked:
        row = item.row
        regions = set(item.judgement.regions_tried) or {str(row.get("region") or "")}
        counts["regions"].update(r for r in regions if r)
        datasets, categories = data.get(str(row.get("expression") or ""), (set(), set()))
        counts["datasets"].update(datasets)
        counts["categories"].update(categories)
        if row.get("universe"):
            counts["universes"][str(row["universe"])] += 1
        if row.get("neutralization"):
            counts["neutralizations"][str(row["neutralization"])] += 1
    return TabFacets(
        **{k: [Facet(value=v, alphas=n) for v, n in c.most_common()] for k, c in counts.items()}
    )


@router.get("/alphas")
async def tab(
    state: State,
    tab: Annotated[Kind, Query()],
    verdict: Annotated[Verdict, Query()] = Verdict.SUBMITTABLE,
    region: Annotated[str | None, Query()] = None,
    sort: Annotated[SortKey, Query()] = "sharpe",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    filters: Annotated[TabFilter, Depends()] = _NO_FILTER,
) -> TabPage:
    """One tab's Alphas with one verdict, best first, narrowed by the filters."""
    judged = await judge_vault(state)
    data = await _data_of(state, judged) if filters.dataset or filters.category else {}
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
        and filters.keeps(item, data)
    ]
    descending = sort != "turnover"

    def order(item: Judged) -> tuple[bool, Any]:
        value = figure(item, sort) if sort != "date_created" else str(item.row.get(sort) or "")
        missing = value is None
        return (
            missing,
            (-value if descending else value) if isinstance(value, int | float) else value or "",
        )

    if sort == "date_created":
        picked.sort(key=lambda i: str(i.row.get("date_created") or ""), reverse=True)
    else:
        picked.sort(key=order)
    page = picked[offset : offset + limit]
    floors = await crowd_floors(state, judged) if tab in _PROD_KINDS else {}
    return TabPage(total=len(picked), rows=[_row(i, floors) for i in page])


class RecheckStarted(Out):
    task_id: str
    alphas: int


#: Most Alphas one re-check takes on: ``/check`` is slow and rate-limited.
RECHECK_MAX = 200


@router.post("/recheck")
async def recheck(
    state: State,
    tab: Annotated[Kind, Body()],
    verdict: Annotated[Verdict, Body()] = Verdict.RECHECK,
    limit: Annotated[int, Body(ge=1, le=RECHECK_MAX)] = 50,
    filters: Annotated[TabFilter | None, Body()] = None,
) -> RecheckStarted:
    """Re-run BRAIN's submission checks on a tab's best Alphas, without submitting.

    Fresh prod, Power Pool and self-correlation results replace the stored ones, so the tabs
    re-sort themselves as each answer lands. Spends no simulations. RA families are re-checked
    child by child.
    """
    vault = await judge_vault(state)
    judged = [i for i in vault if in_tab(i, tab) and i.judgement.verdict == verdict]
    if filters is not None:
        # The same Alphas the screen shows, so "Re-check top N" means the filtered top N.
        data = await _data_of(state, judged) if filters.dataset or filters.category else {}
        region = filters.region
        judged = [
            i
            for i in judged
            if filters.keeps(i, data)
            and (not region or region == i.row.get("region") or region in i.judgement.regions_tried)
        ]
    judged.sort(key=lambda i: -(figure(i, "sharpe") or float("-inf")))
    if tab in _PROD_KINDS:
        # An Alpha already crowded past the limit by the local floor cannot pass prod
        # correlation (bar BRAIN's Sharpe exception): BRAIN's slow check goes elsewhere.
        floors = await crowd_floors(state, vault)
        judged = [
            i
            for i in judged
            if (f := floors.get(str(i.row.get("alpha_id")))) is None
            or f.value is None
            or f.value < PROD_LIMIT
        ]
    ids: list[str] = []
    for item in judged[:limit]:
        rows = item.children or [item.row]
        ids.extend(str(r.get("alpha_id")) for r in rows)
    if not ids:
        raise refuse(409, "nothing_to_check", "No Alphas in this view to re-check.")

    async def work(task: Any) -> str:
        failed = 0
        for done, alpha_id in enumerate(ids, start=1):
            try:
                body = await state.endpoints.check_alpha(alpha_id)
                checks = (body.get("is") or {}).get("checks") or []
                if checks:
                    await state.alphas.save_checks(alpha_id, checks)
            # One Alpha that BRAIN will not check must not stop the rest.
            except Exception:  # noqa: BLE001
                failed += 1
            await state.tasks.update(
                task, progress=done / len(ids), detail=f"Re-checked {done} of {len(ids)} Alphas"
            )
        return f"Re-checked {len(ids) - failed} of {len(ids)} Alphas" + (
            f"; {failed} could not be read" if failed else ""
        )

    try:
        task_id = await state.backfill.start_job(
            "separation-recheck", f"Re-checking {len(ids)} {tab.value} Alphas", work
        )
    except RuntimeError as exc:
        raise refuse(409, "busy", str(exc)) from exc
    return RecheckStarted(task_id=task_id, alphas=len(ids))
