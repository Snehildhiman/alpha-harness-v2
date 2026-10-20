"""The governor deals cores toward the tasks whose Alphas pass."""

import random

from alpha_harness.governor import TaskYield, deal


def y(study_id: int, cores: int, passing: int, refused: int) -> TaskYield:
    return TaskYield(study_id, f"t{study_id}", f"t{study_id}", cores, passing, refused)


def test_deal_keeps_the_total_and_a_core_each() -> None:
    tasks = [y(1, 4, 0, 200), y(2, 2, 60, 140), y(3, 2, 5, 5)]
    got = deal(tasks, random.Random(0))
    assert sum(got.values()) == 8
    assert min(got.values()) >= 1


def test_deal_favours_the_proven_yield() -> None:
    tasks = [y(1, 4, 2, 300), y(2, 4, 80, 220)]
    totals = {1: 0, 2: 0}
    for seed in range(20):
        for k, v in deal(tasks, random.Random(seed)).items():
            totals[k] += v
    assert totals[2] > totals[1] * 3


def test_yields_read_each_running_tasks_judged_alphas(tmp_path) -> None:
    import asyncio
    import json
    from types import SimpleNamespace

    from alpha_harness.db.duck import Catalog
    from alpha_harness.db.models import Study, StudyStatus, Trial, TrialState
    from alpha_harness.db.sqlite import Database
    from alpha_harness.governor import yields

    ok = [
        {"name": "LOW_SHARPE", "result": "PASS", "value": 1.5, "limit": 1.25},
        {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.2, "limit": 0.7},
        {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.5, "limit": 0.7},
    ]
    bad = [{"name": "LOW_SHARPE", "result": "FAIL", "value": 0.5, "limit": 1.25}]

    async def body() -> dict[str, tuple[int, int, int]]:
        catalog = Catalog(tmp_path / "c.duckdb")
        await catalog.open()
        db = Database(tmp_path / "h.db")
        await db.create_all()
        async with db.session() as session:
            for name, results in (("good", [ok, ok, bad]), ("poor", [bad, bad])):
                study = Study(
                    name=name,
                    task=name,
                    sampler="search",
                    template_source="",
                    status=StudyStatus.RUNNING,
                    sampler_params={"region": "USA", "delay": 1, "cores": 3, "space": {}},
                )
                session.add(study)
                await session.flush()
                for n, checks in enumerate(results):
                    alpha_id = f"{name}{n}"
                    session.add(
                        Trial(
                            study_id=study.id,
                            number=n,
                            state=TrialState.COMPLETE,
                            alpha_id=alpha_id,
                        )
                    )
                    await catalog.execute(
                        "INSERT INTO alpha (alpha_id, sim_type, status, checks) VALUES "
                        "(?, 'REGULAR', 'UNSUBMITTED', ?)",
                        [alpha_id, json.dumps(checks)],
                    )
            await session.commit()
        found = await yields(SimpleNamespace(db=db), catalog)  # type: ignore[arg-type]
        await db.dispose()
        await catalog.close()
        return {y.name: (y.cores, y.passing, y.refused) for y in found}

    assert asyncio.run(body()) == {"good": (3, 2, 1), "poor": (3, 0, 2)}
