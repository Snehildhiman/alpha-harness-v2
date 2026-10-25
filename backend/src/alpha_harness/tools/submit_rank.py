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


# -- a theme's combination ----------------------------------------------------------------

#: The most recent days the out-of-sample figures are read over: BRAIN's two test years.
OS_DAYS = 2 * metrics.YEAR


@dataclass(frozen=True, slots=True)
class Combo:
    """A set of Alphas merged at equal weight, as the Power Pool leaderboard shows it (Merged
    PnL, BC Combo IR, AC Combo IR), and the same IRs over recent years (the OS proxy)."""

    #: Combo IR over the whole history, before and after cost.
    bc_ir: float | None
    ac_ir: float | None
    #: The same over the last :data:`OS_DAYS` only: what an out-of-sample score sees.
    os_ir: float | None
    ac_os_ir: float | None
    #: The merged book's total PnL over its history, in dollars of one Alpha's book (an
    #: estimate of the leaderboard's Merged PNL, from the stored daily PnL).
    pnl: float | None = None

    def values(self) -> tuple[float | None, ...]:
        return (self.bc_ir, self.ac_ir, self.os_ir, self.ac_os_ir)


#: How much each figure counts in a pick's score: the leaderboard shows BC and AC Combo IR, so
#: they lead; the recent-years IRs keep a pick from leaning on an old stretch alone.
WEIGHTS = (0.35, 0.35, 0.15, 0.15)


@dataclass(frozen=True, slots=True)
class ComboPick:
    alpha_id: str
    #: The set's figures with this Alpha added (to the pool and every earlier pick).
    combo: Combo
    #: Each figure's change from the set without it, and their mean, the order picks come in.
    delta: Combo
    score: float | None
    #: Highest daily PnL correlation with an Alpha already in the set, and which.
    max_correlation: float | None
    max_correlation_with: str | None


def _combo(book: Floats, traded: Floats, live: Floats, cost_bps: float) -> Combo:
    on = np.flatnonzero(live > 0)
    if not on.size:
        return Combo(None, None, None, None)
    book, traded = book[on[0] :], traded[on[0] :]
    recent = slice(max(0, book.size - OS_DAYS), None)
    return Combo(
        _ir(book, traded, None),
        _ir(book, traded, cost_bps),
        _ir(book[recent], traded[recent], None),
        _ir(book[recent], traded[recent], cost_bps),
        float(book.sum()),
    )


def _less(a: Combo, b: Combo) -> Combo:
    pairs = zip((*a.values(), a.pnl), (*b.values(), b.pnl), strict=True)
    found = [None if x is None or y is None else x - y for x, y in pairs]
    return Combo(*found)


def _mean(c: Combo) -> float | None:
    """The weighted mean of the four IR changes (:data:`WEIGHTS`), over those known."""
    known = [(w, v) for w, v in zip(WEIGHTS, c.values(), strict=True) if v is not None]
    total = sum(w for w, _ in known)
    return sum(w * v for w, v in known) / total if known else None


def theme_combo(
    series: dict[str, dict[date, tuple[float, float]]],
    meta: dict[str, dict[str, Any]],
    pool: list[str],
    candidates: list[str],
    *,
    picks: int = 10,
    cost_bps: float = metrics.DEFAULT_COST_BPS,
) -> tuple[Combo, list[ComboPick], list[ComboPick]]:
    """A theme's combination now, the best order to add candidates in, and every candidate's
    effect on the combination as it stands.

    A theme ranks a user's Alphas as one equal-weight book: Combo IR before and after cost,
    and an out-of-sample score before and after cost. Each candidate is scored on the weighted
    change of those four (:data:`WEIGHTS`: BC and AC first, as the leaderboard shows them);
    ``picks`` are then chosen greedily, each judged against the pool *and the picks before
    it*, so two candidates that repeat each other are not both picked. The out-of-sample
    figures here are the last two years held out of nothing: a proxy for
    the score BRAIN keeps for after submission, which no stored series can show.
    """
    kept = [a for a in dict.fromkeys(pool) if series.get(a)]
    wanted = [a for a in dict.fromkeys(candidates) if series.get(a) and a not in kept]
    ids = kept + wanted
    if not ids:
        return Combo(None, None, None, None), [], []
    _, pnl, turnover, _ = portfolio.frame(series, meta, ids)
    filled = np.nan_to_num(pnl)
    started = np.maximum.accumulate((filled != 0) | (turnover != 0), axis=0).astype(float)

    def score_all(chosen: list[int], left: list[int]) -> tuple[Combo, list[ComboPick]]:
        total = filled[:, chosen].sum(axis=1)
        traded = turnover[:, chosen].sum(axis=1)
        live = started[:, chosen].sum(axis=1)
        div = np.maximum(live, 1)
        base = _combo(total / div, traded / div, live, cost_bps)
        out: list[ComboPick] = []
        for col in left:
            with_live = live + started[:, col]
            div_new = np.maximum(with_live, 1)
            combo = _combo(
                (total + filled[:, col]) / div_new,
                (traded + turnover[:, col]) / div_new,
                with_live,
                cost_bps,
            )
            delta = _less(combo, base) if chosen else combo
            best: tuple[float, str] | None = None
            for j in chosen:
                c, _ = _corr(pnl[:, col], pnl[:, j])
                if c is not None and (best is None or c > best[0]):
                    best = (c, ids[j])
            out.append(
                ComboPick(
                    alpha_id=ids[col],
                    combo=combo,
                    delta=delta,
                    score=_mean(delta),
                    max_correlation=best[0] if best else None,
                    max_correlation_with=best[1] if best else None,
                )
            )
        out.sort(key=lambda p: -(p.score if p.score is not None else float("-inf")))
        return base, out

    pool_cols = list(range(len(kept)))
    left = list(range(len(kept), len(ids)))
    base, each = score_all(pool_cols, left)
    order: list[ComboPick] = []
    chosen = list(pool_cols)
    while left and len(order) < picks:
        _, ranked = score_all(chosen, left)
        top = ranked[0]
        # A pick that lowers the set on average is not worth submitting for the theme.
        if top.score is None or (chosen and top.score <= 0):
            break
        order.append(top)
        col = ids.index(top.alpha_id)
        chosen.append(col)
        left.remove(col)
    return base, order, each
