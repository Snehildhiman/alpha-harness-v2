"""Power Pool themes, checked locally.

BRAIN publishes each Power Pool theme as a rule over an Alpha's settings and data, e.g.
``delay=1 & datacategory in ['analyst', 'model', 'news'] & single datacategory``, valid for a
range of dates. Its ``MATCHES_THEMES`` check only appears on an Alpha once BRAIN has checked
it, so most of the vault carries no answer. This module answers from the rule itself: the
Alpha's delay and region, and the data categories of the fields its expression reads
(grouping fields such as ``subindustry`` excluded, as BRAIN excludes them).

Rules are entered by the user (Settings, or the Current Theme tab) because BRAIN's theme
calendar is a page, not an API.
"""

from collections.abc import Callable
from datetime import date

from pydantic import Field

from .labs.fastexpr import GROUPING, ParseError, data_fields, parse, walk
from .schemas import Out

#: How a typo in a published rule is read: the calendar has printed "fundamnetal".
_ALIASES = {"fundamnetal": "fundamental", "fundamentals": "fundamental", "price volume": "pv"}


def normalise(category: str) -> str:
    key = category.strip().lower()
    return _ALIASES.get(key, key)


class ThemeRule(Out):
    """One Power Pool theme: what an Alpha must be, and the dates it runs."""

    name: str
    start: date
    end: date
    #: ``None``: any delay.
    delay: int | None = 1
    #: Data category ids (``pv``, ``fundamental``, ``analyst``, ...); empty: any category.
    categories: list[str] = Field(default_factory=list)
    #: Every data field must come from one category.
    single_category: bool = True
    #: Empty: any region.
    regions: list[str] = Field(default_factory=list)
    #: No PV1 group data fields (``industry``, ``sector``, ``subindustry``...): BRAIN counts
    #: them as Price Volume, so a theme whose categories exclude PV excludes them too. A
    #: group operator over anything else is still allowed.
    no_grouping: bool = True
    #: A Power Pool theme (judged on the Current Theme tab) or one for regular Alphas, such as
    #: a turnover-range theme with its own multiplier.
    power_pool: bool = True
    #: Turnover bounds as fractions (0.15 = 15%); ``None``: no bound.
    turnover_min: float | None = None
    turnover_max: float | None = None
    #: The pyramid multiplier BRAIN announced, shown beside the rule.
    multiplier: float | None = None

    def describe(self) -> str:
        parts = []
        if self.delay is not None:
            parts.append(f"delay={self.delay}")
        if self.categories:
            parts.append("datacategory in [" + ", ".join(self.categories) + "]")
        if self.single_category:
            parts.append("single datacategory")
        if self.regions:
            parts.append("region in [" + ", ".join(self.regions) + "]")
        if self.no_grouping:
            parts.append("no PV1 group fields")
        if self.turnover_min is not None or self.turnover_max is not None:
            low = f"{self.turnover_min:.0%}" if self.turnover_min is not None else "0%"
            high = f"{self.turnover_max:.0%}" if self.turnover_max is not None else "any"
            parts.append(f"turnover {low}-{high}")
        return " & ".join(parts) or "any Alpha"


#: The October 2026 calendar, as published: D1, two categories the first fortnight, three
#: the second, one category per Alpha throughout.
DEFAULT_THEMES = [
    ThemeRule(
        name="D1 Power Pool Oct`26 (pv, fundamental)",
        start=date(2026, 9, 28),
        end=date(2026, 10, 11),
        delay=1,
        categories=["pv", "fundamental"],
        no_grouping=False,
    ),
    # As BRAIN announced it: Delay 1, one data category of Analyst, Model or News, and no PV1
    # group data fields (they are Price Volume). Multiplier 1x.
    ThemeRule(
        name="D1 Power Pool Oct`26 2",
        start=date(2026, 10, 12),
        end=date(2026, 10, 25),
        delay=1,
        categories=["analyst", "model", "news"],
        multiplier=1.0,
    ),
    # For regular Alphas: GLB delay 1 with turnover between 15% and 30%, at 2.5x.
    ThemeRule(
        name="GLB/D1 Turnover 15-30%",
        start=date(2026, 10, 12),
        end=date(2026, 11, 8),
        delay=1,
        regions=["GLB"],
        categories=[],
        single_category=False,
        no_grouping=False,
        power_pool=False,
        turnover_min=0.15,
        turnover_max=0.30,
        multiplier=2.5,
    ),
]


