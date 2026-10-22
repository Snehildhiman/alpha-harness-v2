"""Families of near-identical Alphas, dead families, and requests BRAIN refused for good."""

from alpha_harness.engine.slots import errored_for_good
from alpha_harness.labs import families


def test_skeleton_ignores_numbers_only() -> None:
    a = families.skeleton("rank(ts_delta(eps, 21))")
    assert a == families.skeleton("rank(ts_delta(eps,63))")
    assert a != families.skeleton("rank(ts_delta(sales, 21))")
    # A digit inside a field name is part of the name.
    assert "fnd6" in families.skeleton("rank(fnd6_eps)")


def test_dead_needs_repeated_failure_and_no_pass() -> None:
    rows = [
        {"expression": f"rank(ts_delta(eps, {d}))", "region": "USA", "failed": True}
        for d in (5, 10, 21, 63)
    ]
    rows.append({"expression": "rank(ts_delta(eps, 5))", "region": "EUR", "failed": True})
    dead = families._dead(rows)
    assert families.family("rank(ts_delta(eps, 126))", "USA") in dead
    # One failure in EUR is not enough.
    assert families.family("rank(ts_delta(eps, 126))", "EUR") not in dead
    # One pass anywhere in the region keeps the family alive.
    rows.append({"expression": "rank(ts_delta(eps, 252))", "region": "USA", "failed": False})
    assert families.family("rank(ts_delta(eps, 126))", "USA") not in families._dead(rows)


def test_errors_that_would_repeat() -> None:
    assert errored_for_good('Attempted to use unknown variable "fnd99"')
    assert errored_for_good("Invalid number of inputs : 1, should be exactly 2 input(s)")
    assert not errored_for_good("Simulation timed out")
    assert not errored_for_good("Too many concurrent simulations, try again later")
    assert not errored_for_good("Internal server error")
