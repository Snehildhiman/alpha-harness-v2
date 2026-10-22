"""The labs plan in bounded rounds on their own thread, and the watchdog sees stalls."""

# ruff: noqa: ARG002 - the fake lab takes the real lab's arguments and needs none of them

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import optuna

from alpha_harness import workers
from alpha_harness.brain.schemas import SimulationRequest, SimulationSettings
from alpha_harness.labs import scheduler


class _SlowLab:
    """Every point costs 50 ms, like a large task's optimizer."""

    def field_choices(self, space: dict[str, Any]) -> dict[str, list[str]]:
        return {}

    def first_pass(self, space: dict[str, Any], field_id: str) -> dict[str, Any]:
        return {}

    def draw(self, trial: Any, run: Any, choices: Any) -> tuple[dict[str, Any], SimulationRequest]:
        time.sleep(0.05)
        x = trial.suggest_int("x", 0, 10**9)
        settings = SimulationSettings(region="USA", delay=1, universe="TOP3000")
        return {"x": x}, SimulationRequest(settings=settings, regular=f"rank(f{x})")


def test_a_round_stops_at_its_time(monkeypatch: Any) -> None:
    monkeypatch.setattr(workers, "PLAN_SECONDS", 0.3)
    optuna.logging.set_verbosity(optuna.logging.ERROR)
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler())
    run = SimpleNamespace(space={})
    started = time.monotonic()
    picked = scheduler.ask_points(study, _SlowLab(), run, 100, {}, [])  # type: ignore[arg-type]
    took = time.monotonic() - started
    assert 1 <= len(picked) < 100
    assert took < 1.0


def test_labs_share_one_thread() -> None:
    async def go() -> set[str]:
        import threading

        names = await asyncio.gather(
            *(workers.in_labs(lambda: threading.current_thread().name) for _ in range(5))
        )
        return set(names)

    assert len(asyncio.run(go())) == 1


def test_watchdog_reports_a_stall() -> None:
    async def go() -> list[dict[str, Any]]:
        dog = workers.Watchdog()
        dog.start()
        await asyncio.sleep(0.3)
        time.sleep(2.6)  # noqa: ASYNC251 - the stall under test
        await asyncio.sleep(0.7)
        await dog.stop()
        return list(dog.stalls)

    stalls = asyncio.run(go())
    assert stalls
    assert stalls[0]["seconds"] >= 2.0
