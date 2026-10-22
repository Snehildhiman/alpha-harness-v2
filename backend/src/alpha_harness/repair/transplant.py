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
from ..labs.power_pool import MIN_REGIONS, RA_MARKETS, RA_UNIVERSES

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
    #: Judged as a Power Pool Alpha (Power Pool correlation, not prod) in its new region too.
    power_pool: bool = False


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


#: Expression text → its canonical form. Expressions never change, and a vault re-read every
#: few minutes while simulations land would otherwise re-parse 50k of them each time.
_CANONICAL: dict[str, str | None] = {}


def _canonical(expression: str) -> str | None:
    if expression not in _CANONICAL:
        if len(_CANONICAL) > 500_000:
            _CANONICAL.clear()
        _CANONICAL[expression] = canonical(expression)
    return _CANONICAL[expression]


def ran_in(rows: Iterable[dict[str, Any]]) -> dict[str, set[tuple[str, int]]]:
    """Canonical expression → every (region, delay) it has run in."""
    out: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for row in rows:
        key = _canonical(str(row.get("expression") or ""))
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
    of any download: a name outside it (a keyword, an operator option) is not a field. A
    source row with ``power_pool`` set stays a Power Pool Alpha."""
    out: list[Transplant] = []
    seen: set[tuple[str, str, int]] = set()
    for row in sources:
        expression = str(row.get("expression") or "")
        key = _canonical(expression)
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
                    power_pool=bool(row.get("power_pool")),
                )
            )
    return out


@dataclass(frozen=True, slots=True)
class Promotion:
    """An expression that passes as a regular Alpha in two or more of BRAIN's region-agnostic
    markets, and has never run as a region-agnostic Alpha: the family BRAIN would take."""

    expression: str
    delay: int
    #: Regions it passes in, each with the passing Alpha's id.
    regions: dict[str, str]
    sharpe: float | None
    #: Settings of its strongest passing Alpha; the family runs at these.
    neutralization: str | None
    decay: int | None
    truncation: float | None


def promotions(
    passing: Iterable[dict[str, Any]], simulated: dict[str, set[tuple[str, int]]]
) -> list[Promotion]:
    """Group passing regular Alphas by canonical expression and delay; keep the groups that
    pass in ``MIN_REGIONS`` region-agnostic markets and have not run in region ``ALL``.
    Most regions first, then the stronger.

    Regular only: an RA family answers to the regular rules, prod correlation included, so a
    Power Pool pass says nothing about it."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in passing:
        region = str(row.get("region") or "")
        key = _canonical(str(row.get("expression") or ""))
        if key and region in RA_MARKETS:
            groups[(key, int(row.get("delay") or 0))].append(row)
    out: list[Promotion] = []
    for (key, delay), rows in groups.items():
        by_region: dict[str, dict[str, Any]] = {}
        for row in rows:
            region = str(row["region"])
            best = by_region.get(region)
            if best is None or (row.get("sharpe") or 0.0) > (best.get("sharpe") or 0.0):
                by_region[region] = row
        if len(by_region) < MIN_REGIONS or ("ALL", delay) in simulated.get(key, set()):
            continue
        strongest = max(by_region.values(), key=lambda r: r.get("sharpe") or 0.0)
        sharpes = [float(r["sharpe"]) for r in by_region.values() if r.get("sharpe") is not None]
        out.append(
            Promotion(
                expression=str(strongest.get("expression")),
                delay=delay,
                regions={r: str(row.get("alpha_id")) for r, row in sorted(by_region.items())},
                sharpe=sum(sharpes) / len(sharpes) if sharpes else None,
                neutralization=strongest.get("neutralization"),
                decay=strongest.get("decay"),
                truncation=strongest.get("truncation"),
            )
        )
    out.sort(key=lambda p: (-len(p.regions), -(p.sharpe or 0.0)))
    return out


#: The region whose passing Alphas the webinar calls the easiest start for ARC.
GLB = "GLB"


def from_global(
    passing: Iterable[dict[str, Any]], simulated: dict[str, set[tuple[str, int]]]
) -> list[Promotion]:
    """Passing (or submitted) Global Alphas at delay 1 that never ran as region-agnostic:
    a Global signal already spans markets and currencies, so it is the likeliest to pass in
    two regions as one. Strongest first; one per expression."""
    best: dict[str, dict[str, Any]] = {}
    for row in passing:
        if str(row.get("region") or "") != GLB or int(row.get("delay") or 0) != 1:
            continue
        key = _canonical(str(row.get("expression") or ""))
        if not key or ("ALL", 1) in simulated.get(key, set()):
            continue
        if key not in best or (row.get("sharpe") or 0.0) > (best[key].get("sharpe") or 0.0):
            best[key] = row
    out = [
        Promotion(
            expression=str(row.get("expression")),
            delay=1,
            regions={GLB: str(row.get("alpha_id"))},
            sharpe=row.get("sharpe"),
            neutralization=row.get("neutralization"),
            decay=row.get("decay"),
            truncation=row.get("truncation"),
        )
        for row in best.values()
    ]
    out.sort(key=lambda p: -(p.sharpe or 0.0))
    return out
