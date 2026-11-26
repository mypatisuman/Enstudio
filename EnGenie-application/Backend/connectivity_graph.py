"""
connectivity_graph.py — deterministic P&ID connectivity graph builder.

Builds a CANDIDATE connection graph directly from YOLO symbol detections and
UNet line segments, using geometry only — no LLM involved. This candidate
graph is then handed to the LLM as a PROPOSAL to audit against the original
image (confirm / correct direction / delete if wrong / add only if certain),
instead of asking the LLM to invent the whole topology from a blank slate.

Why: this session's testing showed the LLM tracing pipes from scratch on a
crowded full-sheet image reliably produces two failure classes — (a) fully
fabricated edges between unrelated pipes that never touch, and (b) the same
real pipe traced twice as near-duplicate parallel paths. Both come from the
LLM guessing at topology under a large, un-narrowed search space. Building
the candidate graph from segment geometry first removes that guesswork for
everything geometry can resolve on its own; the LLM's job narrows to the
much smaller, much more reliable task of confirming/correcting a short list.

ponytail: no junction-dot detector exists upstream yet, so a geometric
crossing between two segments that do NOT share an endpoint is NEVER
auto-joined (matches the P&ID drawing convention: no dot = not connected).
Such crossings are reported as `ambiguous_crossings` for the LLM to resolve
by looking at the image, rather than guessed at here. If a real junction-dot
detector is added later, wire its output in here instead of always saying no.
"""
from __future__ import annotations
import math

SNAP_TOLERANCE_PX_DEFAULT = 35.0  # symbol-bbox matching radius — kept loose
                                   # since a segment often falls short of the
                                   # actual symbol shape (matches
                                   # _snap_segments_to_symbols' snap_px scale)
ENDPOINT_CLUSTER_TOL_PX = 18.0     # endpoint-to-endpoint clustering radius —
                                   # kept TIGHT and deliberately separate from
                                   # SNAP_TOLERANCE_PX_DEFAULT. Union-find
                                   # clustering is transitive (A-B, B-C chains
                                   # even when A and C are far apart), so a
                                   # loose tolerance here lets a cluster's
                                   # average point drift well outside range of
                                   # the symbol it should have matched. Same
                                   # lesson Engram's connectivity.py already
                                   # learned for T-junction matching (25px -> 10px).
FALLBACK_SNAP_MULTIPLIER = 2.0     # second, widened pass in _closest_symbol —
                                   # Engram's connectivity.py gives up only
                                   # after SNAP_TOLERANCE * 2; a single hard
                                   # cutoff at 35 px was orphaning real tap
                                   # stubs whose far end sat 59-60 px from the
                                   # symbol they feed.
NEAR_MISS_RADIUS_PX = 250.0        # stub-to-symbol search radius for candidates
                                    # geometry can't confirm alone (segment fell
                                    # short of the real target) — flagged for the
                                    # LLM to resolve by looking at the image


def _dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_to_bbox_dist(pt: tuple, bbox: list) -> float:
    x1, y1, x2, y2 = bbox
    dx = max(x1 - pt[0], 0.0, pt[0] - x2)
    dy = max(y1 - pt[1], 0.0, pt[1] - y2)
    return math.hypot(dx, dy)


def _point_strictly_inside(pt: tuple, bbox: list) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2


def _closest_symbol(pt: tuple, symbols: list[dict], tol: float) -> int | None:
    """Index of the best-matching symbol for pt, else None.

    Tiered, following Engram's connectivity.py `_find_node_at_point`. Engram
    tries six priorities in order and only gives up after a widened pass at
    SNAP_TOLERANCE * 2; this had a single hard cutoff at `tol` and returned
    None past it. Four of Engram's six priorities key on node types this
    pipeline does not produce (t_junction, terminal_junction,
    expansion_joint_endpoint, endpoint_share), so what is ported here is the
    part that needs only bboxes and a point:

      1. strictly INSIDE a bbox — always wins over a merely-nearby symbol,
         even one whose centre is numerically closer. Two components can sit
         close together, and "the line ends inside this shape" is much
         stronger evidence than raw distance.
      2. nearest bbox within `tol`.
      3. nearest bbox within `tol * FALLBACK_SNAP_MULTIPLIER`.

    Tier 3 is what recovers the case this was measurably losing: a tap stub
    whose far end lands 59-60 px from the filter it feeds. At tol=35 the old
    cutoff rejected it, the segment matched nothing, and — because it became
    neither an edge nor an open stub nor an ambiguous crossing — it appeared
    nowhere in the LLM prompt either. 17 of 109 segments on p-id-1 were being
    dropped that way.

    The widened tier is deliberately NOT applied when the caller already
    passes a wide radius (the NEAR_MISS_RADIUS_PX = 250 near-miss search):
    doubling 250 would reach half the sheet. Guarded on tol so that call
    keeps its exact previous behaviour.
    """
    for i, s in enumerate(symbols):
        if _point_strictly_inside(pt, s['bbox']):
            return i

    radii = [tol]
    if tol <= SNAP_TOLERANCE_PX_DEFAULT * 1.5:
        radii.append(tol * FALLBACK_SNAP_MULTIPLIER)

    for radius in radii:
        best_i, best_d = None, radius
        for i, s in enumerate(symbols):
            d = _point_to_bbox_dist(pt, s['bbox'])
            if d <= best_d:
                best_d, best_i = d, i
        if best_i is not None:
            return best_i
    return None


