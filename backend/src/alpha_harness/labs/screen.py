"""Screening: ask the search for more points than a round sends, simulate the best of them.

Without a screen every point the sampler asks for costs a simulation. With one, a round asks
for ``factor`` times what it will send, the trained models score every candidate by its chance
of passing everything its type is judged on (see :func:`alpha_harness.repair.rank.score`), and
only the best are simulated. A share of every round (``explore``) is picked at random from
the rest, so the models keep seeing the kinds of Alpha they are pessimistic about and do not
talk the search into one corner. Candidates not sent are told to the sampler as pruned, which
teaches it nothing either way.

A candidate that could be a Power Pool Alpha (BRAIN's operator and field limits) is scored as
both and keeps the better: it can be submitted as either.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..repair.rank import score
from ..separation import Kind
from .fastexpr import MAX_FIELDS, MAX_OPERATORS, ParseError, data_fields, operator_count, parse

if TYPE_CHECKING:
    import random
    from collections.abc import Sequence

    from ..brain.schemas import SimulationRequest


@dataclass(frozen=True, slots=True)
class Screened:
    #: Indices into the candidates, in the order they should be sent.
    keep: list[int]
    #: Each candidate's chance of passing everything, as the models see it.
    chance: list[float | None]
    #: Indices kept for exploration rather than on their score.
    explored: set[int]


def power_pool_eligible(expression: str | None) -> bool:
    """Within BRAIN's Power Pool limits: at most 8 operators and 3 data fields."""
    if not expression:
        return False
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return False
    return operator_count(tree) <= MAX_OPERATORS and len(data_fields(tree)) <= MAX_FIELDS


def row_of(request: SimulationRequest) -> dict[str, Any]:
    """A candidate in the shape the models read a vault row."""
    s = request.settings
    expression = request.regular
    return {
        "expression": expression,
        "sim_type": str(request.type),
        "region": s.region,
        "delay": s.delay,
        "universe": s.universe,
        "neutralization": s.neutralization,
        "decay": s.decay,
        "truncation": s.truncation,
        "checks": None,
        "power_pool": power_pool_eligible(expression if isinstance(expression, str) else None),
        "date_created": datetime.now(UTC),
    }


def chance_of(predicted: dict[str, float], power_pool: bool) -> float | None:
    """Chance of passing everything; ``None`` when the models said nothing about it."""
    if not predicted:
        return None
    kinds = [Kind.REGULAR, Kind.POWER_POOL] if power_pool else [Kind.REGULAR]
    # A type whose correlation model is missing would score as a sure pass on it; it only
    # counts when no type has one.
    rated = [score(predicted, k) for k in kinds]
    known = [s.p_all for s in rated if s.p_correlation is not None]
    return max(known) if known else rated[0].p_all


def pick(
    chances: Sequence[float | None], want: int, *, explore: float, rng: random.Random
) -> Screened:
    """The ``want`` candidates to send: best chances first, plus a random exploration share."""
    n = len(chances)
    want = min(want, n)
    if want <= 0:
        return Screened([], list(chances), set())
    if all(c is None for c in chances):
        # No model has an opinion: send them in the order the sampler asked.
        return Screened(list(range(want)), list(chances), set())

    def rating(i: int) -> float:
        chance = chances[i]
        return -1.0 if chance is None else chance

    ranked = sorted(range(n), key=rating, reverse=True)
    explored_n = min(want - 1, round(want * explore)) if want > 1 else 0
    top = ranked[: want - explored_n]
    rest = ranked[want - explored_n :]
    explored = set(rng.sample(rest, min(explored_n, len(rest))))
    return Screened(top + sorted(explored), list(chances), explored)
