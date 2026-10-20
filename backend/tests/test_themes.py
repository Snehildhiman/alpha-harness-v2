"""Power Pool themes, checked locally from the Alpha's delay, region and data categories."""

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

from alpha_harness.api.separation import _categories
from alpha_harness.db.duck import Catalog
from alpha_harness.separation import Kind, Verdict, judge_all
from alpha_harness.themes import DEFAULT_THEMES, ThemeRule, check, current, normalise

ANALYST = ThemeRule(
    name="D1 analyst/model/news",
    start=date(2026, 10, 14),
    end=date(2026, 10, 31),
    delay=1,
    categories=["analyst", "model", "news"],
)
CATS = {"est_eps": "analyst", "est_rev": "analyst", "close": "pv", "mdl_score": "model"}


def cat(name: str, _region: str, _delay: int) -> str | None:
    return CATS.get(name)


def fits(expression: str, delay: int = 1) -> tuple[bool, str]:
    return check(ANALYST, expression=expression, region="USA", delay=delay, category_of=cat)


def test_single_category_from_the_allowed_set_matches() -> None:
    ok, note = fits("group_rank(ts_mean(est_eps / est_rev, 20), subindustry)")
    assert ok
    assert note == "analyst only"


def test_grouping_fields_do_not_count_as_a_category() -> None:
    assert fits("group_neutralize(rank(est_eps), industry)")[0]


def test_mixing_categories_or_using_others_fails_with_a_reason() -> None:
    ok, note = fits("rank(est_eps) * rank(mdl_score)")
    assert not ok
    assert "mixes analyst, model" in note
    ok, note = fits("rank(est_eps / close)")
    assert not ok
    assert note.startswith("uses pv")


def test_delay_and_unknown_fields() -> None:
    assert fits("rank(est_eps)", delay=0) == (False, "delay 0, theme needs 1")
    ok, note = fits("rank(mystery_field)")
    assert not ok
    assert "not in the synced catalog" in note


def test_running_theme_follows_the_calendar() -> None:
    assert current(DEFAULT_THEMES, date(2026, 10, 5)) is not None
    oct20 = current(DEFAULT_THEMES, date(2026, 10, 20))
    assert oct20 is not None
    assert oct20.categories == ["analyst", "model", "news"]
    assert current(DEFAULT_THEMES, date(2026, 11, 2)) is None
    assert normalise("fundamnetal") == "fundamental"


PP_CHECKS = json.dumps(
    [
        {"name": "LOW_SHARPE", "result": "PASS", "value": 1.3, "limit": 1.0},
        {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.3, "limit": 0.7},
        {"name": "POWER_POOL_CORRELATION", "result": "PASS", "value": 0.2, "limit": 0.5},
    ]
)


def pp(alpha_id: str, expression: str) -> dict[str, Any]:
    return {
        "alpha_id": alpha_id,
        "expression": expression,
        "region": "USA",
        "delay": 1,
        "checks": PP_CHECKS,
        "status": "UNSUBMITTED",
        "sim_type": "REGULAR",
    }


def test_theme_tab_takes_power_pool_alphas_the_rule_accepts() -> None:
    def theme(row: dict[str, Any]) -> tuple[bool, str]:
        return check(
            ANALYST,
            expression=row["expression"],
            region=row["region"],
            delay=row["delay"],
            category_of=cat,
        )

    judged = {
        j.row["alpha_id"]: j.judgement
        for j in judge_all([pp("in", "rank(est_eps)"), pp("out", "rank(close)")], theme)
    }
    assert (judged["in"].kind, judged["in"].verdict) == (Kind.THEME, Verdict.SUBMITTABLE)
    assert judged["in"].theme_note == "analyst only"
    assert judged["out"].kind == Kind.POWER_POOL
    assert judged["out"].theme_note is not None and "pv" in judged["out"].theme_note


def test_categories_are_read_from_the_synced_catalog(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = Catalog(tmp_path / "c.duckdb")
        await catalog.open()
        for field_id, category in (("est_eps", "analyst"), ("close", "pv")):
            await catalog.execute(
                "INSERT INTO data_field (field_id, category_id, instrument_type, region, delay,"
                " universe) VALUES (?, ?, 'EQUITY', 'USA', 1, 'TOP3000')",
                [field_id, category],
            )
        theme = await _categories(
            SimpleNamespace(catalog=catalog),  # type: ignore[arg-type]
            [pp("a", "rank(est_eps)"), pp("b", "rank(close)")],
            ANALYST,
        )
        assert theme(pp("a", "rank(est_eps)")) == (True, "analyst only")
        assert theme(pp("b", "rank(close)"))[0] is False
        await catalog.close()

    asyncio.run(body())


def test_brain_theme_match_is_named_when_the_local_rule_disagrees() -> None:
    checks = json.loads(PP_CHECKS) + [
        {"name": "MATCHES_THEMES", "result": "PASS", "matched": ["Analyst Revisions"]}
    ]
    row = {**pp("b", "rank(close)"), "checks": json.dumps(checks)}

    def theme(r: dict[str, Any]) -> tuple[bool, str]:
        return check(
            ANALYST,
            expression=r["expression"],
            region=r["region"],
            delay=r["delay"],
            category_of=cat,
        )

    j = judge_all([row], theme)[0].judgement
    assert j.kind == Kind.THEME
    assert j.theme_note is not None and j.theme_note.startswith("BRAIN's theme check passed")
