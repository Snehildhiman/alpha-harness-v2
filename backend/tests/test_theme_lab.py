"""Current Theme Lab: the search space keeps only what the running theme allows."""

import asyncio
from datetime import date
from typing import Any

from alpha_harness.api import theme_lab
from alpha_harness.themes import ThemeRule, grouping_in

RULE = ThemeRule(
    name="D1 analyst", start=date(2026, 10, 1), end=date(2026, 10, 31), categories=["analyst"]
)


def test_group_shapes_are_dropped_and_samples_fit(monkeypatch: Any) -> None:
    async def theme(_state: Any, _name: str | None = None) -> ThemeRule:
        return RULE

    async def allowed(_state: Any, _rule: Any, _region: Any) -> list[dict[str, Any]]:
        return [{"dataset_id": "analyst4"}]

    seen: dict[str, Any] = {}

    async def plan_search(body: Any, _state: Any) -> dict[str, Any]:
        seen["datasets"], seen["delay"] = body.dataset_ids, body.delay
        return {
            "problems": [],
            "warnings": [],
            "round": 10,
            "sample": [],
            "space": {
                "fields": {"est_eps": "MATRIX"},
                "families": ["cs", "ts", "group", "cs_ts", "group_ts"],
                "cs": ["rank"],
                "ts": ["ts_mean"],
                "group": ["group_rank"],
                "vector": [],
                "lookbacks": [5, 21],
                "groups": ["industry"],
                "universes": ["TOP3000"],
                "absent": {},
                "neutralizations": ["SUBINDUSTRY"],
            },
        }

    monkeypatch.setattr(theme_lab, "_theme", theme)
    monkeypatch.setattr(theme_lab, "_allowed", allowed)
    monkeypatch.setattr(theme_lab.search_lab, "plan_search", plan_search)
    body = theme_lab.ThemeLabRequest(region="USA", dataset_ids=["pv1"], neutralizations=["X"])
    plan, rule = asyncio.run(theme_lab._plan(body, None))  # type: ignore[arg-type]
    assert rule is RULE
    assert seen == {"datasets": ["analyst4"], "delay": 1}  # pv1 is outside the theme
    assert plan["space"]["families"] == ["cs", "ts", "cs_ts"]
    assert plan["sample"] and all(grouping_in(s.expression) is None for s in plan["sample"])
    assert any("outside the theme" in w for w in plan["warnings"])
