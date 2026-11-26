"""Grid Layout Agent — maintains an n x n tile grid over the P&ID graph
so the Describe workflow can insert an element "between tile(1) and
tile(2)" and have the WHOLE grid reflow correctly, not just one row.

Not conversational — this is layout math, the same family as
relationship_agent.py. It is invoked as a post-write hook after any
Describe write (add/update/delete), or on demand.

THE PROBLEM THIS SOLVES
    Row 1: [vessel]---[pressure chamber]
    Row 2:      [pump]-------[filter]
Insert a valve between vessel and chamber in row 1. A naive "grow every
row by one column at that index" blindly shifts pump/filter too, even
though nothing in row 2 relates to the insertion point — misalignment.
A naive "only grow row 1" desyncs anything that WAS meaningfully aligned
across rows (e.g. a transmitter under its equipment, or two equipment
items linked by a signal loop).

THE FIX — three passes, all derived from existing graph data, no new
fields to maintain by hand:

  1. ROWS      one row per process stream (reuses the stream-walking
               logic from adapters/stream_graph.py: follow 'stream' kind
               edges from source to sink).
  2. COLUMNS   within a row, column = topological (flow) order along
               that stream.
  3. ALIGNMENT propagate a column shift across rows ONLY along real
               graph relationships: equipment_ref (instrument sits under
               its equipment), signal edges (loop wiring), and shared
               `area`. Two nodes with no such relationship never affect
               each other's column, however uniform-grow would treat
               them.
  4. COMPACT   drop any column that ends up empty in every row (created
               when only one row actually needed the insert), so unrelated
               rows don't accumulate blank columns over repeated inserts.

Alignment rule (v1, per current scope): equipment_ref and shared area
only. Explicit engineer-pinned alignment is a documented future
extension point (see _alignment_groups).
"""
from __future__ import annotations

from collections import defaultdict, deque

from agents.extraction.state import ExtractionState
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report

STAGE = "grid_layout"


# ── 1. Rows: one per process stream ─────────────────────────────────────────

