"""The learned models: train them, see how good they are, ask them about an expression."""

from typing import Annotated, Any

from fastapi import APIRouter, Body

from ..models.train import label_of
from ..schemas import Out
from .deps import State, refuse

router = APIRouter(prefix="/api/models", tags=["models"])


class TargetReport(Out):
    target: str
    label: str
    kind: str
    labelled: int
    trained: bool
    n_train: int
    n_test: int
    metrics: dict[str, float]
    trees: int
    top_features: list[tuple[str, float]]
    note: str | None


class ModelStatus(Out):
    trained_at: str | None
    alphas: int
    #: The date the held-out test Alphas start from: everything after it was never trained on.
    test_from: str | None
    reports: list[TargetReport]
    #: ``[done, total, target]`` while training runs.
    training: tuple[int, int, str] | None


class Candidate(Out):
    expression: str
    region: str = "USA"
    delay: int = 1
    universe: str = "TOP3000"
    neutralization: str = "SUBINDUSTRY"
    decay: int = 0
    truncation: float = 0.08
    power_pool: bool = False


class Prediction(Out):
    target: str
    label: str
    value: float
    #: What the value means: a probability of passing, or the figure itself.
    kind: str


class TrainStarted(Out):
    task_id: str


@router.get("")
async def status(state: State) -> ModelStatus:
    models = await state.predictors.current()
    reports = (
        [
            TargetReport(
                target=r.target,
                label=r.label,
                kind=r.kind,
                labelled=r.labelled,
                trained=r.trained,
                n_train=r.n_train,
                n_test=r.n_test,
                metrics=r.metrics,
                trees=r.trees,
                top_features=r.top_features,
                note=r.note,
            )
            for r in models.reports
        ]
        if models
        else []
    )
    return ModelStatus(
        trained_at=models.trained_at if models else None,
        alphas=models.alphas if models else 0,
        test_from=models.test_from if models else None,
        reports=reports,
        training=state.predictors.progress,
    )


@router.post("/train")
async def train(state: State) -> TrainStarted:
    """Train every model on the whole vault in the background. A minute or two for 50k Alphas."""

    async def work(_task: Any) -> str:
        models = await state.predictors.train()
        trained = sum(r.trained for r in models.reports)
        return f"Trained {trained} models on {models.alphas:,} Alphas"

    try:
        task_id = await state.backfill.start_job("models-train", "Training models", work)
    except RuntimeError as exc:
        raise refuse(409, "busy", str(exc)) from exc
    return TrainStarted(task_id=task_id)


@router.post("/predict")
async def predict(state: State, candidate: Annotated[Candidate, Body()]) -> list[Prediction]:
    """What the models expect of one expression at these settings, before simulating it."""
    if await state.predictors.current() is None:
        raise refuse(409, "untrained", "Train the models first.")
    row: dict[str, Any] = {
        **candidate.model_dump(),
        "sim_type": "REGULAR",
        "checks": None,
    }
    found = (await state.predictors.predict([row]))[0]
    order = sorted(found, key=lambda t: (t.startswith("check:"), t))
    return [
        Prediction(
            target=t,
            label=label_of(t),
            value=found[t],
            kind="probability" if t.startswith("check:") else "value",
        )
        for t in order
    ]
