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
from typing import TYPE_CHECKING, Any

from . import currency, search

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
    # One amount over another: the currency cancels (the webinar's first cure).
    Shape("amount_ratio", "rank({b} / {c})"),
    Shape("amount_ratio_trend", "ts_rank({b} / {c}, {e})"),
    # Unusual on purpose: what few Alphas are, so prod correlation stays low.
    Shape("cross_comovement", "rank(ts_corr(ts_rank({b}, {d}), ts_rank({c}, {d}), {e}))"),
    Shape(
        "residual_of_partner",
        "rank(ts_regression(ts_zscore({b}, {e}), ts_zscore({c}, {e}), {e}))",
    ),
    Shape("recency_of_change", "rank(-days_from_last_change({b}))"),
    Shape(
        "change_steadiness",
        "rank(-ts_std_dev(ts_delta({b}, 1), {e}) / (ts_mean(abs(ts_delta({b}, 1)), {e}) + 0.0001))",
    ),
    Shape(
        "busy_days_signal",
        "trade_when(ts_rank(volume / adv20, {d}) > 0.5, ts_zscore({b}, {e}), -1)",
    ),
    Shape(
        "volatility_regime",
        "if_else(ts_std_dev(returns, {d}) > ts_std_dev(returns, {e}), "
        "-ts_zscore({b}, {e}), ts_zscore({b}, {e}))",
    ),
    Shape("field_skew", "rank(ts_skewness({b}, {e}))"),
    Shape("versus_returns", "-rank(ts_corr(ts_rank({b}, {d}), returns, {e}))"),
    Shape("extremes_emphasised", "signed_power(ts_zscore({b}, {e}), 2)"),
    Shape("extremes_only", "ts_zscore({b}, {e}) * (abs(ts_zscore({b}, {e})) > 1.5)"),
)

#: The unusual shapes, drawn twice as often as the rest: what the crowd rarely writes.
UNIQUE = frozenset(
    {
        "cross_comovement",
        "residual_of_partner",
        "recency_of_change",
        "change_steadiness",
        "busy_days_signal",
        "volatility_regime",
        "field_skew",
        "versus_returns",
        "extremes_emphasised",
        "extremes_only",
        "spread_trend",
    }
)
UNIQUE_WEIGHT = 2.0

#: Each shape as the Region Agnostic Lab lists it: a name and the idea behind it.
ABOUT: dict[str, tuple[str, str]] = {
    "rank": ("Plain rank", "The field itself, ranked. The most common shape, so the most crowded."),
    "ts_rank": ("Against its own past", "Where the field stands in its own history."),
    "zscore_change": ("Size of the change", "How far the field moved, scored across stocks."),
    "vol_scaled_change": (
        "Change in its own swings",
        "A recent change divided by the field's usual variation: a surprise.",
    ),
    "steady": ("High and steady", "Average over variation: high and stable beats high and noisy."),
    "reversion": ("Back to normal", "Leans against a field far from its own average."),
    "trend": ("Rising against its past", "The field's z-score in its own history."),
    "av_diff": ("Fade the move", "Leans against the field's distance from its recent mean."),
    "decayed": ("Smoothed level", "A smoothed field: trades less, so crowds less."),
    "rank_change": ("Climbing the ranking", "How far a stock rose among all stocks on the field."),
    "ratio_momentum": ("Fast over slow", "A short average over a long one."),
    "peer_trend": ("Rising against peers", "Own-history score, ranked within industry."),
    "peer_neutral": ("Peer-neutral history", "Own-history rank, with the industry's taken out."),
    "peer_zscore": ("Change against peers", "A change scored within industry."),
    "spread": ("One field over another", "Two fields' ranks against each other."),
    "spread_trend": (
        "Two histories apart",
        "How far one field's own-history score runs ahead of another's.",
    ),
    "price_divergence": ("Against the price", "The field moving against the stock's price."),
    "volume_divergence": ("Against the volume", "The field moving against trading activity."),
    "quantile_change": ("Distribution shift", "Its recent distribution against its longer one."),
    "short_reversal": ("Short reversal", "Leans against the last week's change."),
    "slow_level": ("Slow level", "A year's average, ranked."),
    "year_change": ("Year over year", "The change on a year ago, in its yearly swings."),
    "revision_trend": (
        "Revision momentum",
        "A month's change over half a year's swings, within industry: estimates keep moving.",
    ),
    "amount_ratio": ("Amount over amount", "One amount over another: the currency cancels."),
    "amount_ratio_trend": ("Ratio against its past", "The ratio of two amounts in its history."),
    "cross_comovement": (
        "Two datasets moving together",
        "How closely two fields from different datasets move: rarely written.",
    ),
    "residual_of_partner": (
        "What the other does not explain",
        "One field with a second field's effect regressed out.",
    ),
    "recency_of_change": (
        "Freshly changed",
        "Favours stocks whose figure changed most recently: new information.",
    ),
    "change_steadiness": ("Steady changes", "Changes that are steady rather than jumpy."),
    "busy_days_signal": (
        "Only on busy days",
        "The signal only while volume runs above its usual level.",
    ),
    "volatility_regime": (
        "Flips in rough markets",
        "Follows the signal in calm markets and fades it when volatility rises.",
    ),
    "field_skew": ("Lopsided history", "The skew of the field over time."),
    "versus_returns": ("Against returns", "The field moving against the stock's returns."),
    "extremes_emphasised": ("Extremes count more", "Its z-score squared, sign kept."),
    "extremes_only": ("Extremes only", "Trades only when the field is far from its normal."),
    "disagreement": (
        "Analysts disagreeing",
        "For vector data: the spread of the values over their mean.",
    ),
}
#: Suggested for region-agnostic Alphas: unit-free (they compare across currencies and
#: markets), and built on a stock's own history or a ratio, so they tend to hold in two
#: or more regions.
SUGGESTED = frozenset(
    {
        "ts_rank",
        "vol_scaled_change",
        "steady",
        "trend",
        "reversion",
        "peer_trend",
        "peer_neutral",
        "year_change",
        "revision_trend",
        "amount_ratio",
        "amount_ratio_trend",
        "spread_trend",
        "cross_comovement",
        "residual_of_partner",
        "recency_of_change",
        "busy_days_signal",
        "volatility_regime",
        "extremes_only",
        "disagreement",
    }
)


