"""Region Agnostic without an LLM, SuperAlpha recipes and repair, and the universe choices."""

import random

from alpha_harness.api.power_pool_lab import writes
from alpha_harness.brain.schemas import SimulationRequest, SimulationSettings
from alpha_harness.labs import ra_shapes, search, super_alpha
from alpha_harness.labs.fastexpr import operator_table
from alpha_harness.labs.ga import universe_for
from alpha_harness.labs.params import EvolutionParams, RegionAgnosticParams
from alpha_harness.labs.power_pool import Context, Field, Rejected, check, draw_regions
from alpha_harness.repair import super_repair

OPS = [
    {"name": n, "category": c, "definition": d}
    for n, c, d in [
        ("rank", "Cross Sectional", "rank(x)"),
        ("zscore", "Cross Sectional", "zscore(x)"),
        ("ts_rank", "Time Series", "ts_rank(x, d)"),
        ("ts_delta", "Time Series", "ts_delta(x, d)"),
        ("ts_mean", "Time Series", "ts_mean(x, d)"),
        ("ts_std_dev", "Time Series", "ts_std_dev(x, d)"),
        ("ts_zscore", "Time Series", "ts_zscore(x, d)"),
        ("ts_backfill", "Time Series", "ts_backfill(x, d)"),
        ("ts_corr", "Time Series", "ts_corr(x, y, d)"),
        ("group_rank", "Group", "group_rank(x, group)"),
        ("vec_avg", "Vector", "vec_avg(x)"),
    ]
]
NAMES = {o["name"] for o in OPS}


def _field(fid: str, where: str) -> Field:
    return Field(
        id=fid, type="MATRIX", coverage=0.9, description="", regions=len(where.split(", "))
    )


def _ctx() -> Context:
    held = {
        "eps": frozenset({"USA", "EUR", "ASI"}),
        "sales": frozenset({"USA", "EUR"}),
        "estimates": frozenset({"USA", "EUR", "ASI"}),
        "close": frozenset({"USA", "EUR", "ASI"}),
        "volume": frozenset({"USA", "EUR", "ASI"}),
        "industry": frozenset({"USA", "EUR", "ASI"}),
    }
    types = dict.fromkeys(held, "MATRIX") | {"estimates": "VECTOR", "industry": "GROUP"}
    return Context(
        id="chosen fields",
        name="3 chosen fields",
        category="",
        description="",
        fields=(
            _field("eps", "USA, EUR, ASI"),
            _field("estimates", "USA, EUR, ASI"),
            _field("sales", "USA, EUR"),
        ),
        basics=(),
        groups=("industry",),
        types=types,
        own=frozenset({"eps", "sales", "estimates"}),
        names=frozenset(held),
        held=held,
        chosen=True,
    )


def test_shapes_write_checked_region_agnostic_alphas() -> None:
    ctx = _ctx()
    table = operator_table(OPS)
    written, fields = ra_shapes.write(ctx, NAMES, random.Random(3), count=40, offset=0)
    assert written
    assert fields >= 1
    run = RegionAgnosticParams(
        region="ALL",
        delay=1,
        universes=["TOP3000", "TOP2500", "MINVOL1M"],
        neutralizations=["SUBINDUSTRY"],
        regions=["USA", "EUR", "ASI"],
        region_universes={"USA": "TOP3000", "EUR": "TOP2500", "ASI": "MINVOL1M"},
    )
    passed = 0
    for item in written:
        # Each needs every operator on the account, and the shapes use only those.
        assert "{" not in item["expression"]
        try:
            expression, used = check(item["expression"], ctx, table, power_pool=False)
        except Rejected:
            continue
        runs = draw_regions(random.Random(1), used, ctx, run)
        assert len(runs) >= 2
        assert "vec_avg(estimates)" in expression or "estimates" not in expression
        passed += 1
    assert passed >= len(written) // 2


def test_shapes_skip_operators_the_account_lacks() -> None:
    usable = ra_shapes.usable({"rank", "ts_backfill"}, frozenset({"close"}))
    assert [s.name for s in usable] == ["rank", "spread"]
    assert ra_shapes.usable({"rank"}, frozenset()) == ()


def test_better_shapes_are_written_more() -> None:
    ctx = _ctx()
    rng = random.Random(0)
    scores = {"rank": 3.0}
    counts = {"rank": 0, "other": 0}
    for _ in range(30):
        written, _ = ra_shapes.write(ctx, NAMES, rng, count=6, offset=0, scores=scores)
        for item in written:
            counts["rank" if item["shape"] == "rank" else "other"] += 1
    assert counts["rank"] > counts["other"] / len(ra_shapes.usable(NAMES, ctx.names))


