"""The drawing as knowledge cards: short plain-language documents that an
embedding model can match and an LLM can read, each naming the tags it is
about so retrieval can also match them exactly and expand along the graph.

    drawing      title, origin, counts, equipment, flags, systems, warnings
    group        a system / subsystem / area: its members and their roles
    equipment    what it is, what flows in and out, the instruments on it
    instrument   ISA meaning, loop, connections, specs, vendor, accessories,
                 provenance (and the caveat for inferred / recovered items)
    loop         controller, measurement, final element, status
    run          a process path between equipment / flags, with line numbers
    design       the designed solution's objective, roles, considerations
    review       what the engineer must check: inferred / recovered /
                 untagged items, digitisation warnings, drawing quality
"""
from __future__ import annotations

from collections import defaultdict, deque

from domain.pid_rag.snapshot import SIGNAL_EDGE_KINDS, role_of

MAX_RUNS = 60
MAX_RUN_LEN = 14
_SPEC_KEYS_SKIP = {"origin", "source", "reader", "points", "x", "y", "page", "page_w", "page_h", "drawing",
                   "snapped", "inferred", "recovered", "untagged", "placeholder", "tile", "reads", "raw"}


def _isa(tag: str) -> str:
    try:
        from domain.solution.services.brownfield_vision_service import isa_description
        return isa_description(tag) or ""
    except Exception:
        return ""


def _fmt_value(v) -> str:
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_fmt_value(x)}" for k, x in v.items() if x not in (None, "", [], {}))
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt_value(x) for x in v if x not in (None, "", [], {}))
    return str(v)


def _provenance(n: dict) -> str:
    x = n["extra"]
    if x.get("inferred"):
        return "inferred from its loop and a printed note, not read as a tag - the engineer should confirm it"
    if x.get("recovered"):
        return "tag recovered from its printed lettering after the main reading missed it - confirm it"
    if x.get("untagged"):
        return "an untagged symbol on the drawing (no tag printed)"
    if x.get("placeholder"):
        return "a template placeholder tag"
    if x.get("source") == "brownfield_vision" or x.get("origin") == "extracted":
        return "read from the uploaded drawing"
    if x.get("origin") == "authored" or x.get("source") == "describe_agent":
        return "added by the design agent / engineer in this project"
    return ""


def _neighbours(snap: dict) -> dict[str, list[tuple[str, str, str, str]]]:
    """tag -> [(direction, other, kind, line label)]."""
    nb: dict[str, list] = defaultdict(list)
    for e in snap["edges"]:
        label = e["label"] or e["extra"].get("printed_line_no") or e["extra"].get("line_id") or ""
        if str(label).startswith(("L-", "e_vis_")):
            label = e["extra"].get("printed_line_no") or ""
        nb[e["from"]].append(("to", e["to"], e["kind"], label))
        nb[e["to"]].append(("from", e["from"], e["kind"], label))
    return nb


def _conn_text(items) -> str:
    parts = []
    for d, other, kind, label in items:
        bit = f"{'to' if d == 'to' else 'from'} {other} ({kind or 'line'}"
        bit += f", line {label})" if label else ")"
        parts.append(bit)
    return "; ".join(parts)


def _loop_of(tag: str, loops: list[dict]) -> dict | None:
    for lp in loops:
        members = {lp.get(k) for k in ("controller", "measurement", "final_element")}
        for k in ("indicators", "alarms", "other"):
            members.update(lp.get(k) or [])
        if tag in members:
            return lp
    return None


def _loop_text(lp: dict) -> str:
    bits = [f"loop {lp.get('loop_id')}"]
    for k in ("measurement", "controller", "final_element"):
        if lp.get(k):
            bits.append(f"{k.replace('_', ' ')} {lp[k]}")
    for k in ("indicators", "alarms", "other"):
        if lp.get(k):
            bits.append(f"{k} {', '.join(lp[k])}")
    if lp.get("status"):
        bits.append(f"status {lp['status']}")
    return ", ".join(bits)


def _card(cid: str, kind: str, tags: list[str], title: str, lines: list[str]) -> dict:
    text = title + "\n" + "\n".join(f"- {ln}" for ln in lines if ln)
    return {"id": cid, "kind": kind, "tags": sorted({t for t in tags if t}), "text": text.strip()}


