"""Repair: find near-misses, generate variants, let the models pick, simulate the best few."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query

from ..brain.schemas import (
    FULL_MODE,
    REGION_AGNOSTIC_REGION,
    SimulationRequest,
    SimulationSettings,
)
from ..db.models import utcnow
from ..engine.packer import MAX_BATCH
from ..engine.slots import DEFAULT_SLOTS
from ..labs.launch import AddedTask, account_operators, add_study
from ..labs.params import CORRELATION_BREAKER, BreakerParams
from ..repair.generate import Reshape, Variant, variants
from ..repair.rank import Score, at_least, near_miss, score
from ..repair.transplant import Markets, Promotion, Transplant, promotions, ran_in, transplants
from ..schemas import Out
from ..separation import RA_MIN_REGIONS, Judged, Kind, Verdict
from ..tools import correlation_breaker, settings_sampler
from .deps import State, refuse
from .separation import (
    NO_FILTER,
    Issue,
    TabFacets,
    TabFilter,
    data_of,
    facets_of,
    figure,
    judge_vault,
)

router = APIRouter(prefix="/api/repair", tags=["repair"])

#: Tabs that hold repairable Alphas. RA families have their own pipeline.
REPAIRABLE = (Kind.REGULAR, Kind.RA, Kind.POWER_POOL, Kind.THEME, Kind.SUPER)
#: Where an RA family's regions are unknown (its children not stored yet), these are scored.
RA_REGIONS = ("USA", "EUR", "ASI")
#: Variants returned to the screen; the task takes from the top of these.
SHOWN = 60


class NearMiss(Out):
    alpha_id: str
    expression: str | None
    kind: str
    region: str | None
    sharpe: float | None
    fitness: float | None
    #: 0 at the limits, 1 at the edge of what counts as narrow.
    gap: float
    failed: list[Issue]


async def _repairable(state: State, tab: Kind | None, region: str | None) -> list[Judged]:
    return [
        item
        for item in await judge_vault(state)
        if item.judgement.kind in REPAIRABLE
        and (tab is None or item.judgement.kind == tab)
        and (
            not region or region == item.row.get("region") or region in item.judgement.regions_tried
        )
        and item.judgement.verdict == Verdict.REFUSED
    ]


@router.get("/near-misses/facets")
async def near_miss_facets(state: State, tab: Annotated[Kind | None, Query()] = None) -> TabFacets:
    """What the near-misses are split by, with counts: the filter choices."""
    near = [i for i in await _repairable(state, tab, None) if near_miss(i) is not None]
    return await facets_of(state, near)


@router.get("/near-misses")
async def near_misses(
    state: State,
    tab: Annotated[Kind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    region: Annotated[str | None, Query()] = None,
    filters: Annotated[TabFilter, Depends()] = NO_FILTER,
) -> list[NearMiss]:
    """Refused Alphas whose every failure is narrow, nearest first, narrowed by the filters."""
    found: list[tuple[float, Any]] = []
    candidates = await _repairable(state, tab, region)
    wanted = filters.dataset or filters.category or filters.theme
    data = await data_of(state, candidates) if wanted else {}
    for item in candidates:
        if not filters.keeps(item, data):
            continue
        gap = near_miss(item)
        if gap is not None:
            found.append((gap, item))
    found.sort(key=lambda g: (g[0], -(figure(g[1], "sharpe") or 0)))
    return [
        NearMiss(
            alpha_id=str(item.row.get("alpha_id")),
            expression=item.row.get("expression"),
            kind=item.judgement.kind.value,
            region=item.row.get("region"),
            sharpe=figure(item, "sharpe"),
            fitness=figure(item, "fitness"),
            gap=gap,
            failed=[
                Issue(name=i.name, result=i.result, value=i.value, limit=i.limit)
                for i in item.judgement.failed
            ],
        )
        for gap, item in found[:limit]
    ]


class RepairVariant(Out):
    id: str
    edit: str
    family: str
    expression: str
    neutralization: str | None
    decay: int | None
    truncation: float | None
    p_all: float | None
    p_correlation: float | None
    correlation: float | None
    sharpe: float | None
    fitness: float | None
    #: RA only: each region's chance of passing everything. ``p_all`` is then the chance that
    #: at least two do, which is what BRAIN needs to take the family.
    regions: dict[str, float] | None = None


class RepairPlan(Out):
    alpha_id: str
    expression: str
    kind: str
    power_pool: bool
    region: str
    #: Every variant generated; ``variants`` holds the best of them.
    generated: int
    #: False until the models are trained: variants are then in generation order.
    ranked: bool
    variants: list[RepairVariant]
    problems: list[str]


async def _plan(
    state: State, alpha_id: str
) -> tuple[RepairPlan, list[tuple[Variant, Score | None]], dict[str, Any]]:
    found = await correlation_breaker.plan(state, alpha_id)
    expression = str(found.get("expression") or "")
    settings: dict[str, Any] = dict(found.get("rawSettings") or {})
    power_pool = bool(found.get("powerPool"))
    region_agnostic = str(settings.get("region") or "") == REGION_AGNOSTIC_REGION
    kind = Kind.RA if region_agnostic else Kind.POWER_POOL if power_pool else Kind.REGULAR
    problems = list(found.get("problems") or [])
    candidates: list[Variant] = []
    if expression and not problems:
        blocked = {r["id"] for r in found["recipes"] if r["blocked"]}
        compressed = correlation_breaker.compress(expression)
        reshapes = [
            Reshape(r.id, r.name, compressed.program(r.tail, r.setup))
            for r in found["recipeSet"]
            if r.id not in blocked and r.tail
        ]
        operators = {
            str(o.get("name"))
            for o in await account_operators(state, refresh=False)
            if o.get("name")
        }
        universes = (
            []
            if region_agnostic
            else [
                str(r["universe"])
                for r in await state.catalog.query(
                    "SELECT DISTINCT universe FROM data_field "
                    "WHERE region = ? AND delay = ? ORDER BY universe",
                    [str(settings.get("region") or ""), int(settings.get("delay") or 0)],
                )
            ]
        )
        candidates = variants(
            expression,
            settings,
            reshapes=reshapes,
            operators=operators,
            power_pool=power_pool,
            universes=universes,
        )
    scored: list[tuple[Variant, Score | None]] = [(v, None) for v in candidates]
    per_region: dict[str, dict[str, float]] = {}
    ranked = await state.predictors.current() is not None
    if ranked and candidates:
        markets = await _ra_markets(state, alpha_id, settings) if region_agnostic else {}
        scored, per_region = await _score(state, candidates, kind, power_pool, markets)
    shown = [
        RepairVariant(
            id=v.id,
            edit=v.edit,
            family=v.family,
            expression=v.expression,
            neutralization=v.settings.get("neutralization"),
            decay=v.settings.get("decay"),
            truncation=v.settings.get("truncation"),
            p_all=s.p_all if s else None,
            p_correlation=s.p_correlation if s else None,
            correlation=s.correlation if s else None,
            sharpe=s.sharpe if s else None,
            fitness=s.fitness if s else None,
            regions=per_region.get(v.id),
        )
        for v, s in scored[:SHOWN]
    ]
    plan = RepairPlan(
        alpha_id=alpha_id,
        expression=expression,
        kind=kind.value,
        power_pool=power_pool,
        region=str(settings.get("region") or ""),
        generated=len(candidates),
        ranked=ranked,
        variants=shown,
        problems=problems,
    )
    return plan, scored, settings


def _row(
    v: Variant,
    *,
    power_pool: bool,
    now: datetime,
    region: str | None = None,
    universe: str | None = None,
) -> dict[str, Any]:
    return {
        "expression": v.expression,
        "region": region or v.settings.get("region"),
        "delay": v.settings.get("delay"),
        "universe": universe or v.settings.get("universe"),
        "neutralization": v.settings.get("neutralization"),
        "decay": v.settings.get("decay"),
        "truncation": v.settings.get("truncation"),
        "power_pool": power_pool,
        "sim_type": "REGULAR",
        "date_created": now,
    }


async def _ra_markets(state: State, alpha_id: str, settings: dict[str, Any]) -> dict[str, str]:
    """Each region an RA family runs in, with that region's universe, from its stored
    children; the usual regions at the family's universe when none are stored yet."""
    for item in await judge_vault(state):
        if str(item.row.get("alpha_id")) == alpha_id and item.children:
            return {
                str(c.get("region")): str(c.get("universe") or settings.get("universe") or "")
                for c in item.children
                if c.get("region")
            }
    return {region: str(settings.get("universe") or "") for region in RA_REGIONS}


