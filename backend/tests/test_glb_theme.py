"""The GLB/D1 Power Pool Nov`26 theme: its rule, the combo objective and what to submit next."""

import json
from datetime import date, timedelta

import numpy as np

from alpha_harness.labs.objectives import theme_combo
from alpha_harness.preferences import Preferences
from alpha_harness.themes import DEFAULT_THEMES, check, sub_region_sharpe
from alpha_harness.tools import submit_rank

RULE = next(r for r in DEFAULT_THEMES if r.name == "GLB/D1 Power Pool Nov`26")


def _checks(amer: float) -> str:
    return json.dumps([{"name": "GLB_AMER_SHARPE", "result": "PASS", "value": amer, "limit": 1}])


def test_rule_needs_glb_delay_1_and_amer_sharpe_above_1() -> None:
    def fits(region: str, delay: int, checks: str | None) -> tuple[bool, str]:
        return check(
            RULE,
            expression="rank(ts_rank(mdl110_score, 20))",
            region=region,
            delay=delay,
            category_of=lambda *_: "model",
            checks=checks,
        )

    assert fits("GLB", 1, _checks(1.4))[0]
    assert not fits("GLB", 1, _checks(0.9))[0]
    assert "AMER Sharpe 0.90" in fits("GLB", 1, _checks(0.9))[1]
    assert not fits("USA", 1, _checks(1.4))[0]
    assert not fits("GLB", 0, _checks(1.4))[0]
    # Checks not read yet: judged on the rest.
    assert fits("GLB", 1, None)[0]
    assert "AMER Sharpe > 1" in RULE.describe()
    assert "model110" in RULE.datasets
    assert sub_region_sharpe([{"name": "LOW_GLB_AMER_SHARPE", "value": 1.2}], "AMER") == 1.2


def test_new_theme_reaches_a_saved_calendar_once() -> None:
    saved = {"power_pool_themes": [{"name": "mine", "start": "2026-10-01", "end": "2027-01-01"}]}
    first = Preferences.model_validate(saved)
    assert RULE.name in {r.name for r in first.power_pool_themes}
    # Removed by the user and saved: it stays removed.
    again = Preferences.model_validate(saved | {"themes_offered": first.themes_offered})
    assert RULE.name not in {r.name for r in again.power_pool_themes}


def test_combo_objective_rewards_after_cost_and_the_amer_floor() -> None:
    slow = theme_combo(train_sharpe=1.5, sharpe=1.6, turnover=0.05, returns=0.10)
    fast = theme_combo(train_sharpe=1.5, sharpe=1.6, turnover=0.40, returns=0.10)
    assert slow is not None and fast is not None and slow > fast
    weak_amer = theme_combo(
        train_sharpe=1.5, sharpe=1.6, turnover=0.05, returns=0.10, checks=_checks(0.8)
    )
    assert weak_amer is not None and weak_amer < slow - 0.5
    assert theme_combo(train_sharpe=None, sharpe=None, turnover=0.1, returns=0.1) is None


def test_combo_picks_do_not_repeat_each_other() -> None:
    rng = np.random.default_rng(0)
    days = [date(2018, 1, 1) + timedelta(days=i) for i in range(1500)]
    signal = rng.normal(0.2, 1, 1500)

    def series(pnl: np.ndarray) -> dict[date, tuple[float, float]]:
        return {d: (float(p) * 1e4, 0.1) for d, p in zip(days, pnl, strict=True)}

    store = {
        "twin_a": series(signal + rng.normal(0, 0.1, 1500)),
        "twin_b": series(signal + rng.normal(0, 0.1, 1500)),
        "other": series(rng.normal(0.2, 1, 1500)),
    }
    _, order, each = submit_rank.theme_combo(store, {}, [], list(store), picks=3)
    picked = [p.alpha_id for p in order]
    assert "other" in picked[:2]
    assert not {"twin_a", "twin_b"} <= set(picked[:2])
    assert len(each) == 3


def test_glb_alphas_are_standardised_within_country() -> None:
    from alpha_harness.labs import search

    point = {
        "field": "mdl110_score",
        "family": "ts",
        "ts": "ts_rank",
        "d": 21,
        "within": "country",
        "within_op": "group_zscore",
    }
    assert search.render(point) == (
        "group_zscore(ts_rank(ts_backfill(mdl110_score, 21), 21), country)"
    )
    grouped = point | {"family": "group", "group_op": "group_rank", "group": "country"}
    assert search.render(grouped) == "group_rank(ts_backfill(mdl110_score, 21), country)"
    plain = {k: v for k, v in point.items() if not k.startswith("within")}
    assert search.render(plain) == "ts_rank(ts_backfill(mdl110_score, 21), 21)"


