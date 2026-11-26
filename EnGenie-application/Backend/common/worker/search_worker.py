"""
Search worker — runs the heavy LangGraph search pipeline in a SEPARATE process
and relays node-level progress back to the main API.

Dispatch flow:
    Main API ──(signed POST /jobs)──► THIS worker ──run_search_workflow(...)──► nodes emit()
    nodes' emit() ─(signed POST /api/callbacks/{stream_id})─► Main API ─► Redis ─► browser WS

Transport is chosen by PROGRESS_TRANSPORT:
    "callback" (default) — relay every node/sub-step event to the API as a signed
                           HTTP callback (CallbackProgressTracker). Use when the
                           worker cannot share the API's Redis.
    "redis"              — emit straight to the SHARED Redis (requires the same
                           REDIS_URL as the API). No per-event HTTP.

Run:
    cd Backend
    venv\\Scripts\\python -m uvicorn common.worker.search_worker:app --port 7072

Point the main API at it:  WORKER_URL=http://127.0.0.1:7072
                           PUBLIC_BASE_URL=http://127.0.0.1:7071
                           CALLBACK_SECRET=<shared secret>
"""
import logging
import os
import sys

# Make Backend/ importable: …/common/worker/search_worker.py → Backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ── Select the progress transport BEFORE importing the workflow/agents, so the
#    agent modules bind to the chosen progress_tracker at import time
#    (they do `from common.helpers.progress_tracker import progress_tracker`). ──
_TRANSPORT = os.getenv("PROGRESS_TRANSPORT", "callback").lower().strip()

import common.helpers.progress_tracker as _pt_mod  # noqa: E402
from common.helpers.callback_progress_tracker import CallbackProgressTracker  # noqa: E402

if _TRANSPORT == "callback":
    _cb_tracker = CallbackProgressTracker()
    _pt_mod.progress_tracker = _cb_tracker          # nodes now emit via callbacks
    logging.info("[SEARCH_WORKER] progress transport = callback")
else:
    _cb_tracker = None                              # use the shared-Redis tracker
    logging.info("[SEARCH_WORKER] progress transport = redis (shared)")

# Safe to import the workflow now — its agents capture the tracker set above.
import json  # noqa: E402
import threading  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from common.helpers.callback_security import verify_signature  # noqa: E402
from common.helpers.response_formatter import standardize_and_convert_response  # noqa: E402
from domain.search.workflows.search_workflow import run_search_workflow  # noqa: E402

app = FastAPI(title="EnGenie Search Worker")


def _run_search_job(stream_id: str, callback_url: str, payload: dict) -> None:
    """Run the search workflow; node emits stream out, terminal result closes."""
    if _cb_tracker is not None:
        _cb_tracker.register(stream_id, callback_url)
    try:
        kwargs = dict(payload or {})
        kwargs["stream_id"] = stream_id
        kwargs.setdefault("enable_streaming", True)
        user_input = kwargs.pop("user_input", "")

        res = run_search_workflow(user_input, **kwargs)
        standardized = standardize_and_convert_response(res)
        failed = res.get("success", True) is False and res.get("error")
        _pt_mod.progress_tracker.emit(stream_id, "error" if failed else "result", standardized)
    except Exception as exc:  # noqa: BLE001 — always report failure back
        logging.exception("[SEARCH_WORKER] job %s failed", stream_id)
        _pt_mod.progress_tracker.emit(stream_id, "error", {"message": str(exc), "success": False})
    finally:
        _pt_mod.progress_tracker.close_stream(stream_id, reason="search-worker-job-finished")
        if _cb_tracker is not None:
            _cb_tracker.deregister(stream_id)


@app.post("/jobs")
async def jobs(request: Request):
    """Accept a signed, dispatched search job and run it asynchronously."""
    raw = await request.body()
    ts = request.headers.get("X-Timestamp", "")
    sig = request.headers.get("X-Signature", "")
    if not verify_signature(raw, ts, sig):
        logging.warning("[SEARCH_WORKER] rejected job: invalid signature")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        job = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "malformed JSON"}, status_code=400)

    stream_id = job.get("job_id")
    callback_url = job.get("callback_url")
    payload = job.get("payload", {})
    if not stream_id or not callback_url:
        return JSONResponse({"error": "job_id and callback_url required"}, status_code=400)

    threading.Thread(
        target=_run_search_job,
        args=(stream_id, callback_url, payload),
        daemon=True,
        name=f"search-worker-{stream_id}",
    ).start()
    return JSONResponse({"status": "accepted", "job_id": stream_id}, status_code=202)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "transport": _TRANSPORT})
