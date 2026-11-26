"""
Reference worker for the server-to-server async callback pattern.

This is a standalone service that plays the WORKER role in the dispatch flow:

    main app  ──(signed POST /jobs)──►  THIS worker
    THIS worker ──(signed POST {callback_url})──►  main app /api/callbacks/{id}

It verifies the signature on the incoming job, runs the work in a background
thread, streams a couple of signed "progress" callbacks, then a signed
"completed" callback. Signing uses the SAME shared CALLBACK_SECRET and helper
as the main app, so the main app accepts the callbacks.

IMPORTANT: this reference worker returns a STUB result — it does not run the
real AI workflow. It exists to exercise/verify the dispatch→callback transport
end to end. Running the actual workflow in a worker would require the domain
code to live here too.

Run it:
    cd Backend
    venv\\Scripts\\python -m uvicorn common.worker.reference_worker:app --port 7072

Then point the main app at it and restart the backend:
    WORKER_URL=http://127.0.0.1:7072
    PUBLIC_BASE_URL=http://127.0.0.1:7071
"""
import json
import logging
import os
import sys
import threading
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.helpers.callback_security import sign_payload, verify_signature

app = FastAPI(title="EnGenie Reference Worker")

# Delay between simulated progress steps (seconds). Override for tests.
PROGRESS_DELAY = float(os.getenv("WORKER_PROGRESS_DELAY", "0.5"))


def _send_callback(callback_url: str, status: str, data: dict) -> None:
    """Sign and POST one callback to the main app."""
    body = json.dumps({"status": status, **data}).encode("utf-8")
    ts = str(time.time())
    sig = sign_payload(body, ts)
    resp = httpx.post(
        callback_url,
        content=body,
        headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sig},
        timeout=10,
    )
    logging.info("[WORKER] callback %s -> %s (%s)", status, callback_url, resp.status_code)


def run_job(job_id: str, callback_url: str, payload: dict, *, send_fn=_send_callback, delay: float = None) -> None:
    """Do the (stub) work and report progress + result via signed callbacks."""
    delay = PROGRESS_DELAY if delay is None else delay
    try:
        for pct in (25, 60, 90):
            send_fn(callback_url, "progress", {"step": {"progress": pct, "message": f"Working… {pct}%"}})
            if delay:
                time.sleep(delay)
        send_fn(callback_url, "completed", {"result": {"worker": "reference", "job_id": job_id, "echo": payload}})
    except Exception as exc:  # noqa: BLE001 — report any failure back to the stream
        logging.exception("[WORKER] job %s failed", job_id)
        try:
            send_fn(callback_url, "failed", {"error": {"message": str(exc), "success": False}})
        except Exception:
            pass


@app.post("/jobs")
async def jobs(request: Request):
    """Receive a dispatched job, verify its signature, run it asynchronously."""
    raw = await request.body()
    ts = request.headers.get("X-Timestamp", "")
    sig = request.headers.get("X-Signature", "")
    if not verify_signature(raw, ts, sig):
        logging.warning("[WORKER] rejected job: invalid signature")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        job = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "malformed JSON"}, status_code=400)

    job_id = job.get("job_id")
    callback_url = job.get("callback_url")
    if not job_id or not callback_url:
        return JSONResponse({"error": "job_id and callback_url required"}, status_code=400)

    threading.Thread(
        target=run_job,
        args=(job_id, callback_url, job.get("payload", {})),
        daemon=True,
        name=f"refworker-{job_id}",
    ).start()
    return JSONResponse({"status": "accepted", "job_id": job_id}, status_code=202)