def build_cards(snap: dict) -> list[dict]:
    nodes = [n for n in snap["nodes"] if n["tag"]]
    nb = _neighbours(snap)
    loops = snap.get("loops") or []
    roles = {}
    for r in ((snap.get("design") or {}).get("component_roles") or []):
        if isinstance(r, dict) and (r.get("tag") or r.get("name")):
            roles[str(r.get("tag") or r.get("name")).upper()] = r
    cards: list[dict] = []

    # ── drawing ──
    by_role = defaultdict(list)
    for n in nodes:
        by_role[role_of(n["kind"])].append(n)
    kinds = defaultdict(int)
    for n in nodes:
        kinds[n["kind"] or "unknown"] += 1
    meta = snap.get("meta") or {}
    lines = [f"origin: {snap.get('source')}",
             f"{len(nodes)} elements and {len(snap['edges'])} connections; by kind: "
             + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])),
             "equipment: " + (", ".join(f"{n['tag']} ({n['kind_detail'] or n['kind']})" for n in by_role["equipment"]) or "none"),
             "off-sheet flags / tie-ins: " + (", ".join(n["tag"] for n in by_role["terminal"]) or "none"),
             f"control loops: {len(loops)}" + (f" ({', '.join(str(l.get('loop_id')) for l in loops[:30])})" if loops else "")]
    groups = sorted({g for n in nodes for g in n["groups"]})
    if groups:
        lines.append("plant groups: " + ", ".join(groups))
    if meta.get("summary"):
        lines.append(f"summary: {meta['summary']}")
    cards.append(_card("drawing", "drawing", [n["tag"] for n in by_role["equipment"] + by_role["terminal"]],
                       f"P&ID drawing '{snap.get('title')}'", lines))

    # ── groups (hierarchy, else areas) ──
    members = defaultdict(list)
    for n in nodes:
        if n["groups"]:
            members[n["groups"][-1]].append(n)
        elif n["area"]:
            members[f"{n['area']} (area)"].append(n)
    for name, ns in sorted(members.items()):
        eq = [n["tag"] for n in ns if role_of(n["kind"]) == "equipment"]
        inst = [n["tag"] for n in ns if role_of(n["kind"]) == "instrument"]
        parent = " > ".join(ns[0]["groups"][:-1]) if ns[0]["groups"][:-1] else ""
        cards.append(_card(f"group:{name}", "group", [n["tag"] for n in ns], f"Plant group {name}",
                           [f"part of {parent}" if parent else "",
                            f"equipment: {', '.join(eq) or 'none'}",
                            f"instruments and valves: {', '.join(inst) or 'none'}"]))

    # ── equipment / instruments / flags ──
    for n in nodes:
        tag, role, x = n["tag"], role_of(n["kind"]), n["extra"]
        conns = nb.get(tag, [])
        lines = []
        what = n["kind_detail"] or n["kind"]
        isa = _isa(tag) if role == "instrument" else ""
        if isa and isa.lower() != (what or "").lower():
            lines.append(f"ISA meaning: {isa}")
        if x.get("description"):
            lines.append(f"description / notes on the drawing: {x['description']}")
        if n["groups"]:
            lines.append("belongs to " + " > ".join(n["groups"]))
        elif n["area"]:
            lines.append(f"area: {n['area']}")
        process = [c for c in conns if c[2] not in SIGNAL_EDGE_KINDS]
        signal = [c for c in conns if c[2] in SIGNAL_EDGE_KINDS]
        if process:
            lines.append("process connections: " + _conn_text(process))
        if signal:
            lines.append("signal connections: " + _conn_text(signal))
        if not conns:
            lines.append("not connected to anything on the drawing")
        if role == "equipment":
            on_it = [c[1] for c in conns if role_of(next((m["kind"] for m in nodes if m["tag"] == c[1]), "")) == "instrument"]
            if on_it:
                lines.append("instruments and valves attached: " + ", ".join(sorted(set(on_it))))
        lp = _loop_of(tag, loops)
        if lp:
            lines.append("member of " + _loop_text(lp))
        elif x.get("loop"):
            lines.append(f"loop number {x['loop']}")
        for key in ("specifications", "categorized_specs", "instrument_config"):
            if x.get(key):
                lines.append(f"{key.replace('_', ' ')}: {_fmt_value(x[key])}")
        vendor = " ".join(str(x[k]) for k in ("vendor", "model_family", "model_series", "model_number") if x.get(k))
        if vendor:
            lines.append(f"vendor / model: {vendor}")
        if x.get("standards"):
            lines.append("standards: " + _fmt_value(x["standards"]))
        accs = x.get("accessories")
        if accs:
            lines.append("accessories: " + ", ".join(
                str(a.get("productName") or a.get("name") or a.get("category") or a) if isinstance(a, dict) else str(a)
                for a in accs))
        if x.get("spec_status"):
            lines.append(f"specification source: {x['spec_status']}")
        role_info = roles.get(tag.upper())
        if role_info and role_info.get("purpose"):
            lines.append(f"design purpose: {role_info['purpose']}")
        other = {k: v for k, v in x.items() if k not in _SPEC_KEYS_SKIP and k not in (
            "description", "loop", "specifications", "categorized_specs", "instrument_config", "vendor", "model_family",
            "model_series", "model_number", "standards", "accessories", "spec_status", "equipment_ref", "line_id")
            and isinstance(v, (str, int, float)) and str(v).strip()}
        if other:
            lines.append("other attributes: " + "; ".join(f"{k}: {v}" for k, v in list(other.items())[:8]))
        prov = _provenance(n)
        if prov:
            lines.append(f"provenance: {prov}")
        title = {"equipment": "Equipment", "terminal": "Off-sheet flag / tie-in", "junction": "Junction"}.get(role, "Instrument / valve")
        cards.append(_card(f"node:{tag}", "equipment" if role == "equipment" else "flag" if role == "terminal" else "instrument",
                           [tag] + [c[1] for c in conns], f"{title} {tag} - {what}", lines))

    # ── loops ──
    for lp in loops:
        tags = [lp.get(k) for k in ("controller", "measurement", "final_element")]
        for k in ("indicators", "alarms", "other"):
            tags += list(lp.get(k) or [])
        missing = lp.get("missing") or lp.get("gaps")
        cards.append(_card(f"loop:{lp.get('loop_id')}", "loop", tags, f"Control loop {lp.get('loop_id')}",
                           [_loop_text(lp), f"missing: {_fmt_value(missing)}" if missing else ""]))

    # ── process runs between equipment / flags ──
    cards += _run_cards(snap, nb)

    # ── design rationale (greenfield) ──
    design = snap.get("design") or {}
    if design:
        lines = []
        for key in ("inferred_plant_type", "project_objective", "design_overview"):
            if design.get(key):
                lines.append(f"{key.replace('_', ' ')}: {design[key]}")
        for key in ("optimizations", "design_considerations", "assumptions", "unit_operations"):
            if design.get(key):
                lines.append(f"{key.replace('_', ' ')}: {_fmt_value(design[key])}")
        role_lines = [f"{r.get('tag') or r.get('name')}: {r.get('category', '')} - {r.get('purpose', '')}"
                      for r in design.get("component_roles") or [] if isinstance(r, dict)]
        if role_lines:
            lines.append("component roles: " + "; ".join(role_lines[:60]))
        cards.append(_card("design", "design", list(roles), "Design rationale of this P&ID", lines))

    # ── review notes ──
    flagged = [(n["tag"], _provenance(n)) for n in nodes
               if any(n["extra"].get(k) for k in ("inferred", "recovered", "untagged", "placeholder"))]
    orphans = [n["tag"] for n in nodes if not nb.get(n["tag"]) and role_of(n["kind"]) != "junction"]
    warnings = meta.get("warnings") or []
    notes = meta.get("notes") or []
    if flagged or orphans or warnings or notes:
        lines = [f"{t}: {why}" for t, why in flagged]
        if orphans:
            lines.append("elements with no connection: " + ", ".join(orphans))
        lines += [f"digitisation warning: {w}" for w in warnings]
        lines += [f"note: {w}" for w in notes]
        cards.append(_card("review", "review", [t for t, _ in flagged] + orphans,
                           "Items the engineer should review on this P&ID", lines))
    return cards