def test_combo_objective_prefers_balanced_sub_regions() -> None:
    def regions(amer: float, apac: float, emea: float) -> str:
        return json.dumps(
            [
                {"name": f"GLB_{area}_SHARPE", "value": value}
                for area, value in (("AMER", amer), ("APAC", apac), ("EMEA", emea))
            ]
        )

    base = {"train_sharpe": 1.5, "sharpe": 1.5, "turnover": 0.1, "returns": 0.1}
    balanced = theme_combo(**base, checks=regions(1.4, 1.3, 1.35))
    lopsided = theme_combo(**base, checks=regions(2.6, 1.05, 1.1))
    weak_emea = theme_combo(**base, checks=regions(1.6, 1.5, 0.7))
    assert balanced is not None and lopsided is not None and weak_emea is not None
    assert balanced > lopsided > weak_emea


def test_combo_reports_merged_pnl_and_weights_bc_ac_first() -> None:
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(600)]
    store = {"a": {d: (100.0 + (i % 7), 0.1) for i, d in enumerate(days)}}
    now, order, _ = submit_rank.theme_combo(store, {}, [], ["a"], picks=1)
    assert now.pnl is None
    assert order[0].combo.pnl is not None and order[0].combo.pnl > 0
    assert submit_rank.WEIGHTS[0] == submit_rank.WEIGHTS[1] > submit_rank.WEIGHTS[2]


def test_chosen_templates_render_and_check_operators() -> None:
    from alpha_harness.labs import search, theme_templates

    smooth = theme_templates.BY_NAME["Smoothed change"]
    assert smooth.operators() == {"rank", "ts_decay_linear", "ts_delta"}
    point = {
        "field": "mdl110_score",
        "family": "tpl",
        "template": smooth.expression,
        "d": 63,
        "within": "country",
        "within_op": "group_rank",
    }
    assert search.render(point) == (
        "group_rank(rank(ts_decay_linear(ts_delta(ts_backfill(mdl110_score, 21), 63), 10)), "
        "country)"
    )
    country = theme_templates.BY_NAME["Country, then sector"]
    assert country.groups() == {"country", "sector"}
    ops = {"rank", "ts_rank", "group_rank", "group_neutralize"}
    names = {t.name for t in theme_templates.usable(ops, grouping=True)}
    assert {"Rank", "Own history", "Country, then sector"} <= names
    assert "Smoothed change" not in names
    assert "Country, then sector" not in {
        t.name for t in theme_templates.usable(ops, grouping=False)
    }
    # Every template stays inside Power Pool's eight operators with the GLB country step.
    from alpha_harness.labs.fastexpr import operator_count, parse

    for t in theme_templates.TEMPLATES:
        point = {"field": "f", "vector_op": "vec_avg", "family": "tpl", "template": t.expression}
        point |= {"d": 21, "within": "country", "within_op": "group_zscore"}
        assert operator_count(parse(search.render(point))) <= 8, t.name


def test_search_requests_carry_the_chosen_mode() -> None:
    from alpha_harness.labs import search
    from alpha_harness.labs.params import SearchParams

    space = {"neutralizations": ["MARKET"]}
    point = {"field": "f", "family": "cs", "cs": "rank", "universe": "MINVOL1M"}
    point["neutralization"] = "MARKET"
    run = SearchParams(region="GLB", delay=1, space=space, simulation_mode="FULL")
    assert search.request_for(point, run).settings.simulation_mode == "FULL"
    auto = SearchParams(region="GLB", delay=1, space=space)
    assert search.request_for(point, auto).settings.simulation_mode is None


def test_theme_sub_region_miss_reads_as_fail_only_while_the_theme_runs() -> None:
    from alpha_harness.preferences import theme_floors
    from alpha_harness.vault import yields

    warn = {"name": "LOW_GLB_AMER_SHARPE", "result": "WARNING", "value": 0.8, "limit": 1.0}
    apac = warn | {"name": "LOW_GLB_APAC_SHARPE"}
    try:
        yields.set_theme_areas(frozenset({"AMER"}))
        read = yields.checks_of(json.dumps([warn, apac, warn | {"value": 1.3}]))
        assert [c["result"] for c in read] == ["FAIL", "WARNING", "WARNING"]
        # No theme running: BRAIN's own reading.
        yields.set_theme_areas(frozenset())
        assert yields.without_quota_checks([warn])[0]["result"] == "WARNING"
        # The calendar decides: Nov`26 names AMER, and runs today or not.
        theme_floors([RULE.model_copy(update={"start": date.today(), "end": date.today()})])
        assert yields.without_quota_checks([warn])[0]["result"] == "FAIL"
        theme_floors([RULE.model_copy(update={"start": date(2020, 1, 1), "end": date(2020, 2, 1)})])
        assert yields.without_quota_checks([warn])[0]["result"] == "WARNING"
    finally:
        yields.set_theme_areas(frozenset())


