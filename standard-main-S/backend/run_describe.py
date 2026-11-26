"""Describe agent CLI — test harness for description-based P&ID editing.

Usage:
    python run_describe.py <hub> <pid> "add a feed drum V-101 and pump P-101"
    python run_describe.py <hub> <pid> --resolve confirm      # pending delete
    python run_describe.py <hub> <pid> --resolve cancel

Uses the langgraph.db checkpointer, so a turn paused on a delete
confirmation can be resumed by a later invocation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

STUDIO_DIR = Path(__file__).parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))


#: Prefix marking the single machine-readable result line on stdout. The
#: agents stream NDJSON progress on the same stream, so a caller cannot simply
#: json-parse stdout -- it scans for this prefix instead.
RESULT_SENTINEL = "@@DESCRIBE_RESULT@@ "


def _emit_result(payload: dict) -> None:
    sys.stdout.write(RESULT_SENTINEL + json.dumps(payload) + chr(10))
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description="Describe agent CLI")
    ap.add_argument("hub")
    ap.add_argument("pid")
    ap.add_argument("message", nargs="?")
    ap.add_argument("--session", default="cli")
    ap.add_argument("--resolve", choices=["confirm", "cancel"])
    # Machine-readable mode for the desktop app. The agents emit NDJSON
    # progress lines on stdout as they work, so the final result is printed
    # on a single sentinel-prefixed line that a caller can find unambiguously
    # instead of trying to parse the whole stream.
    ap.add_argument("--json", action="store_true",
                    help="emit one RESULT_SENTINEL-prefixed JSON line")
    args = ap.parse_args()

    os.environ["ENGINEERING_HUB"] = args.hub

    # Create every table this process may write. Only main.py and auth.py used
    # to run init_db(), so on a hub the desktop app created (whose schema.rs
    # lacked the agent tables) a clarification or session save failed with
    # "no such table".
    from adapters import db as _db
    _db.reset_for_path(Path(args.hub) / "studio.db")
    _db.init_db()
    from agents.checkpoints import make_checkpointer
    from agents.describe.workflows.describe_workflow import (resolve_describe_turn,
                                                     run_describe_turn)

    cp = make_checkpointer(args.hub)
    if args.resolve:
        final = resolve_describe_turn(args.pid, args.session,
                                      args.resolve == "confirm",
                                      checkpointer=cp)
    elif args.message:
        final = run_describe_turn(args.pid, args.message,
                                  session_id=args.session, checkpointer=cp)
    else:
        ap.error("either a message or --resolve is required")
        return 2

    if "__interrupt__" in final:
        payload = final["__interrupt__"][0].value
        result = {"status": "pending_delete", "pending_delete": payload}
        if args.json:
            _emit_result(result)
        else:
            print(json.dumps({"pending_delete": payload}))
            print("Deletion awaits confirmation: re-run with --resolve confirm|cancel")
        return 3

    result = {
        "status": "ok",
        "agent": final.get("agent"),
        # The specialist's own outcome, distinct from this CLI's envelope
        # status. "no_pending" means a confirm/cancel arrived with nothing to
        # resolve, which the UI should show as information, not as an error.
        "agent_status": final.get("status"),
        "reply": final.get("reply"),
        "title": final.get("title"),
        "solution_design": final.get("solution_design"),
        "ops": final.get("ops") or [],
    }
    if args.json:
        _emit_result(result)
    else:
        print(json.dumps({"reply": result["reply"], "ops": result["ops"]},
                         indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
