"""Live learning: retraining by itself, and the gate that protects the models in use."""

import asyncio
import json
import random
from typing import Any

from alpha_harness.db.duck import Catalog
from alpha_harness.models.service import AUTO_NEW, ModelService
from alpha_harness.models.train import gate, train_all
from tests.test_models import _vault


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["alpha_id"]: r for r in rows}


def test_gate_accepts_an_honest_retrain_and_rejects_a_damaged_one() -> None:
    rows, fields = _vault(n=3000)
    old = train_all(rows[:2000], fields, min_labels=200)
    # As if trained the day the 2,000th Alpha was simulated: everything after is unseen.
    old.trained_at = str(rows[1999]["date_created"])[:10] + "T23:59:59+00:00"

    honest = train_all(rows, fields, min_labels=200)
    verdict = gate(old, honest, _by_id(rows), fields)
    assert verdict.accepted, verdict.reason
    assert any(t == "prod_corr" for t, *_ in verdict.compared)

    rng = random.Random(1)
    damaged_rows = [dict(r) for r in rows]
    shuffled = [json.loads(r["checks"])[0]["value"] for r in damaged_rows[:2400]]
    rng.shuffle(shuffled)
    for r, value in zip(damaged_rows[:2400], shuffled, strict=True):
        check = json.loads(r["checks"])[0]
        r["checks"] = json.dumps([{**check, "value": value}])
    damaged = train_all(damaged_rows, fields, min_labels=200)
    verdict = gate(old, damaged, _by_id(rows), fields)
    assert not verdict.accepted, verdict.reason


def test_auto_retrain_waits_for_enough_new_results(tmp_path: Any) -> None:
    async def body() -> None:
        rows, fields = _vault(n=1200)
        catalog = Catalog(tmp_path / "c.duckdb")
        await catalog.open()
        cols = (
            "alpha_id",
            "expression",
            "region",
            "delay",
            "universe",
            "neutralization",
            "decay",
            "truncation",
            "sharpe",
            "checks",
            "date_created",
        )

        async def insert(batch: list[dict[str, Any]]) -> None:
            await catalog.upsert("alpha", cols, [tuple(r.get(c) for c in cols) for r in batch])

        for name, info in fields.items():
            await catalog.execute(
                "INSERT INTO data_field (field_id, dataset_id, category_id, alpha_count,"
                " user_count, instrument_type, region, delay, universe)"
                " VALUES (?, ?, ?, ?, ?, 'EQUITY', 'USA', 1, 'TOP3000')",
                [name, info.dataset, info.category, info.alpha_count, info.user_count],
            )
        await insert(rows[:1000])
        service = ModelService(catalog, tmp_path / "models")
        assert await service.tick() == "trained"  # first models as soon as there is enough
        assert await service.tick() is None  # nothing new
        await insert(rows[1000 : 1000 + AUTO_NEW - 1])
        assert await service.tick() is None  # one short
        await insert(rows[1000 + AUTO_NEW - 1 : 1000 + AUTO_NEW])
        assert await service.tick() == "trained"
        assert service.last_gate is not None
        service.auto = False
        await insert(rows[1100:])
        assert await service.tick() is None  # switched off in Settings
        await catalog.close()

    asyncio.run(body())
