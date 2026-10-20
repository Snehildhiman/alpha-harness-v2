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

from .labs.fastexpr import ParseError, data_fields, parse
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
        return " & ".join(parts) or "any Alpha"


#: The October 2026 calendar, as published: D1, two categories the first fortnight, three
#: the second, one category per Alpha throughout.
DEFAULT_THEMES = [
    ThemeRule(
        name="D1 Power Pool Oct`26 (pv, fundamental)",
        start=date(2026, 9, 28),
        end=date(2026, 10, 13),
        delay=1,
        categories=["pv", "fundamental"],
    ),
    ThemeRule(
        name="D1 Power Pool Oct`26 (analyst, model, news)",
        start=date(2026, 10, 14),
        end=date(2026, 10, 31),
        delay=1,
        categories=["analyst", "model", "news"],
    ),
]


def current(rules: list[ThemeRule], today: date) -> ThemeRule | None:
    """The rule running on ``today``; the latest-starting one if several overlap."""
    running = [r for r in rules if r.start <= today <= r.end]
    return max(running, key=lambda r: r.start) if running else None


def fields_of(expression: str | None) -> list[str] | None:
    """The data fields an expression reads, grouping fields excluded; ``None`` if unreadable."""
    if not expression:
        return None
    try:
        return data_fields(parse(expression))
    except ParseError, RecursionError:
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
) -> tuple[bool, str]:
    """Whether an Alpha fits ``rule``, and a short reason when it does not."""
    if rule.delay is not None and delay != rule.delay:
        return False, f"delay {delay}, theme needs {rule.delay}"
    if rule.regions and region not in rule.regions:
        return False, f"region {region} not in theme"
    fields = fields_of(expression)
    if fields is None:
        return False, "expression could not be read"
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
