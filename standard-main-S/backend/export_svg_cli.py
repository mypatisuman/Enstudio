"""
export_svg_cli.py — standalone ISA-5.1 SVG export for a project.

Usage: python export_svg_cli.py <project_id> [--preview] [--view full|control]
                                             [--bg dark|light]

Reads nodes/edges straight from studio.db and renders via adapters/svg_pid.py,
writing to <hub>/projects/<pid>/exports/<pid>_pid.svg and printing that path.
With --preview it writes nothing and emits the SVG on stdout instead.

No Flask dependency — the desktop app spawns this the same way it spawns
export_dxf_cli.py. Going through the Flask route instead would need a Studio
login: security.py installs a fail-closed guard that demands a Bearer token on
every /api/* route, and the desktop app holds no such token.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


def find_db() -> Path:
    sys.path.insert(0, str(Path(__file__).parent))
    from utils.paths import resolve_database_path
    return resolve_database_path(candidates=[
        Path(__file__).parent.parent / "EngineeringHub" / "EngineeringHub" / "studio.db",
        Path(__file__).parent / "studio.db",
    ])


def load_graph(conn: sqlite3.Connection, project_id: str):
    """Nodes and edges for one project, shaped as generate_svg_pid expects."""
    node_rows = conn.execute(
        "SELECT id, label, kind, kind_detail, x, y, area FROM nodes WHERE pid=?",
        (project_id,),
    ).fetchall()
    nodes = [{
        "id":          nid,
        "label":       label or nid,
        "kind":        kind or "equipment",
        "kind_detail": kd or "",
        "x":           x,
        "y":           y,
        "area":        area or "",
    } for (nid, label, kind, kd, x, y, area) in node_rows]

    edges = []
    edge_rows = conn.execute(
        "SELECT from_id, to_id, kind, label, extra_json FROM edges WHERE pid=?",
        (project_id,),
    ).fetchall()
    for (src, dst, kind, label, extra) in edge_rows:
        if not src or not dst:
            continue
        edge = {"from": src, "to": dst,
                "kind": kind or "stream", "label": label or ""}
        # Real traced pipe route. The Canvas draws these, so carrying them
        # through is what makes the exported pipe runs match the screen
        # rather than being independently re-routed.
        try:
            wp = (json.loads(extra) if extra else {}).get("waypoints")
            if wp and len(wp) >= 2:
                edge["waypoints"] = wp
        except (ValueError, TypeError, AttributeError):
            pass
        edges.append(edge)

    # Fall back to the tag-keyed connections table only when the node-keyed
    # edges table is empty — joining by label fans out into false edges
    # wherever a label repeats (see graph.rs get_graph for the same reasoning).
    if not edges:
        try:
            for (src, dst, kind) in conn.execute("""
                SELECT n1.id, n2.id, COALESCE(c.type, 'stream')
                FROM connections c
                JOIN nodes n1 ON n1.label = c.from_tag AND n1.pid = c.pid
                JOIN nodes n2 ON n2.label = c.to_tag   AND n2.pid = c.pid
                WHERE c.pid=?
            """, (project_id,)).fetchall():
                edges.append({"from": src, "to": dst, "kind": kind})
        except sqlite3.OperationalError:
            pass

    return nodes, edges


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a project as ISA-5.1 SVG")
    ap.add_argument("project_id")
    ap.add_argument("--preview", action="store_true",
                    help="write the SVG to stdout instead of a file")
    ap.add_argument("--view", default="control", choices=("control", "full"))
    ap.add_argument("--bg", default="dark", choices=("dark", "light"))
    ap.add_argument("--positions", default=None, metavar="FILE",
                    help='JSON {"node_id": [x, y]} of laid-out positions, '
                         'normally produced by the Canvas so the export '
                         'reproduces the arrangement on screen exactly')
    args = ap.parse_args()

    canvas_positions = None
    canvas_routes = None
    if args.positions:
        try:
            with open(args.positions, encoding="utf-8") as f:
                raw = json.load(f)
            # {"positions": {...}, "routes": [...]} from the Canvas, or a bare
            # {"id": [x, y]} map.
            pos_raw = raw.get("positions", raw) if isinstance(raw, dict) else {}
            canvas_positions = {
                str(k): (float(v[0]), float(v[1]))
                for k, v in pos_raw.items()
                if isinstance(v, (list, tuple)) and len(v) >= 2
            } or None
            canvas_routes = {}
            for r in (raw.get("routes") or []) if isinstance(raw, dict) else []:
                pts = [(float(p[0]), float(p[1])) for p in r.get("pts", [])
                       if isinstance(p, (list, tuple)) and len(p) >= 2]
                if len(pts) >= 2 and r.get("from") and r.get("to"):
                    canvas_routes[(str(r["from"]), str(r["to"]))] = pts
            canvas_routes = canvas_routes or None
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            # Fall back to the built-in layout rather than failing the export.
            print(f"positions file ignored ({e})", file=sys.stderr)

    db_path = find_db()
    hub_dir = db_path.parent

    sys.path.insert(0, str(Path(__file__).parent))
    from adapters.svg_pid import generate_svg_pid, ALL_LAYERS

    conn = sqlite3.connect(str(db_path))
    try:
        nodes, edges = load_graph(conn, args.project_id)
        plant_name = conn.execute(
            "SELECT COALESCE(plant_name, title, id) FROM projects WHERE id=?",
            (args.project_id,),
        ).fetchone()
        plant_name = plant_name[0] if plant_name else args.project_id
    finally:
        conn.close()

    if not nodes:
        print(f"No nodes found for project {args.project_id!r}", file=sys.stderr)
        sys.exit(1)

    svg = generate_svg_pid(
        {"nodes": nodes, "edges": edges},
        plant_name,
        layers=ALL_LAYERS if args.view == "full" else None,
        canvas_positions=canvas_positions,
        routes=canvas_routes,
        view_preset=args.view,
        background=args.bg,
    )

    # Preview mode never touches disk, so opening the preview doesn't quietly
    # create an export file each time.
    if args.preview:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(svg)
        return

    exports_dir = hub_dir / "projects" / args.project_id / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out_path = exports_dir / f"{args.project_id}_pid.svg"
    out_path.write_text(svg, encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
