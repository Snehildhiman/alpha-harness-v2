"""Current Theme Lab: simulate only Alphas that fit the running Power Pool theme. No LLM.

It is the Search Lab held to the theme's rule: the theme's delay, only datasets of the
categories it allows, one field per Alpha (so one category), no PV1 group fields
(industry, sector...) when the theme forbids them, so the group shapes, which group by
them, are left out, and within the Power Pool limits (every shape
the search writes reads one field through at most three operators). The space holds only
what the rule allows, so nothing that breaks the theme is spent on.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import preferences
from ..brain.schemas import FULL_MODE, QUICK_MODE
from ..catalog.queries import FieldFilter
from ..db.models import Trial, TrialState, utcnow
from ..labs import search, theme_templates
from ..labs.launch import (
    NO_SIMULATIONS,
    AddedTask,
    FieldCounts,
    SampleAlpha,
    SearchRequest,
    account_operators,
    add_study,
    preview_samples,
    startup_trials,
)
from ..labs.params import SEARCH_SAMPLER, SearchParams
from ..recent import Recent, StillReading
from ..schemas import Out
from ..separation import Kind, Verdict
from ..themes import ThemeRule, grouping_in, normalise, sub_region_sharpe
from ..tools import submit_rank
from . import search_lab
from . import separation as separation_api
from .deps import State, refuse

router = APIRouter(prefix="/api/theme-lab", tags=["theme-lab"])


class ThemeDataset(Out):
    dataset_id: str
    name: str | None
    category: str
    fields: int | None
    alphas: int | None
    #: BRAIN tags it as a theme dataset (the x1 badge).
    themed: bool
    #: Named in the theme's announcement as recommended; the lab starts from these.
    recommended: bool = False
    #: A less crowded sibling of a popular GLB dataset (see :data:`GLB_LESS_CROWDED`).
    less_crowded: bool = False


class ThemeMarket(Out):
    region: str
    datasets: list[ThemeDataset]


class ThemeLabOptions(Out):
    #: ``None``: no theme is running today; add it on Alpha Types → Current Theme.
    theme: ThemeRule | None
    rule: str | None
    delay: int | None
    markets: list[ThemeMarket]
    #: Power Pool themes running today or starting within :data:`UPCOMING_DAYS`, latest
    #: first; ``theme`` is the one these options are for.
    themes: list[ThemeRule] = Field(default_factory=list)


class ThemeLabRequest(BaseModel):
    region: str
    #: Which theme to search for, by name; empty: the latest-starting of :func:`_themes`.
    theme: str | None = None
    universe: str | None = None
    #: Searched universes; empty: every downloaded one.
    universes: list[str] = Field(default_factory=list, max_length=20)
    random_universe: bool = False
    #: Empty: every allowed dataset of the region.
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    neutralizations: list[str] = Field(default_factory=list, max_length=20)
    decay: int = 0
    cores: int = Field(default=search.MAX_CORES, ge=1, le=search.MAX_CORES)
    simulations: int = Field(default=0, ge=0, le=search.MAX_SIMULATIONS)
    vector_operators: list[str] = Field(default_factory=list)
    #: Templates to simulate, by name (``GET /templates``); empty: the built-in shapes only.
    templates: list[str] = Field(default_factory=list, max_length=len(theme_templates.TEMPLATES))
    #: Also search the lab's own shapes beside the chosen templates.
    search_shapes: bool = True
    #: ``FULL`` (a normal simulation, BRAIN's whole check list), ``QUICK`` (fewer checks,
    #: faster; a passing Alpha is re-run in Full), or ``AUTO``: as Settings choose per region.
    simulation_mode: Literal["FULL", "QUICK", "AUTO"] = "FULL"


class ThemeLabPreview(Out):
    theme: str | None
    fields: FieldCounts | None
    universes: list[str]
    offered_universes: list[str] = Field(default_factory=list)
    sample: list[SampleAlpha]
    problems: list[str]
    warnings: list[str]


#: GLB: each Alpha is standardised within its country (BRAIN's GLB notes: neutralizing by
#: country removes each country's mean, not its spread), by whichever of these the account has.
WITHIN_COUNTRY = ("group_rank", "group_zscore")
#: GLB: a field thinner than this leans the Alpha toward the sub-region that has it, and the
#: sub-region Sharpe floors fail on the others.
GLB_MIN_COVERAGE = 0.7
#: Less crowded GLB siblings of the most used datasets, each with submitted Alphas on record
#: (BRAIN's "Hidden Gems" note): offered beside the recommended ones.
GLB_LESS_CROWDED = ("tech_chart_model", "predictive_starmine", "model135", "analyst_consensus")

#: A theme starting within this many days can be searched for already: its Alphas are
#: simulated now and submitted once it opens.
UPCOMING_DAYS = 7


async def _themes(state: State) -> list[ThemeRule]:
    """Power Pool themes running today or starting soon, latest-starting first."""
    rules = (await preferences.load(state.db)).power_pool_themes
    today = datetime.now().astimezone().date()
    soon = today + timedelta(days=UPCOMING_DAYS)
    return sorted(
        (r for r in rules if r.power_pool and r.start <= soon and r.end >= today),
        key=lambda r: r.start,
        reverse=True,
    )


async def _theme(state: State, name: str | None = None) -> ThemeRule | None:
    found = await _themes(state)
    if name:
        return next((r for r in found if r.name == name), None)
    return found[0] if found else None


async def _allowed(state: State, rule: ThemeRule, region: str | None) -> list[dict[str, Any]]:
    """Datasets of the theme's categories, per region, at the theme's delay."""
    delay = rule.delay if rule.delay is not None else 1
    rows = await state.catalog.query(
        "SELECT region, dataset_id, any_value(name) AS name, any_value(category_id) AS category, "
        "max(field_count) AS fields, max(alpha_count) AS alphas, "
        "bool_or(themes IS NOT NULL AND themes NOT IN ('', '[]')) AS themed "
        "FROM data_set WHERE instrument_type = 'EQUITY' AND delay = ? AND category_id IS NOT NULL "
        + ("AND region = ? " if region else "")
        + "GROUP BY region, dataset_id ORDER BY region, max(alpha_count) NULLS LAST",
        [delay, region] if region else [delay],
    )
    allowed = {normalise(c) for c in rule.categories}
    regions = set(rule.regions)
    return [
        r
        for r in rows
        if (not allowed or normalise(str(r["category"])) in allowed)
        and (not regions or r["region"] in regions)
    ]


@router.get("/options")
async def options(state: State, theme: str | None = None) -> ThemeLabOptions:
    """The running (or chosen upcoming) theme and, per downloaded region, the datasets it
    allows, the recommended ones first."""
    themes = await _themes(state)
    rule = await _theme(state, theme)
    if rule is None:
        return ThemeLabOptions(theme=None, rule=None, delay=None, markets=[], themes=themes)
    recommended = {d.lower(): i for i, d in enumerate(rule.datasets)}
    by_region: dict[str, list[ThemeDataset]] = {}
    for r in await _allowed(state, rule, None):
        by_region.setdefault(str(r["region"]), []).append(
            ThemeDataset(
                dataset_id=str(r["dataset_id"]),
                name=r["name"],
                category=normalise(str(r["category"])),
                fields=r["fields"],
                alphas=r["alphas"],
                themed=bool(r["themed"]),
                recommended=str(r["dataset_id"]).lower() in recommended,
                less_crowded=r["region"] == "GLB" and str(r["dataset_id"]) in GLB_LESS_CROWDED,
            )
        )
    for found in by_region.values():
        # The announcement's order first, then the rest as the catalog listed them.
        found.sort(key=lambda d: recommended.get(d.dataset_id.lower(), len(recommended)))
    return ThemeLabOptions(
        theme=rule,
        rule=rule.describe(),
        delay=rule.delay,
        markets=[ThemeMarket(region=k, datasets=v) for k, v in sorted(by_region.items())],
        themes=themes,
    )


async def _plan(body: ThemeLabRequest, state: State) -> tuple[dict[str, Any], ThemeRule | None]:
    rule = await _theme(state, body.theme)
    if rule is None:
        return {
            "problems": [
                "No Power Pool theme is running today. Add it on Alpha Types → Current Theme."
            ],
            "warnings": [],
        }, None
    allowed = {str(r["dataset_id"]) for r in await _allowed(state, rule, body.region)}
    wanted = {x.lower() for x in rule.datasets}
    if body.region == "GLB":
        wanted |= set(GLB_LESS_CROWDED)
    recommended = [d for d in allowed if d.lower() in wanted]
    chosen = [d for d in body.dataset_ids if d in allowed] or sorted(recommended or allowed)
    outside = [d for d in body.dataset_ids if d not in allowed]
    plan = await search_lab.plan_search(
        SearchRequest(
            region=body.region,
            delay=rule.delay if rule.delay is not None else 1,
            universe=body.universe,
            universes=body.universes,
            random_universe=body.random_universe,
            dataset_ids=chosen,
            vector_operators=body.vector_operators,
            neutralizations=body.neutralizations,
            decay=body.decay,
            cores=body.cores,
            simulations=body.simulations,
            field_filter=FieldFilter(coverage_min=GLB_MIN_COVERAGE)
            if body.region == "GLB"
            else None,
        ),
        state,
    )
    if not allowed:
        plan["problems"].insert(
            0,
            f"No {body.region} dataset of the theme's categories is downloaded. Sync "
            f"{body.region} delay {rule.delay} first.",
        )
    if outside:
        plan["warnings"].append(
            f"{len(outside)} chosen datasets are outside the theme and are left out."
        )
    space = plan.get("space")
    if space is not None:
        await _templates_into(space, plan, body, rule, state)
    if space is not None and rule.no_grouping:
        # One field per shape keeps one category; dropping the group shapes keeps the rest.
        space["families"] = [
            f for f in space["families"] if not f.startswith("group") and f != "tpl"
        ] + (["tpl"] if "tpl" in space["families"] else [])
        space["group"] = []
        space["groups"] = []
        if not space["families"]:
            plan["problems"].append("Without the group shapes none of your operators fit a shape.")
    if space is not None and body.region == "GLB":
        _country_first(space, plan)
    if space is not None and not plan["problems"]:
        # Drawn again from the space as narrowed, so the sample shows what will be sent.
        run = SearchParams(
            region=body.region,
            delay=rule.delay or 0,
            decay=body.decay,
            space=space,
            simulation_mode=MODES[body.simulation_mode],
        )
        choices = search.field_choices(space)
        plan["sample"] = [
            s
            for s in preview_samples(
                lambda rng: search.reroll_universe(
                    search.request_for(
                        search.suggest(search.RandomTrial(rng), space, choices), run
                    ),
                    space,
                    rng,
                ),
                tries=8,
            )
            if not rule.no_grouping or grouping_in(s.expression) is None
        ]
    return plan, rule


#: The request's mode as the simulation settings name it; ``None`` leaves it to Settings.
MODES: dict[str, str | None] = {"FULL": FULL_MODE, "QUICK": QUICK_MODE, "AUTO": None}


class ThemeTemplateInfo(Out):
    name: str
    expression: str
    about: str
    low_turnover: bool
    suggested: bool
    #: Every operator it calls is on your account (and it reads no group field the theme forbids).
    available: bool
    #: Of its Alphas back from BRAIN, the share that passed, and how many came back.
    pass_rate: float | None = None
    tried: int = 0


@router.get("/templates")
async def templates(state: State, theme: str | None = None) -> list[ThemeTemplateInfo]:
    """The templates the lab can simulate, the suggested ones first."""
    rule = await _theme(state, theme)
    # The stored list only, never a fetch from BRAIN: this list must show at once.
    names = {str(o.get("name")) for o in await state.metadata.cached_operators() or []}
    grouping = rule is None or not rule.no_grouping
    # Operators not read yet (signed out): every template is offered, and the plan says why
    # it cannot run until they are.
    every = {o for t in theme_templates.TEMPLATES for o in t.operators()}
    ok = {t.name for t in theme_templates.usable(names or every, grouping=grouping)}
    try:
        rates = await _rates.get("rates", lambda: _template_rates(state), wait=RATES_WAIT)
    except StillReading:
        # Counted in the background: shown on the next visit, never waited for.
        rates = {}
    return sorted(
        (
            ThemeTemplateInfo(
                name=t.name,
                expression=t.expression,
                about=t.about,
                low_turnover=t.low_turnover,
                suggested=t.suggested,
                available=t.name in ok,
                pass_rate=rates.get(t.expression, (None, 0))[0],
                tried=rates.get(t.expression, (None, 0))[1],
            )
            for t in theme_templates.TEMPLATES
        ),
        key=lambda t: (not t.available, not t.suggested),
    )


#: Pass rates per template are counted over every trial: kept five minutes, and waited for
#: at most this long before the list is shown without them.
RATES_WAIT = 1.5
_rates = Recent(ttl=300)


async def _template_rates(state: State) -> dict[str, tuple[float | None, int]]:
    """Per template expression: the share of its Alphas back that passed, and how many."""
    template = func.json_extract(Trial.params, "$.template")
    async with state.db.session() as session:
        rows = (
            await session.execute(
                select(template, Trial.state, func.count())
                .where(
                    func.json_extract(Trial.params, "$.family") == "tpl",
                    Trial.state.in_([TrialState.COMPLETE, TrialState.FAIL]),
                )
                .group_by(template, Trial.state)
            )
        ).all()
        passed = (
            await session.execute(
                select(template, func.count())
                .where(
                    func.json_extract(Trial.params, "$.family") == "tpl",
                    Trial.state == TrialState.COMPLETE,
                    Trial.feasible.is_(True),
                )
                .group_by(template)
            )
        ).all()
    feasible: dict[str, int] = {str(e): int(n) for e, n in passed}
    tried: dict[str, int] = {}
    for expression, _, n in rows:
        tried[str(expression)] = tried.get(str(expression), 0) + int(n)
    return {e: ((feasible.get(e, 0) / n) if n else None, n) for e, n in tried.items()}


async def _templates_into(
    space: dict[str, Any],
    plan: dict[str, Any],
    body: ThemeLabRequest,
    rule: ThemeRule,
    state: State,
) -> None:
    """The chosen templates into the space, beside the built-in shapes or instead of them."""
    # Read only when templates are chosen: the built-in shapes have checked the operators.
    names = (
        {str(o.get("name")) for o in await account_operators(state, refresh=False)}
        if body.templates
        else set[str]()
    )
    usable = {t.name: t for t in theme_templates.usable(names, grouping=not rule.no_grouping)}
    chosen = [usable[n] for n in dict.fromkeys(body.templates) if n in usable]
    if skipped := [n for n in body.templates if n not in usable]:
        plan["warnings"].append(
            f"{len(skipped)} chosen templates need an operator your account lacks (or a group "
            "field the theme forbids) and are left out: " + ", ".join(skipped) + "."
        )
    shapes = list(space["families"]) if body.search_shapes else []
    if chosen:
        space["templates"] = [t.expression for t in chosen]
        shapes.append("tpl")
    if not shapes:
        plan["problems"].append("Choose at least one template, or keep the built-in shapes on.")
    space["families"] = shapes
    if body.simulation_mode == "QUICK" and not state.engine.quick_allowed:
        plan["warnings"].append(
            "Your account has no Quick mode, so BRAIN may refuse these; choose Full."
        )


def _country_first(space: dict[str, Any], plan: dict[str, Any]) -> None:
    """GLB: every Alpha standardised within its country, and country among the groups.

    BRAIN neutralizes a GLB Alpha against the global mean, so country effects stay in the
    signal and one sub-region can carry it; ranking or z-scoring within each country also
    evens out the scale of fields whose raw values differ by market.
    """
    ops = [op for op in WITHIN_COUNTRY if op in space.get("group", ())]
    if not ops:
        plan["warnings"].append(
            "Your account lacks group_rank and group_zscore, so GLB Alphas are not standardised "
            "within each country; expect one sub-region to dominate more often."
        )
        return
    space["within"] = {"group": "country", "ops": ops}
    if space.get("groups") is not None and "country" not in space["groups"]:
        space["groups"] = ["country", *space["groups"]]


@router.post("/preview")
async def preview(body: ThemeLabRequest, state: State) -> ThemeLabPreview:
    """What a task would search, held to the theme. Free; queues nothing."""
    plan, rule = await _plan(body, state)
    return ThemeLabPreview.model_validate(
        {
            "theme": rule.describe() if rule else None,
            "fields": plan.get("fields"),
            "universes": plan.get("universes", []),
            "offeredUniverses": plan.get("offeredUniverses", []),
            "sample": plan.get("sample", []),
            "problems": plan["problems"],
            "warnings": plan["warnings"],
        }
    )


@router.post("/tasks", status_code=201)
async def add_task(body: ThemeLabRequest, state: State) -> AddedTask:
    """Add the theme search to Tasks and start it."""
    if body.simulations < 1:
        raise refuse(422, "no_simulations", NO_SIMULATIONS)
    plan, rule = await _plan(body, state)
    if plan["problems"] or rule is None:
        raise refuse(422, "theme_blocked", plan["problems"][0])
    per_round = plan["round"]
    delay = rule.delay if rule.delay is not None else 1
    return await add_study(
        state,
        now=utcnow(),
        sampler=SEARCH_SAMPLER,
        params=SearchParams(
            space=plan["space"],
            region=body.region,
            delay=delay,
            decay=body.decay,
            cores=body.cores,
            dataset_ids=body.dataset_ids,
            simulation_mode=MODES[body.simulation_mode],
            n_startup_trials=startup_trials(
                len(plan["space"]["fields"]), body.simulations, per_round
            ),
        ),
        simulations=body.simulations,
        batch_size=per_round,
        template_source=f"# Current Theme Lab: {rule.describe()}",
        template_name=f"Current Theme · {rule.name}",
        label=f"Current Theme · {body.region} · {rule.name}"[:128],
        # A theme with a sub-region floor is judged on its combination (BC and AC Combo IR,
        # OS Score): scored before and after cost, out of sample, under the floor.
        objective="theme_combo" if rule.sub_region_sharpe else None,
        run=True,
    )


# -- what to submit next for the theme's combination -----------------------------------------

#: Candidates combined per request, strongest Sharpe first.
COMBO_CANDIDATES = 300


class ComboFigures(Out):
    """A combination's four figures, as a theme ranks it."""

    bc_ir: float | None
    ac_ir: float | None
    os_ir: float | None
    ac_os_ir: float | None
    #: Estimated Merged PnL: the merged book's total PnL, in dollars.
    pnl: float | None = None


