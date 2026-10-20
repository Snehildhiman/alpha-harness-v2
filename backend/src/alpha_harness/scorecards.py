"""Scorecards: which building blocks come with high or low correlation, read off the vault.

Every Alpha with a reported correlation is broken into its parts: the operators it calls,
parent-to-child operator pairs (``rank>ts_mean``), the data fields, datasets and data
categories it reads, the lookbacks it uses, and its settings. Each part then gets the average
of every metric over the Alphas that contain it, beside how far that sits from the vault-wide
average.

Averages over few Alphas are noisy, so parts are ranked by a shrunk mean, pulled toward the
vault average by :data:`PRIOR` Alphas' worth of weight: a part seen twice with a 0.95 does
not outrank one seen 400 times with a 0.88.

The models learn these effects jointly; scorecards are the readable version, one part at a
time, so a consultant can see what to build more of and what to avoid.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from .models.features import FieldInfo, read_expression, targets_of

Part = Literal[
    "operator", "pair", "field", "dataset", "category", "lookback", "neutralization", "region"
]
PARTS: tuple[Part, ...] = (
    "operator",
    "pair",
    "field",
    "dataset",
    "category",
    "lookback",
    "neutralization",
    "region",
)

#: Metrics read per part: correlation values, pass rates and performance.
METRICS = (
    "prod_corr",
    "power_pool_corr",
    "self_corr",
    "check:PROD_CORRELATION",
    "check:POWER_POOL_CORRELATION",
    "check:SELF_CORRELATION",
    "sharpe",
    "fitness",
)

#: Alphas' worth of weight the vault average carries in a shrunk mean.
PRIOR = 10.0
#: Numbers that read as lookback windows rather than constants.
LOOKBACK_MIN, LOOKBACK_MAX = 2, 512


@dataclass(slots=True)
class _Sum:
    n: int = 0
    total: float = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        self.total += value


@dataclass(slots=True)
class Card:
    part: Part
    name: str
    #: Alphas containing this part.
    alphas: int
    #: metric -> (alphas with a value, mean, shrunk mean, shrunk mean minus vault mean)
    metrics: dict[str, tuple[int, float, float, float]] = field(default_factory=dict)


@dataclass(slots=True)
class Scorecards:
    alphas: int
    #: Vault-wide mean of every metric, and how many Alphas carry it.
    overall: dict[str, tuple[int, float]]
    cards: list[Card]


def parts_of(row: dict[str, Any], fields: dict[str, FieldInfo]) -> set[tuple[Part, str]]:
    """The building blocks of one Alpha, each once."""
    parsed = read_expression(row.get("expression"))
    out: set[tuple[Part, str]] = set()
    if parsed.ok:
        out.update(("operator", o) for o in parsed.operators)
        out.update(("pair", p) for p in parsed.pairs)
        for name in parsed.fields:
            out.add(("field", name))
            info = fields.get(name)
            if info is not None and info.dataset:
                out.add(("dataset", info.dataset))
            if info is not None and info.category:
                out.add(("category", info.category))
        for number in parsed.numbers:
            if number.is_integer() and LOOKBACK_MIN <= number <= LOOKBACK_MAX:
                out.add(("lookback", str(int(number))))
    if row.get("neutralization"):
        out.add(("neutralization", str(row["neutralization"]).upper()))
    if row.get("region"):
        out.add(("region", str(row["region"]).upper()))
    return out


def build(
    rows: list[dict[str, Any]], fields: dict[str, FieldInfo], *, min_alphas: int = 5
) -> Scorecards:
    """Scorecards for every part seen in at least ``min_alphas`` Alphas with a metric."""
    sums: dict[tuple[Part, str], dict[str, _Sum]] = defaultdict(lambda: defaultdict(_Sum))
    counts: dict[tuple[Part, str], int] = defaultdict(int)
    overall: dict[str, _Sum] = defaultdict(_Sum)
    used = 0
    for row in rows:
        targets = {k: v for k, v in targets_of(row).items() if k in METRICS}
        if not targets:
            continue
        used += 1
        for metric, value in targets.items():
            overall[metric].add(value)
        for part in parts_of(row, fields):
            counts[part] += 1
            for metric, value in targets.items():
                sums[part][metric].add(value)

    means = {m: (s.n, s.total / s.n) for m, s in overall.items() if s.n}
    cards: list[Card] = []
    for part, total in counts.items():
        if total < min_alphas:
            continue
        card = Card(part=part[0], name=part[1], alphas=total)
        for metric, s in sums[part].items():
            if s.n == 0 or metric not in means:
                continue
            base = means[metric][1]
            mean = s.total / s.n
            shrunk = (s.total + PRIOR * base) / (s.n + PRIOR)
            card.metrics[metric] = (s.n, mean, shrunk, shrunk - base)
        cards.append(card)
    return Scorecards(alphas=used, overall=means, cards=cards)


def ranked(
    cards: Scorecards,
    *,
    part: Part,
    metric: str,
    min_alphas: int,
    highest: bool,
    limit: int,
) -> list[Card]:
    """One part's cards that carry ``metric`` on at least ``min_alphas`` Alphas, by shrunk mean."""
    found = [
        c
        for c in cards.cards
        if c.part == part and metric in c.metrics and c.metrics[metric][0] >= min_alphas
    ]
    found.sort(key=lambda c: c.metrics[metric][2], reverse=highest)
    return found[:limit]
