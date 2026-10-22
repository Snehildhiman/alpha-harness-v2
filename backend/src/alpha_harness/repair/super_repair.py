"""Repair for SuperAlphas: one-step changes to the settings, the selection and the combo.

A SuperAlpha has no single expression to re-shape: it is a selection, a combo and settings.
So its variants change one of those at a time, and they are ordered by the check that
failed: low fitness or high turnover tries more decay and lighter truncation first; low
Sharpe (the IS ladder, a sub-region such as GLB EMEA) tries other combos and selections
first. The learned models are trained on regular Alphas and do not score these; BRAIN's own
checks judge each one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..labs import super_alpha

#: Neutralizations a SuperAlpha is tried at besides its own.
NEUTRALIZATIONS = ("MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY")
TRUNCATIONS = (0.03, 0.05, 0.08, 0.1)


@dataclass(frozen=True, slots=True)
class SuperVariant:
    id: str
    edit: str
    #: ``settings``, ``combo`` or ``selection``: what was changed.
    family: str
    selection: str
    combo: str
    settings: dict[str, Any]


def code_of(body: dict[str, Any], key: str) -> str:
    part = body.get(key)
    if isinstance(part, dict):
        return str(part.get("code") or "")
    return str(part or "")


def failed_checks(body: dict[str, Any]) -> list[str]:
    checks = ((body.get("is") or {}).get("checks")) or []
    return [str(c.get("name") or "").upper() for c in checks if c.get("result") == "FAIL"]


def _priority(family: str, edit: str, failed: list[str]) -> int:
    """Lower first. Fitness and turnover want slower books; Sharpe wants other weights."""
    sharpe = any("SHARPE" in f for f in failed)
    fitness = any("FITNESS" in f for f in failed)
    turnover = any("TURNOVER" in f for f in failed)
    if (
        (fitness or turnover)
        and family == "settings"
        and ("Decay +" in edit or "Truncation" in edit)
    ):
        return 0
    if sharpe and family == "combo":
        return 1
    if sharpe and family == "selection":
        return 2
    if family == "settings":
        return 3
    return 4


def variants(body: dict[str, Any]) -> list[SuperVariant]:
    """Every one-step change to a stored SuperAlpha, likeliest fix first."""
    settings = dict(body.get("settings") or {})
    selection, combo = code_of(body, "selection"), code_of(body, "combo")
    failed = failed_checks(body)
    decay = int(settings.get("decay") or 0)
    truncation = float(settings.get("truncation") or super_alpha.TRUNCATION)
    limit = int(settings.get("selectionLimit") or 30)
    out: list[SuperVariant] = []

    def add(edit: str, family: str, change: dict[str, Any], sel: str = "", com: str = "") -> None:
        out.append(
            SuperVariant(
                id=f"s{len(out)}",
                edit=edit,
                family=family,
                selection=sel or selection,
                combo=com or combo,
                settings=settings | change,
            )
        )

    for step in (2, 4, 6, 10):
        add(f"Decay +{step} ({decay} → {decay + step})", "settings", {"decay": decay + step})
    if decay >= 2:
        add(f"Decay -2 ({decay} → {decay - 2})", "settings", {"decay": decay - 2})
    for t in TRUNCATIONS:
        if abs(t - truncation) > 1e-9:
            add(f"Truncation {truncation:g} → {t:g}", "settings", {"truncation": t})
    for new in sorted({limit - 10, limit + 10, limit + 20, limit * 2}):
        if super_alpha.MIN_SELECTION <= new <= 200 and new != limit:
            add(f"Selection limit {limit} → {new}", "settings", {"selectionLimit": new})
    own = str(settings.get("neutralization") or "")
    for n in NEUTRALIZATIONS:
        if n != own:
            add(
                f"Neutralization {own.lower() or '—'} → {n.lower()}",
                "settings",
                {"neutralization": n},
            )
    activation = str(settings.get("componentActivation") or "IS")
    flipped = "OS" if activation == "IS" else "IS"
    add(
        f"Component activation {activation} → {flipped}",
        "settings",
        {"componentActivation": flipped},
    )
    for recipe in super_alpha.ALL_COMBOS:
        if recipe.code.strip() != combo.strip():
            add(f"Combo → {recipe.name}", "combo", {}, com=recipe.code)
    for recipe in super_alpha.library(limit):
        if recipe.code.strip() != selection.strip():
            add(f"Selection → {recipe.name}", "selection", {}, sel=recipe.code)
    # Stable: within a priority, the order above (smallest change first).
    order = {v.id: i for i, v in enumerate(out)}
    out.sort(key=lambda v: (_priority(v.family, v.edit, failed), order[v.id]))
    return out
