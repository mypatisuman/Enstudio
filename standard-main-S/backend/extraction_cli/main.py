"""
extraction_cli/main.py -- CLI entry point: parses arguments, validates the
hub/pid/source path, loads .env, and dispatches to run_extraction().

Extracted from extract_cli.py's main() (Phase 11), moved verbatim except
for delegating argparse construction to parser.build_parser() (see
parser.py) and using Path(__file__).parent.parent for the .env search --
this file now lives one directory deeper (extraction_cli/main.py vs the
original extract_cli.py), so it needs one extra `.parent` at each step to
resolve to the same two directories (<studio>/.env and <repo-root>/.env)
the original script searched.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .output import die
from .parser import build_parser
from .commands import run_extraction


def main() -> None:
    args = build_parser().parse_args()

    hub         = Path(args.hub_path).resolve()
    source_path = Path(args.pdf_path).resolve()

    if not hub.exists():
        die(f"Hub directory not found: {hub}")
    if not (hub / 'studio.db').exists():
        die(f"studio.db not found in hub: {hub / 'studio.db'}")
    if not source_path.exists():
        die(f"File not found: {source_path}")
    if not args.pid:
        die("pid must not be empty")

    # Load .env (API keys) before importing main
    for env_candidate in [
        Path(__file__).parent.parent / '.env',
        Path(__file__).parent.parent.parent / '.env',
    ]:
        if env_candidate.exists():
            for line in env_candidate.read_text(encoding='utf-8', errors='replace').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    try:
        run_extraction(hub, args.pid, source_path, llm_only=args.llm_only,
                       source_id=args.source_id)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        die(f"Unexpected error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
