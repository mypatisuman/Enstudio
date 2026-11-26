"""
export_dxf_cli.py — standalone DXF export for a project.
Usage: python export_dxf_cli.py <project_id>
Reads nodes/edges from studio.db, generates DXF via adapters/dxf.py,
writes to <hub>/<pid>/exports/<pid>_pid.dxf
Prints the output filename to stdout.

Mirrors export_svg_cli.py's direct-from-DB approach — no Flask dependency.
"""
import sys
import sqlite3
from pathlib import Path

def find_db() -> Path:
    sys.path.insert(0, str(Path(__file__).parent))
    from utils.paths import resolve_database_path
    return resolve_database_path(candidates=[
        Path(__file__).parent.parent / "EngineeringHub" / "EngineeringHub" / "studio.db",
        Path(__file__).parent / "studio.db",
    ])

def main():
    if len(sys.argv) < 2:
        print("Usage: export_dxf_cli.py <project_id>", file=sys.stderr)
        sys.exit(1)

    project_id = sys.argv[1]
    preview    = '--preview' in sys.argv[2:]   # print to stdout, never write a file
    db_path    = find_db()
    hub_dir    = db_path.parent

    sys.path.insert(0, str(Path(__file__).parent))
    from adapters.dxf import generate_dxf

    conn = sqlite3.connect(str(db_path))
    try:
        node_rows = conn.execute(
            "SELECT id, label, kind, x, y, area FROM nodes WHERE pid=?",
            (project_id,)
        ).fetchall()
        if not node_rows:
            print(f"No nodes found for project {project_id!r}", file=sys.stderr)
            sys.exit(1)

        nodes = []
        for (nid, label, kind, x, y, area) in node_rows:
            nodes.append({
                "id":    nid,
                "label": label or nid,
                "kind":  kind or "equipment",
                "x":     x,
                "y":     y,
                "area":  area or "",
            })

        edges = []
        try:
            edge_rows = conn.execute(
                "SELECT from_id, to_id, kind FROM edges WHERE pid=?",
                (project_id,)
            ).fetchall()
            for (src, dst, kind) in edge_rows:
                edges.append({"from": src, "to": dst, "kind": kind or "stream"})
        except sqlite3.OperationalError:
            pass

        if not edges:
            try:
                edge_rows = conn.execute("""
                    SELECT n1.id AS src, n2.id AS dst,
                           COALESCE(c.type, 'stream') AS kind
                    FROM connections c
                    JOIN nodes n1 ON n1.label = c.from_tag AND n1.pid = c.pid
                    JOIN nodes n2 ON n2.label = c.to_tag   AND n2.pid = c.pid
                    WHERE c.pid=?
                """, (project_id,)).fetchall()
                for (src, dst, kind) in edge_rows:
                    edges.append({"from": src, "to": dst, "kind": kind})
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()

    # ── Normalise React Flow pixel coords to 0-1 range (matches export_svg_cli.py) ──
    xs = [n["x"] for n in nodes if n["x"] is not None]
    ys = [n["y"] for n in nodes if n["y"] is not None]
    if xs and ys:
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1)
        span_y = max(max_y - min_y, 1)
        for n in nodes:
            if n["x"] is not None and n["y"] is not None:
                n["x"] = (n["x"] - min_x) / span_x
                n["y"] = (n["y"] - min_y) / span_y

    dxf_bytes = generate_dxf({'nodes': nodes, 'edges': edges}, project_id)

    # Preview mode: emit the DXF content to stdout and never touch disk — so
    # clicking "Preview" doesn't silently create an export file every time.
    if preview:
        content = dxf_bytes.decode('utf-8', errors='replace') if isinstance(dxf_bytes, (bytes, bytearray)) else str(dxf_bytes)
        sys.stdout.write(content)
        return

    exports_dir = hub_dir / "projects" / project_id / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out_path = exports_dir / f"{project_id}_pid.dxf"
    out_path.write_bytes(dxf_bytes)
    print(str(out_path))

if __name__ == "__main__":
    main()
