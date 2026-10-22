"""Super Alpha Lab: one form, one task of SuperAlphas from your own submitted Alphas."""

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from ..db.models import utcnow
from ..engine.packer import MAX_BATCH
from ..labs import super_alpha
from ..labs.launch import AddedTask, add_study
from ..labs.params import SUPER_LAB, SuperParams
from ..schemas import Out
from .deps import State, refuse

router = APIRouter(prefix="/api/super-lab", tags=["super-lab"])

#: BRAIN runs at most three SuperAlpha simulations per person at once.
MAX_CORES = 3


class SuperTask(Out):
    region: str
    delay: int
    universe: str
    neutralization: str
    selection_limit: int = Field(default=30, ge=super_alpha.MIN_SELECTION, le=200)
    #: ``BOTH`` runs every pairing under each Component Activation.
    activation: Literal["IS", "OS", "BOTH"] = "BOTH"
    cores: int = Field(default=MAX_CORES, ge=1, le=MAX_CORES)
    run: bool = False
    #: Recipe names to run; empty runs the default set.
    selections: list[str] = Field(default_factory=list, max_length=40)
    combos: list[str] = Field(default_factory=list, max_length=40)
    #: Empty: the default decays.
    decays: list[int] = Field(default_factory=list, max_length=len(super_alpha.DECAY_CHOICES))


class Recipe(Out):
    name: str
    code: str
    #: Part of this task.
    chosen: bool = True
    default: bool = True


class SuperPlan(Out):
    selections: list[Recipe]
    combos: list[Recipe]
    decays: list[int]
    decay_choices: list[int]
    truncation: float
    simulations: int


def _activations(choice: str) -> list[str]:
    return ["IS", "OS"] if choice == "BOTH" else [choice]


def _decays(body: SuperTask) -> list[int]:
    return sorted(
        {d for d in body.decays if d in super_alpha.DECAY_CHOICES} or set(super_alpha.DECAYS)
    )


def _found(body: SuperTask) -> list[super_alpha.Candidate]:
    return super_alpha.candidates(
        region=body.region,
        delay=body.delay,
        universe=body.universe,
        neutralization=body.neutralization,
        selection_limit=body.selection_limit,
        activations=_activations(body.activation),
        selection_names=body.selections,
        combo_names=body.combos,
        decays=_decays(body),
    )


@router.post("/plan")
async def plan(body: SuperTask) -> SuperPlan:
    """What a task with these settings would run, without running anything."""
    every = super_alpha.library(body.selection_limit)
    chosen_s = {r.name for r in super_alpha.selections(body.selection_limit, body.selections)}
    chosen_c = {r.name for r in super_alpha.combos(body.combos)}
    decays = _decays(body)
    return SuperPlan(
        selections=[
            Recipe(name=r.name, code=r.code, chosen=r.name in chosen_s, default=r.default)
            for r in every
        ],
        combos=[
            Recipe(name=r.name, code=r.code, chosen=r.name in chosen_c, default=r.default)
            for r in super_alpha.ALL_COMBOS
        ],
        decays=decays,
        decay_choices=list(super_alpha.DECAY_CHOICES),
        truncation=super_alpha.TRUNCATION,
        simulations=len(chosen_s)
        * len(chosen_c)
        * len(decays)
        * len(_activations(body.activation)),
    )


@router.post("/tasks", status_code=201)
async def add_task(body: SuperTask, state: State) -> AddedTask:
    """Write every pairing as a SuperAlpha simulation, and queue the task when ``run``."""
    if body.region == "ALL":
        raise refuse(422, "region_agnostic", "SuperAlphas combine Alphas of one region.")
    found = _found(body)
    return await add_study(
        state,
        now=utcnow(),
        sampler=SUPER_LAB,
        params=SuperParams(
            region=body.region,
            delay=body.delay,
            universe=body.universe,
            neutralization=body.neutralization,
            selection_limit=body.selection_limit,
            activation=_activations(body.activation),
            recipes=sorted({c.name for c in found}),
            cores=body.cores,
        ),
        simulations=len(found),
        batch_size=body.cores * MAX_BATCH,
        template_source=super_alpha.COMBOS[0].code,
        template_name=f"Super Alpha Lab · {body.region} D{body.delay} {body.universe}",
        run=body.run,
        seeds=super_alpha.seed_trials(found),
    )