def _assign_rows(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """node_id -> row index. Reuses the stream-finding idea from
    adapters/stream_graph.py: a row is a maximal chain of 'stream'-kind
    (or unlabeled) edges. Nodes touched by no stream edge get their own
    singleton row, appended after the real streams, so nothing is lost."""
    stream_edges = [e for e in edges if (e.get("kind") or "stream") in
                    ("stream", "")]
    succ: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = defaultdict(int)
    all_ids = {n["id"] for n in nodes}
    connected: set[str] = set()
    for e in stream_edges:
        f, t = e.get("from"), e.get("to")
        if f in all_ids and t in all_ids:
            succ[f].append(t)
            indeg[t] += 1
            connected.add(f)
            connected.add(t)

    row_of: dict[str, int] = {}
    row = 0
    visited: set[str] = set()

    def _walk_chain(start: str, pending: deque) -> bool:
        """Follow one chain from `start`: main path continues the row;
        at a fan-out, the first unvisited successor stays in this row
        and every OTHER branch head is queued to start its own row —
        one row per branch, never one row per node (which is what the
        old first-successor-only walk degenerated into on splits)."""
        nonlocal row
        node_id, has_any = start, False
        while node_id is not None and node_id not in visited:
            visited.add(node_id)
            row_of[node_id] = row
            has_any = True
            nxts = [n for n in succ.get(node_id, []) if n not in visited]
            for branch_head in nxts[1:]:
                pending.append(branch_head)
            node_id = nxts[0] if nxts else None
        return has_any

    pending: deque[str] = deque(
        n["id"] for n in nodes
        if n["id"] in connected and indeg.get(n["id"], 0) == 0)
    while pending:
        start = pending.popleft()
        if _walk_chain(start, pending):
            row += 1

    # Pure cycles (recycle loops with no indeg-0 entry): every member is
    # connected but unreachable from any source — walk the cycle as one
    # chain rather than exploding it into singleton rows.
    for n in nodes:
        nid = n["id"]
        if nid in connected and nid not in visited:
            if _walk_chain(nid, pending):
                row += 1
            while pending:
                start = pending.popleft()
                if _walk_chain(start, pending):
                    row += 1

    # Truly isolated nodes (no stream edges at all): singleton rows.
    for n in nodes:
        if n["id"] not in row_of:
            row_of[n["id"]] = row
            row += 1
    return row_of


# ── 2. Columns: topological order within each row ───────────────────────────

def _assign_columns(nodes: list[dict], edges: list[dict],
                    row_of: dict[str, int]) -> dict[str, int]:
    """node_id -> column index, computed independently per row via a
    topological walk of that row's own stream edges."""
    by_row: dict[int, list[str]] = defaultdict(list)
    for nid, r in row_of.items():
        by_row[r].append(nid)

    edge_by_from: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if (e.get("kind") or "stream") in ("stream", ""):
            edge_by_from[e.get("from")].append(e.get("to"))

    col_of: dict[str, int] = {}
    for r, ids in by_row.items():
        id_set = set(ids)
        indeg = {i: 0 for i in ids}
        for i in ids:
            for t in edge_by_from.get(i, []):
                if t in id_set:
                    indeg[t] += 1
        queue = deque(i for i in ids if indeg[i] == 0)
        col = 0
        seen: set[str] = set()
        while queue:
            nid = queue.popleft()
            if nid in seen:
                continue
            seen.add(nid)
            col_of[nid] = col
            col += 1
            for t in edge_by_from.get(nid, []):
                if t in id_set and t not in seen:
                    indeg[t] -= 1
                    if indeg[t] <= 0:
                        queue.append(t)
        # Any row-member not reached by the walk (disconnected within the
        # row) still gets a column, appended at the end.
        for nid in ids:
            if nid not in col_of:
                col_of[nid] = col
                col += 1
    return col_of


# ── 3. Alignment groups (v1: equipment_ref + shared area) ───────────────────

def _equipment_ref(node: dict) -> str | None:
    """equipment_ref lives in extra_json for DB-sourced nodes, but may
    also arrive as a top-level field from in-memory/test callers —
    accept both without forcing every caller to know the DB layout."""
    ref = node.get("equipment_ref")
    if ref:
        return ref
    extra = node.get("extra_json")
    if isinstance(extra, str):
        import json
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict):
        return extra.get("equipment_ref")
    return None


def _alignment_groups(nodes: list[dict]) -> list[set[str]]:
    """Sets of node ids that must stay column-aligned across rows.
    v1 rule (per current scope): equipment_ref chains + shared area.
    Extension point for future rules (explicit engineer pins, signal
    edges) — add another grouping pass here without touching insert()."""
    by_id = {n["id"]: n for n in nodes}
    groups: dict[str, set[str]] = {}

    def _union(a: str, b: str):
        ga, gb = groups.get(a, {a}), groups.get(b, {b})
        merged = ga | gb
        for x in merged:
            groups[x] = merged

    for n in nodes:
        ref = _equipment_ref(n)
        if ref and ref in by_id:
            _union(n["id"], ref)

    by_area: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        area = n.get("area")
        if area:
            by_area[area].append(n["id"])
    for ids in by_area.values():
        if len(ids) > 1:
            for other in ids[1:]:
                _union(ids[0], other)

    seen: set[str] = set()
    out: list[set[str]] = []
    for g in groups.values():
        key = frozenset(g)
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out


# ── 3b. Chemical Process Layout Rules ───────────────────────────────────────