def _point_on_segment_interior(pt, seg_a, seg_b, tol, margin):
    """If pt projects onto the INTERIOR of segment seg_a-seg_b — not near
    either endpoint, guarded by `margin` so this never fires for an ordinary
    endpoint-to-endpoint match — within perpendicular distance `tol`, return
    the projected point; else None."""
    ax, ay = seg_a
    bx, by = seg_b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-6:
        return None
    t = ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / length_sq
    if t <= 0.0 or t >= 1.0:
        return None  # projects outside the segment's own span entirely
    proj = (ax + t * dx, ay + t * dy)
    # Guard against double-handling: skip only if ORDINARY endpoint clustering
    # would already connect this tap (i.e. the ACTUAL tap point pt is close
    # enough to one of the host's own endpoints for normal clustering to
    # catch it). Checking the PROJECTED point instead of pt here was the bug
    # that let this exact case fall through: the projection can land close to
    # a host endpoint even when the real tap point — which is what endpoint
    # clustering actually compares — is just outside clustering tolerance.
    if _dist(pt, seg_a) < margin or _dist(pt, seg_b) < margin:
        return None  # too close to a real endpoint — ordinary clustering handles this
    if _dist(pt, proj) > tol:
        return None
    return t, proj


CROSSOVER_GAP_TOL_PX = 120.0    # matches Engram-Main's detect_crossovers.py GAP_TOLERANCE
CROSSOVER_ALIGN_TOL_PX = 25.0   # matches Engram-Main's ALIGNMENT_TOLERANCE


def _bridge_crossover_gaps(lines: list[dict]) -> list[dict]:
    """Port of Engram-Main's detect_crossovers.py — pure geometry, no vision
    model. Two same-direction lines (both horizontal, or both vertical)
    nearly aligned on their perpendicular axis, separated by a small gap,
    are almost certainly the SAME physical pipe — UNLESS confirmed further:
    if a PERPENDICULAR line crosses exactly through that gap's centre, this
    is the standard P&ID convention of leaving a break in one pipe where
    another crosses it, to show they do NOT connect. Without this check, the
    two dead-end stubs flanking the gap would cluster with the crossing
    line's nearby endpoint into a false junction (exactly the "crossover
    mistaken for a junction" failure this was written to fix) — no junction-
    dot detector needed, since the gap-plus-perpendicular-crossing pattern
    is itself sufficient evidence.
    """
    def axis_entries(indices_and_lines, is_h):
        entries = []
        for i, l in indices_and_lines:
            if is_h:
                pos = (l['y1'] + l['y2']) / 2
                lo, hi = sorted((l['x1'], l['x2']))
            else:
                pos = (l['x1'] + l['x2']) / 2
                lo, hi = sorted((l['y1'], l['y2']))
            entries.append({'i': i, 'pos': pos, 'lo': lo, 'hi': hi})
        entries.sort(key=lambda e: (e['pos'], e['lo']))
        return entries

    h = [(i, l) for i, l in enumerate(lines) if l.get('direction') == 'horizontal']
    v = [(i, l) for i, l in enumerate(lines) if l.get('direction') == 'vertical']
    h_entries = axis_entries(h, True)
    v_entries = axis_entries(v, False)

    consumed: set[int] = set()
    bridged: list[dict] = []

    def try_bridge(entries, cross_entries, is_h):
        n = len(entries)
        for a in range(n):
            if entries[a]['i'] in consumed:
                continue
            for b in range(a + 1, n):
                if entries[b]['i'] in consumed:
                    continue
                if entries[b]['pos'] - entries[a]['pos'] > CROSSOVER_ALIGN_TOL_PX:
                    break
                gap = entries[b]['lo'] - entries[a]['hi']
                if not (0 < gap < CROSSOVER_GAP_TOL_PX):
                    continue
                gap_along = (entries[a]['hi'] + entries[b]['lo']) / 2
                gap_pos = (entries[a]['pos'] + entries[b]['pos']) / 2
                gx, gy = (gap_along, gap_pos) if is_h else (gap_pos, gap_along)
                if is_h:
                    crossed = any(abs(c['pos'] - gx) < CROSSOVER_ALIGN_TOL_PX
                                  and c['lo'] - 10 <= gy <= c['hi'] + 10
                                  for c in cross_entries)
                else:
                    crossed = any(abs(c['pos'] - gy) < CROSSOVER_ALIGN_TOL_PX
                                  and c['lo'] - 10 <= gx <= c['hi'] + 10
                                  for c in cross_entries)
                if not crossed:
                    continue
                host = lines[entries[a]['i']]
                merged = dict(host)
                if is_h:
                    merged['x1'], merged['y1'] = entries[a]['lo'], gap_pos
                    merged['x2'], merged['y2'] = entries[b]['hi'], gap_pos
                else:
                    merged['x1'], merged['y1'] = gap_pos, entries[a]['lo']
                    merged['x2'], merged['y2'] = gap_pos, entries[b]['hi']
                bridged.append(merged)
                consumed.add(entries[a]['i'])
                consumed.add(entries[b]['i'])
                break

    try_bridge(h_entries, v_entries, True)
    try_bridge(v_entries, h_entries, False)

    kept = [l for i, l in enumerate(lines) if i not in consumed]
    return kept + bridged


