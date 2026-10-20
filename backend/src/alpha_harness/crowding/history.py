"""Crowding history: dated snapshots of how busy each dataset and field is.

The catalog tables hold only the counts of the last sync. Prod correlation is about where
other consultants are working, and the signal that matters is *movement*: a dataset that
gained 2,000 Alphas this week is filling up even if it is still mid-table. So every sync
leaves a dated snapshot behind, and :func:`dataset_trends` / :func:`field_trends` read growth
over any window.

Storage: one row per dataset per snapshot day (a few thousand rows a day), but a field row
only when its counts differ from that field's previous snapshot, because a market holds
~85k fields and most do not move on a given day. Reading a field "as of" a day is therefore
"its latest row on or before that day".

Only markets the sync actually refreshed are snapshotted (rows with ``synced_at`` at or after
the run's start), so a region-agnostic-only sync never re-stamps stale ordinary markets.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from ..db.duck import Catalog

log = structlog.get_logger(__name__)

#: Rows the trend reads return unless asked for fewer.
DEFAULT_LIMIT = 200


def today() -> date:
    """The snapshot day: the machine's own calendar day, which is the day the user lives in."""
    return datetime.now().astimezone().date()


# -- writing -------------------------------------------------------------------------------

_DELETE_DATASETS = """
DELETE FROM dataset_snapshot AS s
WHERE s.snapshot_date = ?
  AND EXISTS (
    SELECT 1 FROM data_set d
    WHERE d.synced_at >= ?
      AND d.instrument_type = s.instrument_type AND d.region = s.region
      AND d.delay = s.delay AND d.universe = s.universe
  )
"""

_INSERT_DATASETS = """
INSERT INTO dataset_snapshot
SELECT CAST(? AS DATE), dataset_id, instrument_type, region, delay, universe,
       user_count, alpha_count, field_count, pyramid_multiplier, themes
FROM data_set
WHERE synced_at >= ?
"""

# Same-day re-syncs replace the day's rows rather than stacking on them, so the comparison
# below is always against the previous *day*.
_DELETE_FIELDS = """
DELETE FROM field_snapshot AS s
WHERE s.snapshot_date = ?
  AND EXISTS (
    SELECT 1 FROM data_field f
    WHERE f.synced_at >= ?
      AND f.instrument_type = s.instrument_type AND f.region = s.region
      AND f.delay = s.delay AND f.universe = s.universe
  )
"""

_INSERT_FIELDS = """
INSERT INTO field_snapshot
WITH cur AS (
    SELECT field_id, instrument_type, region, delay, universe,
           any_value(dataset_id) AS dataset_id,
           max(user_count) AS user_count,
           max(alpha_count) AS alpha_count
    FROM data_field
    WHERE synced_at >= ?
    GROUP BY field_id, instrument_type, region, delay, universe
),
prev AS (
    SELECT field_id, instrument_type, region, delay, universe,
           arg_max(user_count, snapshot_date) AS user_count,
           arg_max(alpha_count, snapshot_date) AS alpha_count
    FROM field_snapshot
    WHERE snapshot_date < ?
    GROUP BY field_id, instrument_type, region, delay, universe
)
SELECT CAST(? AS DATE), c.field_id, c.instrument_type, c.region, c.delay, c.universe,
       c.dataset_id, c.user_count, c.alpha_count
FROM cur c
LEFT JOIN prev p
  ON p.field_id = c.field_id AND p.instrument_type = c.instrument_type
 AND p.region = c.region AND p.delay = c.delay AND p.universe = c.universe
WHERE p.field_id IS NULL
   OR c.user_count IS DISTINCT FROM p.user_count
   OR c.alpha_count IS DISTINCT FROM p.alpha_count
"""


async def snapshot(
    catalog: Catalog, *, synced_since: datetime, day: date | None = None
) -> dict[str, int]:
    """Record today's counts for every market refreshed since ``synced_since``.

    Returns how many dataset and field rows were written. Safe to call twice in a day: the
    second call replaces the first for the markets it covers.
    """
    day = day or today()
    since = synced_since.replace(tzinfo=None) if synced_since.tzinfo else synced_since
    await catalog.execute(_DELETE_DATASETS, [day, since])
    await catalog.execute(_INSERT_DATASETS, [day, since])
    await catalog.execute(_DELETE_FIELDS, [day, since])
    await catalog.execute(_INSERT_FIELDS, [since, day, day])
    datasets = int(
        await catalog.scalar("SELECT count(*) FROM dataset_snapshot WHERE snapshot_date = ?", [day])
        or 0
    )
    fields = int(
        await catalog.scalar("SELECT count(*) FROM field_snapshot WHERE snapshot_date = ?", [day])
        or 0
    )
    log.info("crowding.snapshot", day=day.isoformat(), datasets=datasets, fields=fields)
    return {"datasets": datasets, "fields": fields}


