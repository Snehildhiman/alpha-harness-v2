"""ARC: when regional runs earn a real region-agnostic run, and how candidates are written."""

import random

from alpha_harness.labs import ra_shapes
from alpha_harness.labs.params import RegionAgnosticParams
from alpha_harness.labs.power_pool import child_state, draw_regions, promotable

from .test_no_llm_and_universes import NAMES, _ctx


def _checks(sharpe: float, fitness: float = 1.2, prod: str = "PASS") -> list[dict[str, object]]:
    return [
        {
            "name": "LOW_SHARPE",
            "result": "PASS" if sharpe >= 1.58 else "FAIL",
            "value": sharpe,
            "limit": 1.58,
        },
        {
            "name": "LOW_FITNESS",
            "result": "PASS" if fitness >= 1 else "FAIL",
            "value": fitness,
            "limit": 1.0,
        },
        {"name": "PROD_CORRELATION", "result": prod, "value": 0.6, "limit": 0.7},
    ]


def test_child_state_ignores_correlation() -> None:
    assert child_state(_checks(1.7, prod="FAIL")) == "pass"
    assert child_state(_checks(1.5)) == "near"  # 95% of the limit
    assert child_state(_checks(1.2)) == "fail"
    assert child_state([]) == "fail"


def test_two_regions_earn_a_real_ra_run() -> None:
    two = {"USA": _checks(1.8), "GLB": _checks(1.7), "EUR": _checks(0.4)}
    assert promotable(two, "strict")
    assert promotable(two, "near")
    one_and_near = {"USA": _checks(1.8), "GLB": _checks(1.5)}
    assert not promotable(one_and_near, "strict")
    assert promotable(one_and_near, "near")
    assert not promotable({"USA": _checks(1.8), "GLB": _checks(0.9)}, "near")
    assert not promotable(two, "off")


def test_all_passing_regions_crowded_is_not_promoted() -> None:
    crowded = {"USA": _checks(1.8, prod="FAIL"), "GLB": _checks(1.7, prod="FAIL")}
    assert not promotable(crowded, "near")
    # One passing child under the prod limit is enough for BRAIN.
    assert promotable({"USA": _checks(1.8, prod="FAIL"), "GLB": _checks(1.7)}, "near")


def test_asi_runs_with_max_trade() -> None:
    run = RegionAgnosticParams(
        region="ALL",
        delay=1,
        universes=[],
        neutralizations=["MARKET"],
        regions=["USA", "EUR", "ASI"],
        region_universes={"USA": "TOP3000", "EUR": "TOP2500", "ASI": "MINVOL1M"},
    )
    runs = {r["region"]: r for r in draw_regions(random.Random(0), frozenset({"eps"}), _ctx(), run)}
    assert runs["ASI"].get("maxTrade") == "ON"
    assert "maxTrade" not in runs["USA"]


def test_hypotheses_follow_the_dataset() -> None:
    assert "short_reversal" in ra_shapes.favoured("imbalance5")
    assert "revision_trend" in ra_shapes.favoured("analyst69")
    assert "amount_ratio" in ra_shapes.favoured("fundamental17")
    assert "decayed" in ra_shapes.favoured("model38")
    assert ra_shapes.favoured("xyz") == frozenset()


def test_currency_needs_a_cure() -> None:
    from alpha_harness.labs import currency

    amount = currency.is_amount
    assert currency.problem("rank(sales)", amount)
    assert currency.problem("x = ts_backfill(sales, 21); rank(x)", amount)
    assert currency.problem("-rank(ts_delta(close, 5))", amount)
    assert currency.problem("close", amount)
    assert currency.problem("rank(sales / assets)", amount) is None
    assert currency.problem("rank(ts_zscore(sales, 63))", amount) is None
    assert currency.problem("ts_rank(close, 20)", amount) is None
    assert currency.problem("rank(returns)", amount) is None
    assert not currency.is_amount("gross_margin_ratio", "gross margin ratio")


def test_shapes_never_rank_an_amount_raw() -> None:
    from alpha_harness.labs import currency

    ctx = _ctx()
    written, _ = ra_shapes.write(
        ctx, NAMES | {"ts_rank", "group_neutralize"}, random.Random(5), count=40, offset=0
    )
    amount = currency.amounts_in([*ctx.fields, *ctx.basics])
    assert written
    assert all(currency.problem(w["expression"], amount) is None for w in written)
