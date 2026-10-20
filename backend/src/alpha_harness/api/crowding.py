"""Crowding history: which datasets and fields are filling up, and how fast."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from ..crowding import history
from ..schemas import Out
from .deps import State

router = APIRouter(prefix="/api/crowding", tags=["crowding"])


class DatasetTrend(Out):
    dataset_id: str
    alpha_count: int | None
    user_count: int | None
    field_count: int | None
    pyramid_multiplier: float | None
    themes: str | None
    as_of: date
    since: date | None
    alpha_growth: int | None
    user_growth: int | None
    alpha_growth_per_day: float | None


class FieldTrend(Out):
    field_id: str
    dataset_id: str | None
    alpha_count: int | None
    user_count: int | None
    as_of: date | None
    since: date | None
    alpha_growth: int | None
    user_growth: int | None


class Scope(Out):
    instrument_type: str = "EQUITY"
    region: str
    delay: int
    universe: str
    days: int = 7
    limit: int = history.DEFAULT_LIMIT


@router.get("/days")
async def snapshot_days(state: State) -> list[date]:
    """Every day a crowding snapshot exists for."""
    return await history.history_days(state.catalog)


@router.get("/datasets")
async def datasets(state: State, scope: Annotated[Scope, Query()]) -> list[DatasetTrend]:
    """Datasets in one market, fastest-growing first over ``days``."""
    rows = await history.dataset_trends(
        state.catalog,
        instrument_type=scope.instrument_type,
        region=scope.region,
        delay=scope.delay,
        universe=scope.universe,
        days=scope.days,
        limit=scope.limit,
    )
    return [DatasetTrend.model_validate(r) for r in rows]


@router.get("/fields")
async def fields(
    state: State,
    scope: Annotated[Scope, Query()],
    dataset_id: Annotated[str | None, Query(alias="datasetId")] = None,
) -> list[FieldTrend]:
    """Fields in one market (optionally one dataset), fastest-growing first over ``days``."""
    rows = await history.field_trends(
        state.catalog,
        instrument_type=scope.instrument_type,
        region=scope.region,
        delay=scope.delay,
        universe=scope.universe,
        days=scope.days,
        dataset_id=dataset_id,
        limit=scope.limit,
    )
    return [FieldTrend.model_validate(r) for r in rows]
