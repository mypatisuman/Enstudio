"""YMPL export CLI — the one YMPL writer, for the desktop app.

Usage:
    python export_ympl_cli.py <hub> <pid> [--topology-only] [--stdout]

Writes <hub>/projects/<pid>/exports/<pid>.ympl (or <pid>_topology.ympl) and
prints one JSON line: {"success", "path", "filename"}. With --stdout the YAML is
printed instead of being written.

The desktop used to build its own topology-only YAML in Rust, so desktop and
Flask exports of the same project differed. Both now go through
adapters/ympl_export.py.
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
    ap = argparse.ArgumentParser(description="Export YMPL")
    ap.add_argument("hub")
    ap.add_argument("pid")
    ap.add_argument("--topology-only", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    from adapters import db
    db.reset_for_path(Path(args.hub) / "studio.db")
    db.init_db()
    from adapters.ympl_export import render_ympl, write_ympl

    try:
        if args.stdout:
            sys.stdout.write(render_ympl(args.pid, args.topology_only))
            return 0
        path = write_ympl(args.pid, Path(args.hub) / "projects" / args.pid / "exports",
                          args.topology_only)
        print(json.dumps({"success": True, "path": str(path), "filename": path.name}))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)[:500]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