def _dedupe_near_identical_lines(lines: list[dict], tol: float = 6.0) -> list[dict]:
    """Drop duplicate line detections — the same physical stub/segment
    reported twice by the UNet detector at a ~1-4px offset, common in
    tightly-packed instrument-tap clusters. Left in, a duplicate pair gets
    treated as "2 segments support this edge" and independently chained by
    _chain_pixel_segments, producing a zigzag waypoint path (down, back up,
    down again) instead of one clean line — and can bridge two unrelated
    nearby symbols into a fabricated edge that a single real segment
    wouldn't have reached on its own. It can also inflate a junction's
    apparent degree (a real 3-way point misread as a 4-way one) when the
    duplicate pair's endpoints land right at the junction.

    tol was 3.0 — too tight to catch a confirmed real-world duplicate pair
    4px apart (both endpoints), which survived and inflated a junction from
    degree 3 to 4. Widened to 6.0, still far below the ~15px gap seen
    between two genuinely SEPARATE parallel headers on a denser drawing
    (p-id-3) — that case must never be caught here, since those are real,
    distinct pipes, not a duplicate detection.
    """
    kept: list[dict] = []
    for l in lines:
        a, b = (l['x1'], l['y1']), (l['x2'], l['y2'])
        is_dup = False
        for k in kept:
            ka, kb = (k['x1'], k['y1']), (k['x2'], k['y2'])
            if (_dist(a, ka) <= tol and _dist(b, kb) <= tol) or \
               (_dist(a, kb) <= tol and _dist(b, ka) <= tol):
                is_dup = True
                break
        if not is_dup:
            kept.append(l)
    return kept


def _split_lines_at_taps(
    lines: list[dict],
    symbols: list[dict] | None = None,
    tol: float = 15.0,
    margin: float | None = None,
) -> list[dict]:
    """Pre-process: whenever one line's endpoint lands on the INTERIOR of a
    different line — a T-tap partway along it, not at either end — split the
    host line into two at that point so the tap becomes a real SHARED
    ENDPOINT that the normal endpoint-clustering step can recognize.

    Without this, a mid-span tap either falls through entirely (both its
    real endpoint and the host line's own endpoints are too far apart for
    endpoint clustering to connect them) or — worse — gets wrongly matched
    to whichever SYMBOL happens to sit geometrically nearby via the loose
    bbox-distance fallback, fabricating a direct edge to that symbol instead
    of correctly representing "this taps onto the pipe that runs through
    here." That exact failure produced a phantom direct edge between two
    valves that were never piped together — each merely tapped its own
    outlet onto a shared header line a short distance away.

    Also splits at a SYMBOL's own centre when it sits on a line's interior
    with no line endpoint anywhere near it — mirrors Engram's connectivity.py
    threading component ports along a line's point sequence. Without this, an
    inline component (e.g. a valve drawn on an unbroken pipe segment) is
    invisible to endpoint clustering entirely and silently drops into
    unmatched_symbols even though the line clearly runs through it.
    """
    if margin is None:
        margin = ENDPOINT_CLUSTER_TOL_PX
    symbols = symbols or []

    result: list[dict] = []
    for host_idx, host in enumerate(lines):
        a = (host['x1'], host['y1'])
        b = (host['x2'], host['y2'])
        taps: list[tuple[float, tuple[float, float]]] = []
        for other_idx, other in enumerate(lines):
            if other_idx == host_idx:
                continue
            for ex, ey in ((other['x1'], other['y1']), (other['x2'], other['y2'])):
                hit = _point_on_segment_interior((ex, ey), a, b, tol, margin)
                if hit is not None:
                    taps.append(hit)
        for s in symbols:
            x1, y1, x2, y2 = s['bbox']
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            hit = _point_on_segment_interior((cx, cy), a, b, tol, margin)
            if hit is not None:
                taps.append(hit)
        if not taps:
            result.append(host)
            continue

        taps.sort(key=lambda ht: ht[0])
        clean_taps: list[tuple[float, tuple[float, float]]] = []
        for t, pt in taps:
            if clean_taps and _dist(pt, clean_taps[-1][1]) < margin:
                continue  # dedupe near-identical tap points on the same host
            clean_taps.append((t, pt))

        chain = [a] + [pt for _, pt in clean_taps] + [b]
        for i in range(len(chain) - 1):
            p0, p1 = chain[i], chain[i + 1]
            seg = dict(host)
            seg['x1'], seg['y1'] = p0
            seg['x2'], seg['y2'] = p1
            result.append(seg)
    return result


