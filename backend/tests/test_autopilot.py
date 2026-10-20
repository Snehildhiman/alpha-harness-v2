"""Autopilot: counts what it queued in the last day, and waits while its last task runs."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from alpha_harness.autopilot import NAME, Autopilot
from alpha_harness.db.models import Study, StudyStatus
from alpha_harness.db.sqlite import Database


def study(name: str, template: str, trials: int, status: str, at: datetime) -> Study:
    return Study(
        name=name,
        template_name=template,
        template_source="rank(close)",
        max_trials=trials,
        status=status,
        created_at=at,
    )


def test_budget_and_busy(tmp_path: Any) -> None:
    async def body() -> tuple[tuple[int, bool], tuple[int, bool], str]:
        db = Database(tmp_path / "h.db")
        await db.create_all()
        now = datetime.now(UTC)
        async with db.session() as session:
            session.add_all(
                [
                    study("a", f"{NAME} · 20 transplants", 20, StudyStatus.COMPLETE, now),
                    study("b", f"{NAME} · 5", 5, StudyStatus.COMPLETE, now - timedelta(days=2)),
                    study("c", "Repair · A1", 30, StudyStatus.RUNNING, now),
                ]
            )
            await session.commit()
        pilot = Autopilot(SimpleNamespace(db=db), signed_in=lambda: True)
        idle = await pilot.spent()
        async with db.session() as session:
            session.add(study("d", f"{NAME} · 10", 10, StudyStatus.RUNNING, now))
            await session.commit()
        busy = await pilot.spent()
        return idle, busy, await pilot.tick()

    idle, busy, said = asyncio.run(body())
    assert idle == (20, False)  # the old one and yours do not count
    assert busy == (30, True)
    assert said == "Waiting for its last task to finish."