def _run_cards(snap: dict, nb: dict) -> list[dict]:
    """Process paths: from each equipment item / flag along process lines,
    through valves and in-line instruments, to the next equipment item / flag."""
    kind_of = {n["tag"]: n["kind"] for n in snap["nodes"]}
    anchors = {t for t, k in kind_of.items() if role_of(k) in ("equipment", "terminal")}
    adj = defaultdict(list)
    for e in snap["edges"]:
        if e["kind"] in SIGNAL_EDGE_KINDS:
            continue
        adj[e["from"]].append((e["to"], e))
        adj[e["to"]].append((e["from"], e))
    runs, seen = [], set()
    for start in sorted(anchors):
        q = deque([[start]])
        while q and len(runs) < MAX_RUNS:
            path = q.popleft()
            for nxt, e in adj.get(path[-1], []):
                if nxt in path or len(path) >= MAX_RUN_LEN:
                    continue
                new = path + [nxt]
                if nxt in anchors:
                    key = tuple(new) if new[0] < new[-1] else tuple(reversed(new))
                    if key not in seen:
                        seen.add(key)
                        runs.append(new)
                else:
                    q.append(new)
    out = []
    for path in runs:
        labels = set()
        for a, b in zip(path, path[1:]):
            for d, other, kind, label in nb.get(a, []):
                if other == b and label:
                    labels.add(str(label))
        lines = [" -> ".join(path)]
        middle = [t for t in path[1:-1]]
        if middle:
            lines.append("in-line items: " + ", ".join(f"{t} ({kind_of.get(t, '')})" for t in middle))
        if labels:
            lines.append("line numbers: " + ", ".join(sorted(labels)))
        out.append(_card(f"run:{path[0]}>{path[-1]}:{len(path)}", "run", path,
                         f"Process run from {path[0]} to {path[-1]}", lines))
    return out
