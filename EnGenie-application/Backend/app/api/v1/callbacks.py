"""
Server-to-server async callback endpoint.

A separate worker/service is handed a long-running job together with a
`callback_url` of the form `/api/callbacks/{stream_id}`. When the worker
finishes (or wants to report interim progress), it signs and POSTs the result
here. This handler verifies the signature and re-emits the payload onto the
existing Redis-backed progress stream, so it fans out to the browser through
the same SSE/progress pipeline used by in-process work.

`stream_id` doubles as the job correlation ID.

Authentication is by shared-secret HMAC (see callback_security), NOT by user
session — the caller is a backend service, not the logged-in browser.
"""
import json
import logging
import os
import threading

from fastapi import APIRouter, Request

from common.helpers.callback_security import verify_signature
from common.helpers.progress_tracker import progress_tracker
from common.helpers.responses import JSONResponse
from common.services import credit_service

blueprint = APIRouter()

# Default deadline after which a job with NO events at all is considered dead.
# Raised from 600s to 1800s to match the system's real job ceiling (frontend WS
# timeout, per-vendor analysis timeout are both 30 min). The watchdog is also
# liveness-aware (see arm_watchdog): as long as progress events keep arriving it
# re-arms instead of killing, so this only fails truly silent/crashed jobs.
# progress_tracker._STREAM_TTL (default 3600s) must stay >= this value so the
# liveness marker outlives the watchdog window.
_WATCHDOG_TIMEOUT_SECONDS = int(os.getenv("CALLBACK_WATCHDOG_TIMEOUT_SECONDS", "1800"))


@blueprint.post("/api/callbacks/{stream_id}")
async def job_callback(request: Request, stream_id: str):
    """Receive a signed callback from the worker and relay it to the stream."""
    raw = await request.body()  # verify over the RAW bytes, before parsing
    timestamp = request.headers.get("X-Timestamp", "")
    signature = request.headers.get("X-Signature", "")

    if not verify_signature(raw, timestamp, signature):
        logging.warning("[CALLBACK] Rejected callback for %s: invalid signature", stream_id)
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    # Idempotency: a retried/duplicate callback for an already-finished job is
    # acknowledged (200) so the sender stops retrying, but not re-processed.
    if progress_tracker.is_closed(stream_id):
        logging.info("[CALLBACK] Duplicate callback for closed stream %s — ignored", stream_id)
        return JSONResponse({"status": "duplicate-ignored"}, status_code=200)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "malformed JSON body"}, status_code=400)

    # ── Event-passthrough contract: {event_type, data} ──
    # A worker's CallbackProgressTracker relays each agent/node event verbatim
    # (start/step/sub_step/preview/result/error/close). Re-emit it onto our
    # Redis stream; close only on a terminal event.
    event_type = payload.get("event_type")
    if event_type:
        if event_type == "close":
            progress_tracker.close_stream(stream_id, reason="worker-close-event")
            return JSONResponse({"status": "ok"}, status_code=200)
        data = payload.get("data", {})
        progress_tracker.emit(stream_id, event_type, data)
        if event_type in ("result", "error"):
            progress_tracker.close_stream(stream_id, reason=f"worker-terminal-{event_type}")
            logging.info("[CALLBACK] Stream %s closed via callback (event=%s)", stream_id, event_type)
            # Worker-mode settlement: the in-process closure never ran, so charge
            # (or mark failed) here. Idempotent no-op for untracked streams.
            run_success = event_type == "result" and (
                not isinstance(data, dict) or data.get("success", True) is not False
            )
            credit_service.settle_workflow_run(stream_id, success=run_success, source="worker-callback")
        return JSONResponse({"status": "ok"}, status_code=200)

    # ── Legacy status-based contract: {status, step|result|error} ──
    status = payload.get("status")

    # Interim progress — emit a step event and keep the stream open.
    if status == "progress":
        progress_tracker.emit(stream_id, "step", payload.get("step", {}))
        return JSONResponse({"status": "ok"}, status_code=200)

    # Terminal events — emit then close so the watchdog stands down.
    if status == "completed":
        result_data = payload.get("result", {})
        progress_tracker.emit(stream_id, "result", result_data)
        run_success = not isinstance(result_data, dict) or result_data.get("success", True) is not False
        credit_service.settle_workflow_run(stream_id, success=run_success, source="worker-callback")
    else:
        progress_tracker.emit(
            stream_id,
            "error",
            payload.get("error", {"message": "Worker reported failure", "success": False}),
        )
        credit_service.settle_workflow_run(stream_id, success=False, source="worker-callback")

    progress_tracker.close_stream(stream_id, reason=f"worker-status-{status}")
    logging.info("[CALLBACK] Stream %s closed via callback (status=%s)", stream_id, status)
    return JSONResponse({"status": "ok"}, status_code=200)


def arm_watchdog(stream_id: str, timeout: int = _WATCHDOG_TIMEOUT_SECONDS) -> None:
    """
    Guard against a worker that crashes and never calls back.

    LIVENESS-AWARE: every callback event is re-emitted through progress_tracker,
    which records a last-emit timestamp. When the timer fires, if an event
    arrived within the last `timeout` seconds the job is demonstrably alive, so
    the watchdog RE-ARMS for the remaining window instead of killing it. It only
    fails the stream when NO event has arrived for the full `timeout`.

    (The previous fixed 600s one-shot deadline killed every healthy analysis
    that ran past 10 minutes — with several parallel search instances sharing
    LLM quota, the fastest finished in time and all slower siblings were
    force-terminated together, then their real results were discarded as
    duplicate callbacks on a closed stream.)
    """
    def _fire():
        if progress_tracker.is_closed(stream_id):
            return
        last_event_age = progress_tracker.seconds_since_last_emit(stream_id)
        if last_event_age is not None and last_event_age < timeout:
            remaining = max(timeout - last_event_age, 30.0)
            logging.info(
                "[CALLBACK] Watchdog deferred for %s — last event %.0fs ago; re-arming for %.0fs",
                stream_id, last_event_age, remaining,
            )
            retimer = threading.Timer(remaining, _fire)
            retimer.daemon = True
            retimer.start()
            return
        logging.warning(
            "[CALLBACK] Watchdog firing for %s — no event within %ss (last_event_age=%s)",
            stream_id, timeout, last_event_age,
        )
        progress_tracker.emit(
            stream_id,
            "error",
            {"message": "The analysis timed out. Please try again.", "success": False},
        )
        progress_tracker.close_stream(stream_id, reason="watchdog-timeout")
        # Timed-out runs are failed runs — mark the pending charge record so
        # it never charges and the ledger reflects the outcome.
        credit_service.settle_workflow_run(stream_id, success=False, source="watchdog-timeout")

    timer = threading.Timer(timeout, _fire)
    timer.daemon = True
    timer.start()
