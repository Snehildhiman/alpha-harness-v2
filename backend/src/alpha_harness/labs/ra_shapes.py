"""Region Agnostic Lab without an LLM: expressions written from shapes over the chosen fields.

Each call writes a batch the way the LLM would, then the batch takes the same road: it is
checked against the fields, operators and vector rules, and each Alpha runs in every chosen
region that carries all its fields (two at least). Fields are taken in the order the context
ranks them (most regions first), from where the last call stopped, so a task works through
every field before it repeats one.

The shapes are the Search Lab's one-field degrees plus the less crowded families of the
Template Lab: volatility-scaled change, steadiness, two-field spread, divergence from price,
rank change, ratio momentum, peer-relative trend. A shape needs every operator it names to be
on the account. It learns as the task runs: a shape is drawn in proportion to one plus the
mean Sharpe its Alphas scored, so shapes that pass in several regions are written more often.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import search

if TYPE_CHECKING:
    import random

    from .power_pool import Context


@dataclass(frozen=True, slots=True)
class Shape:
    name: str
    #: ``{b}`` the cleaned field, ``{c}`` a second one, ``{d}`` < ``{e}`` lookbacks, ``{g}`` a
    #: grouping field.
    text: str


SHAPES: tuple[Shape, ...] = (
    Shape("rank", "rank({b})"),
    Shape("ts_rank", "rank(ts_rank({b}, {d}))"),
    Shape("zscore_change", "zscore(ts_delta({b}, {d}))"),
    Shape("vol_scaled_change", "rank(ts_delta({b}, {d}) / ts_std_dev({b}, {e}))"),
    Shape("steady", "rank(ts_mean({b}, {d}) / ts_std_dev({b}, {d}))"),
    Shape("reversion", "-rank(ts_zscore({b}, {d}))"),
    Shape("trend", "rank(ts_zscore({b}, {e}))"),
    Shape("av_diff", "-rank(ts_av_diff({b}, {d}))"),
    Shape("decayed", "rank(ts_decay_linear({b}, {d}))"),
    Shape("rank_change", "ts_delta(rank({b}), {d})"),
    Shape("ratio_momentum", "rank(ts_mean({b}, {d}) / ts_mean({b}, {e}))"),
    Shape("peer_trend", "group_rank(ts_zscore({b}, {e}), {g})"),
    Shape("peer_neutral", "group_neutralize(ts_rank({b}, {d}), {g})"),
    Shape("peer_zscore", "group_zscore(ts_delta({b}, {d}), {g})"),
    Shape("spread", "rank({b}) - rank({c})"),
    Shape("spread_trend", "rank(ts_zscore({b}, {e})) - rank(ts_zscore({c}, {e}))"),
    Shape("price_divergence", "-rank(ts_corr({b}, close, {e}))"),
    Shape("volume_divergence", "-rank(ts_corr({b}, volume, {e}))"),
    Shape("quantile_change", "rank(ts_quantile({b}, {e}) - ts_quantile({b}, {d}))"),
    # Hypotheses with their horizon fixed, from how each kind of data is known to work.
    Shape("short_reversal", "-rank(ts_delta({b}, 5))"),
    Shape("slow_level", "rank(ts_mean({b}, 252))"),
    Shape("year_change", "rank(ts_delta({b}, 252) / ts_std_dev({b}, 252))"),
    Shape("revision_trend", "group_rank(ts_delta({b}, 21) / ts_std_dev({b}, 126), {g})"),
)

#: The hypotheses that suit each kind of data, by words in its dataset's id: analyst figures
#: drift after revisions, scores built by models are signals already, fundamentals move slowly,
#: price-volume and order imbalance mean-revert over days, holdings and news change in steps.
#: A field's preferred shapes are drawn three times as often; the rest stay possible.
HYPOTHESES: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (
        ("analyst", "estimate", "consensus", "starmine", "ibes", "earnings"),
        frozenset({"vol_scaled_change", "revision_trend", "trend", "zscore_change", "peer_trend"}),
    ),
    (
        ("model", "ai_", "factor", "pattern", "chart", "quant", "predict", "score", "signal"),
        frozenset({"rank", "ts_rank", "decayed", "peer_neutral", "rank_change", "steady"}),
    ),
    (
        ("fundamental", "fnd", "balance", "income", "cashflow", "valuation"),
        frozenset({"slow_level", "year_change", "trend", "peer_trend", "ratio_momentum"}),
    ),
    (
        ("pv", "intraday", "imbalance", "price", "volume", "option", "short"),
        frozenset({"short_reversal", "reversion", "av_diff", "volume_divergence", "decayed"}),
    ),
    (
        ("institution", "ownership", "holding", "insider"),
        frozenset({"zscore_change", "rank_change", "year_change", "peer_trend"}),
    ),
    (
        ("news", "sentiment", "social", "media"),
        frozenset({"decayed", "reversion", "zscore_change", "steady"}),
    ),
    (
        ("riskfree", "macro", "rates", "seasonal", "other"),
        frozenset({"trend", "steady", "peer_neutral", "ratio_momentum", "year_change"}),
    ),
)
#: How much more often a field's own hypotheses are drawn.
FAVOUR = 3.0
#: Share of expressions wrapped to move them away from the crowd: neutralized within an
#: industry (what every region's peers share) or smoothed so they trade less.
DECORRELATE = 0.35


def favoured(dataset: str) -> frozenset[str]:
    """The shapes that suit a dataset, from words in its id; none when nothing matches."""
    text = dataset.lower()
    found: set[str] = set()
    for words, shapes in HYPOTHESES:
        if any(w in text for w in words):
            found |= shapes
    return frozenset(found)


_CALL = re.compile(r"([a-z_][a-z0-9_]*)\(")
_PRICE = ("close", "volume")
#: The vector reductions tried, in order, when a field is a vector.
VECTOR_OPS = ("vec_avg", "vec_sum", "vec_max", "vec_min", "vec_stddev")


def usable(operators: set[str], names: frozenset[str]) -> tuple[Shape, ...]:
    """The shapes whose every operator is on the account and whose fixed fields exist.

    Every shape reads its fields through ``ts_backfill``, so without it none is usable.
    """
    if "ts_backfill" not in operators:
        return ()
    out = []
    for shape in SHAPES:
        ops = set(_CALL.findall(shape.text))
        fixed = {p for p in _PRICE if p in shape.text}
        if ops <= operators and fixed <= names:
            out.append(shape)
    return tuple(out)


def _base(field_id: str, ctx: Context, vector: list[str], rng: random.Random) -> str | None:
    if ctx.types.get(field_id) == "VECTOR":
        if not vector:
            return None
        return search.base(field_id, rng.choice(vector))
    return search.base(field_id)


def write(
    ctx: Context,
    operators: set[str],
    rng: random.Random,
    *,
    count: int,
    offset: int,
    scores: dict[str, float] | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Up to ``count`` new expressions, and how many fields this call worked through.

    Every expression names its shape, so the task can learn which shapes pay.
    """
    shapes = usable(operators, ctx.names)
    # Most regions first (two passing are what BRAIN needs), then the least crowded: a field
    # few Alphas use is where prod correlation stays low.
    ordered = sorted(
        ctx.fields,
        key=lambda f: (-len(ctx.held.get(f.id, ())), f.alphas if f.alphas is not None else 0),
    )
    fields = [f.id for f in ordered]
    dataset_of = {f.id: f.dataset for f in ordered}
    if not shapes or not fields:
        return [], 0
    vector = [v for v in VECTOR_OPS if v in operators]
    weights = [1.0 + max(0.0, (scores or {}).get(s.name, 0.0)) for s in shapes]
    wrap = [w for w in ("group_neutralize", "ts_decay_linear") if w in operators]
    n = len(fields)
    out: list[dict[str, str]] = []
    written: set[str] = set()
    step = 0
    # Two expressions per field, so a batch of 40 covers 20 fields.
    for step in range(min(n, max(1, count // 2))):
        field = fields[(offset + step) % n]
        b = _base(field, ctx, vector, rng)
        if b is None:
            continue
        likes = favoured(dataset_of.get(field) or "")
        mine = [
            w * (FAVOUR if s.name in likes else 1.0) for s, w in zip(shapes, weights, strict=True)
        ]
        for _ in range(2):
            shape = rng.choices(shapes, weights=mine)[0]
            text = shape.text
            if "{c}" in text:
                # A partner from the same regions, so the spread can run where this field runs.
                partners = [
                    f
                    for f in fields
                    if f != field and ctx.held.get(f, frozenset()) & ctx.held[field]
                ]
                if not partners:
                    continue
                c = _base(rng.choice(partners), ctx, vector, rng)
                if c is None:
                    continue
            else:
                c = ""
            if "{g}" in text and not ctx.groups:
                continue
            d = rng.choice(search.LOOKBACKS[:-1])
            e = rng.choice([x for x in search.LOOKBACKS if x > d])
            expression = text.format(
                b=b, c=c, d=d, e=e, g=rng.choice(ctx.groups) if ctx.groups else ""
            )
            if wrap and rng.random() < DECORRELATE:
                how = rng.choice(wrap)
                if how == "group_neutralize" and ctx.groups:
                    expression = f"group_neutralize({expression}, {rng.choice(ctx.groups)})"
                elif how == "ts_decay_linear":
                    expression = f"ts_decay_linear({expression}, {rng.choice((5, 10, 21))})"
            if expression in written:
                continue
            written.add(expression)
            out.append({"expression": expression, "shape": shape.name})
            if len(out) >= count:
                return out, step + 1
    return out, step + 1
