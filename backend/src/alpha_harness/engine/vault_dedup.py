"""Duplicates of Alphas already in the vault, caught before they are simulated.

The engine's own dedup memory only knows what this app sent. The vault also holds every Alpha
imported from BRAIN — tens of thousands simulated by hand or by other tools — and re-sending
one of those spends a simulation on a result that already exists.

An Alpha matches when its canonical expression (:mod:`alpha_harness.canon`) and every setting
the vault stores agree: type, instrument, region, universe, delay, neutralization, decay,
truncation, whether a test period was held out, and Full mode (a Quick Alpha cannot stand in
for a Full one). Settings the vault does not store (pasteurization, NaN handling) cannot be
compared, so only requests that leave them at the app's defaults are matched.

The index is built off the event loop (about 0.1 ms an Alpha) and rebuilt when the vault changes.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from ..brain.schemas import FULL_MODE, QUICK_MODE
from ..canon import canonical

if TYPE_CHECKING:
    from ..brain.schemas import SimulationRequest
    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

_COLUMNS = (
    "alpha_id, expression, sim_type, instrument_type, region, universe, delay, neutralization, "
    "decay, truncation, simulation_mode, test_start"
)

Key = tuple[Any, ...]


def _key(
    expression: str | None,
    *,
    sim_type: str | None,
    instrument_type: str | None,
    region: str | None,
    universe: str | None,
    delay: Any,
    neutralization: str | None,
    decay: Any,
    truncation: Any,
    tested: bool,
) -> Key | None:
    code = canonical(expression)
    if not code:
        return None
    try:
        trunc = round(float(truncation), 6) if truncation is not None else None
        return (
            code,
            str(sim_type or "REGULAR").upper(),
            str(instrument_type or "EQUITY").upper(),
            str(region or "").upper(),
            str(universe or "").upper(),
            int(delay) if delay is not None else None,
            str(neutralization or "NONE").upper(),
            int(decay) if decay is not None else 0,
            trunc,
            tested,
        )
    except TypeError, ValueError:
        return None


def row_key(row: dict[str, Any]) -> Key | None:
    """A vault row's key, or ``None`` for one that cannot stand in for a request."""
    if str(row.get("simulation_mode") or FULL_MODE).upper() == QUICK_MODE:
        return None
    return _key(
        row.get("expression"),
        sim_type=row.get("sim_type"),
        instrument_type=row.get("instrument_type"),
        region=row.get("region"),
        universe=row.get("universe"),
        delay=row.get("delay"),
        neutralization=row.get("neutralization"),
        decay=row.get("decay"),
        truncation=row.get("truncation"),
        tested=row.get("test_start") is not None,
    )


def request_key(request: SimulationRequest) -> Key | None:
    """A request's key, or ``None`` when the vault could not tell it apart from a neighbour."""
    s = request.settings
    if s.pasteurization != "ON" or s.nan_handling != "ON" or s.max_trade or s.max_position:
        return None
    expression = request.regular
    if not isinstance(expression, str):
        return None
    return _key(
        expression,
        sim_type=str(request.type),
        instrument_type=s.instrument_type,
        region=s.region,
        universe=s.universe,
        delay=s.delay,
        neutralization=s.neutralization,
        decay=s.decay,
        truncation=s.truncation,
        tested=bool(s.test_period),
    )


def build(rows: list[dict[str, Any]]) -> dict[Key, str]:
    index: dict[Key, str] = {}
    for row in rows:
        key = row_key(row)
        if key is not None:
            index.setdefault(key, str(row["alpha_id"]))
    return index


class VaultIndex:
    """Canonical key → an Alpha already stored with it."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._marker: tuple[str, ...] | None = None
        self._index: dict[Key, str] = {}
        self._lock = asyncio.Lock()

    async def _current(self) -> dict[Key, str]:
        found = await self.catalog.query("SELECT count(*) AS n, max(fetched_at) AS t FROM alpha")
        marker = tuple(str(v) for v in found[0].values()) if found else None
        async with self._lock:
            if marker != self._marker:
                rows = await self.catalog.query(f"SELECT {_COLUMNS} FROM alpha")  # noqa: S608 - constant
                self._index = await asyncio.to_thread(build, rows)
                self._marker = marker
                log.info("vault_dedup.indexed", alphas=len(rows), keys=len(self._index))
            return self._index

    async def find(self, requests: list[SimulationRequest]) -> list[str | None]:
        """The stored Alpha each request would only repeat, or ``None``, in order."""
        keys = [request_key(r) for r in requests]
        if not any(keys):
            return [None] * len(requests)
        index = await self._current()
        return [index.get(k) if k is not None else None for k in keys]
