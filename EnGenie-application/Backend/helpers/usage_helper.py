"""
helpers/usage_helper.py — LLM usage-log file read/write.

Extracted from main.py (Phase 9): _load_usage()/_append_usage(), moved
verbatim. `usage_file` is an explicit parameter (these originally closed
over main.py's `_USAGE_FILE = HUB / 'usage.json'`) — `_USAGE_FILE` itself
stays in main.py since it's computed from `HUB` at startup (dependency
wiring, not helper logic) and is referenced directly by the `clear_usage`
route. main.py keeps thin wrappers with the original zero-argument
signatures (see Phase 9 Step 3 / the Phase 5-7 wrapper precedent).
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_usage(usage_file: Path) -> list:
    try:
        return json.loads(usage_file.read_text(encoding='utf-8')) if usage_file.exists() else []
    except Exception:
        return []


def _append_usage(record: dict, usage_file: Path) -> None:
    records = _load_usage(usage_file)
    records.append(record)
    usage_file.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
