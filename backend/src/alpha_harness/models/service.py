"""The models as the app uses them: trained in the background, kept on disk, asked anywhere.

One set of models lives in ``<data dir>/models``. Training reads the whole vault and the
synced catalog, runs off the event loop, and swaps the new set in only when it is complete.
"""

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from ..db.duck import AMONG, packed
from .features import FieldInfo, read_expression
from .train import MIN_LABELS, Gate, ModelSet, gate, train_all

if TYPE_CHECKING:
    from pathlib import Path

    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

#: What training reads of each Alpha.
COLUMNS = (
    "alpha_id, expression, sim_type, region, delay, universe, neutralization, decay, "
    "truncation, sharpe, fitness, turnover, returns, drawdown, margin, long_count, "
    "short_count, checks, classifications, simulation_mode, date_created"
)


async def field_infos(catalog: Catalog, expressions: list[str | None]) -> dict[str, FieldInfo]:
    """Dataset, category and crowding of every field the expressions read."""

    def read() -> set[str]:
        wanted: set[str] = set()
        for expression in expressions:
            wanted.update(read_expression(expression).fields)
        return wanted

    # Off the event loop: parsing thousands of expressions takes most of a second.
    wanted = await asyncio.to_thread(read)
    if not wanted:
        return {}
    rows = await catalog.query(
        "SELECT field_id, any_value(dataset_id) AS dataset, any_value(category_id) AS category, "  # noqa: S608
        "max(alpha_count) AS alphas, max(user_count) AS users "
        f"FROM data_field WHERE field_id IN {AMONG} GROUP BY field_id",
        [packed(sorted(wanted))],
    )
    growth = {
        r["field_id"]: float(r["per_day"])
        for r in await catalog.query(_GROWTH, [packed(sorted(wanted))])
        if r["per_day"] is not None
    }
    return {
        r["field_id"]: FieldInfo(
            dataset=r["dataset"],
            category=r["category"],
            alpha_count=r["alphas"],
            user_count=r["users"],
            alpha_growth=growth.get(r["field_id"]),
        )
        for r in rows
    }


#: Each field's fastest market: new Alphas a day between its first and last snapshot of the
#: past month. Snapshots keep a row only when a count changed, so two rows mean it moved.
_GROWTH = f"""
SELECT field_id, max(per_day) AS per_day FROM (
    SELECT field_id,
           (arg_max(alpha_count, snapshot_date) - arg_min(alpha_count, snapshot_date))
             / greatest(date_diff('day', min(snapshot_date), max(snapshot_date)), 1) AS per_day
    FROM field_snapshot
    WHERE field_id IN {AMONG} AND snapshot_date >= current_date - 30
    GROUP BY field_id, instrument_type, region, delay, universe
    HAVING count(*) >= 2
) GROUP BY field_id
"""  # noqa: S608


#: Seconds between looks for enough new results to retrain on.
AUTO_SECONDS = 600.0
#: New Alphas, or Alphas re-checked since the last training, that earn a retrain.
AUTO_NEW = 100


class ModelService:
    def __init__(self, catalog: Catalog, folder: Path) -> None:
        self.catalog = catalog
        self.folder = folder
        self.models: ModelSet | None = None
        self._loaded = False
        #: ``(done, total, target)`` while training, for the screen.
        self.progress: tuple[int, int, str] | None = None
        #: Retrain by itself as results arrive (Settings).
        self.auto = True
        #: The last automatic retrain's verdict, and when.
        self.last_gate: tuple[str, Gate] | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    # -- the automatic loop --------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="models-auto")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(AUTO_SECONDS)
            try:
                await self.tick()
            # One failed retrain must not end learning for the rest of the session.
            except Exception:
                log.warning("models.auto_failed", exc_info=True)

    async def new_since_training(self) -> int:
        """Alphas added, plus Alphas whose checks were re-run, since the models were trained."""
        models = await self.current()
        total = int(await self.catalog.scalar("SELECT count(*) FROM alpha") or 0)
        if models is None:
            return total
        cutoff = datetime.fromisoformat(models.trained_at).astimezone(UTC).replace(tzinfo=None)
        rechecked = int(
            await self.catalog.scalar("SELECT count(*) FROM alpha WHERE checks_at > ?", [cutoff])
            or 0
        )
        return max(0, total - models.alphas) + rechecked

    async def tick(self) -> str | None:
        """Retrain if enough has changed. Returns what happened, for logs and tests."""
        if not self.auto or self._lock.locked():
            return None
        models = await self.current()
        fresh = await self.new_since_training()
        if models is None and fresh < MIN_LABELS:
            return None
        if models is not None and fresh < AUTO_NEW:
            return None
        await self.train(gated=True)
        return "trained"

    async def current(self) -> ModelSet | None:
        if not self._loaded:
            self.models = await asyncio.to_thread(ModelSet.load, self.folder)
            self._loaded = True
        return self.models

    async def train(self, *, gated: bool = False) -> ModelSet:
        """Train on the whole vault. ``gated``: replace the models in use only if the new set
        does at least as well on Alphas the old one never saw (see :func:`.train.gate`)."""
        async with self._lock:
            rows = await self.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608
            fields = await field_infos(self.catalog, [r.get("expression") for r in rows])

            def report(done: int, total: int, target: str) -> None:
                self.progress = (done, total, target)

            old = await self.current()
            try:
                models = await asyncio.to_thread(train_all, rows, fields, progress=report)
                if gated and old is not None:
                    by_id = {str(r.get("alpha_id")): r for r in rows}
                    verdict = await asyncio.to_thread(gate, old, models, by_id, fields)
                    self.last_gate = (datetime.now(UTC).isoformat(timespec="seconds"), verdict)
                    log.info("models.gate", accepted=verdict.accepted, reason=verdict.reason)
                    self.record(models, accepted=verdict.accepted)
                    if not verdict.accepted:
                        return old
                else:
                    self.record(models, accepted=True)
                await asyncio.to_thread(models.save, self.folder)
            finally:
                self.progress = None
            self.models, self._loaded = models, True
            log.info(
                "models.trained",
                alphas=models.alphas,
                targets=sum(r.trained for r in models.reports),
            )
            return models

    @property
    def history_path(self) -> Path:
        # Beside the models folder, which is swapped whole on every save.
        return self.folder.parent / "models-history.jsonl"

    def record(self, models: ModelSet, *, accepted: bool) -> None:
        """One line per training: each target's test score, so accuracy can be followed."""
        line = {
            "trainedAt": models.trained_at,
            "alphas": models.alphas,
            "accepted": accepted,
            "targets": {
                r.target: {"label": r.label, "kind": r.kind, "n": r.n_test, **r.metrics}
                for r in models.reports
                if r.trained
            },
        }
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(line) + "\n")
        except OSError:
            log.warning("models.history_unwritten", exc_info=True)

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    async def predict_post(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        """For simulated Alphas: the correlations expected from what BRAIN already reported
        (Sharpe, turnover, margin, long/short counts...) besides the expression itself."""
        models = await self.current()
        if models is None:
            return [{} for _ in rows]
        fields = await field_infos(self.catalog, [r.get("expression") for r in rows])
        return await asyncio.to_thread(models.predict_post, rows, fields)

    async def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        models = await self.current()
        if models is None:
            return [{} for _ in rows]
        fields = await field_infos(self.catalog, [r.get("expression") for r in rows])
        return await asyncio.to_thread(models.predict, rows, fields)
