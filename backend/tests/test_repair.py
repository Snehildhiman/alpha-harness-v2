"""Repair: variants of a near-miss, ranked by the models."""

import json
from typing import Any

from alpha_harness.repair.generate import Reshape, variants
from alpha_harness.repair.rank import near_miss, score
from alpha_harness.separation import Kind, judge_all
from tests.test_models import _vault

SETTINGS = {
    "region": "USA",
    "delay": 1,
    "universe": "TOP3000",
    "neutralization": "INDUSTRY",
    "decay": 4,
    "truncation": 0.08,
}


def test_variants_cover_every_family_once_each() -> None:
    out = variants(
        "rank(ts_mean(close, 20))",
        SETTINGS,
        reshapes=[Reshape("r1", "Residualize", "regression_neut(rank(close), returns)")],
        operators={"ts_decay_linear", "zscore"},
    )
    edits = {v.edit for v in out}
    assert "lookback 20 → 15" in edits and "lookback 20 → 40" in edits
    assert "ts_mean → ts_decay_linear" in edits
    assert "rank → zscore" in edits
    assert "Residualize" in edits
    assert "neutralization → subindustry" in edits
    assert "decay → 8" in edits
    assert "lookback 20 → 40 + neutralization → market" in edits
    assert len({v.key() for v in out}) == len(out)  # no duplicates
    assert not any(
        v.expression == "rank(ts_mean(close, 20))" and v.settings == SETTINGS for v in out
    )  # never the source itself


def test_swaps_need_the_operator_on_the_account() -> None:
    edits = {v.edit for v in variants("rank(ts_mean(close, 20))", SETTINGS, operators={"zscore"})}
    assert "rank → zscore" in edits
    assert "ts_mean → ts_decay_linear" not in edits


def test_power_pool_variants_keep_within_the_pool_limits() -> None:
    expr = "rank(ts_mean(close, 20) + ts_mean(open, 5) + ts_mean(high, 5))"
    big = Reshape("r", "Adds a fourth field", "rank(close + open + high + low)")
    out = variants(expr, SETTINGS, reshapes=[big], power_pool=True)
    assert "Adds a fourth field" not in {v.edit for v in out}
    assert out  # other edits still offered


def test_score_multiplies_the_types_checks_and_ignores_the_other_correlation() -> None:
    predicted = {
        "check:PROD_CORRELATION": 0.5,
        "check:POWER_POOL_CORRELATION": 0.9,
        "check:LOW_SHARPE": 0.8,
        "prod_corr": 0.69,
        "sharpe": 1.4,
    }
    regular = score(predicted, Kind.REGULAR)
    assert abs(regular.p_all - 0.4) < 1e-9
    assert regular.correlation == 0.69
    pp = score(predicted, Kind.POWER_POOL)
    assert abs(pp.p_all - 0.72) < 1e-9


def _row(alpha_id: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"alpha_id": alpha_id, "checks": json.dumps(checks), "status": "UNSUBMITTED"}


BASE = [{"name": "SELF_CORRELATION", "result": "PASS", "value": 0.3, "limit": 0.7}]


def test_near_miss_needs_every_failure_to_be_narrow() -> None:
    near = _row(
        "near", [*BASE, {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.72, "limit": 0.7}]
    )
    far = _row(
        "far", [*BASE, {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.83, "limit": 0.7}]
    )
    mixed = _row(
        "mixed",
        [
            *BASE,
            {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.71, "limit": 0.7},
            {"name": "LOW_SHARPE", "result": "FAIL", "value": 0.9, "limit": 1.25},
        ],
    )
    sharpe = _row(
        "sharpe",
        [
            *BASE,
            {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.5, "limit": 0.7},
            {"name": "LOW_SHARPE", "result": "FAIL", "value": 1.2, "limit": 1.25},
        ],
    )
    gaps = {j.row["alpha_id"]: near_miss(j) for j in judge_all([near, far, mixed, sharpe])}
    assert gaps["near"] is not None and abs(gaps["near"] - 0.4) < 1e-9
    assert gaps["far"] is None
    assert gaps["mixed"] is None  # sharpe 0.9 is 28% under its limit
    assert gaps["sharpe"] is not None


def test_ranked_variants_of_a_crowded_alpha_predict_lower_correlation() -> None:
    from alpha_harness.models.train import train_all

    rows, fields = _vault(n=3000)
    models = train_all(rows, fields, min_labels=200)
    crowded = max(fields, key=lambda f: fields[f].alpha_count or 0)
    quiet = min(fields, key=lambda f: fields[f].alpha_count or 0)
    source = f"rank(ts_delta({crowded}, 5))"
    swap = Reshape("q", f"Read {quiet} instead", f"rank(ts_mean({quiet}, 5))")
    out = variants(source, SETTINGS, reshapes=[swap], operators={"ts_av_diff", "zscore"})
    predicted = models.predict([{"expression": v.expression, **v.settings} for v in out], fields)
    ranked = sorted(
        zip(out, predicted, strict=True), key=lambda vp: -score(vp[1], Kind.REGULAR).p_all
    )
    base = models.predict([{"expression": source, **SETTINGS}], fields)[0]["prod_corr"]
    assert ranked[0][0].edit.startswith(f"Read {quiet} instead")
    assert ranked[0][1]["prod_corr"] < base - 0.2


def test_at_least_two_of_independent_regions() -> None:
    from alpha_harness.repair.rank import at_least

    assert abs(at_least([0.5, 0.5], 2) - 0.25) < 1e-9
    assert abs(at_least([0.5, 0.5, 0.5], 2) - 0.5) < 1e-9
    assert abs(at_least([0.9, 0.8, 0.1], 2) - (0.72 + 0.9 * 0.2 * 0.1 + 0.1 * 0.8 * 0.1)) < 1e-9
    assert at_least([0.7], 2) == 0.0


def _ra(regions: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    same = {
        "expression": "rank(x)",
        "date_created": "2026-10-20 10:00:00",
        "delay": 1,
        "neutralization": "INDUSTRY",
        "decay": 4,
        "truncation": 0.08,
    }
    parent = {
        "alpha_id": "p",
        "sim_type": "RA_PARENT",
        "region": "ALL",
        "checks": None,
        "status": "UNSUBMITTED",
        **same,
    }
    kids = [
        {
            "alpha_id": f"c-{r}",
            "sim_type": "RA_CHILD",
            "region": r,
            "checks": json.dumps(c),
            "status": "UNSUBMITTED",
            **same,
        }
        for r, c in regions.items()
    ]
    return [parent, *kids]


PASS = [*BASE, {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.6, "limit": 0.7}]
NEAR = [*BASE, {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.73, "limit": 0.7}]
FAR = [*BASE, {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.9, "limit": 0.7}]


def test_ra_family_is_near_when_narrow_fixes_reach_two_regions() -> None:
    one_pass_one_near = judge_all(_ra({"USA": PASS, "EUR": NEAR, "ASI": FAR}))[0]
    gap = near_miss(one_pass_one_near)
    assert gap is not None and abs(gap - 0.6) < 1e-9
    two_near = judge_all(_ra({"USA": NEAR, "EUR": NEAR, "ASI": FAR}))[0]
    assert near_miss(two_near) is not None
    one_pass_only = judge_all(_ra({"USA": PASS, "EUR": FAR, "ASI": FAR}))[0]
    assert near_miss(one_pass_only) is None
