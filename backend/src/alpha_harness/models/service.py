"""The models as the app uses them: trained in the background, kept on disk, asked anywhere.

One set of models lives in ``<data dir>/models``. Training reads the whole vault and the
synced catalog, runs off the event loop, and swaps the new set in only when it is complete.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from .features import FieldInfo, read_expression
from .train import ModelSet, train_all

if TYPE_CHECKING:
    from pathlib import Path

    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

#: What training reads of each Alpha.
COLUMNS = (
    "alpha_id, expression, sim_type, region, delay, universe, neutralization, decay, "
    "truncation, sharpe, fitness, turnover, checks, classifications, simulation_mode, "
    "date_created"
)


async def field_infos(catalog: Catalog, expressions: list[str | None]) -> dict[str, FieldInfo]:
    """Dataset, category and crowding of every field the expressions read."""
    wanted: set[str] = set()
    for expression in expressions:
        wanted.update(read_expression(expression).fields)
    if not wanted:
        return {}
    rows = await catalog.query(
        "SELECT field_id, any_value(dataset_id) AS dataset, any_value(category_id) AS category, "
        "max(alpha_count) AS alphas, max(user_count) AS users "
        "FROM data_field WHERE field_id IN (SELECT unnest(?)) GROUP BY field_id",
        [sorted(wanted)],
    )
    return {
        r["field_id"]: FieldInfo(
            dataset=r["dataset"],
            category=r["category"],
            alpha_count=r["alphas"],
            user_count=r["users"],
        )
        for r in rows
    }


class ModelService:
    def __init__(self, catalog: Catalog, folder: Path) -> None:
        self.catalog = catalog
        self.folder = folder
        self.models: ModelSet | None = None
        self._loaded = False
        #: ``(done, total, target)`` while training, for the screen.
        self.progress: tuple[int, int, str] | None = None

    async def current(self) -> ModelSet | None:
        if not self._loaded:
            self.models = await asyncio.to_thread(ModelSet.load, self.folder)
            self._loaded = True
        return self.models

    async def train(self) -> ModelSet:
        rows = await self.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608 - constant
        fields = await field_infos(self.catalog, [r.get("expression") for r in rows])

        def report(done: int, total: int, target: str) -> None:
            self.progress = (done, total, target)

        try:
            models = await asyncio.to_thread(train_all, rows, fields, progress=report)
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

    async def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        models = await self.current()
        if models is None:
            return [{} for _ in rows]
        fields = await field_infos(self.catalog, [r.get("expression") for r in rows])
        return await asyncio.to_thread(models.predict, rows, fields)
