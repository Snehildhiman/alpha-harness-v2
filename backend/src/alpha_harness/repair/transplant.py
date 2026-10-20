"""Transplants: an Alpha that passes in one region, tried in the regions it has not run in.

The same idea traded on another market faces another crowd: prod correlation is measured
against what others submitted *there*, so a signal that is crowded in USA can be quiet in EUR
or ASI. And an expression that passes in two or more regions is the all-region Alpha the
region-agnostic work is after. A transplant keeps the expression and its settings and changes
only the region and its universe (the same size, as BRAIN's region-agnostic universes map
sizes between regions). Only regions whose download carries every field it reads are offered,
and only regions it has not already run in. The models then say which are worth a simulation.
Nothing in this module talks to BRAIN.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..canon import canonical
from ..labs.fastexpr import ParseError, data_fields, parse
from ..labs.power_pool import RA_UNIVERSES

if TYPE_CHECKING:
    from collections.abc import Iterable

#: (region, delay) → universe → the fields its download carries.
Markets = dict[tuple[str, int], dict[str, frozenset[str]]]


@dataclass(frozen=True, slots=True)
class Transplant:
    source_id: str
    expression: str
    #: The source's own region and universe.
    origin: str
    region: str
    universe: str
    delay: int
    settings: dict[str, Any]


def size_of(region: str, universe: str) -> str | None:
    """``LARGE``/``MEDIUM``/``SMALL`` for a universe BRAIN's region-agnostic map knows."""
    for size, per_region in RA_UNIVERSES.items():
        if per_region.get(region) == universe:
            return size
    return None


def target_universe(
    source_region: str, source_universe: str, region: str, offered: dict[str, frozenset[str]]
) -> str | None:
    """The universe in ``region`` that matches the source's size, or its widest download."""
    size = size_of(source_region, source_universe) or "LARGE"
    mapped = RA_UNIVERSES[size].get(region)
    if mapped is not None:
        # A mapped region without that universe downloaded: sync it first, no guessing.
        return mapped if mapped in offered else None
    widest = sorted(offered.items(), key=lambda kv: (len(kv[1]), kv[0]))
    return widest[-1][0] if widest else None


def fields_of(expression: str) -> frozenset[str] | None:
    try:
        return frozenset(data_fields(parse(expression), grouping=True))
    except ParseError, RecursionError:
        return None


def ran_in(rows: Iterable[dict[str, Any]]) -> dict[str, set[tuple[str, int]]]:
    """Canonical expression → every (region, delay) it has run in."""
    out: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for row in rows:
        key = canonical(str(row.get("expression") or ""))
        if key and row.get("region"):
            out[key].add((str(row["region"]), int(row.get("delay") or 0)))
    return out


def transplants(
    sources: Iterable[dict[str, Any]],
    markets: Markets,
    simulated: dict[str, set[tuple[str, int]]],
    *,
    known_fields: frozenset[str],
) -> list[Transplant]:
    """Every region each source could run in and has not. ``known_fields`` holds every field
    of any download: a name outside it (a keyword, an operator option) is not a field."""
    out: list[Transplant] = []
    seen: set[tuple[str, str, int]] = set()
    for row in sources:
        expression = str(row.get("expression") or "")
        key = canonical(expression)
        fields = fields_of(expression)
        if not key or fields is None:
            continue
        needed = fields & known_fields
        region0 = str(row.get("region") or "")
        universe0 = str(row.get("universe") or "")
        delay = int(row.get("delay") or 0)
        done = simulated.get(key, set()) | {(region0, delay)}
        for (region, d), offered in sorted(markets.items()):
            if d != delay or (region, delay) in done or (key, region, delay) in seen:
                continue
            universe = target_universe(region0, universe0, region, offered)
            if universe is None or not needed <= offered[universe]:
                continue
            seen.add((key, region, delay))
            out.append(
                Transplant(
                    source_id=str(row.get("alpha_id")),
                    expression=expression,
                    origin=f"{region0} {universe0}",
                    region=region,
                    universe=universe,
                    delay=delay,
                    settings={
                        "instrumentType": str(row.get("instrument_type") or "EQUITY"),
                        "region": region,
                        "universe": universe,
                        "delay": delay,
                        "neutralization": row.get("neutralization"),
                        "decay": row.get("decay"),
                        "truncation": row.get("truncation"),
                    },
                )
            )
    return out
