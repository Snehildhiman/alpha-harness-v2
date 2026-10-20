"""Repair: find near-misses, generate variants, let the models pick, simulate the best few."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query

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
from ..schemas import Out
from ..separation import RA_MIN_REGIONS, Kind
from ..tools import correlation_breaker, settings_sampler
from .deps import State, refuse
from .separation import Issue, figure, judge_vault

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


@router.get("/near-misses")
async def near_misses(
    state: State,
    tab: Annotated[Kind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[NearMiss]:
    """Refused Alphas whose every failure is narrow, nearest first."""
    found: list[tuple[float, Any]] = []
    for item in await judge_vault(state):
        if item.judgement.kind not in REPAIRABLE or (
            tab is not None and item.judgement.kind != tab
        ):
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
        candidates = variants(
            expression, settings, reshapes=reshapes, operators=operators, power_pool=power_pool
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