def current(rules: list[ThemeRule], today: date) -> ThemeRule | None:
    """The Power Pool rule running on ``today``; the latest-starting one if several overlap."""
    running = [r for r in rules if r.power_pool and r.start <= today <= r.end]
    return max(running, key=lambda r: r.start) if running else None


def running(rules: list[ThemeRule], today: date) -> list[ThemeRule]:
    """Every rule running on ``today``, Power Pool and regular, latest-starting first."""
    return sorted(
        (r for r in rules if r.start <= today <= r.end), key=lambda r: r.start, reverse=True
    )


def fields_of(expression: str | None) -> list[str] | None:
    """The data fields an expression reads, grouping fields excluded; ``None`` if unreadable."""
    if not expression:
        return None
    try:
        return data_fields(parse(expression))
    except ParseError, RecursionError:
        return None


def grouping_in(expression: str) -> str | None:
    """Why an expression breaks a no-PV1-group-fields theme: the grouping field it reads."""
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return "expression could not be read"
    for _, node in walk(tree):
        if node.kind == "name" and node.value in GROUPING:
            return f"uses {node.value}, a PV1 group field the theme does not allow"
    return None


#: ``(field id, region, delay) -> category id``, ``None`` when the catalog has not got it.
CategoryOf = Callable[[str, str, int], str | None]


def check(
    rule: ThemeRule,
    *,
    expression: str | None,
    region: str | None,
    delay: int | None,
    category_of: CategoryOf,
    turnover: float | None = None,
) -> tuple[bool, str]:
    """Whether an Alpha fits ``rule``, and a short reason when it does not."""
    if rule.delay is not None and delay != rule.delay:
        return False, f"delay {delay}, theme needs {rule.delay}"
    if rule.regions and region not in rule.regions:
        return False, f"region {region} not in theme"
    if rule.turnover_min is not None or rule.turnover_max is not None:
        if turnover is None:
            return False, "turnover unknown"
        if rule.turnover_min is not None and turnover < rule.turnover_min:
            return False, f"turnover {turnover:.0%}, theme needs {rule.turnover_min:.0%}+"
        if rule.turnover_max is not None and turnover > rule.turnover_max:
            return False, f"turnover {turnover:.0%}, theme allows up to {rule.turnover_max:.0%}"
        if not rule.categories and not rule.no_grouping:
            return True, "turnover in range"
    fields = fields_of(expression)
    if fields is None:
        return False, "expression could not be read"
    if rule.no_grouping and (reason := grouping_in(str(expression))):
        return False, reason
    if not fields:
        return False, "no data fields"
    categories: dict[str, str] = {}
    for name in fields:
        found = category_of(name, str(region or ""), int(delay or 0))
        if found is None:
            return False, f"{name} not in the synced catalog; sync Data Explorer"
        categories[name] = normalise(found)
    used = sorted(set(categories.values()))
    allowed = {normalise(c) for c in rule.categories}
    if allowed and not set(used) <= allowed:
        outside = [c for c in used if c not in allowed]
        return False, f"uses {', '.join(outside)}, theme allows {', '.join(sorted(allowed))}"
    if rule.single_category and len(used) > 1:
        return False, f"mixes {', '.join(used)}; theme needs one category"
    return True, f"{used[0]} only" if len(used) == 1 else ", ".join(used)
