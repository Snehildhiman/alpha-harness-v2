"""The learned models: features, honest testing, and that they learn a planted signal."""

import json
import math
import random
from datetime import datetime, timedelta
from typing import Any

from alpha_harness.models.features import FieldInfo, read_expression, targets_of
from alpha_harness.models.train import ModelSet, auc, spearman, train_all


def test_expression_structure_is_read() -> None:
    p = read_expression("group_rank(ts_mean(est_eps / close, 20), subindustry)")
    assert p.ok
    assert p.fields == ["close", "est_eps"]  # grouping field excluded
    assert p.operators["ts_mean"] == 1
    assert "group_rank>ts_mean" in p.pairs
    assert "ts_mean>/" in p.pairs
    assert p.numbers == [20.0]
    assert not read_expression("rank(").ok


def test_targets_take_correlation_values_and_check_results() -> None:
    row = {
        "sharpe": 1.4,
        "checks": json.dumps(
            [
                {"name": "PROD_CORRELATION", "result": "WARNING", "value": 0.81, "limit": 0.7},
                {"name": "LOW_SHARPE", "result": "PASS", "value": 1.4, "limit": 1.25},
                {"name": "SELF_CORRELATION", "result": "PENDING"},
                {"name": "MATCHES_THEMES", "result": "PASS"},
            ]
        ),
    }
    t = targets_of(row)
    assert t["prod_corr"] == 0.81
    assert t["check:PROD_CORRELATION"] == 0.0  # above the limit
    assert t["check:LOW_SHARPE"] == 1.0
    assert "check:SELF_CORRELATION" not in t  # pending teaches nothing
    assert "check:MATCHES_THEMES" not in t  # a label, not a judgement
    assert targets_of({**row, "simulation_mode": "QUICK"}) == {"sharpe": 1.4}


def test_metrics() -> None:
    import numpy as np

    assert auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert auc(np.array([0, 1]), np.array([0.5, 0.5])) == 0.5
    assert math.isclose(spearman(np.array([1.0, 2, 3, 4]), np.array([10.0, 20, 30, 40])), 1.0)


def _vault(n: int = 4000, seed: int = 5) -> tuple[list[dict[str, Any]], dict[str, FieldInfo]]:
    """Prod correlation driven by field crowding and ts_delta, plus noise."""
    rng = random.Random(seed)
    fields = {
        f"f{i}": FieldInfo(
            dataset=f"d{i % 5}",
            category="pv" if i < 10 else "analyst",
            alpha_count=int(10 ** rng.uniform(1.5, 4)),
            user_count=50,
        )
        for i in range(40)
    }
    rows = []
    for i in range(n):
        f = f"f{rng.randrange(40)}"
        op = rng.choice(["ts_mean", "ts_delta", "ts_rank"])
        crowd = math.log1p(fields[f].alpha_count) / math.log1p(10_000)
        corr = 0.2 + 0.6 * crowd + (0.15 if op == "ts_delta" else 0) + rng.gauss(0, 0.05)
        rows.append(
            {
                "alpha_id": f"a{i}",
                "expression": f"rank({op}({f}, {rng.choice([5, 20, 60])}))",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "neutralization": "INDUSTRY",
                "decay": 4,
                "truncation": 0.08,
                "sharpe": rng.gauss(1.2, 0.3),
                "checks": json.dumps(
                    [
                        {
                            "name": "PROD_CORRELATION",
                            "result": "WARNING",
                            "value": round(corr, 3),
                            "limit": 0.7,
                        }
                    ]
                ),
                "date_created": datetime(2025, 1, 1) + timedelta(hours=i),
            }
        )
    return rows, fields


def test_models_learn_a_planted_signal_on_unseen_newer_alphas(tmp_path: Any) -> None:
    rows, fields = _vault()
    models = train_all(rows, fields, min_labels=200)
    report = {r.target: r for r in models.reports}
    prod = report["prod_corr"]
    assert prod.trained
    assert prod.n_test == 800  # the newest 20%, never trained on
    assert prod.metrics["spearman"] > 0.7
    assert prod.metrics["mae"] < prod.metrics["baseline_mae"] * 0.7
    assert report["check:PROD_CORRELATION"].metrics["auc"] > 0.85
    assert models.test_from == "2025-05-14"  # 3,200 hours in: where the newest 20% start
    assert all(math.isfinite(v) for r in models.reports for v in r.metrics.values())

    models.save(tmp_path / "models")
    loaded = ModelSet.load(tmp_path / "models")
    assert loaded is not None
    probe = [{"expression": "rank(ts_delta(f3, 5))", "region": "USA", "delay": 1}]
    assert loaded.predict(probe, fields) == models.predict(probe, fields)
    crowded = max(fields, key=lambda f: fields[f].alpha_count or 0)
    quiet = min(fields, key=lambda f: fields[f].alpha_count or 0)
    hi = models.predict([{"expression": f"rank(ts_delta({crowded}, 5))"}], fields)[0]
    lo = models.predict([{"expression": f"rank(ts_mean({quiet}, 5))"}], fields)[0]
    assert hi["prod_corr"] > lo["prod_corr"] + 0.2


def test_a_constant_target_is_skipped_not_trained() -> None:
    rows, fields = _vault(n=1500)
    for r in rows:
        checks = json.loads(r["checks"]) + [
            {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.3, "limit": 0.7}
        ]
        r["checks"] = json.dumps(checks)
    report = {r.target: r for r in train_all(rows, fields, min_labels=200).reports}
    assert report["self_corr"].kind == "skipped"
    assert report["check:SELF_CORRELATION"].kind == "skipped"
