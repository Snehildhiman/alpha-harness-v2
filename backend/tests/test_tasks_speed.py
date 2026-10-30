"""The Tasks page's reads: many ids in one parameter, lean Region Agnostic groups, cores."""

from types import SimpleNamespace
from typing import Any

import duckdb

from alpha_harness.api.lab_tasks import _rank_groups
from alpha_harness.db.duck import AMONG, packed
from alpha_harness.db.models import TrialState
from alpha_harness.labs.scheduler import cores_of


def test_packed_ids_match_exactly() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE alpha (alpha_id VARCHAR)")
    con.executemany("INSERT INTO alpha VALUES (?)", [(f"A{i}",) for i in range(50)])
    wanted = ["A1", "A10", "A49", "missing"]
    got = con.execute(
        f"SELECT alpha_id FROM alpha WHERE alpha_id IN {AMONG} ORDER BY alpha_id",  # noqa: S608
        [packed(wanted)],
    ).fetchall()
    assert [r[0] for r in got] == ["A1", "A10", "A49"]
    big = [f"A{i}" for i in range(40_000)]
    assert con.execute(
        f"SELECT count(*) FROM alpha WHERE alpha_id IN {AMONG}",  # noqa: S608
        [packed(big)],
    ).fetchone() == (50,)


def _row(trial: int, group: int, region: str, state: str, alpha: str | None) -> tuple[Any, ...]:
    return (trial, trial, group, region, "TOP3000", "MARKET", 4, 0.08, state, alpha, "rank(x)")


def test_groups_rank_cleanest_first() -> None:
    passing = '[{"name": "LOW_SHARPE", "result": "PASS"}]'
    failing = '[{"name": "LOW_SHARPE", "result": "FAIL"}]'
    rows = [
        _row(1, 0, "USA", TrialState.COMPLETE, "a"),
        _row(2, 0, "EUR", TrialState.COMPLETE, "b"),
        _row(3, 1, "USA", TrialState.COMPLETE, "c"),
        _row(4, 1, "EUR", TrialState.QUEUED, None),
    ]
    stored = {
        "a": {"checks": failing, "sharpe": 1.0},
        "b": {"checks": passing, "sharpe": 1.2},
        "c": {"checks": passing, "sharpe": 1.6},
    }
    ranked, complete, calibrated = _rank_groups(rows, stored)
    assert [g.group for g in ranked] == [1, 0]
    assert complete == 3
    assert calibrated == 3
    assert [a.state for a in ranked[0].alphas] == ["complete", "running"]
    assert ranked[0].best_sharpe == 1.6


def test_cores_read_without_validating_the_task() -> None:
    def row(params: dict[str, Any]) -> Any:
        return SimpleNamespace(sampler="region-agnostic", sampler_params=params)

    assert cores_of(row({"cores": 3})) == 3
    # An old row missing fields its lab now requires still reports its cores.
    assert cores_of(row({"region": "USA", "cores": 2})) == 2
    assert cores_of(row({})) == 1
    assert cores_of(row({"cores": "x"})) == 1


def test_progress_counts_in_one_pass(tmp_path: Any) -> None:
    import asyncio

    from alpha_harness.api.lab_tasks import _progress
    from alpha_harness.db.models import Study, Trial
    from alpha_harness.db.sqlite import Database
    from alpha_harness.labs import scheduler

    async def body() -> None:
        db = Database(tmp_path / "h.db")
        await db.create_all()
        async with db.session() as session:
            session.add(Study(id=1, name="t", template_source="", sampler="search"))
            trials = [
                (TrialState.COMPLETE, None, {}, [1.5], None),
                (TrialState.COMPLETE, scheduler.FREE, {}, [0.7], None),
                (TrialState.FAIL, scheduler.FREE, {}, None, None),
                (TrialState.COMPLETE, None, {"fullOf": 1}, [2.0], None),
                (TrialState.FAIL, "Simulation failed: bad unit", {}, None, None),
                (TrialState.FAIL, "Simulation failed: bad unit", {}, None, None),
                # A seed is no best, however good.
                (TrialState.COMPLETE, None, {}, [9.0], 0),
                (TrialState.QUEUED, None, {}, None, None),
            ]
            for n, (st, msg, params, values, generation) in enumerate(trials):
                session.add(
                    Trial(
                        study_id=1,
                        number=n,
                        state=st,
                        message=msg,
                        params=params,
                        values=values,
                        generation=generation,
                    )
                )
            await session.commit()
        out = (await _progress(SimpleNamespace(db=db), [1]))[1]
        assert out["states"] == {"COMPLETE": 4, "FAIL": 3, "QUEUED": 1}
        assert out["free"] == 2
        assert out["fullRuns"] == 1
        assert out["best"] == 2.0
        assert sum(out["failures"].values()) == 3
        await db.dispose()

    asyncio.run(body())


def test_alphas_of_a_failed_batch_go_alone() -> None:
    import dataclasses

    from alpha_harness.engine.packer import WorkItem, key_of, pack

    payload = {"type": "REGULAR", "settings": {"region": "USA", "delay": 1}}
    key = key_of(payload)
    together = [WorkItem(i, key, "t", payload) for i in range(4)]
    assert [len(b.items) for b in pack(together, free_slots=8)] == [4]
    alone = [WorkItem(i, dataclasses.replace(key, alone=True), "t", payload) for i in range(4)]
    assert [len(b.items) for b in pack(alone, free_slots=8)] == [1, 1, 1, 1]


def test_glb_simulations_go_one_at_a_time() -> None:
    from alpha_harness.engine.packer import WorkItem, key_of, pack

    payload = {"type": "REGULAR", "settings": {"region": "GLB", "delay": 1}}
    items = [WorkItem(i, key_of(payload), "t", payload) for i in range(6)]
    # Four at once: two cores each of the eight.
    assert [len(b.items) for b in pack(items, free_slots=8)] == [1, 1, 1, 1]