def _apply_chemical_process_rules(nodes: list[dict], edges: list[dict],
                                  row_of: dict[str, int], col_of: dict[str, int]) -> None:
    """Refines raw DAG topological rows and columns with chemical process
    conventions:
      1. Parallel twin equipment (e.g. R-110A & R-110B, P-101A & P-101B) share
         the same baseline row and sit in consecutive horizontal columns.
      2. Multipoint instrument arrays (e.g. TI-1103A..H) group under their
         parent equipment instead of spawning 8 independent rows.
      3. Relief / PSV headers stay anchored to the top ceiling row (row 0).
    """
    import re
    by_id = {n["id"]: n for n in nodes}

    # 1. Parallel twin equipment alignment (e.g. R-110A / R-110B)
    twin_pattern = re.compile(r"^([A-Z]{1,4}-\d{1,4})([A-Z])$")
    twins_by_base: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        lbl = str(n.get("label") or n.get("id") or "")
        m = twin_pattern.match(lbl)
        if m and (n.get("kind") or "").lower() in ("reactor", "vessel", "pump", "heat_exchanger", "column", "filter", "equipment"):
            twins_by_base[m.group(1)].append(n)

    for base, group in twins_by_base.items():
        if len(group) >= 2:
            # Sort twins by suffix letter (A, B, C...)
            group.sort(key=lambda x: str(x.get("label") or x.get("id") or ""))
            primary_id = group[0]["id"]
            if primary_id in row_of:
                baseline_row = row_of[primary_id]
                primary_col = col_of.get(primary_id, 0)
                for idx, twin in enumerate(group[1:], start=1):
                    tid = twin["id"]
                    row_of[tid] = baseline_row
                    if tid in col_of:
                        col_of[tid] = max(col_of[tid], primary_col + idx * 2)

    # 2. Multipoint sensor arrays (e.g. TI-1103A..H)
    array_pattern = re.compile(r"^([A-Z]{1,4}-\d{1,4})([A-H])$")
    arrays_by_base: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        lbl = str(n.get("label") or n.get("id") or "")
        m = array_pattern.match(lbl)
        if m and (n.get("kind") or "").lower() in ("transmitter", "indicator", "element", "sensor", "instrument", "ti", "te", "pi", "pt"):
            arrays_by_base[m.group(1)].append(n)

    for base, array_nodes in arrays_by_base.items():
        if len(array_nodes) >= 3:
            # Multi-point thermocouple / sensor array: group them near their equipment
            ref_equip_id = None
            for an in array_nodes:
                ref = _equipment_ref(an)
                if ref and ref in row_of:
                    ref_equip_id = ref
                    break
            if ref_equip_id and ref_equip_id in row_of:
                parent_row = row_of[ref_equip_id]
                parent_col = col_of.get(ref_equip_id, 0)
                for i, an in enumerate(array_nodes):
                    aid = an["id"]
                    # Cluster in parent's row/column band
                    row_of[aid] = parent_row + (1 if i >= 4 else 0)
                    col_of[aid] = parent_col + (i % 2)

    # 3. Relief PSV & Vent Headers anchored upward to row 0
    for n in nodes:
        lbl = str(n.get("label") or n.get("id") or "").upper()
        k = str(n.get("kind") or "").lower()
        if "PSV" in lbl or "RELIEF" in lbl or "VENT" in lbl or k in ("psv", "relief_valve", "relief"):
            if n["id"] in row_of:
                row_of[n["id"]] = 0

    # 4. Ingress Feed Headers anchored to column 0
    for n in nodes:
        lbl = str(n.get("label") or n.get("id") or "").upper()
        k = str(n.get("kind") or "").lower()
        if ("FEED" in lbl or "HEADER" in lbl or "INLET" in lbl or k == "off_page") and "VENT" not in lbl and "EFFLUENT" not in lbl:
            if n["id"] in col_of:
                col_of[n["id"]] = 0

    # 5. Downstream sequence enforcement (Exchangers & Separators after Reactors)
    reactor_cols = [col_of[n["id"]] for n in nodes if (n.get("kind") or "").lower() in ("reactor", "cstr", "pfr") and n["id"] in col_of]
    if reactor_cols:
        max_rx_col = max(reactor_cols)
        for n in nodes:
            k = (n.get("kind") or "").lower()
            nid = n["id"]
            if nid in col_of:
                if k in ("heat_exchanger", "condenser", "cooler") and col_of[nid] <= max_rx_col:
                    col_of[nid] = max_rx_col + 1
                elif k in ("separator", "knockout", "flash_drum", "drum") and col_of[nid] <= max_rx_col + 1:
                    col_of[nid] = max_rx_col + 2


