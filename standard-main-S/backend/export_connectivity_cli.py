"""Connectivity graph JSON export CLI.

Usage:
    python export_connectivity_cli.py <hub> <pid> [--schema 2.0.0|2.1.0] [--stdout]

Writes <hub>/projects/<pid>/exports/<pid>_connectivity[_2_1_0].json and prints
one JSON line: {"success", "path", "filename", "schema_version", "validation_errors"}.
With --stdout the document itself is printed instead of being written.

Spawned by the desktop app (src-tauri export.rs, export_connectivity), for the
same reason it spawns the SVG/DXF exporters: the Flask /api routes require a
session token the desktop does not hold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDIO_DIR = Path(__file__).parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))


def main() -> int:
    ap = argparse.ArgumentParser(description="Export the P&ID connectivity graph JSON")
    ap.add_argument("hub")
    ap.add_argument("pid")
    ap.add_argument("--schema", default="2.0.0", choices=["2.0.0", "2.1.0"])
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    from adapters import db
    db.reset_for_path(Path(args.hub) / "studio.db")
    db.init_db()
    from adapters.connectivity_export import build_connectivity_graph, validate, write_export

    try:
        if args.stdout:
            document = build_connectivity_graph(args.pid, args.schema)
            sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False))
            return 0
        path = write_export(args.pid, Path(args.hub) / "projects" / args.pid / "exports",
                            args.schema)
        errors = validate(json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps({"success": True, "path": str(path), "filename": path.name,
                          "schema_version": args.schema, "validation_errors": len(errors)}))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)[:500]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
