"""
CallbackProgressTracker — a drop-in replacement for ProgressTracker used inside
a WORKER process.

Instead of writing progress events to Redis, it relays each event to the main
API as a signed HTTP callback (the event-passthrough contract):

    POST {callback_url}   { "event_type": <type>, "data": <payload>, "seq": <n> }

The main API verifies the HMAC and re-emits the event onto its own Redis stream,
which fans out to the browser's WebSocket. Agent/node code keeps calling
`progress_tracker.emit(...)` unchanged — only the transport differs.

Terminal events (`result`/`error`) are retried with backoff (delivery matters);
intermediate `step`/`start`/`sub_step` events are best-effort (fire once).
"""
import itertools
import json
import logging
import os
import threading
import time

import httpx

from common.helpers.callback_security import sign_payload

_TERMINAL = ("result", "error")


class CallbackProgressTracker:
    """ProgressTracker-compatible writer that relays events as signed callbacks."""

    def __init__(self):
        self._lock = threading.Lock()
        self._callbacks: dict[str, str] = {}   # stream_id -> callback_url
        self._closed: set[str] = set()
        self._seq = itertools.count(1)
        self._timeout = float(os.getenv("CALLBACK_POST_TIMEOUT", "10"))
        self._terminal_retries = int(os.getenv("CALLBACK_TERMINAL_RETRIES", "3"))

    # ── Per-job registration (worker binds stream_id → where to call back) ──

    def register(self, stream_id: str, callback_url: str) -> None:
        with self._lock:
            self._callbacks[stream_id] = callback_url
            self._closed.discard(stream_id)

    def deregister(self, stream_id: str) -> None:
        with self._lock:
            self._callbacks.pop(stream_id, None)

    # ── ProgressTracker writer surface (used by agent nodes) ──

    def create_stream(self, stream_id: str) -> None:
        # The main API already created the Redis stream; nothing to do here.
        return None

    def emit(self, stream_id: str, event_type: str, data) -> None:
        if self.is_closed(stream_id):
            return
        url = self._callbacks.get(stream_id)
        if not url:
            logging.warning("[CB_TRACKER] no callback_url registered for %s — dropping %s", stream_id, event_type)
            return
        terminal = event_type in _TERMINAL
        self._post(url, event_type, data, retries=self._terminal_retries if terminal else 0)
        if terminal:
            # The endpoint closes the stream on a terminal event; mark it locally
            # so a following close_stream() doesn't send a redundant "close".
            with self._lock:
                self._closed.add(stream_id)

    def close_stream(self, stream_id: str, reason: str = "") -> None:
        # `reason` mirrors ProgressTracker.close_stream for signature parity;
        # logged here, not transmitted (the callback contract is unchanged).
        logging.info("[CB_TRACKER] close_stream %s reason=%s", stream_id, reason or "unspecified")
        url = self._callbacks.get(stream_id)
        if url and stream_id not in self._closed:
            self._post(url, "close", {}, retries=1)
        with self._lock:
            self._closed.add(stream_id)

    def seconds_since_last_emit(self, stream_id: str) -> float | None:
        # Signature parity with ProgressTracker — liveness is tracked on the
        # API side (where the watchdog runs), not in the worker.
        return None

    def is_closed(self, stream_id: str) -> bool:
        return stream_id in self._closed

    # ── Reader surface — unused in a worker; return empty/None so accidental
    #    calls don't blow up. ──
    def peek_events(self, stream_id: str) -> list:
        return []

    def consume_events(self, stream_id: str) -> list:
        return []

    def get_final_result(self, stream_id: str):
        return None

    # ── Internal: signed POST with bounded retry/backoff ──

    def _post(self, url: str, event_type: str, data, retries: int = 0) -> None:
        body = json.dumps({"event_type": event_type, "data": data, "seq": next(self._seq)}).encode("utf-8")
        attempt = 0
        while True:
            ts = str(time.time())
            sig = sign_payload(body, ts)
            last = None
            try:
                resp = httpx.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sig},
                    timeout=self._timeout,
                )
                if resp.status_code < 500:
                    return  # 2xx/4xx are final answers — don't retry
                last = f"HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001 — network failures are retryable
                last = type(exc).__name__
            attempt += 1
            if attempt > retries:
                logging.warning("[CB_TRACKER] %s callback to %s failed (%s) after %d attempt(s)",
                                event_type, url, last, attempt)
                return
            time.sleep(min(0.5 * attempt, 2.0))
