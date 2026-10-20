"""Transplants: a passing Alpha offered in each downloaded region it has not run in."""

from alpha_harness.repair.transplant import ran_in, target_universe, transplants

MARKETS = {
    ("USA", 1): {"TOP3000": frozenset({"close", "volume", "est_eps"})},
    ("EUR", 1): {"TOP2500": frozenset({"close", "volume"}), "TOP1200": frozenset({"close"})},
    ("ASI", 1): {"MINVOL1M": frozenset({"close", "volume", "est_eps"})},
    ("CHN", 1): {"TOP2000U": frozenset({"close", "volume", "est_eps"})},
    ("EUR", 0): {"TOP2500": frozenset({"close", "volume", "est_eps"})},
}
KNOWN = frozenset({"close", "volume", "est_eps"})


def source(expression: str, **over: object) -> dict[str, object]:
    return {
        "alpha_id": "A1",
        "expression": expression,
        "region": "USA",
        "universe": "TOP3000",
        "delay": 1,
        "neutralization": "SUBINDUSTRY",
        "decay": 4,
        "truncation": 0.08,
    } | over


def test_regions_that_carry_every_field_and_have_not_run_it() -> None:
    found = transplants([source("rank(est_eps / close)")], MARKETS, {}, known_fields=KNOWN)
    # EUR lacks est_eps; delay 0 is another market; USA is home.
    assert [(t.region, t.universe) for t in found] == [("ASI", "MINVOL1M"), ("CHN", "TOP2000U")]
    assert found[0].settings["neutralization"] == "SUBINDUSTRY"
    assert found[0].settings["region"] == "ASI"


def test_already_ran_there_in_any_spelling_is_skipped() -> None:
    ran = ran_in([{"expression": "rank(close/volume)", "region": "EUR", "delay": 1}])
    found = transplants(
        [source("rank(close / volume)"), source("rank(close / volume)", alpha_id="A2")],
        MARKETS,
        ran,
        known_fields=KNOWN,
    )
    # EUR already ran; the second source is the same Alpha, so nothing twice.
    assert sorted(t.region for t in found) == ["ASI", "CHN"]


def test_universe_keeps_its_size() -> None:
    eur = MARKETS[("EUR", 1)]
    assert target_universe("USA", "TOP3000", "EUR", eur) == "TOP2500"
    assert target_universe("USA", "TOP2000", "EUR", eur) == "TOP1200"
    # A mapped size that is not downloaded is not guessed at.
    assert target_universe("USA", "TOP1000", "EUR", eur) is None
    # An unknown region falls back to its widest download.
    assert target_universe("USA", "TOP3000", "CHN", MARKETS[("CHN", 1)]) == "TOP2000U"


def test_a_power_pool_alpha_stays_power_pool() -> None:
    (first, *_) = transplants(
        [source("rank(close)", power_pool=True)], MARKETS, {}, known_fields=KNOWN
    )
    assert first.power_pool