async def _score(
    state: State,
    candidates: list[Variant],
    kind: Kind,
    power_pool: bool,
    markets: dict[str, str],
) -> tuple[list[tuple[Variant, Score | None]], dict[str, dict[str, float]]]:
    """Each variant scored and sorted best first. An RA variant is predicted region by region,
    and scored by the chance at least two regions pass."""
    now = datetime.now(UTC).replace(tzinfo=None)
    per_region: dict[str, dict[str, float]] = {}
    if not markets:
        rows = [_row(v, power_pool=power_pool, now=now) for v in candidates]
        predicted = await state.predictors.predict(rows)
        scored: list[tuple[Variant, Score | None]] = [
            (v, score(p, kind)) for v, p in zip(candidates, predicted, strict=True)
        ]
    else:
        regions = sorted(markets)
        rows = [
            _row(v, power_pool=power_pool, now=now, region=r, universe=markets[r])
            for v in candidates
            for r in regions
        ]
        predicted = await state.predictors.predict(rows)
        scored = []
        for i, v in enumerate(candidates):
            each = [score(p, kind) for p in predicted[i * len(regions) : (i + 1) * len(regions)]]
            per_region[v.id] = {r: s.p_all for r, s in zip(regions, each, strict=True)}
            correlations = [s.correlation for s in each if s.correlation is not None]
            sharpes = [s.sharpe for s in each if s.sharpe is not None]
            fitnesses = [s.fitness for s in each if s.fitness is not None]
            scored.append(
                (
                    v,
                    Score(
                        p_all=at_least([s.p_all for s in each], RA_MIN_REGIONS),
                        p_correlation=None,
                        correlation=sorted(correlations)[1] if len(correlations) > 1 else None,
                        sharpe=sorted(sharpes)[-2] if len(sharpes) > 1 else None,
                        fitness=sorted(fitnesses)[-2] if len(fitnesses) > 1 else None,
                    ),
                )
            )
    scored.sort(key=lambda vs: -(vs[1].p_all if vs[1] else 0.0))
    return scored, per_region