# -- reading -------------------------------------------------------------------------------

_DATASET_TRENDS = """
WITH s AS (
    SELECT * FROM dataset_snapshot
    WHERE instrument_type = ? AND region = ? AND delay = ? AND universe = ?
),
last_day AS (SELECT max(snapshot_date) AS d FROM s),
now_ AS (SELECT s.* FROM s, last_day WHERE s.snapshot_date = last_day.d),
then_ AS (
    SELECT dataset_id,
           arg_max(alpha_count, snapshot_date) AS alpha_count,
           arg_max(user_count, snapshot_date) AS user_count,
           max(snapshot_date) AS since
    FROM s, last_day
    WHERE s.snapshot_date <= last_day.d - CAST(? AS INTEGER)
    GROUP BY dataset_id
),
first_ AS (
    SELECT dataset_id,
           arg_min(alpha_count, snapshot_date) AS alpha_count,
           arg_min(user_count, snapshot_date) AS user_count,
           min(snapshot_date) AS since
    FROM s
    GROUP BY dataset_id
)
SELECT n.dataset_id, n.alpha_count, n.user_count, n.field_count, n.pyramid_multiplier,
       n.themes, n.snapshot_date AS as_of,
       coalesce(t.since, f.since) AS since,
       n.alpha_count - coalesce(t.alpha_count, f.alpha_count) AS alpha_growth,
       n.user_count - coalesce(t.user_count, f.user_count) AS user_growth,
       (n.alpha_count - coalesce(t.alpha_count, f.alpha_count))
           / greatest(1, n.snapshot_date - coalesce(t.since, f.since)) AS alpha_growth_per_day
FROM now_ n
LEFT JOIN then_ t USING (dataset_id)
LEFT JOIN first_ f USING (dataset_id)
ORDER BY alpha_growth DESC NULLS LAST, n.alpha_count DESC NULLS LAST
LIMIT ?
"""

_FIELD_TRENDS = """
WITH s AS (
    SELECT * FROM field_snapshot
    WHERE instrument_type = ? AND region = ? AND delay = ? AND universe = ?
),
last_day AS (SELECT max(snapshot_date) AS d FROM s),
cur AS (
    SELECT field_id,
           any_value(dataset_id) AS dataset_id,
           arg_max(alpha_count, snapshot_date) AS alpha_count,
           arg_max(user_count, snapshot_date) AS user_count
    FROM s
    GROUP BY field_id
),
then_ AS (
    SELECT field_id,
           arg_max(alpha_count, snapshot_date) AS alpha_count,
           arg_max(user_count, snapshot_date) AS user_count,
           max(snapshot_date) AS since
    FROM s, last_day
    WHERE s.snapshot_date <= last_day.d - CAST(? AS INTEGER)
    GROUP BY field_id
),
first_ AS (
    SELECT field_id,
           arg_min(alpha_count, snapshot_date) AS alpha_count,
           arg_min(user_count, snapshot_date) AS user_count,
           min(snapshot_date) AS since
    FROM s
    GROUP BY field_id
)
SELECT c.field_id, c.dataset_id, c.alpha_count, c.user_count,
       (SELECT d FROM last_day) AS as_of,
       coalesce(t.since, f.since) AS since,
       c.alpha_count - coalesce(t.alpha_count, f.alpha_count) AS alpha_growth,
       c.user_count - coalesce(t.user_count, f.user_count) AS user_growth
FROM cur c
LEFT JOIN then_ t USING (field_id)
LEFT JOIN first_ f USING (field_id)
WHERE CAST(? AS VARCHAR) IS NULL OR c.dataset_id = CAST(? AS VARCHAR)
ORDER BY alpha_growth DESC NULLS LAST, c.alpha_count DESC NULLS LAST
LIMIT ?
"""


async def dataset_trends(
    catalog: Catalog,
    *,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    days: int = 7,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Each dataset's counts at the latest snapshot and their growth over ``days``.

    Where history is shorter than ``days``, growth is measured from the first snapshot and
    ``since`` says from when. Fastest-growing first.
    """
    return await catalog.query(
        _DATASET_TRENDS, [instrument_type, region, delay, universe, days, limit]
    )


async def field_trends(
    catalog: Catalog,
    *,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    days: int = 7,
    dataset_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Each field's latest counts and growth over ``days``, optionally within one dataset."""
    return await catalog.query(
        _FIELD_TRENDS,
        [instrument_type, region, delay, universe, days, dataset_id, dataset_id, limit],
    )


async def history_days(catalog: Catalog) -> list[date]:
    """Every day a snapshot was taken, oldest first."""
    rows = await catalog.query(
        "SELECT DISTINCT snapshot_date AS d FROM dataset_snapshot ORDER BY d"
    )
    return [row["d"] for row in rows]
