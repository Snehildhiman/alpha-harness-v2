"""Which variants are worth a simulation, and which Alphas are near-misses at all.

**Ranking.** Each variant is scored by the chance the models give it of passing everything its
type is judged on: the correlation check of its type (prod for regular, RA and SuperAlphas,
Power Pool for Power Pool Alphas) times every other check model. A check with no trained
model counts as neutral, so a thin vault ranks on what it can.

**Near-misses.** A refused Alpha is a near-miss when *every* check it fails, fails narrowly:
a correlation within 0.05 above its limit, any other numeric check within 10% of its limit.
A failure with no numbers (an error, a Quick run) is not narrow.
"""

from dataclasses import dataclass
from typing import Any

from ..separation import Judged, Kind, Verdict

PROD = "check:PROD_CORRELATION"
POWER_POOL = "check:POWER_POOL_CORRELATION"
#: Correlation margin over the limit that still counts as narrow.
CORRELATION_MARGIN = 0.05
#: Relative margin for other numeric checks.
RELATIVE_MARGIN = 0.10


def correlation_target(kind: Kind) -> tuple[str, str]:
    """The pass/fail and value targets of the correlation check this type answers to."""
    if kind in (Kind.POWER_POOL, Kind.THEME):
        return POWER_POOL, "power_pool_corr"
    return PROD, "prod_corr"


@dataclass(frozen=True, slots=True)
class Score:
    #: Chance of passing everything, as far as the models can say.
    p_all: float
    #: Chance of passing the type's correlation check.
    p_correlation: float | None
    #: Predicted correlation value.
    correlation: float | None
    sharpe: float | None
    fitness: float | None


def score(predicted: dict[str, float], kind: Kind) -> Score:
    corr_check, corr_value = correlation_target(kind)
    other_corr = PROD if corr_check == POWER_POOL else POWER_POOL
    p_corr = predicted.get(corr_check)
    p_all = 1.0 if p_corr is None else p_corr
    for target, value in predicted.items():
        if target.startswith("check:") and target not in (corr_check, other_corr):
            p_all *= value
    return Score(
        p_all=p_all,
        p_correlation=p_corr,
        correlation=predicted.get(corr_value),
        sharpe=predicted.get("sharpe"),
        fitness=predicted.get("fitness"),
    )


def _gap(name: str, value: Any, limit: Any) -> float | None:
    """How far past its limit a failure is, 0 at the limit; ``None`` when not narrow."""
    if not isinstance(value, int | float) or not isinstance(limit, int | float):
        return None
    if name.endswith("CORRELATION"):
        over = float(value) - float(limit)
        return over / CORRELATION_MARGIN if 0 <= over <= CORRELATION_MARGIN else None
    if limit == 0:
        return None
    relative = abs(float(value) - float(limit)) / abs(float(limit))
    return relative / RELATIVE_MARGIN if relative <= RELATIVE_MARGIN else None


def near_miss(item: Judged) -> float | None:
    """How near a refused Alpha is (0: right at the limits, 1: at the edge of narrow), or
    ``None`` when it is not a near-miss. RA families are left to the RA pipeline."""
    judgement = item.judgement
    if judgement.verdict != Verdict.REFUSED or judgement.kind == Kind.RA or not judgement.failed:
        return None
    gaps = []
    for issue in judgement.failed:
        gap = _gap(issue.name, issue.value, issue.limit)
        if gap is None:
            return None
        gaps.append(gap)
    return max(gaps)
