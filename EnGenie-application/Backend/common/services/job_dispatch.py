"""
Dispatch long-running jobs either to a separate worker (server-to-server async
callback pattern) or, when no worker is configured, to an in-process background
thread (the legacy behavior).

The dispatcher returns immediately; results arrive asynchronously on the Redis
progress stream keyed by `stream_id` — either re-emitted by the callback
endpoint (worker mode) or emitted directly by the in-process runner.

Environment:
    WORKER_URL        Base URL of the worker service. If unset/empty, falls
                      back to the in-process thread (no behavior change).
    PUBLIC_BASE_URL   Externally-reachable base URL of THIS API, used to build
                      the callback_url the worker will POST back to.
    CALLBACK_SECRET   Shared HMAC secret (see callback_security).
"""
import json
import logging
import os
import threading
import time
from typing import Callable

import httpx

from common.helpers.callback_security import sign_payload
from common.helpers.progress_tracker import progress_tracker

# How long to wait on the *handoff* POST — not the job itself.
_DISPATCH_TIMEOUT_SECONDS = 10


def dispatch_job(
    stream_id: str,
    job_type: str,
    job_payload: dict,
    in_process_runner: Callable[[], None],
) -> None:
    """
    Hand off a job for asynchronous execution.

    Args:
        stream_id: correlation id; also the progress-stream key.
        job_type: logical job name passed to the worker (e.g. "search").
        job_payload: JSON-serializable kwargs the worker needs to run the job.
        in_process_runner: zero-arg callable that runs the job locally and is
            responsible for emitting result/error and closing the stream. Used
            only when WORKER_URL is not configured.
    """
    worker_url = os.getenv("WORKER_URL", "").strip()

    if not worker_url:
        # Legacy path: run in a background thread inside this process.
        thread = threading.Thread(
            target=in_process_runner,
            daemon=True,
            name=f"{job_type}-worker-{stream_id}",
        )
        thread.start()
        logging.info("[DISPATCH] %s job %s running in-process (no WORKER_URL)", job_type, stream_id)
        return

    # Worker path: sign and POST the job handoff. The worker calls us back.
    # Fast reachability check: if the worker is down, fail over to in-process
    # now rather than waiting out the full dispatch timeout (or hanging the job).
    try:
        healthy = httpx.get(f"{worker_url.rstrip('/')}/health", timeout=3).status_code == 200
    except Exception:
        healthy = False
    if not healthy:
        logging.warning("[DISPATCH] worker %s unreachable — running %s job %s in-process", worker_url, job_type, stream_id)
        threading.Thread(target=in_process_runner, daemon=True, name=f"{job_type}-fallback-{stream_id}").start()
        return

    public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    callback_url = f"{public_base}/api/callbacks/{stream_id}"

    body = json.dumps({
        "job_id": stream_id,
        "job_type": job_type,
        "callback_url": callback_url,
        "payload": job_payload,
    }).encode("utf-8")
    timestamp = str(time.time())
    signature = sign_payload(body, timestamp)

    try:
        resp = httpx.post(
            f"{worker_url.rstrip('/')}/jobs",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
            timeout=_DISPATCH_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        logging.info("[DISPATCH] %s job %s handed off to worker (%s)", job_type, stream_id, resp.status_code)
    except Exception as exc:
        # Handoff failed after the health check passed (worker died mid-dispatch
        # or rejected the job). Fall back to in-process so the job still runs.
        logging.exception("[DISPATCH] Handoff failed for %s job %s: %s — falling back in-process", job_type, stream_id, exc)
        threading.Thread(target=in_process_runner, daemon=True, name=f"{job_type}-fallback-{stream_id}").start()
        return

    # Arm the watchdog only in worker mode (the in-process runner can't vanish
    # silently the way a remote worker can).
    from app.api.v1.callbacks import arm_watchdog
    arm_watchdog(stream_id)
