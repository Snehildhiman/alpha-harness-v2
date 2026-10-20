"""Scorecards: which operators, fields, datasets, lookbacks and settings run hot or cold."""

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from ..models.service import COLUMNS, field_infos
from ..schemas import Out
from ..scorecards import PARTS, Part, Scorecards, build, ranked
from .deps import State

router = APIRouter(prefix="/api/scorecards", tags=["scorecards"])

Metric = Literal[
    "prod_corr",
    "power_pool_corr",
    "self_corr",
    "check:PROD_CORRELATION",
    "check:POWER_POOL_CORRELATION",
    "check:SELF_CORRELATION",
    "sharpe",
    "fitness",
]

_cache: dict[str, Any] = {"key": None, "cards": None}
_lock = asyncio.Lock()


async def _cards(state: State) -> Scorecards:
    marker = await state.catalog.query(
        "SELECT (SELECT count(*) FROM alpha) AS n, (SELECT max(fetched_at) FROM alpha) AS t, "
        "(SELECT max(checks_at) FROM alpha) AS k, (SELECT max(synced_at) FROM data_field) AS c"
    )
    key = tuple(str(v) for v in marker[0].values()) if marker else None
    async with _lock:
        if _cache["key"] != key or _cache["cards"] is None:
            rows = await state.catalog.query(f"SELECT {COLUMNS} FROM alpha")  # noqa: S608 - constant
            fields = await field_infos(state.catalog, [r.get("expression") for r in rows])
            _cache["cards"] = await asyncio.to_thread(build, rows, fields)
            _cache["key"] = key
        return _cache["cards"]


class CardRow(Out):
    name: str
    #: Alphas containing this part, and how many of them carry the metric.
    alphas: int
    measured: int
    mean: float
    #: The mean pulled toward the vault's, so a rarely seen part cannot top the list.
    shrunk: float
    #: Shrunk mean minus the vault's: above zero runs hotter than usual.
    lift: float


class CardPage(Out):
    #: Alphas with at least one metric, and the vault-wide mean of this one.
    alphas: int
    overall: float | None
    overall_alphas: int
    highest: list[CardRow]
    lowest: list[CardRow]


def _row(card: Any, metric: str) -> CardRow:
    n, mean, shrunk, lift = card.metrics[metric]
    return CardRow(
        name=card.name, alphas=card.alphas, measured=n, mean=mean, shrunk=shrunk, lift=lift
    )


@router.get("/parts")
async def parts() -> list[str]:
    return list(PARTS)


@router.get("")
async def scorecards(
    state: State,
    part: Annotated[Part, Query()] = "operator",
    metric: Annotated[Metric, Query()] = "prod_corr",
    min_alphas: Annotated[int, Query(alias="minAlphas", ge=1, le=10_000)] = 20,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> CardPage:
    """One kind of part, highest and lowest on one metric, by shrunk mean."""
    cards = await _cards(state)
    overall = cards.overall.get(metric)
    return CardPage(
        alphas=cards.alphas,
        overall=overall[1] if overall else None,
        overall_alphas=overall[0] if overall else 0,
        highest=[
            _row(c, metric)
            for c in ranked(
                cards, part=part, metric=metric, min_alphas=min_alphas, highest=True, limit=limit
            )
        ],
        lowest=[
            _row(c, metric)
            for c in ranked(
                cards, part=part, metric=metric, min_alphas=min_alphas, highest=False, limit=limit
            )
        ],
    )
