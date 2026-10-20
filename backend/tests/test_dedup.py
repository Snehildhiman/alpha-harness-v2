"""Equivalent alphas are recognised before a simulation is spent on them."""

import asyncio
from typing import Any

from alpha_harness.brain.schemas import SimulationRequest, SimulationSettings
from alpha_harness.canon import canonical
from alpha_harness.db.duck import Catalog
from alpha_harness.db.models import SimStatus
from alpha_harness.db.sqlite import Database
from alpha_harness.engine.lifecycle import legacy_request_hash, request_hash
from alpha_harness.engine.slots import BatchEngine
from alpha_harness.engine.vault_dedup import VaultIndex, request_key


def same(a: str, b: str) -> bool:
    return canonical(a) == canonical(b)


def test_equivalent_spellings_share_one_form() -> None:
    assert same("add(a, b)", "add(b,a)")
    assert same("add(a, b)", "b + a")
    assert same("multiply(rank(x), y)", "y * rank(x)")
    assert same("a + b + c", "c + (b + a)")
    assert same("rank(rank(rank(x)))", "rank(x)")
    assert same("ts_mean(x, 20.0)", "ts_mean(x, 20)")
    assert same("-(-x)", "x")
    assert same("a = rank(x); a * 2", "s = rank(x); 2 * s")
    assert same("  ts_rank( close ,5 ) ", "ts_rank(close, 5)")


def test_different_alphas_stay_different() -> None:
    assert not same("a - b", "b - a")
    assert not same("a / b", "b / a")
    assert not same("ts_mean(x, 20)", "ts_mean(x, 21)")
    assert not same("rank(ts_rank(x, 5))", "ts_rank(x, 5)")
    # A keyword argument pins the order: filter semantics are BRAIN's to decide.
    assert not same("add(a, b, filter=true)", "add(b, a, filter=true)")
    assert canonical("not ( valid") == "not ( valid"


def req(expression: str, **settings: Any) -> SimulationRequest:
    base = {
        "region": "USA",
        "universe": "TOP3000",
        "delay": 1,
        "decay": 4,
        "neutralization": "SUBINDUSTRY",
        "truncation": 0.08,
    }
    return SimulationRequest(
        regular=expression, settings=SimulationSettings(**{**base, **settings})
    )


def test_request_hash_is_canonical_and_legacy_is_exact() -> None:
    a, b = req("add(close, vwap)"), req("add(vwap,close)")
    assert request_hash(a) == request_hash(b)
    assert legacy_request_hash(a) != legacy_request_hash(b)
    assert request_hash(a) != request_hash(req("add(close, vwap)", decay=5))


def test_vault_keys_ignore_unstored_settings_only_at_defaults() -> None:
    assert request_key(req("rank(x)")) is not None
    assert request_key(req("rank(x)", nan_handling="OFF")) is None


class Tracker:
    async def notify(self) -> None:
        return None


def test_enqueue_reuses_a_vault_alpha_written_differently(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = Catalog(tmp_path / "c.duckdb")
        await catalog.open()
        await catalog.execute(
            "INSERT INTO alpha (alpha_id, expression, sim_type, instrument_type, region,"
            " universe, delay, neutralization, decay, truncation, simulation_mode, test_start,"
            " fetched_at) VALUES ('OLD1', 'add(close,vwap)', 'REGULAR', 'EQUITY', 'USA',"
            " 'TOP3000', 1, 'SUBINDUSTRY', 4, 0.08, 'FULL', DATE '2024-01-01', now())"
        )
        db = Database(tmp_path / "h.db")
        await db.create_all()
        engine = BatchEngine(db, None, Tracker(), on_unauthorized=None)  # type: ignore[arg-type]
        engine.vault = VaultIndex(catalog)
        out = await engine.enqueue(
            [
                req("add(vwap, close)"),  # the vault's alpha, spelt the other way
                req("add(vwap, close)", decay=6),  # a different alpha
                req("vwap + close", decay=6),  # the line above, spelt another way
            ]
        )
        statuses = [o["status"] for o in out["outcomes"]]
        assert statuses == [SimStatus.SKIPPED, SimStatus.QUEUED, SimStatus.SKIPPED]
        assert out["outcomes"][0]["alphaId"] == "OLD1"
        assert out["outcomes"][2]["recordId"] == out["outcomes"][1]["recordId"]
        await db.dispose()
        await catalog.close()

    asyncio.run(body())
