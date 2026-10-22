"""Super Alpha Lab: SuperAlphas built from your own submitted Alphas, ready to submit.

A SuperAlpha is a selection expression, ranking every submitted ``ACTIVE`` Alpha of the
region and delay and keeping the top ``selectionLimit``, and a combo expression, weighting
the kept Alphas each day. Nothing here searches either expression: SuperAlpha simulations
are slow and BRAIN runs three at a time, so the lab crosses a small library of
economically grounded selections with proven weighting schemes, each at two decays to land
Turnover inside the 2% to 40% a SuperAlpha must clear, and lets BRAIN's own checks say
which are submittable.

Every selection caps each Alpha's operators at 8,000 / limit: BRAIN warns rather than
fails past 8,000 operators in all, and drops what does not fit.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..brain.schemas import FULL_MODE, SimulationRequest, SimulationSettings, SimulationType
from ..db.models import Trial, TrialState
from .scheduler import PENDING_SEND

if TYPE_CHECKING:
    from collections.abc import Callable

#: BRAIN's own ceiling on operators across every selected Alpha.
OPERATOR_LIMIT = 8000
#: The least ``selectionLimit`` BRAIN accepts.
MIN_SELECTION = 10
#: Combo smoothing, each pairing at both by default: lighter keeps fast components' edge,
#: heavier pulls an over-trading combination under the 40% Turnover ceiling.
DECAYS = (4, 10)
#: Every decay the form offers.
DECAY_CHOICES = (2, 4, 6, 10, 15, 20)
#: Applied to the final weighted combination. Lower than an Alpha's usual 0.08: a SuperAlpha
#: concentrates more easily, and truncation is the documented brake on overfitting.
TRUNCATION = 0.05


@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    code: str
    #: Part of a task when none is chosen: the original, proven set.
    default: bool = True


def selections(limit: int, names: list[str] | None = None) -> list[Recipe]:
    """The selections named, or the defaults: see :func:`library`."""
    return pick(library(limit), names)


def library(limit: int) -> list[Recipe]:
    """Rankings over Alpha properties, each one keeping the pool diverse in its own way.

    ``{cap}`` bounds an Alpha's operators so the kept ones never pass 8,000 between them.
    Products of gates and scores: a gate that fails scores 0, which ``POSITIVE`` drops.
    Every one reads only the properties the first five do, which BRAIN's selection
    expressions accept.
    """
    cap = OPERATOR_LIMIT // max(limit, MIN_SELECTION)
    budget = f"(operator_count <= {cap})"
    broad = "(long_count + short_count) / sqrt(universe_size(universe))"
    return [*_core(budget, broad), *_more_selections(budget, broad)]


def _core(budget: str, broad: str) -> list[Recipe]:
    return [
        Recipe(
            "Least correlated",
            f"{budget} * (self_correlation < 0.7) * (1 - prod_correlation)",
        ),
        Recipe(
            "Tradeable turnover",
            f"{budget} * (turnover >= 0.02) * (turnover < 0.35) * (1 - self_correlation)",
        ),
        Recipe("Broad books", f"{budget} * {broad}"),
        Recipe("Slow core", f"{budget} * (turnover < 0.25) / (turnover + 0.05)"),
        Recipe(
            "Many sources",
            f"{budget} * (1 + datacategory_count) * (1 - prod_correlation)",
        ),
        Recipe(
            "Unique and uncrowded",
            f"{budget} * (prod_correlation < 0.5) * (1 - self_correlation)",
            default=False,
        ),
        Recipe(
            "Lean expressions",
            f"{budget} * (1 - prod_correlation) / (1 + operator_count)",
            default=False,
        ),
        Recipe(
            "Unique broad books",
            f"{budget} * (1 - prod_correlation) * (1 - self_correlation) * {broad}",
            default=False,
        ),
        Recipe(
            "Single source",
            f"{budget} * (datacategory_count == 1) * (1 - prod_correlation)",
            default=False,
        ),
        Recipe(
            "Fast but tradeable",
            f"{budget} * (turnover >= 0.08) * (turnover < 0.4) * (1 - prod_correlation)",
            default=False,
        ),
        Recipe(
            "Quiet and slow",
            f"{budget} * (turnover < 0.15) * (self_correlation < 0.6) * (1 - prod_correlation)",
            default=False,
        ),
        Recipe(
            "Mixed sources, broad",
            f"{budget} * (datacategory_count >= 2) * {broad}",
            default=False,
        ),
    ]


def _more_selections(budget: str, broad: str) -> list[Recipe]:
    """Families beyond the core twelve, each a different way to keep the pool diverse.

    Same properties only: correlations, turnover, book size, operator and category counts.
    """
    out: list[Recipe] = []
    uncorrelated = "(1 - prod_correlation)"
    unique = "(1 - self_correlation)"
    # Hard correlation caps: only Alphas well clear of the crowd and of each other.
    for prod in (0.3, 0.4, 0.5, 0.6):
        for own in (0.5, 0.6, 0.7):
            out.append(  # noqa: PERF401 - one family per loop reads plainer
                Recipe(
                    f"Prod < {prod:g}, self < {own:g}",
                    f"{budget} * (prod_correlation < {prod:g}) * (self_correlation < {own:g})"
                    f" * {uncorrelated}",
                    default=False,
                )
            )
    # Turnover bands, scored by prod or by self-correlation.
    bands = ((0.02, 0.1), (0.05, 0.15), (0.1, 0.2), (0.15, 0.3), (0.2, 0.4))
    for low, high in bands:
        gate = f"(turnover >= {low:g}) * (turnover < {high:g})"
        out.append(
            Recipe(
                f"Turnover {low:.0%}-{high:.0%}, low prod",
                f"{budget} * {gate} * {uncorrelated}",
                default=False,
            )
        )
        out.append(
            Recipe(
                f"Turnover {low:.0%}-{high:.0%}, low self",
                f"{budget} * {gate} * {unique}",
                default=False,
            )
        )
    # Broad books under a prod cap, and broad books that are also unique.
    for prod in (0.4, 0.5, 0.6, 0.7):
        out.append(  # noqa: PERF401 - one family per loop reads plainer
            Recipe(
                f"Broad books, prod < {prod:g}",
                f"{budget} * (prod_correlation < {prod:g}) * {broad}",
                default=False,
            )
        )
    out.append(Recipe("Broad and unique", f"{budget} * {unique} * {broad}", default=False))
    out.append(
        Recipe(
            "Broad, slow, uncrowded",
            f"{budget} * (turnover < 0.2) * {uncorrelated} * {broad}",
            default=False,
        )
    )
    # Simple expressions: fewer operators overfit less.
    for most in (5, 10, 20, 40):
        out.append(  # noqa: PERF401 - one family per loop reads plainer
            Recipe(
                f"At most {most} operators",
                f"{budget} * (operator_count <= {most}) * {uncorrelated}",
                default=False,
            )
        )
    out.append(
        Recipe(
            "Simplest unique",
            f"{budget} * {unique} * {uncorrelated} / (1 + operator_count)",
            default=False,
        )
    )
    # By how many data categories an Alpha reads.
    for name, gate in (
        ("One category", "(datacategory_count == 1)"),
        ("Two categories", "(datacategory_count == 2)"),
        ("Three or more categories", "(datacategory_count >= 3)"),
    ):
        out.append(Recipe(f"{name}, unique", f"{budget} * {gate} * {unique}", default=False))
        out.append(Recipe(f"{name}, broad", f"{budget} * {gate} * {broad}", default=False))
    # Balanced books: as long as short, so the combination stays market-neutral.
    gross = "(long_count + short_count + 1)"
    tilt = f"((long_count - short_count) * (long_count - short_count)) / ({gross} * {gross})"
    out.append(Recipe("Balanced books", f"{budget} * (1 - {tilt})", default=False))
    out.append(
        Recipe(
            "Balanced and uncrowded",
            f"{budget} * (1 - {tilt}) * {uncorrelated}",
            default=False,
        )
    )
    out.append(
        Recipe(
            "Balanced and broad",
            f"{budget} * (1 - {tilt}) * {broad}",
            default=False,
        )
    )
    # Blended scores.
    for name, code in (
        ("Unique, uncrowded", f"{unique} * {uncorrelated}"),
        ("Unique, uncrowded, slow", f"{unique} * {uncorrelated} / (turnover + 0.05)"),
        ("Uncrowded squared", f"{uncorrelated} * {uncorrelated}"),
        ("Unique squared", f"{unique} * {unique}"),
        ("Uncrowded, many sources", f"{uncorrelated} * datacategory_count"),
        ("Slow and simple", "(turnover < 0.25) / ((turnover + 0.05) * (1 + operator_count))"),
        ("Uncrowded per operator", f"{uncorrelated} / sqrt(1 + operator_count)"),
        ("Distance from crowd", "1 / (prod_correlation + 0.1)"),
        ("Distance from own pool", "1 / (self_correlation + 0.1)"),
        (
            "Distance from both",
            "1 / ((prod_correlation + 0.1) * (self_correlation + 0.1))",
        ),
        ("Tradeable, broad, unique", f"(turnover < 0.35) * {unique} * {broad}"),
        ("Low turnover first", "1 / (turnover + 0.02)"),
        ("Mid turnover first", "(turnover >= 0.05) * (turnover < 0.3) / (turnover + 0.1)"),
    ):
        out.append(Recipe(name, f"{budget} * {code}", default=False))
    return out


def pick(recipes: list[Recipe], names: list[str] | None) -> list[Recipe]:
    """Those named, in library order; the defaults when none is (or none named is known)."""
    if names:
        wanted = set(names)
        chosen = [r for r in recipes if r.name in wanted]
        if chosen:
            return chosen
    return [r for r in recipes if r.default]


_STATS = "stats = generate_stats(alpha);\n"
_MAX_CORR = (
    "innerCorr = self_corr(stats.returns, 500);\n"
    "ic = if_else(innerCorr == 1.0, nan, innerCorr);\n"
    "maxCorr = reduce_max(ic);\n"
)

#: Weighting schemes from BRAIN's own combo examples and their risk-aware variants.
_CORE_COMBOS = [
    Recipe("Equal weight", "1"),
    Recipe("Rolling IR", _STATS + "max(ts_ir(stats.returns, 250), 0)"),
    Recipe("Least crowded", _STATS + _MAX_CORR + "max(1 - maxCorr, 0.05)"),
    Recipe(
        "Inverse volatility",
        _STATS + "1 / (ts_std_dev(stats.returns, 120) + 0.0001)",
    ),
    Recipe("Short IR", _STATS + "max(ts_ir(stats.returns, 120), 0)", default=False),
    Recipe("Long IR", _STATS + "max(ts_ir(stats.returns, 500), 0)", default=False),
    Recipe(
        "IR over volatility",
        _STATS + "max(ts_ir(stats.returns, 250), 0) / (ts_std_dev(stats.returns, 120) + 0.0001)",
        default=False,
    ),
    Recipe(
        "Uncrowded IR",
        _STATS + _MAX_CORR + "max(ts_ir(stats.returns, 250), 0) * max(1 - maxCorr, 0.05)",
        default=False,
    ),
    Recipe(
        "Uncrowded, low volatility",
        _STATS + _MAX_CORR + "max(1 - maxCorr, 0.05) / (ts_std_dev(stats.returns, 120) + 0.0001)",
        default=False,
    ),
    Recipe(
        "Floored IR",
        _STATS + "0.2 + max(ts_ir(stats.returns, 250), 0)",
        default=False,
    ),
]


def _more_combos() -> list[Recipe]:
    """Weightings beyond the core ten, from the same pieces: rolling IR, volatility, mean
    return and the highest correlation with the rest, over other windows and blends."""
    r = "stats.returns"
    eps = "0.0001"
    out: list[Recipe] = []

    def add(name: str, code: str, *, crowd: bool = False, corr: int = 500) -> None:
        head = _STATS + (_max_corr(corr) if crowd else "")
        out.append(Recipe(name, head + code, default=False))

    for w in (20, 40, 60, 90, 180, 375, 750):
        add(f"IR {w} days", f"max(ts_ir({r}, {w}), 0)")
    for floor in (0.1, 0.5):
        for w in (120, 250, 500):
            add(f"Floored IR {w}, +{floor:g}", f"{floor:g} + max(ts_ir({r}, {w}), 0)")
    for w in (20, 60, 250, 500):
        add(f"Inverse volatility {w}", f"1 / (ts_std_dev({r}, {w}) + {eps})")
    for w in (60, 120, 250):
        add(
            f"Inverse variance {w}",
            f"1 / (ts_std_dev({r}, {w}) * ts_std_dev({r}, {w}) + {eps})",
        )
    for ir, vol in ((60, 60), (120, 120), (250, 250), (500, 250), (120, 60)):
        add(
            f"IR {ir} over volatility {vol}",
            f"max(ts_ir({r}, {ir}), 0) / (ts_std_dev({r}, {vol}) + {eps})",
        )
    for w in (20, 60, 120, 250):
        add(f"Mean return {w}", f"max(ts_mean({r}, {w}), 0)")
    for corr, floor in ((250, 0.05), (1000, 0.05), (250, 0.2), (500, 0.2), (1000, 0.2)):
        add(
            f"Least crowded {corr}, floor {floor:g}",
            f"max(1 - maxCorr, {floor:g})",
            crowd=True,
            corr=corr,
        )
    for ir, corr in ((120, 250), (500, 250), (120, 500), (500, 500)):
        add(
            f"Uncrowded IR {ir}, corr {corr}",
            f"max(ts_ir({r}, {ir}), 0) * max(1 - maxCorr, 0.05)",
            crowd=True,
            corr=corr,
        )
    for vol in (60, 250):
        add(
            f"Uncrowded, inverse volatility {vol}",
            f"max(1 - maxCorr, 0.05) / (ts_std_dev({r}, {vol}) + {eps})",
            crowd=True,
            corr=250,
        )
    for ir, vol in ((250, 120), (120, 60)):
        add(
            f"Uncrowded IR {ir} over volatility {vol}",
            f"max(ts_ir({r}, {ir}), 0) * max(1 - maxCorr, 0.05) / (ts_std_dev({r}, {vol}) + {eps})",
            crowd=True,
        )
    for w in (120, 250, 500):
        add(f"IR {w} squared", f"max(ts_ir({r}, {w}), 0) * max(ts_ir({r}, {w}), 0)")
    for a, b in ((120, 250), (60, 250), (250, 750)):
        add(f"IR {a} plus IR {b}", f"max(ts_ir({r}, {a}), 0) + max(ts_ir({r}, {b}), 0)")
    for w in (20, 60, 120):
        add(f"Momentum gate {w}", f"if_else(ts_mean({r}, {w}) > 0, 1, 0.2)")
    for vol in (60, 120):
        add(
            f"Positive IR, inverse volatility {vol}",
            f"if_else(ts_ir({r}, 250) > 0, 1 / (ts_std_dev({r}, {vol}) + {eps}), 0)",
        )
    add(
        "Positive IR, uncrowded",
        f"if_else(ts_ir({r}, 250) > 0, max(1 - maxCorr, 0.05), 0)",
        crowd=True,
    )
    add(
        "Mean over volatility 120",
        f"max(ts_mean({r}, 120), 0) / (ts_std_dev({r}, 120) + {eps})",
    )
    return out


def _max_corr(window: int) -> str:
    return (
        f"innerCorr = self_corr(stats.returns, {window});\n"
        "ic = if_else(innerCorr == 1.0, nan, innerCorr);\n"
        "maxCorr = reduce_max(ic);\n"
    )


ALL_COMBOS = [*_CORE_COMBOS, *_more_combos()]
#: The default set, as before.
COMBOS = [r for r in ALL_COMBOS if r.default]


def combos(names: list[str] | None = None) -> list[Recipe]:
    return pick(ALL_COMBOS, names)


@dataclass(frozen=True, slots=True)
class Candidate:
    selection: Recipe
    combo: Recipe
    request: SimulationRequest

    @property
    def name(self) -> str:
        return f"{self.selection.name} · {self.combo.name}"


def candidates(
    *,
    region: str,
    delay: int,
    universe: str,
    neutralization: str,
    selection_limit: int,
    activations: list[str],
    selection_names: list[str] | None = None,
    combo_names: list[str] | None = None,
    decays: list[int] | None = None,
) -> list[Candidate]:
    """Every selection · combo · decay · activation, as Full SUPER simulations.

    Full mode always: only a Full simulation can be submitted, and Quick runs none of the
    correlation checks a SuperAlpha must also pass.
    """
    out: list[Candidate] = []
    for activation in activations:
        for decay in sorted(set(decays or DECAYS)):
            for selection in selections(selection_limit, selection_names):
                for combo in combos(combo_names):
                    settings = SimulationSettings(
                        region=region,
                        delay=delay,
                        universe=universe,
                        neutralization=neutralization,
                        decay=decay,
                        truncation=TRUNCATION,
                        selection_handling="POSITIVE",
                        selection_limit=selection_limit,
                        component_activation=activation,
                        simulation_mode=FULL_MODE,
                    )
                    request = SimulationRequest(
                        type=SimulationType.SUPER,
                        settings=settings,
                        selection=selection.code,
                        combo=combo.code,
                    )
                    out.append(Candidate(selection, combo, request))
    return out


def seed_trials(found: list[Candidate]) -> Callable[[int], list[Trial]]:
    """Parked trials for every candidate. Both expressions ride in ``params``, which
    ``send_parked`` reads; the trial's own expression names the recipe, the line a results
    table shows."""

    def build(study_id: int) -> list[Trial]:
        return [
            Trial(
                study_id=study_id,
                number=number,
                params={
                    "recipe": candidate.name,
                    "selection": candidate.request.selection,
                    "combo": candidate.request.combo,
                },
                distributions={},
                expression=(
                    f"{candidate.name} · Decay {candidate.request.settings.decay}"
                    f" · {candidate.request.settings.component_activation}"
                ),
                settings=candidate.request.settings.model_dump(by_alias=True, exclude_none=True),
                state=TrialState.PRUNED,
                message=PENDING_SEND,
            )
            for number, candidate in enumerate(found)
        ]

    return build


if __name__ == "__main__":
    import sys

    from ..engine.lifecycle import request_hash
    from ..engine.packer import key_of
    from .scheduler import request_of

    limit = 40
    found = candidates(
        region="USA",
        delay=1,
        universe="TOP3000",
        neutralization="SUBINDUSTRY",
        selection_limit=limit,
        activations=["IS", "OS"],
    )
    trials = seed_trials(found)(1)
    wires = [c.request.to_wire() for c in found]
    checks = {
        "every pairing at every decay and activation": len(found)
        == len(selections(limit)) * len(COMBOS) * len(DECAYS) * 2,
        "no two alike": len({request_hash(c.request) for c in found}) == len(found),
        "operators capped at 8,000 / limit": all(
            f"(operator_count <= {OPERATOR_LIMIT // limit})" in r.code for r in selections(limit)
        ),
        "SUPER, Full, Positive, as asked": all(
            w["type"] == "SUPER"
            and w["settings"]["simulationMode"] == FULL_MODE
            and w["settings"]["selectionHandling"] == "POSITIVE"
            and w["settings"]["selectionLimit"] == limit
            and w["selection"]
            and w["combo"]
            for w in wires
        ),
        "a written trial sends the same simulation": all(
            request_hash(request_of(t)) == request_hash(c.request)
            for t, c in zip(trials, found, strict=True)
        ),
        "never batched": all(key_of(w).max_batch == 1 for w in wires),
    }
    if failed := [check for check, ok in checks.items() if not ok]:
        raise SystemExit(f"super alpha self-check failed: {'; '.join(failed)}")
    sys.stdout.write(f"{len(found)} SuperAlpha simulations, e.g. {trials[0].expression}\n")
