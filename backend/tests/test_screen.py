"""Screening: the models choose which asked points are worth a simulation."""

import asyncio
import random
from types import SimpleNamespace
from typing import Any

import optuna

from alpha_harness.brain.schemas import SimulationRequest, SimulationSettings
from alpha_harness.labs import scheduler, screen


def test_pick_keeps_the_best_and_explores_the_rest() -> None:
    chances = [0.1, 0.9, 0.2, 0.8, 0.05, 0.7, 0.3, 0.6, 0.4, 0.5]
    got = screen.pick(chances, 5, explore=0.2, rng=random.Random(1))
    assert len(got.keep) == 5
    assert got.keep[:4] == [1, 3, 5, 7]  # the four best, in order
    assert len(got.explored) == 1
    assert next(iter(got.explored)) not in {1, 3, 5, 7}


def test_pick_without_opinions_keeps_the_sampler_order() -> None:
    got = screen.pick([None, None, None], 2, explore=0.2, rng=random.Random(0))
    assert got.keep == [0, 1]


def test_power_pool_limits() -> None:
    assert screen.power_pool_eligible("rank(ts_delta(est_eps, 5))")
    many = "add(a, add(b, add(c, d)))"  # four data fields
    assert not screen.power_pool_eligible(many)


def test_chance_takes_the_better_type_for_a_power_pool_candidate() -> None:
    predicted = {
        "check:PROD_CORRELATION": 0.1,
        "check:POWER_POOL_CORRELATION": 0.8,
        "check:LOW_SHARPE": 0.5,
    }
    assert screen.chance_of(predicted, power_pool=False) == 0.1 * 0.5
    assert screen.chance_of(predicted, power_pool=True) == 0.8 * 0.5
    assert screen.chance_of({}, power_pool=True) is None


class Predictors:
    """Rates an expression by the window it uses: longer is better."""

    async def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        out = []
        for r in rows:
            window = int(r["expression"].split(",")[1].strip(" )"))
            out.append({"check:PROD_CORRELATION": window / 100})
        return out


def test_screened_round_sends_the_best_and_prunes_the_rest() -> None:
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    picked = []
    for window in range(10, 100, 10):
        trial = study.ask()
        request = SimulationRequest(
            regular=f"ts_mean(close, {window})",
            settings=SimulationSettings(region="USA", universe="TOP3000", delay=1),
        )
        picked.append((trial, {"window": window}, request))
    optimizer = SimpleNamespace(screen_explore=0.0)
    kept = asyncio.run(scheduler._screened(optimizer, Predictors(), study, picked, 3))  # type: ignore[arg-type]
    assert [p["window"] for _, p, _ in kept] == [90, 80, 70]
    assert kept[0][1]["predicted"] == 0.9
    assert kept[0][1]["screen"] == "model"
    states = [t.state for t in study.get_trials(deepcopy=False)]
    assert states.count(optuna.trial.TrialState.PRUNED) == 6


def test_screening_report_compares_model_and_random_picks(tmp_path: Any) -> None:
    import json

    from alpha_harness.api.predictors import screening
    from alpha_harness.db.duck import Catalog
    from alpha_harness.db.models import Study, Trial, TrialState
    from alpha_harness.db.sqlite import Database

    ok = [
        {"name": "LOW_SHARPE", "result": "PASS", "value": 1.5, "limit": 1.25},
        {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.2, "limit": 0.7},
        {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.5, "limit": 0.7},
    ]
    bad = [*ok[:2], {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.9, "limit": 0.7}]

    async def body() -> Any:
        catalog = Catalog(tmp_path / "c.duckdb")
        await catalog.open()
        db = Database(tmp_path / "h.db")
        await db.create_all()
        picks = [
            ("model", "A1", ok),
            ("model", "A2", ok),
            ("model", "A3", bad),
            ("explore", "B1", bad),
            ("explore", "B2", bad),
        ]
        async with db.session() as session:
            study = Study(task="t", name="t", sampler="search", template_source="")
            session.add(study)
            await session.flush()
            for n, (group, alpha_id, checks) in enumerate(picks):
                session.add(
                    Trial(
                        study_id=study.id,
                        number=n,
                        state=TrialState.COMPLETE,
                        alpha_id=alpha_id,
                        params={"screen": group, "predicted": 0.6},
                    )
                )
                await catalog.execute(
                    "INSERT INTO alpha (alpha_id, sim_type, status, checks) VALUES "
                    "(?, 'REGULAR', 'UNSUBMITTED', ?)",
                    [alpha_id, json.dumps(checks)],
                )
            await session.commit()
        report = await screening(SimpleNamespace(db=db, catalog=catalog))  # type: ignore[arg-type]
        await db.dispose()
        await catalog.close()
        return {g.group: (g.passing, g.refused) for g in report.groups}

    assert asyncio.run(body()) == {"explore": (0, 2), "model": (2, 1)}


def test_steering_tells_the_search_a_penalised_estimate() -> None:
    from alpha_harness.labs.scheduler import STEER_PENALTY, steered

    assert steered({"sharpe": 1.5}, 1.0) == 1.5
    assert steered({"sharpe": 1.5}, 0.5) == 1.5 - STEER_PENALTY * 0.5
    assert steered({}, 0.9) is None
    assert steered({"sharpe": 1.0}, None) is None
