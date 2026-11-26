"""
services/asset_specs.py — equipment specifications from real data only.

WHY THIS EXISTS
---------------
The Describe agents used to stamp every new node with specifications invented
from the tag prefix: any `PT-` became an "Emerson Rosemount 3051S, 0-16 bar,
Cabinet PNL-01 / Rack 01 / Slot 01", any `PCV-` a Fisher globe valve. On a
brownfield retrofit of an existing plant that is fabricated data presented as
fact, and it flowed straight into the YMPL export.

The rule now, in priority order:

1. `asset_inventory` — the asset-inventory record for this tag, when inventory
   access is enabled (see services.hierarchy.inventory_enabled).
2. `stated` — specifications the engineer gave in the request, passed through
   by the agent.
3. `unspecified` — nothing is invented. The node carries
   `spec_status: "unspecified"` so reviewers and exports can see the gap.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: After one failed inventory call, stop trying for this process: an
#: unreachable cluster costs a connection timeout per node otherwise.
_inventory_down = False


def _inventory_lookup(tag: str) -> dict | None:
    global _inventory_down
    if _inventory_down or not tag:
        return None
    from services.hierarchy import inventory_enabled
    if not inventory_enabled():
        return None
    try:
        from adapters.mongodb import fetch_asset_by_tag
        return fetch_asset_by_tag(tag)
    except Exception as exc:                       # pragma: no cover - network
        logger.warning("asset inventory unavailable, not retrying: %s", exc)
        _inventory_down = True
        return None


def resolve(tag: str, stated: dict | None = None,
            stated_config: dict | None = None, lookup=None) -> dict:
    """The specification fields to store on a node's extra_json.

    `lookup` is injectable for tests; it defaults to the asset inventory.
    Returns a dict containing `spec_status` and, when known,
    `specifications` / `instrument_config` / `asset_id` / `location`.
    """
    record = (lookup or _inventory_lookup)(tag)
    if record:
        out = {"spec_status": "asset_inventory",
               "specifications": record.get("specifications") or {}}
        for key in ("instrument_config", "asset_id", "location"):
            if record.get(key):
                out[key] = record[key]
        return out
    if stated or stated_config:
        out = {"spec_status": "stated"}
        if stated:
            out["specifications"] = stated
        if stated_config:
            out["instrument_config"] = stated_config
        return out
    return {"spec_status": "unspecified"}