def _segments_intersect(p1, p2, p3, p4):
    """True midpoint-crossing test for two segments (p1-p2) and (p3-p4).
    Returns the intersection point if they cross strictly within both
    segments' interiors (not just near an endpoint), else None."""
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-9:
        return None  # parallel
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / d
    # require the crossing to be well inside both segments (not near an end,
    # those are handled by endpoint clustering instead)
    margin = 0.08
    if margin < t < 1 - margin and margin < u < 1 - margin:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_geometric_connectivity(
    symbols: list[dict],
    lines: list[dict],
    snap_tol: float = SNAP_TOLERANCE_PX_DEFAULT,
) -> dict:
    """
    symbols: [{'bbox': [x1,y1,x2,y2], 'type': str, ...}, ...] — index i is node "n{i+1}"
    lines:   [{'x1','y1','x2','y2','direction','kind'}, ...]  — pixel coords,
              already filtered of degenerate/stub artifacts

    Returns:
      {
        'edges': [
          {'from': 'n3' | 'gj_0', 'to': 'n7' | 'gj_1',
           'line_indices': [...], 'kind': 'process'|'signal'},
          ...
        ],
        'junctions': [{'id': 'gj_0', 'x': px, 'y': py, 'degree': int}],
        'ambiguous_crossings': [{'x': px, 'y': py, 'line_indices': [i, j]}],
        'open_stubs': [{'x': px, 'y': py, 'line_index': i}],
        'lines': [...],  # possibly SPLIT from the input `lines` (see
                         # _split_lines_at_taps) — 'line_indices' on edges/
                         # stubs/ambiguous_crossings index into THIS list, not
                         # the original input. Callers building waypoints from
                         # line_indices must use geo['lines'], not their own
                         # original raw_lines list.
      }
    Symbol node ids follow the SAME convention as prompts.py NODE IDS &
    REQUIRED FIELDS: symbol at `symbols[i]` -> id "n{i+1}".
    """
    if not lines:
        return {'edges': [], 'junctions': [], 'ambiguous_crossings': [], 'open_stubs': [],
                'unmatched_symbols': [], 'unreached_segments': [], 'lines': []}

    lines = _dedupe_near_identical_lines(lines)
    lines = _bridge_crossover_gaps(lines)

    # Split any line wherever another line's endpoint taps onto its INTERIOR
    # (not at either end) — turns a mid-span T-tap into a real shared
    # endpoint so the clustering below recognizes it as a true junction
    # instead of either missing it or mismatching it to a nearby symbol.
    lines = _split_lines_at_taps(lines, symbols)

    # ---- Step 1: cluster line endpoints within ENDPOINT_CLUSTER_TOL_PX ----
    endpoints: list[tuple[int, int, tuple[float, float]]] = []
    for i, l in enumerate(lines):
        endpoints.append((i, 0, (l['x1'], l['y1'])))
        endpoints.append((i, 1, (l['x2'], l['y2'])))

    uf = _UnionFind()
    ekeys = [f"{i}:{w}" for i, w, _ in endpoints]
    epts  = {f"{i}:{w}": p for i, w, p in endpoints}

    # Greedy, nearest-pair-first union that REJECTS any merge which would
    # collapse a single line's own two endpoints into one cluster — directly
    # (ia==ib, as before) or TRANSITIVELY through a chain of other merges.
    # A naive "union everything within tolerance" is exactly what caused a
    # short split-created segment's two ends to fuse together via an
    # unrelated third point bridging them, turning a real edge into a
    # self-loop that then got silently dropped. Processing nearest pairs
    # first and checking for a would-be collision before each union prevents
    # this the same way Kruskal's MST avoids forming a cycle.
    candidates: list[tuple[float, str, str]] = []
    for a in range(len(endpoints)):
        for b in range(a + 1, len(endpoints)):
            ia, _, pa = endpoints[a]
            ib, _, pb = endpoints[b]
            if ia == ib:
                continue  # a single line's own two ends never cluster together
            d = _dist(pa, pb)
            if d <= ENDPOINT_CLUSTER_TOL_PX:
                candidates.append((d, ekeys[a], ekeys[b]))
    candidates.sort(key=lambda c: c[0])

    root_lines: dict[str, set[int]] = {k: {int(k.split(':')[0])} for k in ekeys}
    for _d, ka, kb in candidates:
        ra, rb = uf.find(ka), uf.find(kb)
        if ra == rb:
            continue
        la = root_lines.setdefault(ra, {int(ra.split(':')[0])})
        lb = root_lines.setdefault(rb, {int(rb.split(':')[0])})
        if la & lb:
            continue  # would fuse some line's own two endpoints — reject
        uf.union(ka, kb)
        root_lines[uf.find(ka)] = la | lb

    clusters: dict[str, list[str]] = {}
    for k in ekeys:
        clusters.setdefault(uf.find(k), []).append(k)

    # ---- Step 2: classify each cluster ----
    # 'symbol'  -> touches a symbol bbox: real node, id "n{i+1}"
    # 'junction'-> no symbol, 3+ distinct lines meeting: real node, id "gj_N"
    # 'pass'    -> no symbol, exactly 2 distinct lines: a bend, collapse it
    # 'stub'    -> no symbol, exactly 1 line: open end, no edge
    cluster_point: dict[str, tuple[float, float]] = {}
    cluster_symbol: dict[str, int] = {}
    cluster_lines: dict[str, set[int]] = {}
    for root, members in clusters.items():
        pts = [epts[m] for m in members]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cluster_point[root] = (cx, cy)
        cluster_lines[root] = {int(m.split(':')[0]) for m in members}
        n_lines = len(cluster_lines[root])
        if n_lines >= 3:
            # A point where 3+ distinct lines genuinely meet is real junction
            # evidence — a loose nearby-symbol match must NOT override that
            # (that's exactly what silently swallowed a real 3-way T-tap into
            # "this is just the valve" and fabricated a direct valve-to-valve
            # edge). Only a STRICT bbox-containment match is strong enough
            # evidence to override a genuine multi-line junction.
            sym_i = None
            for i, s in enumerate(symbols):
                if _point_strictly_inside((cx, cy), s['bbox']):
                    sym_i = i
                    break
        else:
            sym_i = _closest_symbol((cx, cy), symbols, snap_tol)
        if sym_i is not None:
            cluster_symbol[root] = sym_i

    def cluster_kind(root: str) -> str:
        if root in cluster_symbol:
            return 'symbol'
        n = len(cluster_lines[root])
        if n >= 3:
            return 'junction'
        if n == 2:
            return 'pass'
        return 'stub'

    def cluster_node_id(root: str, junction_ids: dict[str, str]) -> str:
        if root in cluster_symbol:
            return f"n{cluster_symbol[root] + 1}"
        return junction_ids[root]

    # Assign junction ids only to clusters that end up classified 'junction'
    junction_ids: dict[str, str] = {}
    jcount = 0
    for root in clusters:
        if cluster_kind(root) == 'junction':
            junction_ids[root] = f"gj_{jcount}"
            jcount += 1

    # ---- Step 3: build the line graph (line i connects its two clusters) ----
    line_root: list[tuple[str, str]] = []
    for i, l in enumerate(lines):
        r0 = uf.find(f"{i}:0")
        r1 = uf.find(f"{i}:1")
        line_root.append((r0, r1))

    # adjacency: cluster root -> list of (line_index, other_root)
    adj: dict[str, list[tuple[int, str]]] = {}
    for i, (r0, r1) in enumerate(line_root):
        adj.setdefault(r0, []).append((i, r1))
        adj.setdefault(r1, []).append((i, r0))

    # ---- Step 4: walk from every real node (symbol/junction) through any
    # chain of 'pass' clusters until reaching another real node or a stub.
    # This collapses bends into a single edge with the full line-index path,
    # so a bent pipe becomes ONE proposed edge, not several fragments. ----
    real_roots = [r for r in clusters if cluster_kind(r) in ('symbol', 'junction')]
    edges: list[dict] = []
    open_stubs: list[dict] = []
    seen_traversal: set[tuple[int, str]] = set()  # (line_index, direction_root) already walked

    def walk(start_root: str, first_line_idx: int, first_other_root: str):
        path_lines = [first_line_idx]
        cur_root = first_other_root
        prev_line = first_line_idx
        guard = 0
        while cluster_kind(cur_root) == 'pass' and guard < 500:
            guard += 1
            nxt = None
            for li, other in adj.get(cur_root, []):
                if li != prev_line:
                    nxt = (li, other)
                    break
            if nxt is None:
                return None  # dead end mid-chain (shouldn't happen for a true 'pass' node)
            li, other = nxt
            path_lines.append(li)
            prev_line = li
            cur_root = other
        if cluster_kind(cur_root) == 'stub':
            return None  # ended at an open stub, not a real connection
        return cur_root, path_lines

    for root in real_roots:
        node_id = cluster_node_id(root, junction_ids)
        for line_idx, other_root in adj.get(root, []):
            trav_key = (line_idx, root)
            if trav_key in seen_traversal:
                continue
            result = walk(root, line_idx, other_root)
            if result is None:
                # Unresolved dead end. Geometry alone can't confirm a
                # connection here — either it's a genuine open stub (drain,
                # vent, sheet edge), or the detected segment fell short of
                # its real target (a common UNet gap on long runs to header
                # connectors). Report the nearest symbol within
                # NEAR_MISS_RADIUS_PX as a candidate for the LLM to confirm
                # by looking at the image — never auto-connect it here.
                far_pt = cluster_point.get(other_root, cluster_point[root])
                nearest = _closest_symbol(far_pt, symbols, NEAR_MISS_RADIUS_PX)
                # Self-referential stubs (nearest candidate == the symbol the
                # stub itself came from) are never a real connection — a pipe
                # can't tap onto its own origin. This is exactly the pattern
                # the ISA filter/strainer icon's own decorative arrow-and-cap
                # stroke produces: a short dangling line whose only "nearby
                # symbol" is the Filter itself. Drop these outright instead of
                # surfacing them as noise for the LLM to always reject.
                candidate_id = f"n{nearest + 1}" if nearest is not None else None
                if candidate_id == node_id:
                    seen_traversal.add(trav_key)
                    continue
                stub = {'x': far_pt[0], 'y': far_pt[1], 'line_index': line_idx,
                        'from': node_id}
                if candidate_id is not None:
                    stub['candidate_symbol'] = candidate_id
                open_stubs.append(stub)
                seen_traversal.add(trav_key)
                continue
            end_root, path_lines = result
            # mark all traversal directions along this path as seen so we
            # don't emit the same physical edge twice from the other end
            seen_traversal.add(trav_key)
            for pl in path_lines:
                seen_traversal.add((pl, end_root))
            end_id = cluster_node_id(end_root, junction_ids)
            if node_id == end_id:
                continue  # self-loop artifact, skip
            # Merge into an existing edge between the same two nodes (multiple
            # detected segments between one symbol pair — e.g. a nameplate's
            # two leader-line strokes — almost always represent ONE physical
            # connection candidate, not several; keep it as a single proposal
            # with all contributing segments listed, for a cleaner LLM audit).
            pair = frozenset((node_id, end_id))
            existing = next((e for e in edges if frozenset((e['from'], e['to'])) == pair), None)
            if existing:
                existing['line_indices'] = list(set(existing['line_indices']) | set(path_lines))
                continue
            kinds = {lines[i].get('kind', 'process') for i in path_lines}
            edges.append({
                'from': node_id,
                'to': end_id,
                'line_indices': path_lines,
                'kind': 'signal' if 'signal' in kinds else 'process',
            })

    junctions_out = [
        {'id': jid, 'x': cluster_point[root][0], 'y': cluster_point[root][1],
         'degree': len(cluster_lines[root])}
        for root, jid in junction_ids.items()
    ]

    # ponytail: a prior version of this step absorbed a junction into a
    # nearby symbol whenever the offset was small (~30-50px), on the theory
    # that YOLO/UNet detector disagreement was the only thing that could
    # produce that gap. Proven wrong on a real case: ISA drawings also place
    # a genuine tee fitting a small, deliberate distance from an inline valve
    # — same magnitude offset, opposite meaning (a real distinct node, not
    # jitter). Distance alone can't tell the two apart, so merging by
    # distance silently destroys real topology as often as it fixes noise.
    # Removed; the honest fix for the jitter case is cosmetic waypoint
    # straightening only (_chain_pixel_segments in extract_cli.py), which
    # never deletes a real node.

    # ---- Step 5: ambiguous mid-segment crossings (no shared endpoint) ----
    ambiguous = []
    n = len(lines)
    for i in range(n):
        for j in range(i + 1, n):
            p = _segments_intersect(
                (lines[i]['x1'], lines[i]['y1']), (lines[i]['x2'], lines[i]['y2']),
                (lines[j]['x1'], lines[j]['y1']), (lines[j]['x2'], lines[j]['y2']),
            )
            if p:
                ambiguous.append({'x': p[0], 'y': p[1], 'line_indices': [i, j]})

    # ---- Step 6: symbols with ZERO geometric coverage at all ----
    # Not the same as an open stub — a stub has a real detected line that just
    # didn't reach a confirmed target. These symbols have no nearby detected
    # line whatsoever (a genuine upstream detection gap, common on crowded/
    # repetitive drawings). The strict audit design deliberately never invents
    # edges beyond the candidate list, so without this category these symbols
    # would be permanently invisible to the LLM even when the image clearly
    # shows a connection. Surfaced separately so the LLM can still check them
    # against the image and add — under the same 100%-certain discipline —
    # without reopening blank-slate tracing for everything else.
    covered_symbol_ids: set[str] = set()
    for e in edges:
        covered_symbol_ids.add(e['from'])
        covered_symbol_ids.add(e['to'])
    for s in open_stubs:
        if s.get('from'):
            covered_symbol_ids.add(s['from'])
    unmatched_symbols = [
        f"n{i + 1}" for i in range(len(symbols))
        if f"n{i + 1}" not in covered_symbol_ids
    ]

    # For each unmatched symbol, the nearest OTHER symbol and how far away it
    # is. Geometry cannot join them — there is no detected line to join them
    # with — but "this tank's nearest neighbour is a ball valve 21 px away" is
    # a concrete pair the LLM can check against the image, where a bare list of
    # ten unmatched tanks is not.
    #
    # Measured on p-id-1: all ten unmatched symbols were tanks, each sitting
    # ~21 px from its own ball valve. The tank-to-valve nozzle is a couple of
    # pixels of pipe between two glyphs, so UNet never detects it as its own
    # component and the tank has nothing to match. The pair is obvious in the
    # image and invisible to geometry — exactly the case the audit stage is for.
    unmatched_detail: list[dict] = []
    for nid in unmatched_symbols:
        i = int(nid[1:]) - 1
        cx = (symbols[i]['bbox'][0] + symbols[i]['bbox'][2]) / 2.0
        cy = (symbols[i]['bbox'][1] + symbols[i]['bbox'][3]) / 2.0
        best_j, best_d = None, None
        for j, s in enumerate(symbols):
            if j == i:
                continue
            d = _point_to_bbox_dist((cx, cy), s['bbox'])
            if best_d is None or d < best_d:
                best_d, best_j = d, j
        entry = {'id': nid}
        if best_j is not None and best_d is not None:
            entry['nearest'] = f"n{best_j + 1}"
            entry['distance_px'] = round(best_d, 1)
        unmatched_detail.append(entry)

    # ---- Segments no traversal ever reached ---------------------------------
    # A segment becomes an edge only if a walk starts from a real node (a
    # cluster matched to a symbol, or one where 3+ lines meet). A segment whose
    # BOTH endpoints cluster to neither — no symbol within snap_tol, fewer than
    # three lines meeting — belongs to no real node, so no walk ever visits it.
    # It was then reported nowhere: not an edge, not an open stub, not an
    # ambiguous crossing. The LLM never learned it existed and could not
    # confirm a pipe it was never shown.
    #
    # Measured on p-id-1: an L-shaped run to a header outlet,
    # (3618,2542)->(3618,2721) then (3620,2723)->(4619,2723), 179 px + 999 px,
    # vanished exactly this way.
    #
    # Self-referential segments are NOT reported here, for the same reason
    # open_stubs drops them: a symbol's own icon strokes (the ISA filter's
    # arrow-and-cap, a heat exchanger's internals) detect as short lines whose
    # only nearby symbol is the symbol itself. 14 of p-id-1's 17 unreached
    # segments were exactly that, and surfacing them would be pure noise.
    referenced: set[int] = set()
    for e in edges:
        referenced.update(e['line_indices'])
    for s in open_stubs:
        if s.get('line_index') is not None:
            referenced.add(s['line_index'])
    for a in ambiguous:
        referenced.update(a.get('line_indices', []))

    unreached: list[dict] = []
    for i, l in enumerate(lines):
        if i in referenced:
            continue
        a_pt, b_pt = (l['x1'], l['y1']), (l['x2'], l['y2'])
        na = _closest_symbol(a_pt, symbols, NEAR_MISS_RADIUS_PX)
        nb = _closest_symbol(b_pt, symbols, NEAR_MISS_RADIUS_PX)
        if na is None and nb is None:
            continue                      # nothing to attach it to; noise
        if na is not None and na == nb:
            continue                      # the symbol's own icon strokes
        entry = {'line_index': i, 'x1': a_pt[0], 'y1': a_pt[1],
                 'x2': b_pt[0], 'y2': b_pt[1], 'kind': l.get('kind', 'process')}
        if na is not None:
            entry['candidate_from'] = f"n{na + 1}"
        if nb is not None:
            entry['candidate_to'] = f"n{nb + 1}"
        unreached.append(entry)

    return {
        'edges': edges,
        'junctions': junctions_out,
        'ambiguous_crossings': ambiguous,
        'open_stubs': open_stubs,
        'unmatched_symbols': unmatched_symbols,
        'unmatched_symbols_detail': unmatched_detail,
        'unreached_segments': unreached,
        'lines': lines,  # possibly split — line_indices refer to THIS list
    }


