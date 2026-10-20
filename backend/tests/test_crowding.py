"""Crowding history: snapshots, deltas, trends, and the daily schedule."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from alpha_harness.catalog.sync import SyncTarget
from alpha_harness.crowding import history
from alpha_harness.crowding.daily import DailySync
from alpha_harness.db.duck import Catalog

DAY1 = date(2026, 10, 20)
DAY2 = date(2026, 10, 21)
T1 = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
USA = ("EQUITY", "USA", 1, "TOP3000")


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _open(tmp_path: Any) -> Catalog:
    catalog = Catalog(tmp_path / "catalog.duckdb")
    await catalog.open()
    return catalog


async def _dataset(
    catalog: Catalog,
    dataset_id: str,
    alphas: int,
    users: int,
    at: datetime,
    market: tuple[str, str, int, str] = USA,
) -> None:
    await catalog.execute(
        "INSERT OR REPLACE INTO data_set (dataset_id, user_count, alpha_count, field_count,"
        " instrument_type, region, delay, universe, synced_at) VALUES (?, ?, ?, 10, ?, ?, ?, ?, ?)",
        [dataset_id, users, alphas, *market, at.replace(tzinfo=None)],
    )


async def _field(
    catalog: Catalog, field_id: str, dataset_id: str, alphas: int, users: int, at: datetime
) -> None:
    await catalog.execute(
        "DELETE FROM data_field WHERE field_id = ? AND region = 'USA'", [field_id]
    )
    await catalog.execute(
        "INSERT INTO data_field (field_id, dataset_id, user_count, alpha_count,"
        " instrument_type, region, delay, universe, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [field_id, dataset_id, users, alphas, *USA, at.replace(tzinfo=None)],
    )


def _scope() -> dict[str, Any]:
    return {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}


async def _two_days(catalog: Catalog) -> None:
    await _dataset(catalog, "analyst", 100, 10, T1)
    await _dataset(catalog, "pv", 50, 40, T1)
    await _dataset(catalog, "ra_set", 7, 3, T1, ("EQUITY", "ALL", 1, "TOP3000"))
    await _field(catalog, "est_eps", "analyst", 30, 5, T1)
    await _field(catalog, "est_rev", "analyst", 5, 2, T1)
    await history.snapshot(catalog, synced_since=T1, day=DAY1)

    # Day 2 refreshes USA only; the region-agnostic market is not re-synced.
    await _dataset(catalog, "analyst", 200, 25, T2)
    await _dataset(catalog, "pv", 55, 41, T2)
    await _field(catalog, "est_eps", "analyst", 80, 12, T2)
    await _field(catalog, "est_rev", "analyst", 5, 2, T2)
    await history.snapshot(catalog, synced_since=T2, day=DAY2)


def test_field_rows_are_stored_only_when_counts_move(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        day2 = await catalog.query(
            "SELECT field_id FROM field_snapshot WHERE snapshot_date = ?", [DAY2]
        )
        assert [r["field_id"] for r in day2] == ["est_eps"]
        await catalog.close()

    run(body())


def test_snapshot_skips_markets_the_sync_did_not_refresh(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        regions = await catalog.query(
            "SELECT DISTINCT region FROM dataset_snapshot WHERE snapshot_date = ?", [DAY2]
        )
        assert [r["region"] for r in regions] == ["USA"]
        await catalog.close()

    run(body())


def test_dataset_trends_rank_by_growth(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        rows = await history.dataset_trends(catalog, **_scope(), days=1)
        assert [(r["dataset_id"], r["alpha_growth"], r["user_growth"]) for r in rows] == [
            ("analyst", 100, 15),
            ("pv", 5, 1),
        ]
        assert rows[0]["since"] == DAY1 and rows[0]["as_of"] == DAY2
        assert rows[0]["alpha_growth_per_day"] == pytest.approx(100.0)
        await catalog.close()

    run(body())


def test_field_trends_read_through_unchanged_days(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        rows = await history.field_trends(catalog, **_scope(), days=1, dataset_id="analyst")
        got = {r["field_id"]: (r["alpha_count"], r["alpha_growth"]) for r in rows}
        # est_rev has no day-2 row, yet still reads its latest count and zero growth.
        assert got == {"est_eps": (80, 50), "est_rev": (5, 0)}
        await catalog.close()

    run(body())


def test_same_day_resync_replaces_the_days_rows(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        later = T2 + timedelta(hours=3)
        await _field(catalog, "est_eps", "analyst", 90, 12, later)
        await _field(catalog, "est_rev", "analyst", 5, 2, later)
        await _dataset(catalog, "analyst", 210, 25, later)
        await _dataset(catalog, "pv", 55, 41, later)
        await history.snapshot(catalog, synced_since=later, day=DAY2)
        rows = await history.field_trends(catalog, **_scope(), days=1)
        assert {r["field_id"]: r["alpha_growth"] for r in rows}["est_eps"] == 60
        count = await catalog.scalar(
            "SELECT count(*) FROM dataset_snapshot WHERE snapshot_date = ? AND region = 'USA'",
            [DAY2],
        )
        assert count == 2
        await catalog.close()

    run(body())


class FakeSync:
    def __init__(self) -> None:
        self.started: list[list[SyncTarget]] = []

    def running(self) -> bool:
        return False

    async def start_all(self, targets: list[SyncTarget]) -> dict[str, Any]:
        self.started.append(targets)
        return {}


MARKETS = [
    SyncTarget("EQUITY", "USA", 1, "TOP3000"),
    SyncTarget("EQUITY", "ALL", 1, "TOP3000"),
]


def _daily(catalog: Catalog, sync: FakeSync, *, signed_in: bool = True) -> DailySync:
    async def markets() -> list[SyncTarget]:
        return MARKETS

    daily = DailySync(sync, catalog, markets=markets, signed_in=lambda: signed_in)  # type: ignore[arg-type]
    daily.configure(enabled=True, hour=6, ra_every_days=3)
    return daily


def _local(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0).astimezone()


def test_daily_sync_waits_for_its_hour_and_a_session(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        sync = FakeSync()
        assert await _daily(catalog, sync).tick(_local(DAY1, 5)) is None
        assert await _daily(catalog, sync, signed_in=False).tick(_local(DAY1, 7)) is None
        assert sync.started == []
        await catalog.close()

    run(body())


def test_daily_sync_runs_ordinary_markets_once_a_day(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        sync = FakeSync()
        daily = _daily(catalog, sync)
        # Ordinary markets were snapshotted on DAY2: nothing ordinary is due that day, and the
        # region-agnostic market (last DAY1) is not due until three days on.
        assert await daily.tick(_local(DAY2, 9)) is None
        # The next day the ordinary markets are due, region ALL left out.
        assert await daily.tick(_local(DAY2 + timedelta(days=1), 9)) == "ordinary"
        assert [t.region for t in sync.started[-1]] == ["USA"]
        await catalog.close()

    run(body())


def test_daily_sync_runs_region_agnostic_every_few_days(tmp_path: Any) -> None:
    async def body() -> None:
        catalog = await _open(tmp_path)
        await _two_days(catalog)
        sync = FakeSync()
        daily = _daily(catalog, sync)
        # Pretend the ordinary markets are current on DAY1 + 3.
        later = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)
        await _dataset(catalog, "analyst", 300, 30, later)
        await history.snapshot(catalog, synced_since=later, day=DAY1 + timedelta(days=3))
        assert await daily.tick(_local(DAY1 + timedelta(days=3), 9)) == "agnostic"
        assert [t.region for t in sync.started[-1]] == ["ALL"]
        await catalog.close()

    run(body())