def test_random_size_runs_one_size_in_every_region() -> None:
    ctx = _ctx()
    sizes = {
        "LARGE": {"USA": "TOP3000", "EUR": "TOP2500", "ASI": "MINVOL1M"},
        "SMALL": {"USA": "TOP1000", "EUR": "TOP1200", "ASI": "MINVOL1M"},
    }
    run = RegionAgnosticParams(
        region="ALL",
        delay=1,
        universes=[],
        neutralizations=["MARKET"],
        regions=["USA", "EUR", "ASI"],
        region_universes=sizes["LARGE"],
        size="RANDOM",
        size_universes=sizes,
    )
    seen = set()
    for seed in range(20):
        runs = draw_regions(random.Random(seed), frozenset({"eps"}), ctx, run)
        picked = {r["region"]: r["universe"] for r in runs}
        assert picked in (sizes["LARGE"], sizes["SMALL"])
        seen.add(picked["USA"])
    assert seen == {"TOP3000", "TOP1000"}


def test_random_universe_keeps_to_universes_holding_the_fields() -> None:
    space = {
        "universes": ["TOP3000", "TOP1000", "TOP500"],
        "absent": {"TOP500": ["eps"]},
        "randomUniverse": True,
    }
    request = SimulationRequest(
        settings=SimulationSettings(region="USA", delay=1, universe="TOP3000"),
        regular="rank(ts_backfill(eps, 21))",
    )
    got = {
        search.reroll_universe(request, space, random.Random(i)).settings.universe
        for i in range(40)
    }
    assert got == {"TOP3000", "TOP1000"}
    space["randomUniverse"] = False
    assert search.reroll_universe(request, space, random.Random(0)) is request


def test_evolution_children_run_where_their_fields_are() -> None:
    run = EvolutionParams(
        region="USA",
        delay=1,
        universe="TOP3000",
        universe_absent={"TOP1000": [], "TOP200": ["eps"]},
    )
    got = {universe_for("rank(eps)", run) for _ in range(60)}
    assert got == {"TOP3000", "TOP1000"}
    assert universe_for("rank(eps)", EvolutionParams(region="USA", delay=1, universe="X")) == "X"


def test_super_recipes_default_and_chosen() -> None:
    assert [r.name for r in super_alpha.selections(30)] == [
        "Least correlated",
        "Tradeable turnover",
        "Broad books",
        "Slow core",
        "Many sources",
    ]
    assert len(super_alpha.library(30)) > 5
    assert len(super_alpha.ALL_COMBOS) > len(super_alpha.COMBOS)
    found = super_alpha.candidates(
        region="USA",
        delay=1,
        universe="TOP3000",
        neutralization="SUBINDUSTRY",
        selection_limit=30,
        activations=["IS"],
        selection_names=["Lean expressions"],
        combo_names=["Uncrowded IR", "Short IR"],
        decays=[6],
    )
    assert len(found) == 2
    assert {c.request.settings.decay for c in found} == {6}
    # Unknown names fall back to the defaults rather than an empty task.
    assert len(super_alpha.combos(["nope"])) == len(super_alpha.COMBOS)


def test_super_repair_tries_slower_books_for_fitness() -> None:
    body = {
        "settings": {
            "region": "GLB",
            "delay": 1,
            "universe": "MINVOL1M",
            "neutralization": "SUBINDUSTRY",
            "decay": 4,
            "truncation": 0.05,
            "selectionLimit": 100,
            "componentActivation": "IS",
        },
        "selection": {"code": "(operator_count <= 80) * (1 - prod_correlation)"},
        "combo": {"code": "1"},
        "is": {"checks": [{"name": "LOW_FITNESS", "result": "FAIL"}]},
    }
    found = super_repair.variants(body)
    assert found[0].edit.startswith("Decay +")
    assert all(v.selection and v.combo for v in found)
    assert not any(v.family == "combo" and v.combo == "1" for v in found)
    body["is"] = {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}
    assert super_repair.variants(body)[0].family == "combo"


def test_models_for_other_jobs_are_not_writers() -> None:
    assert not writes("gemini-3.5-live-translate-preview")
    assert not writes("text-embedding-004")
    assert writes("gemini-3.5-flash")
    assert writes("llama-3.3-70b-versatile")


def test_super_library_is_wide_and_distinct() -> None:
    library = super_alpha.library(30)
    combos = super_alpha.ALL_COMBOS
    assert len(library) - len(super_alpha.selections(30)) >= 50
    assert len(combos) - len(super_alpha.COMBOS) >= 50
    for recipes in (library, combos):
        assert len({r.name for r in recipes}) == len(recipes)
        assert len({r.code for r in recipes}) == len(recipes)
    # Every selection keeps the operator budget, and every combo reads the stats first.
    assert all(r.code.startswith("(operator_count <= 266)") for r in library)
    assert all(r.code == "1" or r.code.startswith("stats = generate_stats(alpha);") for r in combos)