def _demo():
    """Self-check: an inline valve sits mid-span on one continuous pipe
    segment between two tanks, with no line break at the valve — the case
    _split_lines_at_taps' symbol-tap pass exists to catch."""
    symbols = [
        {'bbox': [0, 0, 10, 10], 'type': 'Tank'},        # n1
        {'bbox': [95, -5, 105, 5], 'type': 'Ball_Valve'},  # n2, sits mid-span
        {'bbox': [190, 0, 200, 10], 'type': 'Tank'},       # n3
    ]
    lines = [{'x1': 5, 'y1': 5, 'x2': 195, 'y2': 5, 'direction': 'horizontal', 'kind': 'process'}]
    geo = build_geometric_connectivity(symbols, lines)
    ids = {frozenset((e['from'], e['to'])) for e in geo['edges']}
    assert frozenset(('n1', 'n2')) in ids, f"expected n1-n2 edge, got {geo['edges']}"
    assert frozenset(('n2', 'n3')) in ids, f"expected n2-n3 edge, got {geo['edges']}"
    assert 'n2' not in geo['unmatched_symbols']
    print("connectivity_graph self-check OK:", geo['edges'])


def _demo_dedupe():
    """Self-check: a duplicate near-identical vertical stub (~1px offset,
    same as the real UNet detector double-hit that fabricated a phantom
    PI-1014 <-> PI-1017 signal edge in a crowded instrument-tap cluster)
    must not survive as two separate segments feeding the graph."""
    lines = [
        {'x1': 100.0, 'y1': 100.0, 'x2': 100.0, 'y2': 150.0, 'direction': 'vertical', 'kind': 'process'},
        {'x1': 100.2, 'y1': 100.0, 'x2': 100.2, 'y2': 150.0, 'direction': 'vertical', 'kind': 'process'},
    ]
    deduped = _dedupe_near_identical_lines(lines)
    assert len(deduped) == 1, f"expected duplicate collapsed to 1 line, got {len(deduped)}"
    print("dedupe self-check OK:", deduped)


