"""
pid_fallback.py - the deterministic P&ID builder both specialists fall back to.

WHY THIS IS SHARED
------------------
The greenfield and brownfield agents each used to carry their own ~300-line
if/elif ladder building the same four-way chains, and the two copies had
already drifted: greenfield emitted AFR nodes, standards lists and model_family
fields that brownfield did not. Anything fixed in one was not fixed in the
other.

There is one builder now. The two project types differ only in their endpoints
-- battery limits (INLET_FEED / OUTLET_HEADER) for a clean sheet, tie-in
nozzles (TP-01 / TP-02) for a retrofit -- and in whether the user's Assets
Table may bind real devices into the drawing (retrofit only). The topology
itself comes from services.instrument_packages, which is also what the tool
loop calls, so the LLM path and the fallback path build identical wiring.

Nothing here invents a specification. Every node's specs are resolved by
services.asset_specs from the user's Assets Table, from what the engineer
stated, or marked "unspecified".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from domain.solution.services import asset_specs as SPECS
from domain.solution.services import instrument_packages as IP
from domain.solution.services.pid_graph_store import PIDGraphStore

logger = logging.getLogger(__name__)

#: component_role categories that describe a piece of process equipment rather
#: than an instrument, and so belong on the main process run.
_EQUIPMENT_WORDS = ("pump", "vessel", "tank", "exchanger", "reactor", "column",
                    "filter", "drum", "separator", "compressor", "boiler")

#: Node kinds a package may anchor on in an existing drawing, best first.
_ANCHOR_KINDS = ("vessel", "column", "reactor", "heat_exchanger", "pump",
                 "tie_in", "off_page_connector", "valve")

#: Accessories the packages build by construction. When the BOM lists one of
#: these as its own line it is already on the drawing; adding it again would
#: produce a free-floating positioner with no valve.
_PACKAGE_BUILT_ACCESSORIES = ("manifold", "siphon", "thermowell", "positioner",
                              "actuator", "regulator", "root valve", "orifice",
                              "impulse")

_UNMAPPED_PREFIXES = (
    ("relief", "PSV"), ("safety", "PSV"), ("rupture", "RD"),
    ("check", "NRV"), ("isolation", "HV"), ("hand", "HV"),
    ("control valve", "CV"), ("valve", "XV"),
    ("analy", "AT"), ("switch", "XS"), ("gauge", "PI"), ("indicator", "PI"),
)

_TAG_IN_TEXT = re.compile(r"\b[A-Z]{1,5}-\d{2,6}[A-Z]?\b")


# ── helpers ─────────────────────────────────────────────────────────────────

def area_names(sub_systems: list[dict] | None, defaults: list[str]) -> list[str]:
    names = [s.get("name") if isinstance(s, dict) else str(s)
             for s in (sub_systems or [])]
    names = [str(n).strip() for n in names if n]
    return names or list(defaults)


def _equipment_roles(designed_solution: dict[str, Any] | None) -> list[dict]:
    roles = (designed_solution or {}).get("component_roles") or []
    return [r for r in roles if isinstance(r, dict) and
            any(w in str(r.get("category") or "").lower() for w in _EQUIPMENT_WORDS)]


def _is_package_accessory(text: str) -> bool:
    text = text.lower()
    return any(w in text for w in _PACKAGE_BUILT_ACCESSORIES)


def _stream_neighbour(store: PIDGraphStore, tag: str, direction: str) -> str | None:
    """The tag fed by (direction='out') or feeding (direction='in') `tag`
    along a process stream."""
    node = store._find(tag)
    if node is None:
        return None
    for e in store.edges:
        if e.get("kind") != "stream":
            continue
        if direction == "out" and e["from"] == node["id"]:
            other = store._find(e["to"])
        elif direction == "in" and e["to"] == node["id"]:
            other = store._find(e["from"])
        else:
            continue
        if other is not None:
            return store._tag_of(other)
    return None


def _line_at(store: PIDGraphStore, process_tag: str) -> list[str] | None:
    """An existing process line touching `process_tag`, as [upstream, downstream],
    preferring the line leaving it -- where a control valve normally goes."""
    down = _stream_neighbour(store, process_tag, "out")
    if down:
        return [process_tag, down]
    up = _stream_neighbour(store, process_tag, "in")
    return [up, process_tag] if up else None


def _has_inline(package: str, with_control: bool) -> bool:
    return any(m.inline for m in IP.members_for(package, with_control))


def _bind_assets(store: PIDGraphStore, plan: dict, consumed: set[str]) -> dict[str, str]:
    """Retrofit only: bind package roles to devices already recorded in the
    user's Assets Table, so the drawing carries the plant's real tags and
    nameplates. Roles the engineer tagged explicitly are left alone."""
    role_tags = dict(plan.get("role_tags") or {})
    letter = IP.LETTER_OF.get(plan["package"])
    if not letter or not store.asset_index:
        return role_tags
    category = " ".join(str(s.get("category") or "") for s in plan["sources"])
    wanted = ["transmitter"] + (["control_valve"] if plan["with_control"] else [])
    for role in wanted:
        if role in role_tags:
            continue
        record = SPECS.match_for_role(store.asset_index, letter, role, consumed,
                                      category)
        if record:
            role_tags[role] = str(record.get("tag_number")).upper()
    return role_tags


def _tag_for_unmapped(store: PIDGraphStore, category: str) -> str:
    cat = category.lower()
    for word, prefix in _UNMAPPED_PREFIXES:
        if word in cat:
            return store.next_tag(prefix)
    return store.next_tag("XX")


def _add_unmapped(store: PIDGraphStore, item: dict, area: str, anchor: str,
                  line: list[str] | None) -> list[str] | None:
    """Add one instrument no package covers. A throttling or isolating valve
    goes into the process line; anything else hangs off the anchor. Returns the
    process line as it stands afterwards."""
    text = (item.get("category") or "") + " " + (item.get("product_name") or "")
    if _is_package_accessory(text):
        return line
    tag = item.get("tag") or _tag_for_unmapped(store, text)
    if tag.startswith("ERROR") or store._find(tag) is not None:
        return line                     # stated tag already drawn: never duplicate
    low = text.lower()
    inline_valve = "valve" in low and not any(
        w in low for w in ("relief", "safety", "rupture"))
    spec = {"tag": tag, "kind": "", "area": area,
            "description": item.get("product_name") or item.get("category") or ""}
    if inline_valve and line:
        res = store.break_line(line[0], line[1], spec)
        if not res.startswith("ERROR"):
            return [tag, line[1]]
    store.add_nodes([spec], near_tag=anchor)
    store.add_edges([{"from_tag": anchor, "to_tag": tag}])
    return line


def _add_accessories(store: PIDGraphStore, accessories: list[dict] | None,
                     area: str, anchor: str) -> None:
    for acc in accessories or []:
        text = str(acc.get("category") or "") + " " + str(acc.get("accessory_name") or "")
        if _is_package_accessory(text):
            continue                    # the instrument package already built it
        _add_unmapped(store, {"category": text,
                              "product_name": str(acc.get("accessory_name") or ""),
                              "tag": IP.explicit_tag(acc)}, area, anchor, None)


# ── clean build ─────────────────────────────────────────────────────────────

def build_graph(store: PIDGraphStore, *,
                entry: dict[str, Any],
                exit_: dict[str, Any],
                areas: list[str],
                designed_solution: dict[str, Any] | None,
                instruments: list[dict] | None,
                accessories: list[dict] | None = None,
                isolation_tag: str | None = None,
                check_valve_tag: str | None = None,
                line_label: str = "",
                bind_assets: bool = False) -> PIDGraphStore:
    """Populate `store` with a complete four-way topology between two endpoints.

    entry/exit_: {"tag", "kind", "description"} for the two boundary nodes.
    isolation_tag: an inline hand valve right after the entry.
    check_valve_tag: a non-return valve before the exit.
    bind_assets: bind package roles to the user's Assets Table (retrofit only;
      a clean sheet is new equipment and must not inherit an installed
      device's nameplate).
    """
    area_in = areas[0]
    area_mid = areas[1] if len(areas) > 1 else area_in
    area_out = areas[-1] if len(areas) > 2 else area_mid

    backbone: list[str] = []

    def _chain(tag: str, kind: str, description: str, area: str) -> None:
        res = store.add_nodes([{"tag": tag, "kind": kind, "area": area,
                                "description": description}])
        if res.startswith("ERROR"):
            logger.debug("[PID_FALLBACK] skipped %s: %s", tag, res)
            return
        if backbone:
            store.add_edges([{"from_tag": backbone[-1], "to_tag": tag,
                              "kind": "stream", "label": line_label}])
        backbone.append(tag)

    _chain(entry["tag"], entry.get("kind", "off_page_connector"),
           entry.get("description", ""), area_in)
    if isolation_tag:
        _chain(isolation_tag, "valve", "Battery limit isolation valve", area_in)
    for i, role in enumerate(_equipment_roles(designed_solution)):
        tag = str(role.get("name") or role.get("tag") or "").strip()
        if tag:
            _chain(tag, "", str(role.get("purpose") or "Process equipment"),
                   area_in if i == 0 else area_mid)

    # Every package taps the last piece of equipment, or the entry side when
    # the design named none.
    anchor = backbone[-1] if backbone else entry["tag"]
    if check_valve_tag:
        _chain(check_valve_tag, "checkvalve", "Process non-return check valve",
               area_out)
    _chain(exit_["tag"], exit_.get("kind", "off_page_connector"),
           exit_.get("description", ""), area_out)

    # Inline members (control valves, orifices) go into the line leaving the
    # anchor. After each package the line's upstream end moves to the last
    # element placed, so the next package extends the run in series instead
    # of opening a parallel branch.
    line = _line_at(store, anchor)
    consumed = {t.upper() for t in store.preexisting_tags}

    plans, unmapped = IP.plan_packages(instruments)
    for plan in plans:
        role_tags = _bind_assets(store, plan, consumed) if bind_assets \
            else dict(plan.get("role_tags") or {})
        inline = _has_inline(plan["package"], plan["with_control"])
        res = store.add_instrument_package(
            plan["package"], anchor, subsystem=area_mid,
            with_control=plan["with_control"],
            valve_between=line if inline else None,
            role_tags=role_tags or None)
        if res.startswith("ERROR"):
            logger.debug("[PID_FALLBACK] package %s: %s", plan["package"], res)
            continue
        if inline and line:
            line = [_stream_neighbour(store, line[1], "in") or line[0], line[1]]

    for item in unmapped:
        line = _add_unmapped(store, item, area_mid, anchor, line)
    _add_accessories(store, accessories, area_mid, anchor)
    return store


# ── in-place modification ───────────────────────────────────────────────────

def _covering_transmitter(store: PIDGraphStore, package: str,
                          role_tags: dict[str, str]) -> str | None:
    """The transmitter already measuring this package's variable, if the
    drawing has one. A stated transmitter tag counts only when it is drawn."""
    stated = role_tags.get("transmitter")
    if stated:
        return stated if store._find(stated) is not None else None
    letter = IP.LETTER_OF[package]
    for n in store.nodes:
        tag = store._tag_of(n).upper()
        if str(n.get("kind")) == "transmitter" and \
                IP.role_for_tag(package, tag) == "transmitter" and tag.startswith(letter):
            return store._tag_of(n)
    return None


def _process_anchor(store: PIDGraphStore, hint_text: str = "") -> str | None:
    """Where new instrumentation taps an existing drawing.

    A tag the engineer named in the request wins ("add pressure control on
    E-101"). Otherwise the first node of the most process-like kind. The old
    mutation fallback took the first node of any plausible kind in list order,
    so additions attached wherever the list happened to start."""
    for tag in _TAG_IN_TEXT.findall((hint_text or "").upper()):
        node = store._find(tag)
        if node is not None and str(node.get("kind")) in _ANCHOR_KINDS:
            return store._tag_of(node)
    for kind in _ANCHOR_KINDS:
        for n in store.nodes:
            if str(n.get("kind")) == kind:
                return store._tag_of(n)
    return store._tag_of(store.nodes[0]) if store.nodes else None


def mutate_graph(store: PIDGraphStore, *,
                 instruments: list[dict] | None,
                 accessories: list[dict] | None = None,
                 area: str = "",
                 modification_prompt: str = "",
                 bind_assets: bool = True) -> list[str]:
    """Extend an existing drawing in place without disturbing it.

    For each measured variable requested:
      - already measured and no control asked for -> left alone;
      - already measured and control asked for -> the control tail is added to
        that existing loop (add_control_tail), honouring a named valve tag;
      - not measured -> a full package is added at the process anchor.
    A stated tag that is already drawn is never added again. This replaces the
    old fallback, whose duplicate check compared an instrument *category* to
    node *tags* and so re-added every instrument on every modification turn.

    Returns a list of notes describing what was skipped and why.
    """
    notes: list[str] = []
    anchor = _process_anchor(store, modification_prompt)
    if anchor is None:
        notes.append("the drawing is empty; nothing to tie into")
        return notes
    anchor_area = area or str((store._find(anchor) or {}).get("area") or "")
    consumed = {store._tag_of(n).upper() for n in store.nodes}

    plans, unmapped = IP.plan_packages(instruments)
    for plan in plans:
        role_tags = dict(plan.get("role_tags") or {})
        existing = _covering_transmitter(store, plan["package"], role_tags)
        if existing:
            if not plan["with_control"]:
                notes.append("%s already measures %s; not added again"
                             % (existing, plan["package"]))
                continue
            # The process point this loop measures: recorded directly for a
            # package-built transmitter (whose own upstream neighbour is its
            # manifold, not the line), else the node feeding it.
            process = (store._find(existing) or {}).get("package_anchor") or \
                _stream_neighbour(store, existing, "in") or next(
                    (c["other"] for c in store.get_connections(existing)
                     if c["direction"] == "in"), None)
            res = store.add_control_tail(
                existing, subsystem=area or None,
                valve_between=_line_at(store, process) if process else None,
                valve_tag=role_tags.get("control_valve"))
            if res.startswith(("NOOP", "ERROR")):
                notes.append(res)
            continue
        if bind_assets:
            role_tags = _bind_assets(store, {**plan, "role_tags": role_tags}, consumed)
        inline = _has_inline(plan["package"], plan["with_control"])
        res = store.add_instrument_package(
            plan["package"], anchor, subsystem=anchor_area or None,
            with_control=plan["with_control"],
            valve_between=_line_at(store, anchor) if inline else None,
            role_tags=role_tags or None)
        if res.startswith(("NOOP", "ERROR")):
            notes.append(res)

    line = _line_at(store, anchor)
    for item in unmapped:
        if item.get("tag") and store._find(item["tag"]) is not None:
            notes.append("%s is already on the drawing" % item["tag"])
            continue
        line = _add_unmapped(store, item, anchor_area, anchor, line)
    _add_accessories(store, accessories, anchor_area, anchor)
    return notes
