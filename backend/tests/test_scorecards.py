"""Scorecards rank building blocks by the correlation they come with."""

import json
from typing import Any

from alpha_harness.models.features import FieldInfo
from alpha_harness.scorecards import build, parts_of, ranked


def alpha(expression: str, prod: float, neutralization: str = "SUBINDUSTRY") -> dict[str, Any]:
    checks = [
        {
            "name": "PROD_CORRELATION",
            "result": "PASS" if prod < 0.7 else "FAIL",
            "value": prod,
            "limit": 0.7,
        }
    ]
    return {
        "expression": expression,
        "neutralization": neutralization,
        "region": "USA",
        "checks": json.dumps(checks),
        "sharpe": 1.4,
    }


FIELDS = {
    "close": FieldInfo(dataset="pv1", category="pv"),
    "est_eps": FieldInfo(dataset="analyst4", category="analyst"),
}


def test_parts_cover_structure_data_and_settings() -> None:
    got = parts_of(alpha("rank(ts_mean(close, 20))", 0.5), FIELDS)
    assert {
        ("operator", "rank"),
        ("operator", "ts_mean"),
        ("pair", "rank>ts_mean"),
        ("field", "close"),
        ("dataset", "pv1"),
        ("category", "pv"),
        ("lookback", "20"),
        ("neutralization", "SUBINDUSTRY"),
        ("region", "USA"),
    } <= got


def test_crowded_parts_rank_high_and_rare_ones_are_shrunk() -> None:
    rows = [alpha("rank(ts_delta(close, 5))", 0.9) for _ in range(40)]
    rows += [alpha("group_rank(est_eps, industry)", 0.4) for _ in range(40)]
    rows += [alpha("rank(ts_zscore(close, 7))", 0.99) for _ in range(2)]  # seen twice only
    cards = build(rows, FIELDS, min_alphas=1)
    top = ranked(cards, part="category", metric="prod_corr", min_alphas=1, highest=True, limit=5)
    assert [c.name for c in top] == ["pv", "analyst"]
    hot = ranked(cards, part="operator", metric="prod_corr", min_alphas=1, highest=True, limit=10)
    names = [c.name for c in hot]
    # ts_zscore's two 0.99s are pulled toward the vault mean, below ts_delta's forty 0.9s.
    assert names.index("ts_delta") < names.index("ts_zscore")
    cold = ranked(
        cards, part="dataset", metric="check:PROD_CORRELATION", min_alphas=1, highest=True, limit=5
    )
    assert cold[0].name == "analyst4"  # the pass rate is highest where correlation is lowest
