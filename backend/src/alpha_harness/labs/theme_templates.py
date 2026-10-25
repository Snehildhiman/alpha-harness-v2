"""Templates the Current Theme Lab can be told to simulate, one data field each.

Each is a Fast Expression with ``{x}`` for the field (reduced to a matrix if it is a vector,
then backfilled, as every search shape reads it) and ``{d}`` for a lookback the search tries.
One field each keeps an Alpha inside one data category and the Power Pool limits (at most
eight operators, counting the GLB within-country step the lab adds).

``low_turnover`` marks templates that smooth or rank over time: they trade less, which is
what the after-cost figures (AC Combo IR) reward. ``suggested`` marks the ones picked for a
theme judged on its combination: slow, balanced across markets, and unlike each other.
"""

import re
from dataclasses import dataclass

from .search import NAME

#: Grouping fields a template may name. Not data: they do not count toward a data category.
GROUP_FIELDS = frozenset({"market", "sector", "industry", "subindustry", "country"})


@dataclass(frozen=True, slots=True)
class ThemeTemplate:
    name: str
    expression: str
    about: str
    low_turnover: bool = False
    suggested: bool = False

    def operators(self) -> frozenset[str]:
        """The operators it calls."""
        bare = self.expression.replace("{x}", "x").replace("{d}", "1")
        return frozenset(
            m.group(0)
            for m in re.finditer(rf"{NAME.pattern}(?=\()", bare)
            if m.group(0) not in GROUP_FIELDS
        )

    def groups(self) -> frozenset[str]:
        """The grouping fields it reads."""
        return frozenset(n for n in NAME.findall(self.expression) if n in GROUP_FIELDS)


