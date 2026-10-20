"""Which submittable Alpha to submit next: what each would do to the combined book.

BRAIN combines every submitted Alpha at equal weight, and the quarterly payment and level are
judged on that combination's performance, before and after trading costs. So the useful
question about a candidate is not its own Sharpe but how it moves the combination's: an Alpha
with a modest Sharpe that trades differently from the pool can lift it more than a strong one
that repeats what is already there.

For each candidate this computes, on the stored daily PnL and turnover:

* the combined IR (annualised Sharpe of the equal-weight book) with and without it, before
  and after cost, and the change;
* its correlation with the pool's combined book, and its highest correlation with any one
  submitted Alpha (a self-correlation estimate).

BRAIN's base payment formula is not published, so nothing here claims to compute money. The
combined-IR change is the honest proxy for the part of pay that rewards the combination, and
the candidate's own Sharpe and fitness stand beside it for the part that rewards each Alpha.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from ..vault import metrics
from . import portfolio

if TYPE_CHECKING:
    from datetime import date

    from ..vault.metrics import Floats

#: Days a candidate must share with the pool for its correlations to mean anything.
MIN_SHARED = 120


@dataclass(frozen=True, slots=True)
class Ranked:
    alpha_id: str
    ir: float | None
    ir_after_cost: float | None
    delta_ir: float | None
    delta_ir_after_cost: float | None
    pool_correlation: float | None
    max_correlation: float | None
    max_correlation_with: str | None
    shared_days: int


def _ir(book: Floats, traded: Floats, cost_bps: float | None) -> float | None:
    pnl = metrics.after_cost(book, traded, cost_bps) if cost_bps else book
    found = metrics.stats(pnl, traded)
    return found.sharpe if found else None


def _corr(a: Floats, b: Floats) -> tuple[float | None, int]:
    keep = ~(np.isnan(a) | np.isnan(b))
    n = int(keep.sum())
    if n < MIN_SHARED:
        return None, n
    x, y = a[keep], b[keep]
    if x.std() == 0 or y.std() == 0:
        return None, n
    return float(np.corrcoef(x, y)[0, 1]), n


def rank(
    series: dict[str, dict[date, tuple[float, float]]],
    meta: dict[str, dict[str, Any]],
    submitted: list[str],
    candidates: list[str],
    cost_bps: float = metrics.DEFAULT_COST_BPS,
) -> tuple[dict[str, float | None], list[Ranked]]:
    """The pool's combined IR now, and every candidate with a series, best change first."""
    pool = [a for a in dict.fromkeys(submitted) if series.get(a)]
    wanted = [a for a in dict.fromkeys(candidates) if series.get(a) and a not in pool]
    ids = pool + wanted
    if not ids:
        return {"ir": None, "ir_after_cost": None, "alphas": 0}, []
    _, pnl, turnover, _ = portfolio.frame(series, meta, ids)
    filled = np.nan_to_num(pnl)
    started = np.maximum.accumulate((filled != 0) | (turnover != 0), axis=0)
    k = len(pool)
    pool_sum = filled[:, :k].sum(axis=1)
    pool_traded = turnover[:, :k].sum(axis=1)
    pool_live = started[:, :k].sum(axis=1)

    def book(add: int | None) -> tuple[Floats, Floats]:
        if add is None:
            live = np.maximum(pool_live, 1)
            return pool_sum / live, pool_traded / live
        col = k + add
        live = np.maximum(pool_live + started[:, col], 1)
        return (pool_sum + filled[:, col]) / live, (pool_traded + turnover[:, col]) / live

    base_book, base_traded = book(None)
    has_pool = k > 0
    base_ir = _ir(base_book, base_traded, None) if has_pool else None
    base_after = _ir(base_book, base_traded, cost_bps) if has_pool else None
    pool_curve = np.where(pool_live > 0, base_book, np.nan)

    out: list[Ranked] = []
    for i, alpha_id in enumerate(wanted):
        col = k + i
        new_book, new_traded = book(i)
        ir, after = _ir(new_book, new_traded, None), _ir(new_book, new_traded, cost_bps)
        own = pnl[:, col]
        pool_corr, shared = _corr(own, pool_curve) if has_pool else (None, 0)
        best: tuple[float, str] | None = None
        for j, other in enumerate(pool):
            c, _ = _corr(own, pnl[:, j])
            if c is not None and (best is None or c > best[0]):
                best = (c, other)
        out.append(
            Ranked(
                alpha_id=alpha_id,
                ir=ir,
                ir_after_cost=after,
                delta_ir=None if ir is None or base_ir is None else ir - base_ir,
                delta_ir_after_cost=None
                if after is None or base_after is None
                else after - base_after,
                pool_correlation=pool_corr,
                max_correlation=best[0] if best else None,
                max_correlation_with=best[1] if best else None,
                shared_days=shared,
            )
        )
    out.sort(
        key=lambda r: (
            -(
                r.delta_ir_after_cost
                if r.delta_ir_after_cost is not None
                else (r.ir_after_cost if r.ir_after_cost is not None else -99.0)
            )
        )
    )
    return {"ir": base_ir, "ir_after_cost": base_after, "alphas": k}, out
