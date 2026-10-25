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
