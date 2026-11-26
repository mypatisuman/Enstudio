"""
asset_specs.py - P&ID node specifications from real data only.

WHY THIS EXISTS
---------------
The greenfield and brownfield P&ID agents used to stamp every node with
specifications invented from its tag prefix. Any PT- became an "Emerson
Rosemount 3051S, 0.0 - 16.0 bar, Cabinet PNL-100, SN-PT20144"; any PCV- a
"Fisher ET Globe Control Valve, SN-V20189". Those strings were literals in
_build_fallback_greenfield_graph and _build_fallback_brownfield_graph, and
_enrich_nodes_with_bom_metadata carried them into the BOM and the exports.

On a brownfield retrofit of a real plant that is fabricated nameplate data
presented as fact. A reviewer cannot tell an invented serial number from a
real one.

The rule now, in priority order:

1. ``asset_inventory`` - the user's own Assets Table record for this tag,
   loaded from the ``assets`` and ``asset_configurations`` collections.
2. ``stated`` - specifications the engineer gave in the request, passed
   through by the agent.
3. ``unspecified`` - nothing is invented. The node carries
   ``spec_status: "unspecified"`` so the UI, reviewers and exports can see
   the gap instead of reading a plausible lie.

One further provenance is set downstream, not here: ``bom_selection``, when
pid_builder_service._enrich_nodes_with_bom_metadata applies the product this
project's Bill of Materials selected. It never overrides ``asset_inventory``.

Lookup is index-based rather than per-tag network calls: the caller loads the
user's asset resources once per turn (see
brownfield_pid_agent._load_detailed_asset_resources) and hands the index here.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Keys copied from an Assets Table record onto a node's specifications.
_SPEC_KEYS = (
    "tag_number", "asset_name", "manufacturer", "model", "serial_number",
    "calibrated_range", "connected_system", "protocol", "location",
)

UNSPECIFIED = "unspecified"
STATED = "stated"
INVENTORY = "asset_inventory"
BOM_SELECTION = "bom_selection"


def build_index(resources: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Index asset resources by upper-cased tag for O(1) resolution."""
    index: dict[str, dict[str, Any]] = {}
    for r in resources or []:
        tag = str(r.get("tag_number") or "").strip().upper()
        if tag:
            index.setdefault(tag, r)
    return index


def _from_record(record: dict[str, Any]) -> dict[str, Any]:
    specs = {k: record[k] for k in _SPEC_KEYS
             if record.get(k) not in (None, "", "SN-PENDING")}
    out: dict[str, Any] = {"spec_status": INVENTORY, "specifications": specs}

    urv, lrv = record.get("urv"), record.get("lrv")
    units = record.get("pv_units")
    if urv or lrv or units:
        out["instrument_config"] = {
            "hart_identity": {
                "hart_tag": record.get("tag_number", ""),
                "equipment_category": record.get("asset_type", ""),
                "descriptor": record.get("asset_name", ""),
            },
            "pv_mapping": {
                "urv": str(urv or ""),
                "lrv": str(lrv or ""),
                "pv_units": str(units or ""),
            },
        }
    for key in ("location", "asset_type"):
        if record.get(key):
            out.setdefault("meta", {})[key] = record[key]
    return out


def resolve(tag: str,
            stated: dict[str, Any] | None = None,
            stated_config: dict[str, Any] | None = None,
            index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The specification fields to store on a P&ID node.

    Returns a dict always containing ``spec_status`` and, when known,
    ``specifications`` / ``instrument_config``. Never invents a value.
    """
    record = (index or {}).get(str(tag or "").strip().upper())
    if record:
        return _from_record(record)

    if stated or stated_config:
        out: dict[str, Any] = {"spec_status": STATED}
        if stated:
            out["specifications"] = {k: v for k, v in stated.items()
                                     if v not in (None, "")}
        if stated_config:
            out["instrument_config"] = stated_config
        return out

    # Nothing known. The tag itself is not a specification, but it is a fact,
    # so it is the one field carried through.
    return {"spec_status": UNSPECIFIED,
            "specifications": {"tag_number": tag} if tag else {}}


#: Tag prefixes that may fill each package role, per measured-variable letter.
#: A transmitter role accepts PT, PIT or PDT; a control valve role PCV or PV.
def _role_prefixes(letter: str, role: str) -> tuple[str, ...]:
    if role == "transmitter":
        return (letter + "T", letter + "IT", letter + "DT")
    if role == "control_valve":
        return (letter + "CV", letter + "V")
    return ()


def _isa_prefix(tag: str) -> str:
    m = re.match(r"^([A-Z]{1,5})[-_]?\d", tag or "")
    return m.group(1) if m else ""


def match_for_role(index: dict[str, dict[str, Any]], letter: str, role: str,
                   consumed: set[str],
                   category: str = "") -> dict[str, Any] | None:
    """Find an Assets Table record that can fill one package role, so a
    retrofit binds to the device already installed in the plant instead of
    minting a new tag.

    The record's ISA prefix must fit the role -- a pressure transmitter role
    takes PT/PIT/PDT, never a PCV. The previous matcher compared free-text
    asset names by substring, so an asset named just "VALVE" could bind to any
    valve role: a real nameplate on the wrong device, which is worse than an
    honest "unspecified". Among fitting records, one whose type or name shares
    a word with the category is preferred.

    Returns the record (and marks its tag consumed), or None -- which means
    "mint a fresh tag", never "invent this asset's nameplate".
    """
    prefixes = _role_prefixes(letter, role)
    if not prefixes:
        return None
    words = {w for w in re.split(r"\W+", (category or "").upper()) if len(w) > 3}
    fitting = [(tag, r) for tag, r in index.items()
               if tag not in consumed and _isa_prefix(tag) in prefixes]
    if not fitting:
        return None

    def overlap(r: dict[str, Any]) -> int:
        text = ((r.get("asset_type") or "") + " " + (r.get("asset_name") or "")).upper()
        return sum(1 for w in words if w in text)

    tag, record = max(fitting, key=lambda tr: overlap(tr[1]))
    consumed.add(tag)
    return record


def summarize(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """Counts by spec_status across a graph - surfaced in the agent reply and
    the P&ID summary so an engineer sees how much of the drawing is backed by
    real asset data."""
    out: dict[str, int] = {}
    for n in nodes or []:
        status = n.get("spec_status") or UNSPECIFIED
        out[status] = out.get(status, 0) + 1
    return out
