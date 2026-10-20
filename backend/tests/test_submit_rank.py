"""What to submit next: a candidate unlike the pool lifts the combined IR more."""

from datetime import date, timedelta

import numpy as np

from alpha_harness.tools.submit_rank import rank


def test_a_diversifying_alpha_beats_a_copy() -> None:
    rng = np.random.default_rng(3)
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(600)]
    common = rng.normal(0.2, 1.0, len(days))

    def series(values: np.ndarray) -> dict[date, tuple[float, float]]:
        return {d: (float(v) * 1000, 0.1) for d, v in zip(days, values, strict=True)}

    pool = {f"S{i}": series(common + rng.normal(0, 0.3, len(days))) for i in range(3)}
    copy = series(common + rng.normal(0, 0.3, len(days)))
    fresh = series(rng.normal(0.2, 1.0, len(days)))
    all_series = {**pool, "COPY": copy, "FRESH": fresh}
    book, ranked = rank(all_series, {}, list(pool), ["COPY", "FRESH", "NOSERIES"], cost_bps=0)
    assert book["alphas"] == 3 and book["ir"] is not None
    assert [r.alpha_id for r in ranked] == ["FRESH", "COPY"]  # no series: left out
    fresh_row, copy_row = ranked
    assert fresh_row.delta_ir is not None and copy_row.delta_ir is not None
    assert fresh_row.delta_ir > copy_row.delta_ir
    assert copy_row.max_correlation is not None and copy_row.max_correlation > 0.8
    assert fresh_row.pool_correlation is not None and abs(fresh_row.pool_correlation) < 0.2
