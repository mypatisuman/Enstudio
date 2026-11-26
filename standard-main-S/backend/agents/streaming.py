"""NDJSON progress bridge.

Preserves the exact stdout contract of extraction_cli/output.py so the
Tauri desktop app's `run_extraction` command and the IngestScreen log
work unchanged against the agentic pipeline. Additionally forwards each
payload to LangGraph's custom stream (when running inside a graph) so
`graph.stream(..., stream_mode="custom")` consumers see the same events.
"""
from __future__ import annotations

import json
import sys


# Numeric progress contract (reference pattern): coarse per-stage
# percentages so clients can render a progress bar. Additive — consumers
# that ignore "progress" are unaffected.
STAGE_PROGRESS = {
    "init": 5, "pdf_render": 8, "cache": 10,
    "warmup": 12, "symbol_detection": 20, "text_detection": 32,
    "line_detection": 40, "llm_verification_a": 55,
    "cv_consolidation": 62, "relationship_building": 70,
    "llm_verification_b": 80, "merge": 88,
    "inference_passes": 94, "done": 100,
}


def emit(payload: dict) -> None:
    """Emit one NDJSON progress line (stdout + LangGraph custom stream)."""
    line = json.dumps(payload, ensure_ascii=False)
    print(line, flush=True)
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        if writer is not None:
            writer(payload)
    except Exception:
        # Outside a graph run (or stream unavailable) — stdout already served.
        pass


def stage(name: str, status: str, **extra) -> None:
    payload = {"stage": name, "status": status, **extra}
    if name in STAGE_PROGRESS and "progress" not in payload:
        payload["progress"] = STAGE_PROGRESS[name]
    emit(payload)


class FatalAgentError(RuntimeError):
    """Raised for unrecoverable pipeline errors; the supervisor converts
    it into a failed-status finish instead of killing the process, so the
    checkpoint remains resumable."""


def die(msg: str, *, exit_process: bool = False) -> None:
    emit({"stage": "error", "status": "fatal", "message": msg})
    if exit_process:
        sys.exit(1)
    raise FatalAgentError(msg)