def test_chosen_templates_are_what_gets_simulated() -> None:
    import random

    from alpha_harness.labs import search

    space = {
        "fields": {"f": "MATRIX"},
        "families": ["cs", "ts", "group", "cs_ts", "ts_ts", "group_ts", "tpl"],
        "templates": ["rank(ts_mean({x}, {d}))"],
        "cs": ["rank"],
        "ts": ["ts_mean"],
        "group": ["group_rank"],
        "groups": ["industry"],
        "vector": [],
        "lookbacks": [21, 63],
        "universes": ["TOP3000"],
        "neutralizations": ["MARKET"],
    }
    choices = search.field_choices(space)

    def share(families: list[str]) -> float:
        rng = random.Random(1)
        drawn = [
            search.suggest(search.RandomTrial(rng), space | {"families": families}, choices)
            for _ in range(400)
        ]
        return sum(p["family"] == "tpl" for p in drawn) / len(drawn)

    assert 0.4 < share(space["families"]) < 0.6  # beside the shapes: half
    assert share(["tpl"]) == 1.0  # templates only: every one
    rng = random.Random(2)
    point = search.suggest(search.RandomTrial(rng), space | {"families": ["tpl"]}, choices)
    assert search.render(point) in {
        "rank(ts_mean(ts_backfill(f, 21), 21))",
        "rank(ts_mean(ts_backfill(f, 21), 63))",
    }


def test_quick_power_pool_alphas_go_to_full_on_their_own_bar() -> None:
    from alpha_harness.labs.study import passed_quick, soften_quick_power_pool

    expression = "rank(ts_mean(ts_backfill(vec_avg(anl10_x), 21), 63))"

    def result(sharpe: float, *fails: str) -> dict[str, object]:
        names = ["LOW_SHARPE", "LOW_FITNESS", "LOW_TURNOVER", "HIGH_TURNOVER"]
        names += ["LOW_SUB_UNIVERSE_SHARPE", "LOW_2Y_SHARPE", "CONCENTRATED_WEIGHT"]
        checks = [{"name": n, "result": "FAIL" if n in fails else "PASS"} for n in names]
        return {
            "quick": True,
            "stats": {"sharpe": sharpe},
            "checks": checks,
            "failedChecks": list(fails),
            "constraint": {n: (0.3 if n in fails else 0.0) for n in names},
        }

    # The screenshot: Sharpe 1.31 under GLB's 1.58, fitness under 1, the rest passing.
    shot = result(1.31, "LOW_SHARPE", "LOW_FITNESS")
    soften_quick_power_pool(shot, expression)
    read = {c["name"]: c["result"] for c in shot["checks"]}  # type: ignore[index, union-attr]
    assert read["LOW_SHARPE"] == read["LOW_FITNESS"] == "PASS"
    two_year = result(1.31, "LOW_2Y_SHARPE", "HIGH_TURNOVER")
    soften_quick_power_pool(two_year, expression)
    read = {c["name"]: c["result"] for c in two_year["checks"]}  # type: ignore[index, union-attr]
    assert read["LOW_2Y_SHARPE"] == "WARNING"
    assert read["HIGH_TURNOVER"] == "FAIL"  # a gate keeps BRAIN's verdict
    assert shot["feasible"] is True
    assert passed_quick(shot, expression)
    # Only Sharpe above 1, sub-universe and turnover decide; the rest does not.
    assert passed_quick(
        result(1.2, "LOW_SHARPE", "LOW_2Y_SHARPE", "CONCENTRATED_WEIGHT"), expression
    )
    assert not passed_quick(result(1.2, "LOW_SUB_UNIVERSE_SHARPE"), expression)
    assert not passed_quick(result(1.2, "HIGH_TURNOVER"), expression)
    assert not passed_quick(result(0.95, "LOW_SHARPE"), expression)
    assert not passed_quick(result(1.0, "LOW_SHARPE"), expression)
    # Outside Power Pool's limits (four fields): every check must pass, as before.
    wide = "rank(a) + rank(b) + rank(c) + rank(d)"
    assert not passed_quick(result(1.4, "LOW_SHARPE"), wide)
