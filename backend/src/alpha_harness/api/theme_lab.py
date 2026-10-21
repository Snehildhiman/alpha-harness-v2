"""Current Theme Lab: simulate only Alphas that fit the running Power Pool theme. No LLM.

It is the Search Lab held to the theme's rule: the theme's delay, only datasets of the
categories it allows, one field per Alpha (so one category), no group operators and no
grouping fields when the theme forbids them, and within the Power Pool limits (every shape
the search writes reads one field through at most three operators). The space holds only
what the rule allows, so nothing that breaks the theme is spent on.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import preferences
from ..db.models import utcnow
from ..labs import search
from ..labs.launch import (
    NO_SIMULATIONS,
    AddedTask,
    FieldCounts,
    SampleAlpha,
    SearchRequest,
    add_study,
    preview_samples,
    startup_trials,
)
from ..labs.params import SEARCH_SAMPLER, SearchParams
from ..schemas import Out
from ..themes import ThemeRule, current, grouping_in, normalise
from . import search_lab
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


class ThemeMarket(Out):
    region: str
    datasets: list[ThemeDataset]


class ThemeLabOptions(Out):
    #: ``None``: no theme is running today; add it on Alpha Types → Current Theme.
    theme: ThemeRule | None
    rule: str | None
    delay: int | None
    markets: list[ThemeMarket]


class ThemeLabRequest(BaseModel):
    region: str
    universe: str | None = None
    #: Empty: every allowed dataset of the region.
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    neutralizations: list[str] = Field(default_factory=list, max_length=20)
    decay: int = 0
    cores: int = Field(default=search.MAX_CORES, ge=1, le=search.MAX_CORES)
    simulations: int = Field(default=0, ge=0, le=search.MAX_SIMULATIONS)
    vector_operators: list[str] = Field(default_factory=list)


class ThemeLabPreview(Out):
    theme: str | None
    fields: FieldCounts | None
    universes: list[str]
    sample: list[SampleAlpha]
    problems: list[str]
    warnings: list[str]


async def _theme(state: State) -> ThemeRule | None:
    rules = (await preferences.load(state.db)).power_pool_themes
    return current(rules, datetime.now(UTC).date())


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
async def options(state: State) -> ThemeLabOptions:
    """The running theme and, per downloaded region, the datasets it allows."""
    rule = await _theme(state)
    if rule is None:
        return ThemeLabOptions(theme=None, rule=None, delay=None, markets=[])
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
            )
        )
    return ThemeLabOptions(
        theme=rule,
        rule=rule.describe(),
        delay=rule.delay,
        markets=[ThemeMarket(region=k, datasets=v) for k, v in sorted(by_region.items())],
    )


async def _plan(body: ThemeLabRequest, state: State) -> tuple[dict[str, Any], ThemeRule | None]:
    rule = await _theme(state)
    if rule is None:
        return {
            "problems": [
                "No Power Pool theme is running today. Add it on Alpha Types → Current Theme."
            ],
            "warnings": [],
        }, None
    allowed = {str(r["dataset_id"]) for r in await _allowed(state, rule, body.region)}
    chosen = [d for d in body.dataset_ids if d in allowed] or sorted(allowed)
    outside = [d for d in body.dataset_ids if d not in allowed]
    plan = await search_lab.plan_search(
        SearchRequest(
            region=body.region,
            delay=rule.delay if rule.delay is not None else 1,
            universe=body.universe,
            dataset_ids=chosen,
            vector_operators=body.vector_operators,
            neutralizations=body.neutralizations,
            decay=body.decay,
            cores=body.cores,
            simulations=body.simulations,
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
    if space is not None and rule.no_grouping:
        # One field per shape keeps one category; dropping the group shapes keeps the rest.
        space["families"] = [f for f in space["families"] if not f.startswith("group")]
        space["group"] = []
        space["groups"] = []
        if not space["families"]:
            plan["problems"].append("Without group operators none of your operators fit a shape.")
    if space is not None and not plan["problems"]:
        # Drawn again from the space as narrowed, so the sample shows what will be sent.
        run = SearchParams(region=body.region, delay=rule.delay or 0, decay=body.decay, space=space)
        choices = search.field_choices(space)
        plan["sample"] = [
            s
            for s in preview_samples(
                lambda rng: search.request_for(
                    search.suggest(search.RandomTrial(rng), space, choices), run
                ),
                tries=8,
            )
            if not rule.no_grouping or grouping_in(s.expression) is None
        ]
    return plan, rule


@router.post("/preview")
async def preview(body: ThemeLabRequest, state: State) -> ThemeLabPreview:
    """What a task would search, held to the theme. Free; queues nothing."""
    plan, rule = await _plan(body, state)
    return ThemeLabPreview.model_validate(
        {
            "theme": rule.describe() if rule else None,
            "fields": plan.get("fields"),
            "universes": plan.get("universes", []),
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
            n_startup_trials=startup_trials(
                len(plan["space"]["fields"]), body.simulations, per_round
            ),
        ),
        simulations=body.simulations,
        batch_size=per_round,
        template_source=f"# Current Theme Lab: {rule.describe()}",
        template_name=f"Current Theme · {rule.name}",
        label=f"Current Theme · {body.region} · {rule.name}"[:128],
        run=True,
    )
