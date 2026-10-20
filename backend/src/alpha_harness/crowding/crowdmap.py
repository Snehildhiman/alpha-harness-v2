"""The crowd map: a lower bound on an Alpha's prod correlation, worked out locally.

BRAIN's prod correlation is an Alpha's highest PnL correlation with any Alpha in production,
and production is hidden. But every Alpha whose prod correlation BRAIN already reported is a
landmark: if it sits at correlation ``p`` with *something* in production, and a new Alpha
correlates ``r`` with it, the new Alpha's correlation with that same production Alpha is at
least

    r·p - √((1 - r²)(1 - p²))

because correlations are cosines of angles between de-meaned PnL series, and angles obey the
triangle inequality. Your own submitted Alphas are in production too, so for them ``p`` is 1
and the bound is ``r`` itself.

The best bound over every landmark in the region is a floor, not an estimate: when it already
clears BRAIN's 0.7 the Alpha will fail prod correlation (bar BRAIN's Sharpe exception), and
asking BRAIN, a slow and tightly rate-limited check, can wait for something that might pass.
It also tells a repair *which* crowded Alpha it is too close to.

Computed over BRAIN's correlation window, on days both series traded, as
:func:`alpha_harness.tools.submission_planner.correlations` does.
"""

import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from ..tools.submission_planner import correlations, window_start
from ..vault.yields import checks_of, is_submitted

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..vault.store import PnlGrid

#: Landmarks below this prod correlation cannot push a floor past BRAIN's 0.7: the bound
#: never exceeds ``p``. Leaving them out keeps the PnL read small.
MIN_LANDMARK = 0.6


def bound(r: float, p: float) -> float:
    """The lowest correlation with ``p``'s production partner an Alpha at ``r`` can have."""
    r, p = max(-1.0, min(1.0, r)), max(-1.0, min(1.0, p))
    return r * p - math.sqrt(max(0.0, (1 - r * r) * (1 - p * p)))


@dataclass(frozen=True, slots=True)
class Floor:
    #: The highest lower bound over every landmark, or ``None`` when none could be measured.
    value: float | None
    #: The landmark that sets it, its correlation with the Alpha, and its own prod correlation.
    via: str | None = None
    r: float | None = None
    p: float | None = None
    #: Landmarks it was measured against.
    landmarks: int = 0


def floors(
    grid: PnlGrid, candidates: Sequence[str], landmarks: dict[str, float]
) -> dict[str, Floor]:
    """Each candidate's prod-correlation floor against ``landmarks`` (id → its prod correlation).

    All series are one region's. A candidate is never its own landmark.
    """
    ids, dates, pnl = grid
    at = {a: i for i, a in enumerate(ids)}
    left = [c for c in dict.fromkeys(candidates) if c in at]
    right = [m for m in landmarks if m in at]
    out = {c: Floor(None) for c in candidates}
    if not left or not right or not dates:
        return out
    start = bisect_left(dates, window_start(dates[-1]))
    window = pnl[start:]
    rho = correlations(window[:, [at[c] for c in left]], window[:, [at[m] for m in right]])
    p = np.array([landmarks[m] for m in right])
    # Every bound at once: r·p - √((1-r²)(1-p²)), NaN where the pair could not be measured.
    r = np.clip(rho, -1.0, 1.0)
    bounds = r * p - np.sqrt(np.maximum(0.0, (1 - r**2) * (1 - p**2)))
    col = {m: j for j, m in enumerate(right)}
    for i, c in enumerate(left):
        row = bounds[i]
        if c in col:
            row = row.copy()
            row[col[c]] = np.nan
        usable = ~np.isnan(row)
        if not usable.any():
            continue
        j = int(np.nanargmax(row))
        out[c] = Floor(
            value=float(row[j]),
            via=right[j],
            r=float(r[i, j]),
            p=float(p[j]),
            landmarks=int(usable.sum()),
        )
    return out


def landmarks_of(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Region → landmark id → prod correlation: every stored Alpha whose prod correlation BRAIN
    reported at :data:`MIN_LANDMARK` or more, and every submitted one, which is in production
    itself (``p`` = 1)."""
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        region = row.get("region")
        if not region:
            continue
        p: float | None = 1.0 if is_submitted(row) else None
        if p is None:
            for check in checks_of(row.get("checks")):
                value = check.get("value")
                if (
                    str(check.get("name", "")).upper() == "PROD_CORRELATION"
                    and isinstance(value, int | float)
                    and value >= MIN_LANDMARK
                ):
                    p = float(value)
        if p is not None:
            out.setdefault(str(region), {})[str(row["alpha_id"])] = p
    return out
