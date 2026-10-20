"""Type-aware submittability: each Alpha type answers to its own correlation check."""

import json
from typing import Any

from alpha_harness.separation import Kind, Verdict, judge, judge_all, summary


def check(name: str, result: str, value: Any = None, limit: Any = None, **extra: Any) -> dict:
    return {"name": name, "result": result, "value": value, "limit": limit, **extra}


BASE = [
    check("LOW_SHARPE", "PASS", 1.6, 1.25),
    check("LOW_FITNESS", "PASS", 1.1, 1.0),
    check("HIGH_TURNOVER", "PASS", 0.2, 0.7),
    check("SELF_CORRELATION", "PASS", 0.4, 0.7),
]


def row(checks: list[dict], **fields: Any) -> dict[str, Any]:
    return {
        "alpha_id": fields.pop("alpha_id", "a1"),
        "checks": json.dumps(checks),
        "status": "UNSUBMITTED",
        **fields,
    }


def test_regular_alpha_needs_prod_correlation_to_pass() -> None:
    ok = judge(row([*BASE, check("PROD_CORRELATION", "PASS", 0.55, 0.7)]))
    assert (ok.kind, ok.verdict) == (Kind.REGULAR, Verdict.SUBMITTABLE)

    high = judge(row([*BASE, check("PROD_CORRELATION", "FAIL", 0.82, 0.7)]))
    assert high.verdict == Verdict.REFUSED
    assert [i.name for i in high.failed] == ["PROD_CORRELATION"]


def test_prod_correlation_warning_is_read_from_its_numbers() -> None:
    above = judge(row([*BASE, check("PROD_CORRELATION", "WARNING", 0.74, 0.7)]))
    below = judge(row([*BASE, check("PROD_CORRELATION", "WARNING", 0.61, 0.7)]))
    assert above.verdict == Verdict.REFUSED
    assert below.verdict == Verdict.SUBMITTABLE


def test_unrun_correlation_checks_leave_an_alpha_pending() -> None:
    j = judge(row(BASE[:3] + [check("PROD_CORRELATION", "PENDING")]))
    assert j.verdict == Verdict.PENDING
    assert set(j.pending) == {"PROD_CORRELATION", "SELF_CORRELATION"}


def test_power_pool_ignores_prod_but_needs_power_pool_correlation() -> None:
    pp = [*BASE, check("PROD_CORRELATION", "FAIL", 0.9, 0.7)]
    passing = judge(row([*pp, check("POWER_POOL_CORRELATION", "PASS", 0.3, 0.5)]))
    assert (passing.kind, passing.verdict) == (Kind.POWER_POOL, Verdict.SUBMITTABLE)

    failing = judge(row([*pp, check("POWER_POOL_CORRELATION", "FAIL", 0.6, 0.5)]))
    assert failing.verdict == Verdict.REFUSED
    assert [i.name for i in failing.failed] == ["POWER_POOL_CORRELATION"]


def test_theme_alphas_have_their_own_tab_and_must_match() -> None:
    pp = [*BASE, check("POWER_POOL_CORRELATION", "PASS", 0.3, 0.5)]
    themed = judge(row([*pp, check("MATCHES_THEMES", "PASS", matched=["Analyst theme"])]))
    assert (themed.kind, themed.verdict) == (Kind.THEME, Verdict.SUBMITTABLE)
    plain = judge(row([*pp, check("MATCHES_THEMES", "WARNING", matched=[])]))
    assert plain.kind == Kind.POWER_POOL


def test_submitted_and_quick_mode() -> None:
    done = judge(row(BASE, status="ACTIVE"))
    assert done.verdict == Verdict.SUBMITTED
    quick = judge(
        row([*BASE, check("PROD_CORRELATION", "PASS", 0.1, 0.7)], simulation_mode="QUICK")
    )
    assert quick.verdict == Verdict.REFUSED
    assert quick.failed[0].name == "QUICK_MODE"


def test_superalpha_is_its_own_kind_and_checks_prod() -> None:
    j = judge(row([*BASE, check("PROD_CORRELATION", "FAIL", 0.8, 0.7)], sim_type="SUPER"))
    assert (j.kind, j.verdict) == (Kind.SUPER, Verdict.REFUSED)


def _family(regions: dict[str, list[dict]]) -> list[dict[str, Any]]:
    same = {
        "expression": "rank(x)",
        "date_created": "2026-10-20 10:00:00",
        "delay": 1,
        "neutralization": "INDUSTRY",
        "decay": 4,
        "truncation": 0.08,
    }
    parent = {
        "alpha_id": "p",
        "sim_type": "RA_PARENT",
        "region": "ALL",
        "checks": None,
        "status": "UNSUBMITTED",
        **same,
    }
    kids = [
        {
            "alpha_id": f"c-{r}",
            "sim_type": "RA_CHILD",
            "region": r,
            "checks": json.dumps(c),
            "status": "UNSUBMITTED",
            "sharpe": 1.5,
            **same,
        }
        for r, c in regions.items()
    ]
    return [parent, *kids]


OK = [*BASE, check("PROD_CORRELATION", "PASS", 0.5, 0.7)]
CROWDED = [*BASE, check("PROD_CORRELATION", "FAIL", 0.85, 0.7)]


def test_ra_family_needs_two_passing_regions() -> None:
    two = judge_all(_family({"USA": OK, "EUR": OK, "ASI": CROWDED}))
    assert len(two) == 1
    fam = two[0].judgement
    assert (fam.kind, fam.verdict) == (Kind.RA, Verdict.SUBMITTABLE)
    assert fam.regions_passing == ["EUR", "USA"]
    assert fam.regions_tried == ["ASI", "EUR", "USA"]

    one = judge_all(_family({"USA": OK, "EUR": CROWDED}))[0].judgement
    assert one.verdict == Verdict.REFUSED
    assert [i.name for i in one.failed] == ["EUR:PROD_CORRELATION"]


def test_ra_family_with_a_pending_region_can_still_get_there() -> None:
    waiting = [
        *BASE[:3],
        check("SELF_CORRELATION", "PENDING"),
        check("PROD_CORRELATION", "PENDING"),
    ]
    fam = judge_all(_family({"USA": OK, "EUR": waiting}))[0].judgement
    assert fam.verdict == Verdict.PENDING


def test_summary_counts_theme_under_power_pool_too() -> None:
    pp = [
        *BASE,
        check("POWER_POOL_CORRELATION", "PASS", 0.3, 0.5),
        check("MATCHES_THEMES", "PASS", matched=["T"]),
    ]
    counts = summary(judge_all([row(pp, alpha_id="t1"), row(OK, alpha_id="r1")]))
    assert counts["theme"]["submittable"] == 1
    assert counts["power_pool"]["submittable"] == 1
    assert counts["regular"]["submittable"] == 1