# ── 4. Insert + propagate + compact ─────────────────────────────────────────

def compute_grid(nodes: list[dict], edges: list[dict]) -> dict:
    """Full recompute: rows, columns, alignment-propagated shift, and
    compaction. Returns {"positions": {node_id: {"row", "col"}}, "rows",
    "cols", "row_count", "col_count"}."""
    row_of = _assign_rows(nodes, edges)
    col_of = _assign_columns(nodes, edges, row_of)
    _apply_chemical_process_rules(nodes, edges, row_of, col_of)
    groups = _alignment_groups(nodes)

    # Alignment shift: within each alignment group, every member's column
    # is normalized to the group's MAX column — pulls aligned nodes into
    # the same column without moving anyone outside the group.
    for group in groups:
        cols = [col_of[m] for m in group if m in col_of]
        if not cols:
            continue
        target = max(cols)
        for m in group:
            if m in col_of:
                col_of[m] = target

    used_cols = sorted(set(col_of.values()))
    remap = {c: i for i, c in enumerate(used_cols)}   # compaction
    for nid in col_of:
        col_of[nid] = remap[col_of[nid]]

    positions = {nid: {"row": row_of[nid], "col": col_of[nid]}
                for nid in row_of}
    row_count = (max(row_of.values()) + 1) if row_of else 0
    col_count = (max(col_of.values()) + 1) if col_of else 0
    return {"positions": positions, "row_count": row_count,
            "col_count": col_count}


# ── Persistence ──────────────────────────────────────────────────────────────

def save_grid(pid: str, grid: dict) -> None:
    from adapters.db import get_db
    db = get_db()
    db.execute("DELETE FROM grid_positions WHERE pid=?", (pid,))
    db.executemany(
        "INSERT INTO grid_positions (pid, node_id, row_idx, col_idx) "
        "VALUES (?,?,?,?)",
        [(pid, nid, p["row"], p["col"])
         for nid, p in grid["positions"].items()])
    db.commit()


def load_grid(pid: str) -> dict:
    from adapters.db import get_db
    rows = get_db().execute(
        "SELECT node_id, row_idx, col_idx FROM grid_positions WHERE pid=?",
        (pid,)).fetchall()
    positions = {r[0]: {"row": r[1], "col": r[2]} for r in rows}
    row_count = (max((p["row"] for p in positions.values()), default=-1) + 1)
    col_count = (max((p["col"] for p in positions.values()), default=-1) + 1)
    return {"positions": positions, "row_count": row_count,
            "col_count": col_count}


# ── Graph node (post-write hook) ─────────────────────────────────────────────

def recompute_grid_node(state: ExtractionState) -> dict:
    """Extraction-style node signature (state in, delta out) for reuse
    in that workflow's graph shape if ever wired there directly. The
    Describe-side hook calls compute_grid()/save_grid() straight, since
    Describe's state doesn't carry the full node/edge lists."""
    nodes = state.get("verified_nodes") or []
    edges = state.get("verified_edges") or []
    grid = compute_grid(nodes, edges)
    emit_stage(STAGE, "complete", rows=grid["row_count"],
               cols=grid["col_count"], nodes=len(grid["positions"]))
    return {"qc_reports": [qc_report(
        STAGE, "ok",
        {"rows": grid["row_count"], "cols": grid["col_count"]},
        "proceed", "grid recomputed", "rules")]}
