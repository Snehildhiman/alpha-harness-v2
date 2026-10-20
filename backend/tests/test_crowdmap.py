"""The crowd floor: a lower bound on prod correlation from Alphas BRAIN already scored."""

import math
from datetime import date, timedelta

import numpy as np

from alpha_harness.crowding.crowdmap import bound, floors, landmarks_of


def test_bound_is_the_triangle_inequality_on_angles() -> None:
    assert bound(1.0, 0.8) == 0.8
    assert math.isclose(bound(0.9, 0.9), 0.81 - 0.19, abs_tol=1e-9)
    assert bound(0.5, 0.5) < 0  # far apart, nothing is implied


def test_floor_finds_the_crowded_alpha_a_candidate_sits_next_to() -> None:
    rng = np.random.default_rng(0)
    days = 1200
    crowd = rng.normal(size=days)
    crowded = crowd + 0.2 * rng.normal(size=days)  # BRAIN said its prod correlation is 0.95
    near = crowd + 0.25 * rng.normal(size=days)  # a new Alpha built the same way
    far = rng.normal(size=days)  # an unrelated new Alpha
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(days)]
    grid = (["L", "near", "far"], dates, np.column_stack([crowded, near, far]))
    got = floors(grid, ["near", "far"], {"L": 0.95})
    assert got["near"].via == "L"
    assert got["near"].value is not None and got["near"].value > 0.7
    assert got["far"].value is not None and got["far"].value < 0.1


def test_landmarks_are_scored_or_submitted_alphas() -> None:
    rows = [
        {
            "alpha_id": "a",
            "region": "USA",
            "status": "UNSUBMITTED",
            "checks": '[{"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.88}]',
        },
        {
            "alpha_id": "b",
            "region": "USA",
            "status": "UNSUBMITTED",
            "checks": '[{"name": "PROD_CORRELATION", "result": "PASS", "value": 0.3}]',
        },
        {"alpha_id": "c", "region": "EUR", "status": "ACTIVE", "checks": None},
    ]
    assert landmarks_of(rows) == {"USA": {"a": 0.88}, "EUR": {"c": 1.0}}


def test_an_ra_family_floor_is_its_second_best_region() -> None:
    from alpha_harness.api.separation import _family_floor
    from alpha_harness.crowding.crowdmap import Floor

    kids = [{"alpha_id": "u"}, {"alpha_id": "e"}, {"alpha_id": "a"}]
    found = {"u": Floor(0.3), "e": Floor(0.75), "a": Floor(0.9)}
    # Two regions must pass: the best is 0.3, the second best 0.75, so the family is crowded.
    assert _family_floor(kids, found).value == 0.75
    assert _family_floor(kids[:1], found).value is None