@router.post("/plan")
async def plan(
    state: State, alpha_id: Annotated[str, Body(embed=True, alias="alphaId")]
) -> RepairPlan:
    """Generate every variant of one Alpha and rank them. Simulates nothing."""
    return (await _plan(state, alpha_id.strip()))[0]


@router.post("/tasks")
async def queue(
    state: State,
    alpha_id: Annotated[str, Body(alias="alphaId")],
    take: Annotated[int, Body(ge=1, le=40)] = 10,
    cores: Annotated[int, Body(ge=1)] = DEFAULT_SLOTS,
) -> AddedTask:
    """Simulate the best ``take`` variants as one task, each at its own settings, in Full mode
    (the only mode that runs the correlation checks this is for)."""
    if cores > state.engine.slots:
        raise refuse(422, "too_many_cores", f"The engine has {state.engine.slots} slots.")
    found, scored, settings = await _plan(state, alpha_id.strip())
    if found.problems:
        raise refuse(422, "repair_blocked", found.problems[0])
    chosen = [v for v, _ in scored[:take]]
    if not chosen:
        raise refuse(422, "no_variants", "No variant of this Alpha could be generated.")
    requests = [
        SimulationRequest(
            settings=SimulationSettings.model_validate(
                settings | v.settings | {"simulationMode": FULL_MODE}
            ),
            regular=v.expression,
        )
        for v in chosen
    ]
    return await add_study(
        state,
        now=utcnow(),
        sampler=CORRELATION_BREAKER,
        params=BreakerParams(
            region=str(settings.get("region") or ""),
            delay=int(settings.get("delay") or 0),
            alpha_id=found.alpha_id,
            universe=str(settings.get("universe") or ""),
            neutralization=str(settings.get("neutralization") or ""),
            decay=int(settings.get("decay") or 0),
            truncation=float(settings.get("truncation") or 0.08),
            recipes=[v.edit for v in chosen],
            cores=cores,
        ),
        simulations=len(requests),
        batch_size=(cores + 1) * MAX_BATCH,
        template_source=found.expression,
        template_name=f"Repair · {found.alpha_id}",
        seeds=settings_sampler.seed_trials(requests, has_source=False),
    )


# -- transplants ------------------------------------------------------------------------------

