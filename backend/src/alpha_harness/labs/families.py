"""Alpha families: one expression shape with its numbers taken out, per region.

``rank(ts_delta(eps, 21))`` and ``rank(ts_delta(eps, 63))`` are one family. Two uses:

* **Dead families.** A family the vault holds :data:`MIN_FAILS` times or more in a region,
  every one failing a check and none passing, is not worth another lookback: the labs skip
  it there. Repair does not, because its variants are small changes on purpose.
* **Diversity.** A round sends at most :data:`PER_ROUND` Alphas of one family, so a round is
  spread over different ideas rather than spent on near-copies; near-copies only fill a
  round that has nothing else to send.

The index is read off the event loop and rebuilt only when the vault changes.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import structlog

from ..canon import canonical

if TYPE_CHECKING:
    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

#: Failures, with no pass, that mark a family dead in a region.
MIN_FAILS = 4
#: Alphas of one family a round sends before it sends near-copies.
PER_ROUND = 2

_NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?")

Family = tuple[str, str]


def skeleton(expression: str | None) -> str:
    """The expression with every number replaced by ``#``."""
    code = canonical(expression) or ""
    return _NUMBER.sub("#", code)


def family(expression: str | None, region: str | None) -> Family:
    return (skeleton(expression), str(region or "").upper())


def _dead(rows: list[dict[str, object]]) -> frozenset[Family]:
    fails: dict[Family, int] = {}
    passed: set[Family] = set()
    for row in rows:
        key = family(str(row["expression"] or ""), str(row["region"] or ""))
        if row["failed"]:
            fails[key] = fails.get(key, 0) + 1
        else:
            passed.add(key)
    return frozenset(k for k, n in fails.items() if n >= MIN_FAILS and k not in passed)


_cache: dict[str, object] = {"marker": None, "dead": frozenset()}
_lock = asyncio.Lock()


async def dead(catalog: Catalog) -> frozenset[Family]:
    """Families that failed in a region again and again and never passed there."""
    found = await catalog.query("SELECT count(*) AS n, max(fetched_at) AS t FROM alpha")
    marker = tuple(str(v) for v in found[0].values()) if found else None
    async with _lock:
        if marker != _cache["marker"]:
            rows = await catalog.query(
                "SELECT expression, region, "
                "coalesce(checks LIKE '%\"FAIL\"%', true) AS failed FROM alpha "
                "WHERE expression IS NOT NULL AND coalesce(sim_type, 'REGULAR') = 'REGULAR' "
                "AND checks IS NOT NULL"
            )
            _cache["dead"] = await asyncio.to_thread(_dead, rows)
            _cache["marker"] = marker
            log.info("families.indexed", alphas=len(rows), dead=len(_cache["dead"]))  # type: ignore[arg-type]
        return _cache["dead"]  # type: ignore[return-value]
