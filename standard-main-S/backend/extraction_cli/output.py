"""
extraction_cli/output.py -- NDJSON stdout emission + fatal-error helper.

Extracted from extract_cli.py (Phase 11), moved verbatim. Every extraction
progress event is a single NDJSON line on stdout; the Tauri shell reads
these and forwards them as 'extraction-progress' events to the React UI.
"""
from __future__ import annotations

import json
import sys

# Force stdout to UTF-8 binary mode -- avoids OSError 22 on Windows pipes
# when json.dumps produces non-ASCII characters.
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
_stdout_buf = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else None


def emit(obj: dict) -> None:
    """Write one NDJSON line to stdout and flush immediately."""
    line = json.dumps(obj, ensure_ascii=True) + '\n'
    try:
        if _stdout_buf is not None:
            _stdout_buf.write(line.encode('utf-8', errors='replace'))
            _stdout_buf.flush()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()
    except OSError:
        pass   # pipe closed — nothing we can do, just continue


def die(message: str) -> None:
    emit({"stage": "error", "message": message})
    sys.exit(1)
