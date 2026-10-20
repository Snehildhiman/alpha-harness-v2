"""Every EQUITY market the account can simulate, from BRAIN's own settings schema."""

from typing import TYPE_CHECKING, Any

from ..brain.settings_schema import valid_values
from .sync import SyncTarget

if TYPE_CHECKING:
    from ..account import PlatformMetadata


async def markets(metadata: PlatformMetadata) -> list[SyncTarget]:
    """Every EQUITY market, region ``ALL`` included.

    A new region or universe is picked up without a code change. Callers split region
    ``ALL`` (the region-agnostic market) from the ordinary ones: it is its own, much slower,
    download.
    """
    schema = await metadata.cached_settings_schema() or await metadata.refresh_metadata()
    # EQUITY only, the one instrument type the Data Explorer offers.
    base: dict[str, Any] = {"instrumentType": "EQUITY"}
    return [
        SyncTarget(instrument_type="EQUITY", region=region, delay=int(delay), universe=universe)
        for region in valid_values(schema, "region", base)
        for delay in valid_values(schema, "delay", {**base, "region": region})
        for universe in valid_values(schema, "universe", {**base, "region": region, "delay": delay})
    ]
