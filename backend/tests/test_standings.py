"""Competition standings: one reading per hour unless the rank moved, read back oldest first."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from alpha_harness.db.models import CompetitionStanding
from alpha_harness.db.sqlite import Database
from alpha_harness.standings import history, ongoing, record


def test_readings_are_kept_and_read_back(tmp_path: Any) -> None:
    async def body() -> list[tuple[int | None, int | None]]:
        db = Database(tmp_path / "h.db")
        await db.create_all()
        assert await record(db, {"C1": {"rank": 900, "alphas": 3}}) == 1
        # Same reading within the hour: nothing new.
        assert await record(db, {"C1": {"rank": 900, "alphas": 3}}) == 0
        # The rank moved within the hour: the last reading is updated, not duplicated.
        assert await record(db, {"C1": {"rank": 850, "alphas": 4}}) == 1
        async with db.session() as session:
            row = await session.get(CompetitionStanding, 1)
            assert row is not None
            row.at -= timedelta(hours=2)
            await session.commit()
        assert await record(db, {"C1": {"rank": 700, "alphas": 6}, "C2": {}}) == 1
        found = await history(db, ["C1", "C2"])
        assert found["C2"] == []
        return [(p.rank, p.alphas) for p in found["C1"]]

    assert asyncio.run(body()) == [(850, 4), (700, 6)]


def test_ongoing_reads_brain_dates() -> None:
    now = datetime(2026, 10, 20, tzinfo=UTC)
    live = {"startDate": "2026-10-01T00:00:00-04:00", "endDate": "2026-11-01T00:00:00"}
    assert ongoing(live, now)
    assert not ongoing({"startDate": "2026-11-02T00:00:00Z", "endDate": "2026-12-01"}, now)
    assert not ongoing({}, now)