def _demo_crossover():
    """Self-check: a horizontal pipe broken into two pieces by a gap, with a
    vertical pipe crossing exactly through that gap — the standard P&ID
    "no dot = not connected" convention. Must rejoin into ONE continuous
    horizontal line, and must NOT create a junction with the vertical line."""
    lines = [
        {'x1': 0.0,   'y1': 100.0, 'x2': 190.0, 'y2': 100.0, 'direction': 'horizontal', 'kind': 'process'},
        {'x1': 210.0, 'y1': 100.0, 'x2': 400.0, 'y2': 100.0, 'direction': 'horizontal', 'kind': 'process'},
        {'x1': 200.0, 'y1': 0.0,   'x2': 200.0, 'y2': 300.0, 'direction': 'vertical',   'kind': 'process'},
    ]
    bridged = _bridge_crossover_gaps(lines)
    assert len(bridged) == 2, f"expected 2 lines after bridging (1 rejoined horizontal + 1 vertical), got {bridged}"
    h = next(l for l in bridged if l['direction'] == 'horizontal')
    assert min(h['x1'], h['x2']) == 0.0 and max(h['x1'], h['x2']) == 400.0, f"horizontal not fully rejoined: {h}"
    print("crossover self-check OK:", bridged)


if __name__ == '__main__':
    _demo()
    _demo_dedupe()
    _demo_crossover()