#: Transplants scored per request; the models score these in one batch.
TRANSPLANT_POOL = 4000
#: Types a transplant keeps: a regular Alpha stays regular, a Power Pool (or theme) one stays
#: Power Pool, each judged by its own correlation in the new region.
_TRANSPLANT_KINDS = frozenset({Kind.REGULAR, Kind.POWER_POOL, Kind.THEME})
_TRANSPLANT_PASSING = frozenset({Verdict.SUBMITTABLE, Verdict.RECHECK, Verdict.SUBMITTED})
_transplant_cache: dict[str, Any] = {}


class TransplantRow(Out):
    id: str
    source_id: str
    expression: str
    origin: str
    region: str
    universe: str
    delay: int
    #: The source's own state: submitted, submittable or re-check.
    source_verdict: str
    #: ``regular`` or ``power_pool``: the type it is judged as, here and where it came from.
    kind: str
    source_sharpe: float | None
    p_all: float | None
    correlation: float | None
    sharpe: float | None
    fitness: float | None


class TransplantPlan(Out):
    #: Every transplant found; ``transplants`` holds the best of them.
    found: int
    ranked: bool
    transplants: list[TransplantRow]
    #: Regions (with delay) whose catalog is downloaded and so can be transplanted into.
    markets: list[str]


async def _markets_and_runs(state: State) -> tuple[Markets, frozenset[str], dict[str, Any]]:
    """The downloaded markets' fields, and where each canonical expression has run. Cached
    until the catalog or the vault changes: canonicalising 50k expressions takes seconds."""
    (stamp,) = await state.catalog.query(
        "SELECT (SELECT count(*) FROM alpha) AS n, (SELECT max(fetched_at) FROM alpha) AS t, "
        "(SELECT count(*) FROM data_field) AS f, (SELECT max(synced_at) FROM data_field) AS c"
    )
    key = tuple(stamp.values())
    if _transplant_cache.get("key") == key:
        return _transplant_cache["markets"], _transplant_cache["known"], _transplant_cache["ran"]
    held: dict[tuple[str, int], dict[str, set[str]]] = {}
    for r in await state.catalog.query(
        "SELECT DISTINCT region, delay, universe, field_id FROM data_field "
        "WHERE instrument_type = 'EQUITY' AND region <> ?",
        [REGION_AGNOSTIC_REGION],
    ):
        market = held.setdefault((str(r["region"]), int(r["delay"])), {})
        market.setdefault(str(r["universe"]), set()).add(str(r["field_id"]))
    markets: Markets = {m: {u: frozenset(f) for u, f in per.items()} for m, per in held.items()}
    known = frozenset(f for per in markets.values() for fs in per.values() for f in fs)
    ran = ran_in(await state.catalog.query("SELECT expression, region, delay FROM alpha"))
    _transplant_cache.update(key=key, markets=markets, known=known, ran=ran)
    return markets, known, ran


TransplantKind = Literal["regular", "power_pool"]


async def transplant_rows(
    state: State, limit: int, region: str | None, kind: TransplantKind | None = None
) -> tuple[TransplantPlan, list[tuple[Transplant, TransplantRow]]]:
    markets, known, ran = await _markets_and_runs(state)
    sources: list[dict[str, Any]] = []
    verdicts: dict[str, tuple[str, float | None]] = {}
    for item in await judge_vault(state):
        judged_as = item.judgement.kind
        if judged_as not in _TRANSPLANT_KINDS or item.judgement.verdict not in _TRANSPLANT_PASSING:
            continue
        sources.append(item.row | {"power_pool": judged_as != Kind.REGULAR})
        verdicts[str(item.row.get("alpha_id"))] = (
            item.judgement.verdict.value,
            figure(item, "sharpe"),
        )
    # Strongest sources first, so the pool the models score holds the likeliest.
    sources.sort(key=lambda r: -(r.get("sharpe") or 0.0))
    found = transplants(sources, markets, ran, known_fields=known)
    if region:
        found = [t for t in found if t.region == region]
    if kind is not None:
        found = [t for t in found if t.power_pool == (kind == "power_pool")]
    pool = found[:TRANSPLANT_POOL]
    ranked = await state.predictors.current() is not None
    scores: list[Score | None] = [None] * len(pool)
    if ranked and pool:
        now = datetime.now(UTC).replace(tzinfo=None)
        predicted = await state.predictors.predict(
            [
                {
                    "expression": t.expression,
                    "region": t.region,
                    "delay": t.delay,
                    "universe": t.universe,
                    "neutralization": t.settings.get("neutralization"),
                    "decay": t.settings.get("decay"),
                    "truncation": t.settings.get("truncation"),
                    "power_pool": t.power_pool,
                    "sim_type": "REGULAR",
                    "date_created": now,
                }
                for t in pool
            ]
        )
        scores = [
            score(p, Kind.POWER_POOL if t.power_pool else Kind.REGULAR)
            for t, p in zip(pool, predicted, strict=True)
        ]
    rows = [
        (
            t,
            TransplantRow(
                id=f"t{i}",
                source_id=t.source_id,
                expression=t.expression,
                origin=t.origin,
                region=t.region,
                universe=t.universe,
                delay=t.delay,
                source_verdict=verdicts[t.source_id][0],
                kind="power_pool" if t.power_pool else "regular",
                source_sharpe=verdicts[t.source_id][1],
                p_all=s.p_all if s else None,
                correlation=s.correlation if s else None,
                sharpe=s.sharpe if s else None,
                fitness=s.fitness if s else None,
            ),
        )
        for i, (t, s) in enumerate(zip(pool, scores, strict=True))
    ]
    rows.sort(key=lambda tr: -(tr[1].p_all if tr[1].p_all is not None else -1.0))
    plan = TransplantPlan(
        found=len(found),
        ranked=ranked,
        transplants=[r for _, r in rows[:limit]],
        markets=sorted(f"{r} D{d}" for r, d in markets),
    )
    return plan, rows


