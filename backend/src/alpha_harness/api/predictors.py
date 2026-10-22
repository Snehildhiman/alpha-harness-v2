"""The learned models: train them, see how good they are, ask them about an expression."""

from typing import Annotated, Any

from fastapi import APIRouter, Body
from sqlalchemy import func, select

from ..db.models import Trial, TrialState
from ..labs.fastexpr import (
    MAX_FIELDS,
    MAX_OPERATORS,
    ParseError,
    data_fields,
    node_at,
    operator_count,
    parse,
    validate,
    walk,
)
from ..labs.ga import market_for
from ..labs.launch import account_operators
from ..models.train import label_of
from ..schemas import Out
from ..separation import Verdict, judge
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
    #: Retraining by itself, and how many new or re-checked Alphas have arrived since.
    auto: bool
    new_since_training: int
    #: The last automatic retrain: when, whether it replaced the models, and why.
    last_gate: GateReport | None


class GateCompared(Out):
    target: str
    label: str
    old: float
    new: float
    alphas: int


class GateReport(Out):
    at: str
    accepted: bool
    reason: str
    compared: list[GateCompared]


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
        auto=state.predictors.auto,
        new_since_training=await state.predictors.new_since_training(),
        last_gate=_gate(state),
    )


def _gate(state: State) -> GateReport | None:
    last = state.predictors.last_gate
    if last is None:
        return None
    at, verdict = last
    return GateReport(
        at=at,
        accepted=verdict.accepted,
        reason=verdict.reason,
        compared=[
            GateCompared(target=t, label=label_of(t), old=o, new=n, alphas=k)
            for t, o, n, k in verdict.compared
        ],
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


_REGION_CHECKS = ("USA", "EUR", "ASI", "GLB", "CHN", "JPN", "KOR", "TWN", "HKG", "AMR", "IND")


def _applies(target: str, region: str) -> bool:
    """Whether a target means anything for an Alpha in ``region``."""
    if not target.startswith("check:"):
        return True
    head = target.removeprefix("check:").split("_", 1)[0].upper()
    return head not in _REGION_CHECKS or head == region.upper()


async def expression_problems(state: State, candidate: Candidate) -> list[str]:
    """Why BRAIN would refuse this expression in this market, or nothing: it must parse,
    use operators the account has, and read fields the market's download carries."""
    try:
        tree = parse(candidate.expression)
    except ParseError as exc:
        return [f"The expression could not be read: {exc}"]
    except RecursionError:
        return ["The expression is nested too deeply to read."]
    operators = await account_operators(state, refresh=False)
    market = await market_for(
        state.catalog,
        # Unread operators (signed out): every call is let through, fields are still checked.
        operators or [{"name": "_", "definition": "_(x)"}],
        candidate.region,
        candidate.delay,
        candidate.universe,
        [candidate.neutralization],
    )
    if market is None:
        return [
            f"{candidate.region} {candidate.universe} delay {candidate.delay} is not "
            "downloaded. Sync it on the Sync screen first."
        ]
    problems = validate(tree, market.table, market.names)
    if not operators:
        problems = [p for p in problems if "is not an operator" not in p and "inputs" not in p]
    # Vector fields (several values a day) only make sense straight inside a vec_ operator.
    names = sorted({n.value for _, n in walk(tree) if n.kind == "name"})
    types = {
        str(r["field_id"]): str(r["t"])
        for r in await state.catalog.query(
            "SELECT field_id, any_value(field_type) AS t FROM data_field "
            "WHERE region = ? AND delay = ? AND universe = ? AND field_id IN (SELECT unnest(?)) "
            "AND field_type IS NOT NULL GROUP BY field_id",
            [candidate.region, candidate.delay, candidate.universe, names],
        )
    }
    for path, node in walk(tree):
        if node.kind != "name" or not path or node.value not in types:
            continue
        parent = node_at(tree, path[:-1])
        in_vec = parent.kind == "call" and parent.value.startswith("vec_")
        if types[node.value] == "VECTOR" and not in_vec:
            problems.append(f"{node.value} is a vector field: put it inside a vec_ operator.")
        elif types[node.value] == "MATRIX" and in_vec:
            problems.append(f"{node.value} is not a vector field; {parent.value} cannot take it.")
    if candidate.power_pool:
        if (count := operator_count(tree)) > MAX_OPERATORS:
            problems.append(f"{count} operators; Power Pool allows {MAX_OPERATORS}.")
        if (fields := len(data_fields(tree))) > MAX_FIELDS:
            problems.append(f"{fields} data fields; Power Pool allows {MAX_FIELDS}.")
    return problems


@router.post("/predict")
async def predict(state: State, candidate: Annotated[Candidate, Body()]) -> list[Prediction]:
    """What the models expect of one expression at these settings, before simulating it."""
    if await state.predictors.current() is None:
        raise refuse(409, "untrained", "Train the models first.")
    if problems := await expression_problems(state, candidate):
        # A guess about an Alpha BRAIN would refuse to simulate is worse than no answer.
        raise refuse(422, "invalid_expression", " ".join(problems[:5]))
    row: dict[str, Any] = {
        **candidate.model_dump(),
        "sim_type": "REGULAR",
        "checks": None,
    }
    found = (await state.predictors.predict([row]))[0]
    # Region-specific checks (GLB_AMER_SHARPE, ASI_JPN_SHARPE, ...) only exist in their region.
    found = {t: v for t, v in found.items() if _applies(t, candidate.region)}
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


class ScreenGroup(Out):
    #: ``model``: kept for its score; ``explore``: kept at random.
    group: str
    #: Simulated and back from BRAIN.
    finished: int
    #: Every check its type answers to passed, now or once a re-check confirms it.
    passing: int
    #: Still waiting on a check BRAIN has not run (correlations usually).
    pending: int
    refused: int
    #: Mean chance the models gave these Alphas.
    predicted: float | None


class ScreenReport(Out):
    groups: list[ScreenGroup]


#: Most screened trials read back, newest first.
SCREEN_WINDOW = 5000


@router.get("/screening")
async def screening(state: State) -> ScreenReport:
    """How the screen's picks fared against its random exploration picks.

    The test of the screen: if the models help, Alphas kept for their score pass more often
    than Alphas kept at random from the same rounds. Judged on the vault's current checks, so
    a re-check counts.
    """
    async with state.db.session() as session:
        rows = (
            await session.execute(
                select(
                    func.json_extract(Trial.params, "$.screen"),
                    func.json_extract(Trial.params, "$.predicted"),
                    Trial.alpha_id,
                )
                .where(
                    func.json_extract(Trial.params, "$.screen").is_not(None),
                    Trial.state == TrialState.COMPLETE,
                    Trial.alpha_id.is_not(None),
                )
                .order_by(Trial.id.desc())
                .limit(SCREEN_WINDOW)
            )
        ).all()
    ids = sorted({str(a) for _, _, a in rows if a})
    stored = {
        str(r["alpha_id"]): r
        for r in (
            await state.catalog.query(
                "SELECT alpha_id, sim_type, status, checks, classifications, simulation_mode "
                "FROM alpha WHERE alpha_id IN (SELECT unnest(?))",
                [ids],
            )
            if ids
            else []
        )
    }
    tally: dict[str, dict[str, Any]] = {}
    for group, predicted, alpha_id in rows:
        row = stored.get(str(alpha_id))
        if row is None:
            continue
        verdict = judge(row).verdict
        t = tally.setdefault(
            str(group), {"finished": 0, "passing": 0, "pending": 0, "refused": 0, "p": []}
        )
        t["finished"] += 1
        if verdict in (Verdict.SUBMITTABLE, Verdict.RECHECK, Verdict.SUBMITTED):
            t["passing"] += 1
        elif verdict == Verdict.PENDING:
            t["pending"] += 1
        else:
            t["refused"] += 1
        if isinstance(predicted, int | float):
            t["p"].append(float(predicted))
    return ScreenReport(
        groups=[
            ScreenGroup(
                group=group,
                finished=t["finished"],
                passing=t["passing"],
                pending=t["pending"],
                refused=t["refused"],
                predicted=sum(t["p"]) / len(t["p"]) if t["p"] else None,
            )
            for group, t in sorted(tally.items())
        ]
    )


class HistoryTarget(Out):
    target: str
    label: str
    kind: str
    #: AUC for a check, rank correlation (Spearman) for a number: higher is better for both.
    score: float | None
    #: Held-out Alphas it was scored on.
    n: int


class HistoryPoint(Out):
    trained_at: str
    alphas: int
    #: Kept in use: a retrain that did worse than the set in use is recorded but not kept.
    accepted: bool
    targets: list[HistoryTarget]


def _score(metrics: dict[str, Any]) -> float | None:
    for key in ("auc", "spearman"):
        value = metrics.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


@router.get("/history")
async def history(state: State) -> list[HistoryPoint]:
    """Each training's test score per target, oldest first: whether the models improve."""
    lines = state.predictors.history()
    current = await state.predictors.current()
    if not lines and current is not None:
        # Trained before the history was kept: the set in use is its first point.
        state.predictors.record(current, accepted=True)
        lines = state.predictors.history()
    return [
        HistoryPoint(
            trained_at=str(line.get("trainedAt") or ""),
            alphas=int(line.get("alphas") or 0),
            accepted=bool(line.get("accepted")),
            targets=[
                HistoryTarget(
                    target=target,
                    label=str(m.get("label") or target),
                    kind=str(m.get("kind") or ""),
                    score=_score(m),
                    n=int(m.get("n") or 0),
                )
                for target, m in (line.get("targets") or {}).items()
            ],
        )
        for line in lines
    ]