TEMPLATES: tuple[ThemeTemplate, ...] = (
    ThemeTemplate("Rank", "rank({x})", "The field's level, ranked across stocks each day."),
    ThemeTemplate(
        "Own history",
        "ts_rank({x}, {d})",
        "Where today's value sits in the stock's own recent range.",
        suggested=True,
    ),
    ThemeTemplate(
        "Z-score over time",
        "ts_zscore({x}, {d})",
        "How unusual today's value is for this stock: unit-free across markets.",
        suggested=True,
    ),
    ThemeTemplate(
        "Smoothed level",
        "rank(ts_mean({x}, {d}))",
        "The level averaged over the window, then ranked: slow and steady.",
        low_turnover=True,
        suggested=True,
    ),
    ThemeTemplate(
        "Decayed rank",
        "ts_decay_linear(rank({x}), {d})",
        "Today's rank blended with the past days', recent ones weighted most.",
        low_turnover=True,
        suggested=True,
    ),
    ThemeTemplate(
        "Change",
        "rank(ts_delta({x}, {d}))",
        "Ranks how much the field moved over the window.",
    ),
    ThemeTemplate(
        "Smoothed change",
        "rank(ts_decay_linear(ts_delta({x}, {d}), 10))",
        "The move over the window, decayed over two weeks: a change signal that trades less.",
        low_turnover=True,
        suggested=True,
    ),
    ThemeTemplate(
        "Industry relative",
        "group_rank({x}, industry)",
        "The field ranked within its industry, so sector bets cancel.",
    ),
    ThemeTemplate(
        "Industry relative history",
        "group_rank(ts_rank({x}, {d}), subindustry)",
        "Own-history rank, compared only with sub-industry peers.",
        suggested=True,
    ),
    ThemeTemplate(
        "Industry-neutral change",
        "group_neutralize(ts_delta({x}, {d}), industry)",
        "The move over the window less its industry's average move.",
    ),
    ThemeTemplate(
        "Country, then sector",
        "group_rank(group_neutralize({x}, country), sector)",
        "BRAIN's GLB advice: take out each country's level first, then compare within sector.",
        suggested=True,
    ),
    ThemeTemplate(
        "Stability",
        "rank(ts_std_dev({x}, {d}))",
        "How much the field moves about: a volatility of the data, not of the price.",
    ),
    # -- clipping and scaling: tame outliers and put every market on one scale ------------
    ThemeTemplate(
        "Winsorized z-score",
        "zscore(winsorize({x}, std=4))",
        "Extremes clipped at 4 standard deviations, then standardised across stocks.",
    ),
    ThemeTemplate(
        "Winsorized history",
        "ts_zscore(winsorize({x}, std=4), {d})",
        "Clipped, then compared with the stock's own past: one bad print cannot drive it.",
        suggested=True,
    ),
    ThemeTemplate(
        "Winsorized change",
        "rank(winsorize(ts_delta({x}, {d}), std=4))",
        "The move over the window with its outliers clipped, then ranked.",
    ),
    ThemeTemplate(
        "Scale",
        "scale({x})",
        "The field scaled so its absolute values sum to one book: size kept, units removed.",
    ),
    ThemeTemplate(
        "Scale over time",
        "ts_scale({x}, {d})",
        "Where today's value sits between the window's low (0) and high (1).",
        suggested=True,
    ),
    ThemeTemplate(
        "Smoothed, scaled over time",
        "ts_scale(ts_mean({x}, 5), {d})",
        "A week's average placed in the window's range: the scale signal, trading less.",
        low_turnover=True,
        suggested=True,
    ),
    ThemeTemplate(
        "Normalize",
        "normalize({x})",
        "The day's cross-sectional mean taken out of every stock.",
    ),
    ThemeTemplate(
        "Quantile",
        "quantile({x})",
        "Ranked, then shaped to a normal curve: tails count, but never wildly.",
    ),
    ThemeTemplate(
        "Rolling quantile",
        "ts_quantile({x}, {d})",
        "The stock's own-history rank, shaped to a normal curve.",
        suggested=True,
    ),
    ThemeTemplate(
        "Signed square root",
        "signed_power(zscore({x}), 0.5)",
        "Standardised, then extremes dampened while keeping their sign.",
    ),
    ThemeTemplate(
        "Sector scaled",
        "group_scale({x}, sector)",
        "Placed between its sector's low and high each day.",
    ),
    ThemeTemplate(
        "Sub-industry winsorized z-score",
        "group_zscore(winsorize({x}, std=4), subindustry)",
        "Clipped, then standardised among sub-industry peers.",
        suggested=True,
    ),
    # -- distance, timing and change ---------------------------------------------------
    ThemeTemplate(
        "Distance from average",
        "ts_av_diff({x}, {d})",
        "How far today's value is from its own average over the window.",
    ),
    ThemeTemplate(
        "Days since the high",
        "ts_arg_max({x}, {d})",
        "How many days ago the field peaked in the window.",
    ),
    ThemeTemplate(
        "Days since the low",
        "ts_arg_min({x}, {d})",
        "How many days ago the field bottomed in the window.",
    ),
    ThemeTemplate(
        "Days since it changed",
        "rank(days_from_last_change({x}))",
        "How long since the data last updated: fresh news versus stale.",
    ),
    ThemeTemplate(
        "Size of the last change",
        "rank({x} - last_diff_value({x}, {d}))",
        "How far the value moved at its latest update.",
    ),
    # -- slow signals for the after-cost figures ---------------------------------------
    ThemeTemplate(
        "Hump-smoothed rank",
        "hump(rank({x}), hump=0.01)",
        "Ranked, and a position changes only when the signal moves by more than 1%: few trades.",
        low_turnover=True,
        suggested=True,
    ),
    ThemeTemplate(
        "Exponential decay",
        "ts_decay_exp_window(rank({x}), {d}, factor=0.5)",
        "Today's rank blended with the past, weights halving each day back.",
        low_turnover=True,
    ),
    ThemeTemplate(
        "Winsorized smoothed level",
        "rank(ts_mean(winsorize({x}, std=4), {d}))",
        "Clipped, averaged over the window, then ranked: robust and slow.",
        low_turnover=True,
        suggested=True,
    ),
)

BY_NAME = {t.name: t for t in TEMPLATES}


def usable(operators: frozenset[str] | set[str], *, grouping: bool) -> list[ThemeTemplate]:
    """Templates whose every operator the account has; without ``grouping`` (a theme that
    forbids PV1 group fields), none that reads one."""
    return [
        t for t in TEMPLATES if t.operators() <= set(operators) and (grouping or not t.groups())
    ]


def render(template: str, x: str, d: int | None) -> str:
    return template.replace("{x}", x).replace("{d}", str(d if d is not None else 21))