@router.get("/transplants")
async def transplant_plan(
    state: State,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    region: Annotated[str | None, Query()] = None,
    kind: Annotated[TransplantKind | None, Query()] = None,
) -> TransplantPlan:
    """Passing regular and Power Pool Alphas, each in the downloaded regions it has not run
    in, best first. Simulates nothing."""
    return (await transplant_rows(state, limit, region or None, kind))[0]


@router.post("/transplants/tasks")
async def queue_transplants(
    state: State,
    take: Annotated[int, Body(ge=1, le=200)] = 40,
    region: Annotated[str | None, Body()] = None,
    kind: Annotated[TransplantKind | None, Body()] = None,
    cores: Annotated[int, Body(ge=1)] = DEFAULT_SLOTS,
) -> AddedTask:
    """Simulate the best ``take`` transplants as one task, in Full mode so the correlation
    checks run."""
    if cores > state.engine.slots:
        raise refuse(422, "too_many_cores", f"The engine has {state.engine.slots} slots.")
    _, rows = await transplant_rows(state, take, region or None, kind)
    chosen = [t for t, _ in rows[:take]]
    if not chosen:
        raise refuse(
            422,
            "no_transplants",
            "No passing Alpha has a downloaded region left to run in. Sync more markets.",
        )
    return await add_transplants(
        state,
        chosen,
        cores=cores,
        name=f"Transplants · {len(chosen)} into {region or 'other regions'}",
    )


async def add_transplants(
    state: State, chosen: list[Transplant], *, cores: int, name: str, run: bool = False
) -> AddedTask:
    """One Full-mode task simulating these transplants, each at its own settings."""
    requests = [
        SimulationRequest(
            settings=SimulationSettings.model_validate(
                {k: v for k, v in t.settings.items() if v is not None}
                | {"simulationMode": FULL_MODE}
            ),
            regular=t.expression,
        )
        for t in chosen
    ]
    first = chosen[0]
    regions = sorted({t.region for t in chosen})
    return await add_study(
        state,
        now=utcnow(),
        sampler=CORRELATION_BREAKER,
        params=BreakerParams(
            region=regions[0] if len(regions) == 1 else "several",
            delay=first.delay,
            alpha_id="transplants",
            universe=first.universe,
            neutralization=str(first.settings.get("neutralization") or ""),
            decay=int(first.settings.get("decay") or 0),
            truncation=float(first.settings.get("truncation") or 0.08),
            recipes=[f"{t.source_id} → {t.region}" for t in chosen],
            cores=cores,
        ),
        simulations=len(requests),
        batch_size=(cores + 1) * MAX_BATCH,
        template_source=first.expression,
        template_name=name,
        run=run,
        seeds=settings_sampler.seed_trials(requests, has_source=False),
    )


# -- promotions to region agnostic ------------------------------------------------------------


class PromotionRow(Out):
    id: str
    expression: str
    delay: int
    #: Region → the passing regular Alpha there.
    regions: dict[str, str]
    sharpe: float | None
    neutralization: str | None
    decay: int | None
    truncation: float | None


