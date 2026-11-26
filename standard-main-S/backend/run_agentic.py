"""Agentic extraction CLI — parallel entry point to extract_cli.py.

Usage (same positional contract as extract_cli.py):
    python run_agentic.py <hub> <pid> <source_file> [--llm-only] [--no-checkpoint]

Emits the same NDJSON progress lines on stdout, so the Tauri desktop
app's run_extraction command can be pointed here with a one-line change
once parity is signed off. Until then, this is the test harness for the
agent pipeline.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

STUDIO_DIR = Path(__file__).parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent-based P&ID extraction")
    ap.add_argument("hub")
    ap.add_argument("pid")
    ap.add_argument("source_file")
    ap.add_argument("--llm-only", action="store_true")
    # Same contract as extract_cli.py: which sources row this file is. Without
    # it the agentic engine cannot attribute nodes to a document, so a second
    # PDF extracted into the same project could not be told apart from the
    # first.
    ap.add_argument("--source-id", type=int, default=None,
                    help="sources.id for this file; scopes node/edge identity "
                         "to the document")
    ap.add_argument("--no-checkpoint", action="store_true")
    args = ap.parse_args()

    os.environ["ENGINEERING_HUB"] = args.hub

    # Create every table this process may write. Only main.py and auth.py used
    # to run init_db(), so on a hub the desktop app created (whose schema.rs
    # lacked the agent tables) a clarification or session save failed with
    # "no such table".
    from adapters import db as _db
    _db.reset_for_path(Path(args.hub) / "studio.db")
    _db.init_db()

    from agents.extraction.workflows.extraction_workflow import run_extraction_agentic
    final = run_extraction_agentic(
        args.hub, args.pid, args.source_file,
        llm_only=args.llm_only,
        source_id=args.source_id,
        use_checkpointer=not args.no_checkpoint,
    )
    return 0 if final.get("status") in ("complete", "cached") else 1


if __name__ == "__main__":
    raise SystemExit(main())