def listing() -> list[dict[str, Any]]:
    """Every shape for the lab's picker: suggested first, then the rest."""
    texts = {shape.name: shape.text for shape in SHAPES}
    texts["disagreement"] = "rank(-vec_stddev(x) / abs(vec_avg(x)))"
    out = [
        {
            "name": name,
            "title": ABOUT.get(name, (name, ""))[0],
            "about": ABOUT.get(name, (name, ""))[1],
            "text": text.replace("{b}", "x")
            .replace("{c}", "y")
            .replace("{d}", "d")
            .replace("{e}", "D")
            .replace("{g}", "group"),
            "suggested": name in SUGGESTED,
            "unusual": name in UNIQUE,
        }
        for name, text in texts.items()
    ]
    out.sort(key=lambda r: (not r["suggested"], not r["unusual"], str(r["title"])))
    return out


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
        frozenset({"amount_ratio", "amount_ratio_trend", "year_change", "trend", "peer_trend"}),
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
DECORRELATE = 0.5


def favoured(dataset: str) -> frozenset[str]:
    """The shapes that suit a dataset, from words in its id; none when nothing matches."""
    text = dataset.lower()
    found: set[str] = set()
    for words, shapes in HYPOTHESES:
        if any(w in text for w in words):
            found |= shapes
    return frozenset(found)


_CALL = re.compile(r"([a-z_][a-z0-9_]*)\(")
_PRICE = ("close", "volume", "adv20", "returns")
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
    chosen: frozenset[str] | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Up to ``count`` new expressions, and how many fields this call worked through.

    Every expression names its shape, so the task can learn which shapes pay.
    """
    shapes = usable(operators, ctx.names)
    if chosen:
        # Only the shapes ticked in the lab.
        shapes = tuple(sh for sh in shapes if sh.name in chosen)
    # Most regions first (two passing are what BRAIN needs), then the least crowded: a field
    # few Alphas use is where prod correlation stays low.
    # A field only one chosen region has can never run in two: an Alpha on it is wasted.
    ordered = sorted(
        (f for f in ctx.fields if len(ctx.held.get(f.id, ())) >= 2),
        key=lambda f: (-len(ctx.held.get(f.id, ())), f.alphas if f.alphas is not None else 0),
    )
    fields = [f.id for f in ordered]
    dataset_of = {f.id: f.dataset for f in ordered}
    disagreeing = not chosen or "disagreement" in chosen
    if not fields or (not shapes and not disagreeing):
        return [], 0
    vector = [v for v in VECTOR_OPS if v in operators]
    weights = [
        (1.0 + max(0.0, (scores or {}).get(s.name, 0.0)))
        * (UNIQUE_WEIGHT if s.name in UNIQUE else 1.0)
        for s in shapes
    ]
    wrap = [w for w in ("group_neutralize", "ts_decay_linear") if w in operators]
    amount = currency.amounts_in([*ctx.fields, *ctx.basics])
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
        if (
            ctx.types.get(field) == "VECTOR"
            and {"vec_stddev", "vec_avg"} <= operators
            and disagreeing
            and (not shapes or rng.random() < (0.3 if not chosen else 0.6))
        ):
            # Analysts or models disagreeing: the spread of a vector's values over its mean.
            text = (
                f"rank(-ts_backfill(vec_stddev({field}), 21) / "
                f"(abs(ts_backfill(vec_avg({field}), 21)) + 0.0001))"
            )
            if text not in written:
                written.add(text)
                out.append({"expression": text, "shape": "disagreement"})
        if not shapes:
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
                # Two datasets rarely put together are where unusual Alphas come from.
                elsewhere = [p for p in partners if dataset_of.get(p) != dataset_of.get(field)]
                if elsewhere and rng.random() < 0.7:
                    partners = elsewhere
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
            if expression in written or currency.problem(expression, amount):
                # Ranking an amount across currencies: BRAIN's regions would not agree.
                continue
            written.add(expression)
            out.append({"expression": expression, "shape": shape.name})
            if len(out) >= count:
                return out, step + 1
    return out, step + 1