class ComboRow(Out):
    alpha_id: str
    expression: str | None
    sharpe: float | None
    turnover: float | None
    amer_sharpe: float | None
    apac_sharpe: float | None
    emea_sharpe: float | None
    verdict: str
    #: The theme's combination with this Alpha added, and the change it makes.
    combo: ComboFigures
    delta: ComboFigures
    #: Weighted mean of the four IR changes, BC and AC first: the order to submit in.
    score: float | None
    max_correlation: float | None
    max_correlation_with: str | None


class ThemeCombo(Out):
    theme: str | None
    #: Your Alphas submitted for the theme (in its dates, fitting its rule) with a series.
    pool: int
    now: ComboFigures
    cost_bps: float
    #: Submit in this order: each is chosen against the pool and the picks before it.
    picks: list[ComboRow]
    #: Every candidate on its own against the pool, best first.
    rows: list[ComboRow]
    candidates: int
    #: Left out for now: their daily PnL is being downloaded (no quota spent).
    downloading: int


def _figures(c: Any) -> ComboFigures:
    return ComboFigures(bc_ir=c.bc_ir, ac_ir=c.ac_ir, os_ir=c.os_ir, ac_os_ir=c.ac_os_ir, pnl=c.pnl)


@router.get("/combo")
async def combo(
    state: State,
    theme: str | None = None,
    cost_bps: Annotated[float, Query(alias="costBps", ge=0, le=100)] = 5.0,
    picks: Annotated[int, Query(ge=1, le=30)] = 10,
) -> ThemeCombo:
    """Your submittable Alphas that fit the theme, ranked by what each adds to the theme's
    combination: Combo IR before and after cost, and the same over the last two years (the
    out-of-sample proxy), before and after cost. Spends no quota; a missing daily PnL is
    downloaded in the background for the next visit."""
    rule = await _theme(state, theme)
    empty = ComboFigures(bc_ir=None, ac_ir=None, os_ir=None, ac_os_ir=None)
    if rule is None:
        return ThemeCombo(
            theme=None, pool=0, now=empty, cost_bps=cost_bps, picks=[], rows=[], candidates=0,
            downloading=0,
        )  # fmt: skip
    judged = await separation_api.judge_vault(state)
    power_pool = [
        i
        for i in judged
        if i.judgement.kind in (Kind.POWER_POOL, Kind.THEME)
        and i.judgement.verdict in (Verdict.SUBMITTED, Verdict.SUBMITTABLE, Verdict.RECHECK)
        and (rule.delay is None or i.row.get("delay") == rule.delay)
        and (not rule.regions or i.row.get("region") in rule.regions)
    ]
    fits = await separation_api.theme_check(state, [i.row for i in power_pool], rule)
    themed = [i for i in power_pool if fits(i.row)[0]]
    submitted = [str(i.row["alpha_id"]) for i in themed if i.judgement.verdict == Verdict.SUBMITTED]
    stored = await state.alphas.by_ids(submitted)

    def in_window(alpha_id: str) -> bool:
        when = (stored.get(alpha_id) or {}).get("date_submitted")
        day = when.date() if isinstance(when, datetime) else None
        return day is None or rule.start <= day <= rule.end

    pool = [a for a in submitted if in_window(a)]
    ranked = sorted(
        (i for i in themed if i.judgement.verdict != Verdict.SUBMITTED),
        key=lambda i: -(i.row.get("sharpe") or float("-inf")),
    )[:COMBO_CANDIDATES]
    candidates = [str(i.row["alpha_id"]) for i in ranked]
    lacking = await state.alphas.lacking_series([*pool, *candidates])
    if lacking:
        state.backfill.schedule_returns(lacking)
    ids = [a for a in dict.fromkeys([*pool, *candidates]) if a not in set(lacking)]
    series = await state.alphas.series(ids)
    meta = await state.alphas.by_ids(ids)
    now, order, each = await asyncio.to_thread(
        submit_rank.theme_combo,
        series,
        meta,
        [a for a in pool if a in series],
        [a for a in candidates if a in series],
        picks=picks,
        cost_bps=cost_bps,
    )
    rows_by_id = {str(i.row["alpha_id"]): i for i in ranked}

    def row(p: submit_rank.ComboPick) -> ComboRow:
        item = rows_by_id.get(p.alpha_id)
        r = item.row if item else {}
        return ComboRow(
            alpha_id=p.alpha_id,
            expression=r.get("expression"),
            sharpe=r.get("sharpe"),
            turnover=r.get("turnover"),
            amer_sharpe=sub_region_sharpe(r.get("checks"), "AMER"),
            apac_sharpe=sub_region_sharpe(r.get("checks"), "APAC"),
            emea_sharpe=sub_region_sharpe(r.get("checks"), "EMEA"),
            verdict=item.judgement.verdict.value if item else "",
            combo=_figures(p.combo),
            delta=_figures(p.delta),
            score=p.score,
            max_correlation=p.max_correlation,
            max_correlation_with=p.max_correlation_with,
        )

    return ThemeCombo(
        theme=rule.name,
        pool=len([a for a in pool if a in series]),
        now=_figures(now),
        cost_bps=cost_bps,
        picks=[row(p) for p in order],
        rows=[row(p) for p in each[:100]],
        candidates=len(candidates),
        downloading=len(lacking),
    )
