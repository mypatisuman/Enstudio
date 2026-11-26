"""
adapters/ympl_export.py — THE YMPL writer.

WHY THIS EXISTS
---------------
There used to be two YMPL writers that disagreed:

  * Flask   controllers/export_controller.export_ympl_route: the enableSim
            document built by adapters/ympl_convert.to_enablesim_ympl, with
            an `enable:` block of instrument wiring.
  * Desktop src-tauri export.rs build_ympl_yaml: a hand-rolled topology-only
            YAML with no `enable:` block.

The same project therefore produced different YMPL depending on where it was
exported. Both surfaces now call this module: Flask directly, the desktop by
spawning export_ympl_cli.py, the same way it already spawns the SVG and DXF
exporters. The desktop's former topology-only shape stays available as an
explicit option.

Every node also carries its plant hierarchy (system / subsystem) when one is
assigned, and only real specifications ever reach the document, because
invented ones are no longer written to the graph in the first place.
"""

from __future__ import annotations

from pathlib import Path


def projects_dir() -> Path:
    from adapters import db
    return Path(db.DB_PATH).parent / "projects"


def _with_hierarchy(pid: str, nodes: list[dict]) -> list[dict]:
    try:
        from services.hierarchy import assignments
        assigned = assignments(pid)
    except Exception:
        assigned = {}
    out = []
    for n in nodes:
        n = dict(n)
        path = assigned.get(n.get("id"))
        if path:
            n["hierarchy"] = path
            for level in ("system", "subsystem"):
                if path.get(level):
                    n[level] = path[level]
        out.append(n)
    return out


def build_ympl(pid: str, topology_only: bool = False) -> dict:
    """The YMPL document for a project. Raises LookupError if it is unknown."""
    from repositories.canvas_repository import load_espx
    espx, _ = load_espx(pid, projects_dir())
    if not espx:
        raise LookupError(f"project {pid!r} not found")
    nodes = _with_hierarchy(pid, espx.get("nodes") or [])
    edges = espx.get("edges") or []

    if topology_only:
        topo_nodes = []
        for n in nodes:
            entry = {"id": n.get("id")}
            for key in ("area", "kind", "kind_detail", "label", "system", "subsystem"):
                if n.get(key):
                    entry[key] = n[key]
            entry["x"] = float(n.get("x") or 0.0)
            entry["y"] = float(n.get("y") or 0.0)
            topo_nodes.append(entry)
        topo_edges = []
        for e in edges:
            if not e.get("from") or not e.get("to"):
                continue
            entry = {"from": e["from"], "kind": e.get("kind") or "stream", "to": e["to"]}
            if e.get("label"):
                entry["label"] = e["label"]
            topo_edges.append(entry)
        return {"edges": topo_edges, "id": pid,
                "meta": {"confidence": "high", "mermaid": ""},
                "nodes": topo_nodes, "schema_version": "ympl-1.0",
                "title": espx.get("title") or pid}

    from adapters.ympl_convert import to_enablesim_ympl
    meta = espx.get("meta") or {}
    base = {"schema_version": espx.get("schema_version") or "ympl-1.0",
            "id": espx.get("id") or pid, "title": espx.get("title") or pid,
            "nodes": nodes, "edges": edges, "meta": meta}
    return to_enablesim_ympl(base, meta.get("mermaid", ""),
                             instruments=(espx.get("studio") or {}).get("instruments") or {})


def render_ympl(pid: str, topology_only: bool = False) -> str:
    import yaml
    return yaml.dump(build_ympl(pid, topology_only), allow_unicode=True,
                     default_flow_style=False)


def write_ympl(pid: str, exports_dir: Path | None = None,
               topology_only: bool = False) -> Path:
    text = render_ympl(pid, topology_only)
    target_dir = exports_dir or (projects_dir() / pid / "exports")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / (f"{pid}_topology.ympl" if topology_only else f"{pid}.ympl")
    path.write_text(text, encoding="utf-8")
    return path
