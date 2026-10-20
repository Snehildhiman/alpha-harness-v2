"""Variants of one Alpha that might pass where it nearly did.

A near-miss is sound but sits just the wrong side of a limit. Many small, plausible edits are
generated here, cheaply and locally, and the models (:mod:`.rank`) decide which few are worth
a simulation. Nothing in this module talks to BRAIN.

Edit families, each one change away from the source:

* **Re-shapes**: the Correlation Breaker's recipes (residualize, neutralize inside finer
  groups, trade on catalysts, ...), which change what the signal is exposed to.
* **Lookbacks**: every window moved one or two rungs along a ladder of usual lengths.
* **Operator swaps**: like-for-like replacements (``ts_mean`` and ``ts_decay_linear``,
  ``rank`` and ``zscore``, ...), only where the account has the replacement.
* **Settings**: neutralization, decay and truncation, on the source expression and, for
  neutralization, on each expression edit too.

Power Pool Alphas keep within the pool's operator and field limits; a variant that would
break them is never offered.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from ..labs.fastexpr import (
    MAX_FIELDS,
    MAX_OPERATORS,
    Node,
    ParseError,
    data_fields,
    operator_count,
    parse,
    render,
    replace_at,
    walk,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Usual window lengths; a lookback moves along this ladder.
LADDER = (2, 3, 5, 10, 15, 20, 40, 60, 120, 250)
#: Like-for-like operator replacements.
SWAPS: dict[str, tuple[str, ...]] = {
    "ts_mean": ("ts_decay_linear",),
    "ts_decay_linear": ("ts_mean",),
    "rank": ("zscore",),
    "zscore": ("rank",),
    "ts_rank": ("ts_zscore",),
    "ts_zscore": ("ts_rank",),
    "ts_delta": ("ts_av_diff",),
    "ts_av_diff": ("ts_delta",),
    "group_rank": ("group_zscore",),
    "group_zscore": ("group_rank",),
}
NEUTRALIZATIONS = ("MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY")
DECAYS = (0, 2, 4, 8, 12)
TRUNCATIONS = (0.05, 0.08, 0.1)


@dataclass(frozen=True, slots=True)
class Variant:
    """One candidate: what changed, the expression and the settings it would run at."""

    id: str
    edit: str
    family: str
    expression: str
    settings: dict[str, Any]

    def key(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return (self.expression, tuple(sorted((k, str(v)) for k, v in self.settings.items())))


@dataclass(frozen=True, slots=True)
class Reshape:
    """A Correlation Breaker recipe, already written out as a whole expression."""

    id: str
    name: str
    expression: str


def _neighbours(value: float) -> list[int]:
    """The ladder rungs one and two steps either side of ``value``."""
    rung = min(range(len(LADDER)), key=lambda i: abs(LADDER[i] - value))
    picks = [rung - 2, rung - 1, rung + 1, rung + 2]
    out = [LADDER[i] for i in picks if 0 <= i < len(LADDER) and LADDER[i] != value]
    return list(dict.fromkeys(out))


def lookback_edits(tree: Node) -> Iterable[tuple[str, Node]]:
    """Each whole-number window of 2 or more moved along the ladder, one at a time."""
    for path, node in walk(tree):
        if node.kind != "num" or not path:
            continue
        try:
            value = float(node.value)
        except ValueError:
            continue
        # A window is a whole number of days; 1 and below are weights or switches.
        if value < 2 or value != int(value):
            continue
        for new in _neighbours(value):
            yield (
                f"lookback {int(value)} → {new}",
                replace_at(tree, path, replace(node, value=str(new))),
            )


def operator_edits(tree: Node, available: set[str]) -> Iterable[tuple[str, Node]]:
    for path, node in walk(tree):
        if node.kind != "call":
            continue
        for other in SWAPS.get(node.value, ()):
            if available and other not in available:
                continue
            yield f"{node.value} → {other}", replace_at(tree, path, replace(node, value=other))


def _fits_power_pool(expression: str) -> bool:
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return False
    return operator_count(tree) <= MAX_OPERATORS and len(data_fields(tree)) <= MAX_FIELDS


def variants(
    expression: str,
    settings: dict[str, Any],
    *,
    reshapes: Sequence[Reshape] = (),
    operators: set[str] | None = None,
    power_pool: bool = False,
    limit: int = 600,
) -> list[Variant]:
    """Every distinct one-step variant of the Alpha, the source itself excluded."""
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return []
    available = operators or set()
    source = render(tree)
    base = dict(settings)
    out: list[Variant] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def add(edit: str, family: str, expr: str, at: dict[str, Any]) -> None:
        if len(out) >= limit:
            return
        if power_pool and not _fits_power_pool(expr):
            return
        candidate = Variant(f"v{len(out)}", edit, family, expr, at)
        key = candidate.key()
        if key in seen or (expr == source and at == base):
            return
        seen.add(key)
        out.append(candidate)

    expression_edits = [(r.name, "reshape", r.expression) for r in reshapes]
    for edit, new in lookback_edits(tree):
        expression_edits.append((edit, "lookback", render(new)))
    for edit, new in operator_edits(tree, available):
        expression_edits.append((edit, "operator", render(new)))

    for edit, family, expr in expression_edits:
        add(edit, family, expr, base)

    current = str(base.get("neutralization") or "")
    for neutralization in NEUTRALIZATIONS:
        if neutralization != current:
            add(
                f"neutralization → {neutralization.lower()}",
                "settings",
                source,
                {**base, "neutralization": neutralization},
            )
    for decay in DECAYS:
        if decay != base.get("decay"):
            add(f"decay → {decay}", "settings", source, {**base, "decay": decay})
    for truncation in TRUNCATIONS:
        if truncation != base.get("truncation"):
            add(
                f"truncation → {truncation}", "settings", source, {**base, "truncation": truncation}
            )
    # Each expression edit at every other neutralization: exposure is where correlation lives.
    for edit, family, expr in expression_edits:
        for neutralization in NEUTRALIZATIONS:
            if neutralization != current:
                add(
                    f"{edit} + neutralization → {neutralization.lower()}",
                    f"{family}+settings",
                    expr,
                    {**base, "neutralization": neutralization},
                )
    return out
