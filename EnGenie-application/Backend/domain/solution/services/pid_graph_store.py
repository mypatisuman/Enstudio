"""
pid_graph_store.py - an incrementally mutable P&ID graph with a tool surface.

WHY THIS EXISTS
---------------
The enSTUDIO Describe specialists (standard-main-S) are short files because the
work lives in a repository: the agent reads the real graph, then mutates it one
audited call at a time. That repository is SQLite-backed, and EnGenie has no
such store - its P&ID is a plain ``{"nodes": [...], "edges": [...]}`` dict that
lives in LangGraph state (``active_pid_graph``) and is regenerated wholesale on
every turn.

The tool-loop architecture does not actually need SQLite. It needs a graph you
can *read before you write* and *mutate incrementally*. This module wraps
EnGenie's existing graph dict in exactly the tool surface the Describe
repository exposes, so the agents can be rewritten as tool agents without
introducing a new datastore and without changing anything downstream:
build_pid_from_solution, calculate_pid_layout, generate_pid_svg and the
PIDGraph schema all keep receiving the same shape they do today.

When the graph is later persisted (a ``pid_graphs`` collection keyed by
user/project/session), only ``load`` and ``save`` change; every tool below and
every agent stays as written.

TOOL CONTRACT
-------------
Every write returns a string. The agent loop depends on the prefixes:

  ``ERROR: ...``  nothing was written; read it, fix the arguments, or ask
  ``NOOP: ...``   the work already exists; do not repeat it
  anything else   success, describing what changed

Nothing in this module invents a specification. Specs come from
services.asset_specs, which resolves them from the user's Assets Table, from
what the engineer stated, or marks them ``unspecified``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from domain.solution.services import asset_specs as SPECS
from domain.solution.services import instrument_packages as IP
from domain.solution.services.isa_classifier import classify_node_kind

logger = logging.getLogger(__name__)

_TAG_NUM_RE = re.compile(r"^([A-Z]{1,5})-?(\d{2,6})([A-Z]?)$")

#: Edge kinds the PIDEdge schema accepts.
_EDGE_KINDS = ("stream", "impulse", "signal", "pneumatic", "relief",
               "utility", "bypass", "recycle")

#: Node kinds that count as instrumentation for loop inference.
_INSTRUMENT_KINDS = ("transmitter", "controller", "switch", "indicator",
                     "positioner", "actuator", "regulator")

#: Spacing used when a new node is placed beside its anchor. The final layout
#: is recomputed by calculate_pid_layout, so these are advisory only - they
#: exist so insert_between can land an element between two real coordinates.
_OFFSET_X = 160.0
_OFFSET_Y = 140.0


def _infer_edge_kind(f_tag: str, t_tag: str, kind: str | None) -> str:
    """Classify a connection from the tags at its ends when the caller did not
    say, so a transmitter-to-controller link becomes a signal rather than a
    process stream. An explicit kind is always respected."""
    kind = (kind or "stream").lower()
    if kind != "stream":
        return kind if kind in _EDGE_KINDS else "stream"
    f_tag, t_tag = (f_tag or "").upper(), (t_tag or "").upper()
    if f_tag.startswith(("PSV", "PRV", "RV-")) or "VENT" in t_tag or "FLARE" in t_tag:
        return "relief"
    sensors = ("PI-", "TI-", "PT-", "TT-", "FT-", "LT-", "AI-", "PE-", "TE-",
               "FE-", "LE-", "AT-")
    controllers = ("PIC-", "TIC-", "FIC-", "LIC-", "AIC-", "DCS-", "PLC-", "SIS-")
    valves = ("PCV-", "TCV-", "FCV-", "LCV-", "CV-", "FV-", "PV-", "TV-", "LV-")
    if f_tag.startswith(sensors):
        return "signal" if t_tag.startswith(controllers) else "impulse"
    if t_tag.startswith(sensors):
        return "impulse"
    if f_tag.startswith(controllers):
        return "pneumatic" if t_tag.startswith(valves) else "signal"
    if f_tag.startswith("AFR") or f_tag.startswith("POS") or f_tag.startswith("ACT"):
        return "pneumatic"
    return "stream"


class PIDGraphStore:
    """An in-memory P&ID graph exposing the Describe repository tool surface.

    Construct from an existing graph dict (a retrofit) or empty (clean sheet).
    ``to_graph()`` returns the same dict shape the renderer already consumes.
    """

    def __init__(self, graph: dict[str, Any] | None = None,
                 asset_index: dict[str, dict[str, Any]] | None = None,
                 project_type: str = "greenfield") -> None:
        graph = graph or {}
        self.nodes: list[dict[str, Any]] = [dict(n) for n in graph.get("nodes") or []]
        self.edges: list[dict[str, Any]] = []
        for e in graph.get("edges") or []:
            f = e.get("from") or e.get("from_id")
            t = e.get("to") or e.get("to_id")
            if f and t:
                self.edges.append({"from": f, "to": t,
                                   "kind": e.get("kind", "stream"),
                                   "label": e.get("label", "")})
        self.asset_index = asset_index or {}
        self.project_type = project_type
        #: Where fresh loop numbering starts when nothing in the drawing
        #: suggests a series: 100-series for a clean sheet, 200-series for a
        #: retrofit, matching the conventions both prompts teach.
        self.default_loop_base = 201 if project_type == "brownfield" else 101
        self.hierarchy: dict[str, dict[str, Any]] = {}
        self.ops: list[dict[str, Any]] = []
        #: Nodes present when the store was created - the "existing plant" a
        #: brownfield retrofit must preserve and must never renumber.
        self.preexisting_tags = {self._tag_of(n) for n in self.nodes}
        self._seed_hierarchy_from_areas()
        self._next_id = self._highest_id() + 1

    # ── internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _tag_of(node: dict[str, Any]) -> str:
        return str(node.get("label") or node.get("id") or "").strip()

    def _highest_id(self) -> int:
        top = 0
        for n in self.nodes:
            m = re.match(r"^n(\d+)$", str(n.get("id") or ""))
            if m:
                top = max(top, int(m.group(1)))
        return max(top, len(self.nodes))

    def _new_id(self) -> str:
        while True:
            nid = "n%d" % self._next_id
            self._next_id += 1
            if not any(str(n.get("id")) == nid for n in self.nodes):
                return nid

    def _find(self, ref: str) -> dict[str, Any] | None:
        """Resolve a node by tag (preferred) or by raw node id."""
        if not ref:
            return None
        ref_u = str(ref).strip().upper()
        for n in self.nodes:
            if self._tag_of(n).upper() == ref_u:
                return n
        for n in self.nodes:
            if str(n.get("id") or "").upper() == ref_u:
                return n
        return None

    def _seed_hierarchy_from_areas(self) -> None:
        for n in self.nodes:
            area = str(n.get("area") or "").strip()
            if area:
                self.hierarchy.setdefault(
                    area, {"name": area, "system": None, "level": "subsystem"})

    def _positions(self) -> list[tuple[float, float]]:
        return [(float(n.get("x") or 0), float(n.get("y") or 0))
                for n in self.nodes if n.get("x") is not None]

    def _spot_near(self, anchor: dict[str, Any] | None,
                   index: int = 0) -> tuple[float, float]:
        """A free-ish position beside the anchor. Advisory only."""
        if anchor is None:
            return (120.0 + _OFFSET_X * index, 320.0)
        ax = float(anchor.get("x") or 0) or 120.0
        ay = float(anchor.get("y") or 0) or 320.0
        taken = self._positions()
        for dx, dy in ((1, 0), (0, 1), (0, -1), (-1, 0),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            x = ax + dx * _OFFSET_X * (1 + index // 8)
            y = ay + dy * _OFFSET_Y * (1 + index // 8)
            if all(abs(x - px) > 40 or abs(y - py) > 40 for px, py in taken):
                return (x, y)
        return (ax + _OFFSET_X * (index + 1), ay + _OFFSET_Y)

    def _record(self, tool: str, args: dict, result: str) -> None:
        if not result.startswith(("ERROR", "NOOP")):
            self.ops.append({"tool": tool, "args": args, "result": result})

    def _make_node(self, tag: str, kind: str, area: str, description: str,
                   stated: dict | None = None, stated_config: dict | None = None,
                   parent_tag: str | None = None,
                   extra: dict | None = None) -> dict[str, Any]:
        meta = SPECS.resolve(tag, stated, stated_config, self.asset_index)
        classified = classify_node_kind(tag, kind, meta.get("specifications") or {})
        node: dict[str, Any] = {
            "id": self._new_id(),
            "label": tag,
            "kind": classified,
            "description": description or "",
            "area": area or "",
            "is_tie_in": classified == "tie_in",
            "specifications": meta.get("specifications") or {},
            "spec_status": meta["spec_status"],
        }
        if meta.get("instrument_config"):
            node["instrument_config"] = meta["instrument_config"]
        if parent_tag:
            node["parent_instrument_tag"] = parent_tag
        if classified == "tie_in":
            node["tie_in_label"] = tag
        if extra:
            node.update(extra)
        return node

    # ── inspection tools ────────────────────────────────────────────────────

    def search_graph(self, query: str = "", kind_filter: str | None = None) -> list[dict]:
        """Find nodes whose tag, id or kind contains the query."""
        q = (query or "").upper()
        out = []
        for n in self.nodes:
            hay = (self._tag_of(n) + " " + str(n.get("id")) + " " +
                   str(n.get("kind"))).upper()
            if q and q not in hay:
                continue
            if kind_filter and str(n.get("kind")) != kind_filter:
                continue
            out.append({"id": n.get("id"), "tag": self._tag_of(n),
                        "kind": n.get("kind"), "area": n.get("area"),
                        "spec_status": n.get("spec_status")})
        return out[:40]

    def get_node(self, tag: str) -> dict:
        """Full attributes, area, specifications and connections of one node."""
        n = self._find(tag)
        if n is None:
            return {"error": "ERROR: no node with tag '%s'" % tag}
        return {**{k: v for k, v in n.items()},
                "tag": self._tag_of(n),
                "connections": self.get_connections(tag)}

    def get_connections(self, tag: str) -> list[dict]:
        """Inbound and outbound connections of one node."""
        n = self._find(tag)
        if n is None:
            return []
        nid = n.get("id")
        by_id = {x.get("id"): self._tag_of(x) for x in self.nodes}
        out = []
        for e in self.edges:
            if e["from"] == nid:
                out.append({"direction": "out", "other": by_id.get(e["to"], e["to"]),
                            "kind": e.get("kind")})
            elif e["to"] == nid:
                out.append({"direction": "in", "other": by_id.get(e["from"], e["from"]),
                            "kind": e.get("kind")})
        return out

    def get_loops(self, status_filter: str | None = None) -> list[dict]:
        """Control loops inferred from ISA tag numbering, computed fresh from
        the current graph. status: complete | indication_only | no_controller
        (a valve nothing drives) | no_final_element | incomplete."""
        loops: dict[str, dict] = {}
        for n in self.nodes:
            m = _TAG_NUM_RE.match(self._tag_of(n).upper())
            if not m:
                continue
            # Equipment carries an ISA-shaped tag (V-101, P-101A) but is not a
            # control loop member; counting it produced phantom "no_controller"
            # loops for every vessel and pump in the drawing.
            if str(n.get("kind")) not in _INSTRUMENT_KINDS + ("valve", "manifold",
                                                             "siphon", "thermowell"):
                continue
            # A node's own loop attribute wins over its tag number: an engineer-
            # named valve PCV-102 fitted to loop 101 belongs to loop 101.
            prefix, number = m.group(1), str(n.get("loop") or m.group(2))
            rec = loops.setdefault(number, {"loop_id": number, "members": [],
                                            "controller": None,
                                            "measurement": None,
                                            "final_element": None})
            tag = self._tag_of(n)
            rec["members"].append(tag)
            if prefix.endswith("IC") or prefix.endswith("C") and len(prefix) == 3:
                rec["controller"] = rec["controller"] or tag
            elif prefix.endswith("T") and len(prefix) == 2:
                rec["measurement"] = rec["measurement"] or tag
            elif prefix.endswith("CV") or prefix in ("FV", "PV", "TV", "LV"):
                rec["final_element"] = rec["final_element"] or tag
        out = []
        for rec in loops.values():
            # A transmitter with neither controller nor valve is a monitoring
            # loop, which is a legitimate design -- not a gap. The gaps are a
            # valve nothing drives, or a controller with nothing to drive.
            has_m, has_c, has_f = (bool(rec["measurement"]), bool(rec["controller"]),
                                   bool(rec["final_element"]))
            if has_m and has_c and has_f:
                rec["status"] = "complete"
            elif has_m and not has_c and not has_f:
                rec["status"] = "indication_only"
            elif has_f and not has_c:
                rec["status"] = "no_controller"
            elif has_c and not has_f:
                rec["status"] = "no_final_element"
            else:
                rec["status"] = "incomplete"
            if status_filter and rec["status"] != status_filter:
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r["loop_id"])

    def validate_drawing(self) -> dict:
        """Orphans, duplicate tags, missing kinds and an overall quality score."""
        n_nodes = len(self.nodes)
        connected = {e["from"] for e in self.edges} | {e["to"] for e in self.edges}
        orphans = sum(1 for n in self.nodes if n.get("id") not in connected)
        seen: dict[str, int] = {}
        for n in self.nodes:
            t = self._tag_of(n).upper()
            if t:
                seen[t] = seen.get(t, 0) + 1
        dupes = sum(1 for c in seen.values() if c > 1)
        missing_kind = sum(1 for n in self.nodes if not n.get("kind"))
        score = 100
        if n_nodes:
            score -= min(50, round(50 * orphans / n_nodes))
            score -= min(30, 15 * dupes)
            score -= min(20, round(20 * missing_kind / n_nodes))
        return {"nodes": n_nodes, "edges": len(self.edges), "orphans": orphans,
                "duplicate_tags": dupes, "missing_kinds": missing_kind,
                "score": max(0, score)}

    def graph_summary(self, max_tags: int = 40) -> str:
        """Counts, known tags and plant groups - the context block the agent
        prompt is filled with each turn."""
        tags = ", ".join("%s(%s)" % (self._tag_of(n), n.get("kind"))
                         for n in self.nodes[:max_tags] if self._tag_of(n))
        summary = "%d nodes, %d edges. Tags: %s" % (
            len(self.nodes), len(self.edges), tags or "(none yet)")
        if self.hierarchy:
            summary += ". Plant groups: " + ", ".join(sorted(self.hierarchy))
        statuses = SPECS.summarize(self.nodes)
        if statuses:
            summary += ". Specifications: " + ", ".join(
                "%s=%d" % (k, v) for k, v in sorted(statuses.items()))
        return summary

    def digitisation_status(self) -> dict:
        """Whether this project holds an existing drawing a retrofit can build
        on, as opposed to a clean sheet."""
        authored = sum(1 for n in self.nodes
                       if self._tag_of(n) not in self.preexisting_tags)
        existing = len(self.nodes) - authored
        return {"digitised": existing > 0, "existing_nodes": existing,
                "authored_nodes": authored}

    def list_hierarchy(self) -> dict:
        """The project's systems and subsystems with their node counts."""
        out = []
        for name, rec in sorted(self.hierarchy.items()):
            members = [self._tag_of(n) for n in self.nodes
                       if str(n.get("area") or "") == name]
            out.append({"name": name, "level": rec.get("level", "subsystem"),
                        "system": rec.get("system"), "nodes": len(members)})
        return {"groups": out}

    def get_subsystem(self, name: str, system: str | None = None) -> dict:
        """Look up one subsystem by name: its path and node count."""
        matches = [k for k in self.hierarchy
                   if k.lower() == (name or "").lower()]
        if not matches:
            near = [k for k in self.hierarchy if (name or "").lower() in k.lower()]
            return {"error": "ERROR: no subsystem named '%s'" % name,
                    "candidates": near or sorted(self.hierarchy)}
        key = matches[0]
        rec = self.hierarchy[key]
        return {"name": key, "system": rec.get("system"),
                "level": rec.get("level", "subsystem"),
                "nodes": [self._tag_of(n) for n in self.nodes
                          if str(n.get("area") or "") == key]}

    def get_subsystem_contents(self, subsystem: str) -> dict:
        """Nodes, tags and control loops already inside a subsystem - the
        duplicate check before a retrofit adds another transmitter."""
        info = self.get_subsystem(subsystem)
        if info.get("error"):
            return info
        tags = set(info["nodes"])
        loops = [l for l in self.get_loops() if set(l["members"]) & tags]
        kinds: dict[str, int] = {}
        for n in self.nodes:
            if self._tag_of(n) in tags:
                kinds[str(n.get("kind"))] = kinds.get(str(n.get("kind")), 0) + 1
        return {"subsystem": info["name"], "tags": sorted(tags),
                "kinds": kinds, "loops": loops}

    # ── tag allocation ──────────────────────────────────────────────────────

    def _numbers_in_use(self) -> dict[str, set[int]]:
        used: dict[str, set[int]] = {}
        for n in self.nodes:
            m = _TAG_NUM_RE.match(self._tag_of(n).upper())
            if m:
                used.setdefault(m.group(1), set()).add(int(m.group(2)))
        return used

    def next_tag(self, prefix: str, series: str | None = None) -> str:
        """The next free tag for an ISA prefix, following the plant's own
        numbering. An existing tag is never reused or renumbered."""
        prefix = (prefix or "").strip().upper().rstrip("-")
        if not re.match(r"^[A-Z]{1,5}$", prefix):
            return "ERROR: prefix must be 1-5 letters, e.g. PT"
        if series:
            base = "%s-%s" % (prefix, series)
            if self._find(base) is None:
                return base
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if self._find(base + letter) is None:
                    return base + letter
            return "ERROR: no free suffix left for %s" % base
        used = self._numbers_in_use()
        pool = used.get(prefix) or (set().union(*used.values()) if used else set())
        n = (max(pool) + 1) if pool else 101
        while self._find("%s-%d" % (prefix, n)) is not None:
            n += 1
        return "%s-%d" % (prefix, n)

    #: Node kinds that never anchor a loop number. A tie-in named TP-01 or a
    #: battery-limit connector is not a loop; numbering from it gave loop "02".
    _NON_LOOP_ANCHORS = ("tie_in", "off_page_connector", "junction")

    def _reserved_loop_numbers(self) -> set[int]:
        """Loop numbers already claimed by an instrument loop. Equipment (P-101)
        and inline hand valves (HV-101) share the number space but do not claim
        a loop, so they are not counted."""
        reserved: set[int] = set()
        for n in self.nodes:
            m = _TAG_NUM_RE.match(self._tag_of(n).upper())
            if not m:
                continue
            if n.get("loop") or str(n.get("kind")) in (
                    "transmitter", "controller", "switch", "indicator"):
                reserved.add(int(m.group(2)))
        return reserved

    def _free_loop_number(self, prefixes: list[tuple[str, str]],
                          anchor: dict[str, Any]) -> str:
        """A loop number that no other instrument loop uses and where every
        member tag is free.

        Numbering starts from the anchor's own number when the anchor is a
        numbered piece of plant (P-101 -> loop 101, V-2040 -> loop 2040), which
        is the usual ISA practice of aligning a loop with its equipment. The
        Describe repository started one above the anchor instead; aligning is
        what EnGenie's drawings and prompts already use. A tie-in or connector
        anchor carries no loop meaning, so numbering then continues the
        drawing's own series, or starts at the project-type default.

        Loop numbers are unique across measured variables: PT-201 and TT-201
        would otherwise both be "loop 201" and get_loops would merge them.
        """
        reserved = self._reserved_loop_numbers()
        m = _TAG_NUM_RE.match(self._tag_of(anchor).upper())
        if m and str(anchor.get("kind")) not in self._NON_LOOP_ANCHORS:
            start, width = int(m.group(2)), len(m.group(2))
        else:
            start = (max(reserved) + 1) if reserved else self.default_loop_base
            width = 3
        n = start
        while True:
            series = str(n).zfill(width)
            if n not in reserved and all(
                    self._find("%s-%s%s" % (p, series, s)) is None
                    for p, s in prefixes):
                return series
            n += 1

    # ── write tools ─────────────────────────────────────────────────────────

    def add_nodes(self, nodes: list[dict], near_tag: str | None = None,
                  subsystem: str | None = None) -> str:
        """Add equipment or instruments. nodes: [{tag, kind, area?,
        description?, specifications?}]; near_tag places them beside a node.

        Pass
        specifications ONLY with values the engineer stated; nothing is
        invented. An existing tag is rejected, never silently renumbered.
        """
        if not nodes or not isinstance(nodes, list) or \
                any(not isinstance(n, dict) for n in nodes):
            return "ERROR: nodes must be a non-empty list of objects"
        tags = [str(n.get("tag") or "").strip() for n in nodes]
        if any(not t for t in tags):
            return "ERROR: every node needs a tag"
        if len({t.upper() for t in tags}) != len(tags):
            return "ERROR: the same tag appears twice in this request: %s" % tags
        dupes = [t for t in tags if self._find(t) is not None]
        if dupes:
            return ("ERROR: tags already exist: %s. Use update_node, or "
                    "next_tag to get free tags." % dupes)
        anchor = self._find(near_tag) if near_tag else None
        if near_tag and anchor is None:
            return "ERROR: near_tag '%s' does not exist" % near_tag

        area = subsystem or (anchor.get("area") if anchor else "") or ""
        created = []
        for i, (spec, tag) in enumerate(zip(nodes, tags)):
            node = self._make_node(
                tag, spec.get("kind", ""), spec.get("area") or area,
                spec.get("description", ""), spec.get("specifications"),
                spec.get("instrument_config"), spec.get("parent_instrument_tag"))
            node["x"], node["y"] = self._spot_near(anchor, i)
            self.nodes.append(node)
            created.append(tag)
            if node["area"]:
                self.hierarchy.setdefault(
                    node["area"], {"name": node["area"], "system": None,
                                   "level": "subsystem"})
        statuses = SPECS.summarize([n for n in self.nodes
                                    if self._tag_of(n) in created])
        result = "Added %d node(s): %s. Specifications: %s." % (
            len(created), created,
            ", ".join("%s=%d" % kv for kv in sorted(statuses.items())))
        self._record("add_nodes", {"nodes": nodes, "near_tag": near_tag}, result)
        return result

    def _edge_exists(self, f_id: str, t_id: str, kind: str) -> bool:
        return any(e.get("kind") == kind and
                   {e["from"], e["to"]} == {f_id, t_id} for e in self.edges)

    def _insert_edge(self, f: dict, t: dict, kind: str, label: str = "") -> bool:
        if self._edge_exists(f["id"], t["id"], kind):
            return False
        self.edges.append({"from": f["id"], "to": t["id"], "kind": kind,
                           "label": label})
        return True

    def add_edges(self, edges: list[dict]) -> str:
        """Connect existing nodes. edges: [{from_tag, to_tag, kind, label}].

        kind: stream | impulse | signal | pneumatic | relief | bypass. An
        identical connection is skipped, never duplicated.
        """
        if not edges or not isinstance(edges, list):
            return "ERROR: edges must be a non-empty list"
        resolved = []
        for e in edges:
            f_tag, t_tag = e.get("from_tag", ""), e.get("to_tag", "")
            f, t = self._find(f_tag), self._find(t_tag)
            if f is None or t is None:
                missing = f_tag if f is None else t_tag
                return ("ERROR: tag '%s' does not exist. Add it first with "
                        "add_nodes." % missing)
            resolved.append((f, t, _infer_edge_kind(f_tag, t_tag, e.get("kind")),
                             e.get("label", ""), f_tag, t_tag))
        added, skipped = 0, []
        for f, t, kind, label, f_tag, t_tag in resolved:
            if self._insert_edge(f, t, kind, label):
                added += 1
            else:
                skipped.append("%s-%s(%s)" % (f_tag, t_tag, kind))
        if not added:
            return "NOOP: all %d connection(s) already exist: %s" % (
                len(skipped), skipped)
        note = " Skipped %d existing: %s." % (len(skipped), skipped) if skipped else ""
        result = "Added %d edge(s).%s" % (added, note)
        self._record("add_edges", {"edges": edges}, result)
        return result

    def add_junction(self, near_tag: str | None = None) -> str:
        """Add a three-way piping tee beside near_tag."""
        anchor = self._find(near_tag) if near_tag else None
        if near_tag and anchor is None:
            return "ERROR: near_tag '%s' does not exist" % near_tag
        tag = self.next_tag("JT")
        node = self._make_node(tag, "junction",
                               (anchor.get("area") if anchor else "") or "",
                               "Three-way piping junction")
        node["x"], node["y"] = self._spot_near(anchor)
        self.nodes.append(node)
        result = "Added junction %s." % tag
        self._record("add_junction", {"near_tag": near_tag}, result)
        return result

    def insert_between(self, new_node: dict, node_a: str, node_b: str,
                       at_fraction: float = 0.5,
                       subsystem: str | None = None) -> str:
        """Atomically insert an inline element between two nodes: add the node,
        connect A->new->B, and remove any direct A-B edge. The new connections
        keep the kind of the line they replace."""
        ra, rb = self._find(node_a), self._find(node_b)
        if ra is None:
            return "ERROR: '%s' does not exist" % node_a
        if rb is None:
            return "ERROR: '%s' does not exist" % node_b
        if not isinstance(new_node, dict) or not new_node.get("tag"):
            return "ERROR: new_node must be an object with at least a tag"
        tag = new_node["tag"]
        if self._find(tag) is not None:
            return ("ERROR: tags already exist: ['%s']. Use update_node or "
                    "pick new tags." % tag)

        old = [e for e in self.edges
               if {e["from"], e["to"]} == {ra["id"], rb["id"]}]
        line_kind = (old[0].get("kind") if old else "") or "stream"
        frac = min(1.0, max(0.0, float(at_fraction if at_fraction is not None else 0.5)))
        node = self._make_node(
            tag, new_node.get("kind", ""),
            new_node.get("area") or subsystem or ra.get("area") or "",
            new_node.get("description", ""), new_node.get("specifications"),
            new_node.get("instrument_config"))
        ax, ay = float(ra.get("x") or 0), float(ra.get("y") or 0)
        bx, by = float(rb.get("x") or 0), float(rb.get("y") or 0)
        node["x"], node["y"] = ax + (bx - ax) * frac, ay + (by - ay) * frac
        self.nodes.append(node)

        self.edges = [e for e in self.edges
                      if {e["from"], e["to"]} != {ra["id"], rb["id"]}]
        self._insert_edge(ra, node, line_kind)
        self._insert_edge(node, rb, line_kind)
        removed = "; removed the old direct edge" if old else ""
        result = "Inserted %s between %s and %s%s." % (
            tag, self._tag_of(ra), self._tag_of(rb), removed)
        self._record("insert_between",
                     {"new_node": new_node, "node_a": node_a, "node_b": node_b},
                     result)
        return result

    def break_line(self, from_tag: str, to_tag: str, new_node: dict,
                   at_fraction: float = 0.5,
                   subsystem: str | None = None) -> str:
        """Tie into an EXISTING line: split the connection between from_tag and
        to_tag and put new_node inline, keeping the line's kind. Fails when the
        two nodes are not directly connected."""
        ra, rb = self._find(from_tag), self._find(to_tag)
        if ra is None or rb is None:
            return "ERROR: '%s' does not exist" % (
                from_tag if ra is None else to_tag)
        if not any({e["from"], e["to"]} == {ra["id"], rb["id"]} for e in self.edges):
            return ("ERROR: there is no line between %s and %s to break. Check "
                    "get_connections, or use insert_between to create one."
                    % (from_tag, to_tag))
        return self.insert_between(new_node, from_tag, to_tag, at_fraction,
                                   subsystem)

    def reroute_edge(self, from_tag: str, old_to: str, new_to: str,
                     kind: str | None = None) -> str:
        """Move one end of an existing connection: from_tag-old_to becomes
        from_tag-new_to, keeping its kind unless a new kind is given."""
        rf, ro, rn = self._find(from_tag), self._find(old_to), self._find(new_to)
        for ref, row in ((from_tag, rf), (old_to, ro), (new_to, rn)):
            if row is None:
                return "ERROR: '%s' does not exist" % ref
        for e in self.edges:
            if {e["from"], e["to"]} == {rf["id"], ro["id"]}:
                e["to"] = rn["id"]
                e["from"] = rf["id"]
                if kind:
                    e["kind"] = kind
                result = "Rerouted %s-%s to %s-%s." % (
                    from_tag, old_to, from_tag, new_to)
                self._record("reroute_edge",
                             {"from_tag": from_tag, "old_to": old_to,
                              "new_to": new_to}, result)
                return result
        return "ERROR: there is no connection between %s and %s" % (from_tag, old_to)

    def update_node(self, tag: str, new_tag: str | None = None,
                    kind: str | None = None, area: str | None = None,
                    description: str | None = None,
                    specifications: dict | None = None) -> str:
        """Rename, reclassify, re-describe or move a node into another area.
        Specifications are only accepted as stated values."""
        n = self._find(tag)
        if n is None:
            return "ERROR: '%s' does not exist" % tag
        changes = []
        if new_tag and new_tag != tag:
            if self._find(new_tag) is not None:
                return "ERROR: tag '%s' already exists" % new_tag
            n["label"] = new_tag
            n["kind"] = classify_node_kind(new_tag, n.get("kind", ""),
                                           n.get("specifications") or {})
            changes.append("tag -> %s" % new_tag)
        if kind:
            n["kind"] = kind
            changes.append("kind -> %s" % kind)
        if area:
            n["area"] = area
            self.hierarchy.setdefault(area, {"name": area, "system": None,
                                             "level": "subsystem"})
            changes.append("area -> %s" % area)
        if description:
            n["description"] = description
            changes.append("description updated")
        if specifications:
            meta = SPECS.resolve(n["label"], specifications, None, self.asset_index)
            n["specifications"] = meta.get("specifications") or {}
            n["spec_status"] = meta["spec_status"]
            changes.append("specifications -> %s" % meta["spec_status"])
        if not changes:
            return "NOOP: nothing to change on %s" % tag
        result = "Updated %s: %s." % (tag, "; ".join(changes))
        self._record("update_node", {"tag": tag, "new_tag": new_tag}, result)
        return result

    def update_edge(self, from_tag: str, to_tag: str, kind: str | None = None,
                    label: str | None = None) -> str:
        """Reclassify an existing connection, e.g. stream -> signal."""
        rf, rt = self._find(from_tag), self._find(to_tag)
        if rf is None or rt is None:
            return "ERROR: '%s' does not exist" % (
                from_tag if rf is None else to_tag)
        for e in self.edges:
            if {e["from"], e["to"]} == {rf["id"], rt["id"]}:
                if kind:
                    e["kind"] = kind
                if label is not None:
                    e["label"] = label
                result = "Updated the %s-%s connection." % (from_tag, to_tag)
                self._record("update_edge",
                             {"from_tag": from_tag, "to_tag": to_tag}, result)
                return result
        return "ERROR: there is no connection between %s and %s" % (from_tag, to_tag)

    def delete_nodes(self, tags: list[str], reason: str = "") -> str:
        """Executor only - call AFTER the engineer confirmed. Removes the nodes
        and every connection that touched them."""
        if not tags or not isinstance(tags, list):
            return "ERROR: tags must be a non-empty list"
        missing = [t for t in tags if self._find(t) is None]
        if missing:
            return "ERROR: these tags do not exist: %s" % missing
        ids = {self._find(t)["id"] for t in tags}
        self.nodes = [n for n in self.nodes if n["id"] not in ids]
        before = len(self.edges)
        self.edges = [e for e in self.edges
                      if e["from"] not in ids and e["to"] not in ids]
        result = "Deleted %d node(s): %s, and %d connection(s)." % (
            len(tags), tags, before - len(self.edges))
        self._record("delete_nodes", {"tags": tags, "reason": reason}, result)
        return result

    def delete_edges(self, from_tag: str, to_tag: str) -> str:
        """Executor only - call AFTER the engineer confirmed. Removes the
        connection(s) between two nodes, in either direction."""
        rf, rt = self._find(from_tag), self._find(to_tag)
        if rf is None or rt is None:
            return "ERROR: '%s' does not exist" % (
                from_tag if rf is None else to_tag)
        before = len(self.edges)
        self.edges = [e for e in self.edges
                      if {e["from"], e["to"]} != {rf["id"], rt["id"]}]
        removed = before - len(self.edges)
        if not removed:
            return "NOOP: there is no connection between %s and %s" % (
                from_tag, to_tag)
        result = "Deleted %d connection(s) between %s and %s." % (
            removed, from_tag, to_tag)
        self._record("delete_edges", {"from_tag": from_tag, "to_tag": to_tag},
                     result)
        return result

    # ── plant hierarchy ─────────────────────────────────────────────────────

    def create_system(self, system: str, area: str | None = None) -> str:
        """Create (or find) a plant system."""
        if not system:
            return "ERROR: system needs a name"
        if system in self.hierarchy:
            return "NOOP: system '%s' already exists" % system
        self.hierarchy[system] = {"name": system, "system": None, "level": "system"}
        result = "Created system '%s'." % system
        self._record("create_system", {"system": system}, result)
        return result

    def create_subsystem(self, subsystem: str, system: str | None = None) -> str:
        """Create (or find) a subsystem, creating its parent system if needed."""
        if not subsystem:
            return "ERROR: subsystem needs a name"
        if subsystem in self.hierarchy:
            return "NOOP: subsystem '%s' already exists" % subsystem
        if system and system not in self.hierarchy:
            self.hierarchy[system] = {"name": system, "system": None,
                                      "level": "system"}
        self.hierarchy[subsystem] = {"name": subsystem, "system": system,
                                     "level": "subsystem"}
        result = "Created subsystem '%s'%s." % (
            subsystem, " under '%s'" % system if system else "")
        self._record("create_subsystem",
                     {"subsystem": subsystem, "system": system}, result)
        return result

    def assign_to_subsystem(self, tags: list[str], subsystem: str) -> str:
        """Move existing nodes into a subsystem. The subsystem doubles as the
        node's area, which is what the renderer groups its bounding boxes by."""
        if not tags or not isinstance(tags, list):
            return "ERROR: tags must be a non-empty list"
        missing = [t for t in tags if self._find(t) is None]
        if missing:
            return "ERROR: these tags do not exist: %s" % missing
        self.hierarchy.setdefault(subsystem, {"name": subsystem, "system": None,
                                              "level": "subsystem"})
        moved = []
        for t in tags:
            n = self._find(t)
            if str(n.get("area") or "") != subsystem:
                n["area"] = subsystem
                moved.append(t)
        if not moved:
            return "NOOP: all %d node(s) are already in '%s'" % (len(tags), subsystem)
        result = "Assigned %d node(s) to '%s': %s." % (len(moved), subsystem, moved)
        self._record("assign_to_subsystem",
                     {"tags": tags, "subsystem": subsystem}, result)
        return result

    def sync_hierarchy(self, source: str = "areas") -> str:
        """Seed the hierarchy from the areas already present on the nodes."""
        before = len(self.hierarchy)
        self._seed_hierarchy_from_areas()
        added = len(self.hierarchy) - before
        if not added:
            return "NOOP: the hierarchy already covers every area in the drawing"
        result = "Synced hierarchy from areas: %d group(s) added." % added
        self._record("sync_hierarchy", {"source": source}, result)
        return result

    # ── the package builder ─────────────────────────────────────────────────

    def _place_inline(self, members: list, tag_of: dict[str, str],
                      line: list[str] | None, area: str,
                      warnings: list[str]) -> str | None:
        """Put every inline member (orifice, control valve) into the process
        line, upstream to downstream: A-B becomes A-FE-FCV-B.

        The Describe repository handled only the first inline member, so a flow
        package with control put the orifice in the pipe and left the control
        valve body off the line with no warning. Returns an ERROR string, or
        None on success."""
        inline = [m for m in members if m.inline]
        if not inline:
            return None
        if not line:
            for m in inline:
                warnings.append("%s is not inline yet: call break_line with the "
                                "process line it belongs in" % tag_of[m.role])
            return None
        upstream, downstream = line[0], line[1]
        for m in inline:
            spec = {"tag": tag_of[m.role], "kind": m.kind,
                    "description": m.description, "area": area}
            res = self.break_line(upstream, downstream, spec)
            if res.startswith("ERROR"):
                res = self.insert_between(spec, upstream, downstream)
                if res.startswith("ERROR"):
                    return res
                warnings.append("%s and %s were not connected; %s now joins them"
                                % (upstream, downstream, tag_of[m.role]))
            upstream = tag_of[m.role]
        return None

    def add_instrument_package(self, package: str, anchor_tag: str,
                               subsystem: str | None = None,
                               tag_series: str | None = None,
                               with_control: bool = False,
                               valve_between: list[str] | None = None,
                               role_tags: dict[str, str] | None = None) -> str:
        """Build a complete instrument package in one step, wired in the
        four-way topology. package is ONE string: "pressure", "temperature",
        "flow" or "level". anchor_tag is the existing tag it taps.

        (The tool catalog shows only this first paragraph, so the argument
        shapes the model most needs live here.)
        anchor_tag: the existing line, header or vessel the package taps.
        with_control: also add the controller, air regulator, positioner,
          actuator and control valve.
        valve_between: [tag_a, tag_b], an existing process line. Inline members
          (the control valve, and a flow package's orifice) are put into it.
        tag_series: loop number, e.g. "201"; chosen automatically when omitted.
        role_tags: bind roles to tags that already exist in the plant's Assets
          Table or that the engineer named, e.g. {"transmitter": "PT-2041",
          "control_valve": "PCV-2041"}. The loop number follows the transmitter.
        Existing drawing tags are never reused; repeating a call never
        duplicates.
        """
        if not isinstance(package, str):
            return ("ERROR: package must be a single string, one of %s -- not %s"
                    % (IP.names(), type(package).__name__))
        package = package.strip().lower()
        if package not in IP.PACKAGES:
            return "ERROR: unknown package '%s'. Available: %s" % (
                package, IP.names())
        anchor = self._find(anchor_tag)
        if anchor is None:
            return "ERROR: anchor_tag '%s' does not exist" % anchor_tag
        members = IP.members_for(package, bool(with_control))
        connections = IP.connections_for(package, bool(with_control))
        roles = {m.role for m in members}

        role_tags = {k: str(v).strip().upper()
                     for k, v in (role_tags or {}).items() if v}
        bad = [r for r in role_tags if r not in roles]
        if bad:
            return "ERROR: role_tags names roles this package does not have: %s. " \
                   "Roles: %s" % (bad, sorted(roles))
        for role, tag in role_tags.items():
            if not IP.TAG_RE.match(tag):
                return "ERROR: role_tags[%r] = %r is not an ISA tag like PT-101" % (
                    role, tag)
            if IP.role_for_tag(package, tag) not in (role, None):
                return "ERROR: %s cannot fill the %s role of a %s package" % (
                    tag, role, package)

        if valve_between is not None:
            if not isinstance(valve_between, list) or len(valve_between) != 2:
                return "ERROR: valve_between must be [tag_a, tag_b]"
            if self._find(valve_between[0]) is None or \
                    self._find(valve_between[1]) is None:
                return "ERROR: valve_between tag does not exist: %s" % valve_between

        # Idempotency. Without this, a re-run of the same request -- which is
        # exactly what the modification path does -- silently taps the anchor a
        # second time and the drawing grows a duplicate loop on every turn.
        # An intentional second tap on the same anchor is still available by
        # passing an explicit tag_series.
        anchor_ref = self._tag_of(anchor)
        if not tag_series and not role_tags:
            existing = [self._tag_of(n) for n in self.nodes
                        if n.get("package") == package
                        and n.get("package_anchor") == anchor_ref]
            if existing:
                return ("NOOP: a %s package already taps %s (%s). Pass an "
                        "explicit tag_series to add a second, separate tap."
                        % (package, anchor_ref, sorted(existing)))

        bound_series = None
        for role in ("transmitter", "control_valve", "controller"):
            m = IP.TAG_RE.match(role_tags.get(role, ""))
            if m:
                bound_series = m.group(2)
                break
        series = tag_series or bound_series or self._free_loop_number(
            [(m.prefix, m.suffix) for m in members], anchor)
        tag_of = {m.role: "%s-%s%s" % (m.prefix, series, m.suffix) for m in members}
        tag_of.update(role_tags)
        taken = [t for t in tag_of.values() if self._find(t) is not None]
        if taken:
            if (tag_series or role_tags) and len(taken) == len(tag_of):
                return ("NOOP: the %s package for loop %s already exists (%s)."
                        % (package, series, sorted(tag_of.values())))
            return ("ERROR: tags already exist for loop %s: %s. Omit tag_series "
                    "to pick a free loop number." % (series, taken))

        area = subsystem or str(anchor.get("area") or "") or ""
        transmitter_tag = tag_of.get("transmitter")
        placed_inline = {m.role for m in members if m.inline} if valve_between \
            else set()

        created: list[dict[str, Any]] = []
        for i, m in enumerate(members):
            if m.role in placed_inline:
                continue                        # goes into the line below
            tag = tag_of[m.role]
            parent = transmitter_tag if m.role not in ("transmitter", "controller") \
                else None
            node = self._make_node(tag, m.kind, area, m.description,
                                   parent_tag=parent)
            node["x"], node["y"] = self._spot_near(anchor, i)
            self.nodes.append(node)
            created.append(node)

        warnings: list[str] = []
        err = self._place_inline(members, tag_of, valve_between, area, warnings)
        if err:
            return err
        for role in placed_inline:
            node = self._find(tag_of[role])
            if node is not None:
                node["parent_instrument_tag"] = transmitter_tag
                created.append(node)
        for node in created:
            node["package"] = package
            node["package_role"] = next(
                (r for r, t in tag_of.items() if t == self._tag_of(node)), "")
            node["package_anchor"] = anchor_ref
            node["loop"] = series

        added = 0
        for a, b, kind in connections:
            # An inline member already sits on the line the anchor belongs to;
            # a second anchor->member impulse edge would draw a phantom tap.
            if "@anchor" in (a, b) and ({a, b} - {"@anchor"}) & placed_inline:
                continue
            f = anchor if a == "@anchor" else self._find(tag_of[a])
            t = anchor if b == "@anchor" else self._find(tag_of[b])
            if f is not None and t is not None and self._insert_edge(f, t, kind):
                added += 1

        if area:
            self.hierarchy.setdefault(area, {"name": area, "system": None,
                                             "level": "subsystem"})
        statuses = SPECS.summarize(
            [n for n in self.nodes if self._tag_of(n) in set(tag_of.values())])
        bound = " Bound to existing tags: %s." % role_tags if role_tags else ""
        warn = " Warnings: %s." % warnings if warnings else ""
        result = ("Built %s package, loop %s, at %s: %s; %d connection(s)"
                  "%s. Specifications: %s.%s%s" % (
                      package, series, anchor_ref,
                      sorted(tag_of.values()), added,
                      " in '%s'" % area if area else "",
                      ", ".join("%s=%d" % kv for kv in sorted(statuses.items())),
                      bound, warn))
        self._record("add_instrument_package",
                     {"package": package, "anchor_tag": anchor_tag,
                      "subsystem": subsystem, "with_control": with_control,
                      "role_tags": role_tags},
                     result)
        return result

    def add_control_tail(self, transmitter_tag: str,
                         subsystem: str | None = None,
                         valve_between: list[str] | None = None,
                         valve_tag: str | None = None) -> str:
        """Add closed-loop control to a measurement that already exists: the
        controller, air regulator, positioner, actuator and control valve, wired
        to the existing transmitter and numbered in its loop.

        This is the retrofit case add_instrument_package cannot express: the
        plant already has PT-101, and the engineer wants it to control a new
        valve. valve_between=[tag_a, tag_b] puts the valve inline in that line;
        valve_tag uses a valve tag the engineer named (e.g. PCV-102).
        """
        t = self._find(transmitter_tag)
        if t is None:
            return "ERROR: '%s' does not exist" % transmitter_tag
        tag = self._tag_of(t).upper()
        m = IP.TAG_RE.match(tag) or _TAG_NUM_RE.match(tag)
        if not m or str(t.get("kind")) != "transmitter":
            return "ERROR: %s is not a transmitter with a loop number" % tag
        letter = m.group(1)[0]
        if letter not in IP.CONTROL_TAILS:
            return ("ERROR: no control template for measured variable '%s'. "
                    "Available: %s" % (letter, sorted(IP.CONTROL_TAILS)))
        series = m.group(2)
        members, connections = IP.CONTROL_TAILS[letter]
        tag_of = {mem.role: "%s-%s%s" % (mem.prefix, series, mem.suffix)
                  for mem in members}
        tag_of["transmitter"] = self._tag_of(t)
        if valve_tag:
            valve_tag = str(valve_tag).strip().upper()
            if not IP.TAG_RE.match(valve_tag):
                return "ERROR: valve_tag %r is not an ISA tag like PCV-102" % valve_tag
            tag_of["control_valve"] = valve_tag

        if self._find(tag_of["controller"]) is not None:
            return ("NOOP: loop %s already has a controller (%s)."
                    % (series, tag_of["controller"]))
        taken = [x for r, x in tag_of.items()
                 if r != "transmitter" and self._find(x) is not None]
        if taken:
            return "ERROR: tags already exist: %s" % taken
        if valve_between is not None and (
                not isinstance(valve_between, list) or len(valve_between) != 2):
            return "ERROR: valve_between must be [tag_a, tag_b]"

        area = subsystem or str(t.get("area") or "")
        placed_inline = {mem.role for mem in members if mem.inline} \
            if valve_between else set()
        for i, mem in enumerate(members):
            if mem.role in placed_inline:
                continue
            node = self._make_node(tag_of[mem.role], mem.kind, area,
                                   mem.description,
                                   parent_tag=None if mem.role == "controller"
                                   else self._tag_of(t))
            node["x"], node["y"] = self._spot_near(t, i)
            node["loop"] = series
            self.nodes.append(node)
        warnings: list[str] = []
        err = self._place_inline(list(members), tag_of, valve_between, area,
                                 warnings)
        if err:
            return err
        for role in placed_inline:
            node = self._find(tag_of[role])
            if node is not None:
                node["loop"] = series
                node["parent_instrument_tag"] = self._tag_of(t)
        added = 0
        for a, b, kind in connections:
            f, to = self._find(tag_of[a]), self._find(tag_of[b])
            if f is not None and to is not None and self._insert_edge(f, to, kind):
                added += 1
        new_tags = sorted(x for r, x in tag_of.items() if r != "transmitter")
        warn = " Warnings: %s." % warnings if warnings else ""
        result = "Added control to loop %s at %s: %s; %d connection(s).%s" % (
            series, self._tag_of(t), new_tags, added, warn)
        self._record("add_control_tail",
                     {"transmitter_tag": transmitter_tag, "valve_tag": valve_tag},
                     result)
        return result

    def search_assets(self, query: str = "") -> list[dict]:
        """Search the user's Assets Table (installed plant devices) by tag,
        type or name. Bind a hit into a package with role_tags so the drawing
        carries the real tag and nameplate instead of a new one."""
        q = (query or "").upper()
        out = []
        for tag, r in self.asset_index.items():
            hay = " ".join(str(r.get(k) or "") for k in (
                "tag_number", "asset_type", "asset_name")).upper()
            if q and q not in hay:
                continue
            out.append({"tag": tag, "asset_type": r.get("asset_type"),
                        "asset_name": r.get("asset_name"),
                        "manufacturer": r.get("manufacturer"),
                        "model": r.get("model"),
                        "in_drawing": self._find(tag) is not None})
        return out[:25]

    # ── output ──────────────────────────────────────────────────────────────

    def to_graph(self, summary: str = "") -> dict[str, Any]:
        """The graph dict build_pid_from_solution and the SVG renderer consume."""
        return {
            "project_type": self.project_type,
            "summary": summary or self.graph_summary(),
            "nodes": self.nodes,
            "edges": self.edges,
        }

    # ── vision & drawing digitization ────────────────────────────────────────

    def analyze_uploaded_pid(self, pid: str = "default", image_path: str | None = None) -> dict:
        """Visually analyze an uploaded P&ID drawing scan using Qwen3-VL on DeepInfra.

        Detects equipment, piping lines, ISA instrument tags, loops, tie-in points, and hierarchy.
        """
        from domain.solution.services.brownfield_vision_service import analyze_uploaded_pid as _analyze
        return _analyze(pid=pid, image_path=image_path)

    def rebuild_digital_pid(self, pid: str = "default", user_id: int | None = 1) -> str:
        """Reconstruct an interactive digital P&ID graph in the store and persistent databases."""
        from domain.solution.services.brownfield_vision_service import (
            analyze_uploaded_pid as _analyze,
            rebuild_digital_pid as _rebuild,
        )
        analysis = _analyze(pid=pid)
        if "error" in analysis:
            return analysis["error"]
        res = _rebuild(pid=pid, analysis=analysis, user_id=user_id)

        # Update in-memory store representation
        for eq in analysis.get("equipment") or []:
            tag = eq.get("tag")
            if tag and not self._find(tag):
                self.nodes.append({
                    "id": tag, "label": tag, "kind": eq.get("kind", "vessel"),
                    "kind_detail": eq.get("kind_detail", ""), "area": eq.get("area", ""),
                    "x": float(eq.get("x") or 300.0), "y": float(eq.get("y") or 300.0),
                    "description": eq.get("description", "")
                })
        for inst in analysis.get("instruments") or []:
            tag = inst.get("tag")
            if tag and not self._find(tag):
                self.nodes.append({
                    "id": tag, "label": tag, "kind": inst.get("kind", "transmitter"),
                    "kind_detail": inst.get("kind_detail", ""), "area": inst.get("area", ""),
                    "x": float(inst.get("x") or 400.0), "y": float(inst.get("y") or 250.0),
                    "spec_status": "nameplate"
                })
        for tp in analysis.get("tie_ins") or []:
            tag = tp.get("tag")
            if tag and not self._find(tag):
                self.nodes.append({
                    "id": tag, "label": tag, "kind": "tie_in",
                    "kind_detail": "Tie-In Nozzle", "area": "Tie-In Zone",
                    "x": float(tp.get("x") or 100.0), "y": float(tp.get("y") or 400.0)
                })
        for line in analysis.get("lines") or []:
            f_tag, t_tag = line.get("from_tag"), line.get("to_tag")
            if f_tag and t_tag:
                self.edges.append({
                    "from": f_tag, "to": t_tag, "kind": line.get("kind", "stream"),
                    "label": line.get("line_id", "")
                })

        self.preexisting_tags = {self._tag_of(n) for n in self.nodes}
        self.project_type = "brownfield"
        result = res.get("summary", f"Rebuilt digital P&ID for {pid} successfully.")
        self._record("rebuild_digital_pid", {"pid": pid}, result)
        return result

    def evaluate_pid_accuracy(self, pid: str = "default") -> dict:
        """Evaluate engineering accuracy score (0-100), ISA-5.1 compliance, loop completeness, and orphan rates."""
        from domain.solution.services.pid_accuracy_service import evaluate_intrinsic_accuracy
        return evaluate_intrinsic_accuracy(pid, save_local=True, agent_type=self.project_type or "solution")

    def get_accuracy_history(self, pid: str | None = None, limit: int = 50) -> list[dict]:
        """Retrieve historical accuracy evaluation records from local JSONL storage."""
        from domain.solution.services.pid_accuracy_service import get_accuracy_history as _get_hist
        return _get_hist(pid=pid if pid != "default" else None, limit=limit)

    def analyze_accuracy_metrics(self) -> dict:
        """Analyze stored local accuracy metrics and return cross-project diagnostic distributions and improvement recommendations."""
        from domain.solution.services.pid_accuracy_service import analyze_stored_accuracy_metrics
        return analyze_stored_accuracy_metrics()

    def refine_pid_drawing(self, pid: str = "default", user_id: int | None = 1) -> str:
        """Execute diagnostic-guided re-analysis with Qwen3-VL to resolve detected gaps and raise accuracy."""
        from domain.solution.services.pid_accuracy_service import refine_and_reanalyze
        res = refine_and_reanalyze(pid, user_id=user_id)
        if "error" in res:
            return res["error"]
        result = res.get("summary", f"Refinement completed for {pid}.")
        self._record("refine_pid_drawing", {"pid": pid}, result)
        return result