class PromotionPlan(Out):
    promotions: list[PromotionRow]
    #: Delay → the region-agnostic universes downloaded for it, to run the families in.
    universes: dict[int, list[str]]


async def promotion_rows(state: State, delay: int | None) -> tuple[PromotionPlan, list[Promotion]]:
    _, _, ran = await _markets_and_runs(state)
    passing = [
        item.row
        for item in await judge_vault(state)
        if item.judgement.kind == Kind.REGULAR and item.judgement.verdict in _TRANSPLANT_PASSING
    ]
    found = [p for p in promotions(passing, ran) if delay is None or p.delay == delay]
    universes: dict[int, list[str]] = {}
    for r in await state.catalog.query(
        "SELECT DISTINCT delay, universe FROM data_field WHERE region = ? ORDER BY universe",
        [REGION_AGNOSTIC_REGION],
    ):
        universes.setdefault(int(r["delay"]), []).append(str(r["universe"]))
    plan = PromotionPlan(
        promotions=[
            PromotionRow(
                id=f"p{i}",
                expression=p.expression,
                delay=p.delay,
                regions=p.regions,
                sharpe=p.sharpe,
                neutralization=p.neutralization,
                decay=p.decay,
                truncation=p.truncation,
            )
            for i, p in enumerate(found)
        ],
        universes=universes,
    )
    return plan, found


@router.get("/promotions")
async def promotion_plan(
    state: State, delay: Annotated[int | None, Query()] = None
) -> PromotionPlan:
    """Expressions that pass as regular Alphas in two or more region-agnostic markets and
    have never run as a region-agnostic Alpha. Simulates nothing."""
    return (await promotion_rows(state, delay))[0]


@router.post("/promotions/tasks")
async def queue_promotions(
    state: State,
    universe: Annotated[str, Body()],
    delay: Annotated[int, Body()] = 1,
    take: Annotated[int, Body(ge=1, le=100)] = 20,
    cores: Annotated[int, Body(ge=1)] = DEFAULT_SLOTS,
) -> AddedTask:
    """Run the best ``take`` as region-agnostic Alphas in ``universe``, in Full mode."""
    if cores > state.engine.slots:
        raise refuse(422, "too_many_cores", f"The engine has {state.engine.slots} slots.")
    plan, found = await promotion_rows(state, delay)
    if universe not in plan.universes.get(delay, []):
        raise refuse(
            422,
            "universe_not_synced",
            f"The region-agnostic market's {universe} at delay {delay} is not downloaded. "
            "Sync it on the Sync screen.",
        )
    chosen = found[:take]
    if not chosen:
        raise refuse(
            422, "no_promotions", "No expression passes in two region-agnostic markets yet."
        )
    return await add_promotions(
        state,
        chosen,
        universe=universe,
        delay=delay,
        cores=cores,
        name=f"RA promotions · {len(chosen)} families",
    )


async def add_promotions(
    state: State,
    chosen: list[Promotion],
    *,
    universe: str,
    delay: int,
    cores: int,
    name: str,
    run: bool = False,
) -> AddedTask:
    """One Full-mode task running each expression once as a region-agnostic Alpha."""
    requests = [
        SimulationRequest(
            settings=SimulationSettings.model_validate(
                {
                    k: v
                    for k, v in {
                        "region": REGION_AGNOSTIC_REGION,
                        "universe": universe,
                        "delay": delay,
                        "neutralization": p.neutralization,
                        "decay": p.decay,
                        "truncation": p.truncation,
                        "simulationMode": FULL_MODE,
                    }.items()
                    if v is not None
                }
            ),
            regular=p.expression,
        )
        for p in chosen
    ]
    first = chosen[0]
    return await add_study(
        state,
        now=utcnow(),
        sampler=CORRELATION_BREAKER,
        params=BreakerParams(
            region=REGION_AGNOSTIC_REGION,
            delay=delay,
            alpha_id="promotions",
            universe=universe,
            neutralization=str(first.neutralization or ""),
            decay=int(first.decay or 0),
            truncation=float(first.truncation or 0.08),
            recipes=[" + ".join(sorted(p.regions)) for p in chosen],
            cores=cores,
        ),
        simulations=len(requests),
        batch_size=(cores + 1) * MAX_BATCH,
        template_source=first.expression,
        template_name=name,
        run=run,
        seeds=settings_sampler.seed_trials(requests, has_source=False),
    )
