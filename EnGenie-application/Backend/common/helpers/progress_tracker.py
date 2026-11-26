"""
Progress Tracker — Redis-backed SSE event queue for streaming progress to the frontend.

Redis-backed for distributed deployment so that events are accessible
across all worker instances.

Supports two SSE patterns used in the codebase:
  1. Polling  — create_stream / emit / consume_events / close_stream
               (used by /api/solution-status/{stream_id})
  2. Pub/Sub  — subscribe / unsubscribe with a Queue
               (used by /api/stream/{stream_id})

Degradation contract: when Redis is unreachable (Azure cache firewall, network
outage), the tracker falls back to an IN-PROCESS memory store behind a circuit
breaker instead of raising — an infra outage must never 500 the API route that
creates a stream, and must not add a connect-timeout stall to every emit.
The memory fallback is single-process only: with multiple workers, streams
served by another worker are invisible during an outage (still strictly better
than failing the request). Redis is re-probed every PROGRESS_REDIS_RETRY_SECONDS.
"""
import json
import logging
import os
import queue
import threading
import time
from typing import Any

import redis as _redis

# TTL for all per-stream Redis keys (event backlog, closed flag, final result,
# last-emit timestamp). Must be >= the longest-running job the system supports:
# deep vendor analysis is allowed up to 30 min (frontend WS timeout 1800s,
# per-vendor timeout 1800s), so the old 600s default silently expired the
# persisted final result before slow parallel searches could reconnect to it.
_STREAM_TTL = int(os.getenv("STREAM_TTL_SECONDS", "3600"))  # 1 hour default

# Circuit breaker: after a Redis failure, serve from memory for this long
# before re-trying Redis (avoids paying the connect timeout on every call).
_REDIS_RETRY_SECONDS = float(os.getenv("PROGRESS_REDIS_RETRY_SECONDS", "30"))


def _make_redis() -> _redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return _redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


class ProgressTracker:
    """Redis-backed, multi-instance-safe SSE event queue keyed by stream_id."""

    def __init__(self):
        self._redis = _make_redis()
        self._lock = threading.Lock()
        # stream_id -> list of (Queue, Thread|None, stop_Event|None) for pub/sub subscribers
        self._subscriptions: dict[str, list] = {}

        # ── In-process fallback store (used while the circuit breaker is open) ──
        self._mem_lock = threading.Lock()
        self._mem_events: dict[str, list[str]] = {}
        self._mem_closed: set[str] = set()
        self._mem_results: dict[str, str] = {}
        self._mem_last_emit: dict[str, float] = {}
        self._mem_subs: dict[str, list[queue.Queue]] = {}
        self._mem_touched: dict[str, float] = {}
        self._redis_down_until = 0.0

    # ── Key helpers ────────────────────────────────────────────────────────

    def _list_key(self, stream_id: str) -> str:
        return f"stream:{stream_id}:list"

    def _closed_key(self, stream_id: str) -> str:
        return f"stream:{stream_id}:closed"

    def _channel(self, stream_id: str) -> str:
        return f"stream:{stream_id}:events"

    def _result_key(self, stream_id: str) -> str:
        return f"stream:{stream_id}:result"

    def _last_emit_key(self, stream_id: str) -> str:
        return f"stream:{stream_id}:last_emit"

    # ── Circuit breaker / memory store helpers ────────────────────────────

    def _memory_mode(self) -> bool:
        return time.monotonic() < self._redis_down_until

    def _mark_redis_down(self, op: str, exc: Exception) -> None:
        was_up = not self._memory_mode()
        self._redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
        if was_up:
            logging.warning(
                f"[PROGRESS_TRACKER] Redis unavailable ({op}: {exc}) — serving progress "
                f"events from in-process memory for {_REDIS_RETRY_SECONDS:.0f}s "
                f"(single-process fallback; cross-worker streaming suspended)"
            )

    def _mem_touch(self, stream_id: str) -> None:
        # caller holds _mem_lock
        self._mem_touched[stream_id] = time.monotonic()

    def _mem_prune(self) -> None:
        # caller holds _mem_lock — evict streams idle beyond the TTL
        cutoff = time.monotonic() - _STREAM_TTL
        for sid in [s for s, t in self._mem_touched.items() if t < cutoff]:
            self._mem_events.pop(sid, None)
            self._mem_results.pop(sid, None)
            self._mem_last_emit.pop(sid, None)
            self._mem_subs.pop(sid, None)
            self._mem_touched.pop(sid, None)
            self._mem_closed.discard(sid)

    def _mem_notify(self, stream_id: str, item) -> None:
        with self._mem_lock:
            subs = list(self._mem_subs.get(stream_id, []))
        for q in subs:
            q.put(item)

    # ── Polling interface ──────────────────────────────────────────────────

    def create_stream(self, stream_id: str) -> None:
        """Initialize an event queue for a new stream.

        NEVER raises: this is called synchronously from API routes (e.g.
        POST /api/solution-agent), and a Redis outage previously turned into a
        500 before the workflow even started.
        """
        if not self._memory_mode():
            try:
                pipe = self._redis.pipeline()
                pipe.delete(self._list_key(stream_id))
                pipe.delete(self._closed_key(stream_id))
                pipe.execute()
                return
            except Exception as e:
                self._mark_redis_down("create_stream", e)
        with self._mem_lock:
            self._mem_prune()
            self._mem_events[stream_id] = []
            self._mem_closed.discard(stream_id)
            self._mem_touch(stream_id)

    def emit(self, stream_id: str, event_type: str, data: Any) -> None:
        """Push a new event onto the queue and publish it to pub/sub subscribers."""
        if self.is_closed(stream_id):
            # Loud, not silent: a dropped terminal event means a finished job's
            # result was discarded because something closed the stream first
            # (watchdog, client cancel, duplicate close). Key diagnostic for
            # "my search terminated but the backend kept working".
            logging.warning(
                f"[PROGRESS_TRACKER] DROPPED '{event_type}' for {stream_id} — stream already closed"
            )
            return
        message = json.dumps({"type": event_type, "data": data})
        if not self._memory_mode():
            try:
                pipe = self._redis.pipeline()
                pipe.rpush(self._list_key(stream_id), message)
                pipe.expire(self._list_key(stream_id), _STREAM_TTL)
                # Liveness marker for the callback watchdog: any event proves the
                # job is still alive, so a fixed-deadline watchdog can re-arm
                # instead of killing a healthy long-running analysis.
                pipe.set(self._last_emit_key(stream_id), str(time.time()), ex=_STREAM_TTL)
                if event_type in ("result", "error"):
                    pipe.set(self._result_key(stream_id), message, ex=_STREAM_TTL)
                pipe.publish(self._channel(stream_id), message)
                pipe.execute()
                # Subscribers that failed over to memory (their Redis listener
                # died mid-stream) still get the event after Redis recovers.
                if self._mem_subs.get(stream_id):
                    self._mem_notify(stream_id, {"event": event_type, "data": data})
                return
            except Exception as e:
                self._mark_redis_down("emit", e)
        with self._mem_lock:
            self._mem_events.setdefault(stream_id, []).append(message)
            self._mem_last_emit[stream_id] = time.time()
            if event_type in ("result", "error"):
                self._mem_results[stream_id] = message
            self._mem_touch(stream_id)
        self._mem_notify(stream_id, {"event": event_type, "data": data})

    def seconds_since_last_emit(self, stream_id: str) -> float | None:
        """Age (seconds) of the stream's most recent event, or None if unknown."""
        if not self._memory_mode():
            try:
                raw = self._redis.get(self._last_emit_key(stream_id))
                if raw is not None:
                    return max(0.0, time.time() - float(raw))
            except Exception as e:
                self._mark_redis_down("seconds_since_last_emit", e)
            else:
                if raw is None and stream_id not in self._mem_last_emit:
                    return None
        with self._mem_lock:
            ts = self._mem_last_emit.get(stream_id)
        return None if ts is None else max(0.0, time.time() - ts)

    def consume_events(self, stream_id: str) -> list[dict]:
        """Pop and return all pending events for the given stream (polling consumer)."""
        if not self._memory_mode():
            try:
                pipe = self._redis.pipeline()
                pipe.lrange(self._list_key(stream_id), 0, -1)
                pipe.delete(self._list_key(stream_id))
                results, _ = pipe.execute()
                return [json.loads(e) for e in results]
            except Exception as e:
                self._mark_redis_down("consume_events", e)
        with self._mem_lock:
            events = self._mem_events.pop(stream_id, [])
            self._mem_touch(stream_id)
        return [json.loads(e) for e in events]

    def peek_events(self, stream_id: str) -> list[dict]:
        """
        Return all buffered events WITHOUT removing them (SSE backlog replay).

        Unlike consume_events, this is non-destructive, so multiple concurrent
        SSE subscribers can each replay the full backlog independently. Cleanup
        is handled by the list's TTL and close_stream.
        """
        if not self._memory_mode():
            try:
                results = self._redis.lrange(self._list_key(stream_id), 0, -1)
                return [json.loads(e) for e in results]
            except Exception as e:
                self._mark_redis_down("peek_events", e)
        with self._mem_lock:
            events = list(self._mem_events.get(stream_id, []))
        return [json.loads(e) for e in events]

    def close_stream(self, stream_id: str, reason: str = "") -> None:
        """Mark stream closed, clear list, and notify pub/sub subscribers.

        `reason` is diagnostic-only: every close is logged with its origin so a
        terminated stream can always be traced to WHAT closed it (worker finish,
        watchdog, client cancel, ...).
        """
        logging.info(f"[PROGRESS_TRACKER] close_stream {stream_id} reason={reason or 'unspecified'}")
        redis_ok = False
        if not self._memory_mode():
            try:
                sentinel = json.dumps(None)
                pipe = self._redis.pipeline()
                pipe.set(self._closed_key(stream_id), "1", ex=_STREAM_TTL)
                pipe.delete(self._list_key(stream_id))
                pipe.publish(self._channel(stream_id), sentinel)
                pipe.execute()
                redis_ok = True
            except Exception as e:
                self._mark_redis_down("close_stream", e)
        with self._mem_lock:
            self._mem_closed.add(stream_id)
            self._mem_events.pop(stream_id, None)
            subs = self._mem_subs.pop(stream_id, [])
            self._mem_touch(stream_id)
        for q in subs:
            q.put(None)  # sentinel — tells SSE handlers on the memory path to close
        if redis_ok:
            return

    def is_closed(self, stream_id: str) -> bool:
        # Memory flag first: a close recorded during an outage must stay
        # authoritative even after Redis comes back (Redis never saw it).
        if stream_id in self._mem_closed:
            return True
        if self._memory_mode():
            return False
        try:
            return bool(self._redis.exists(self._closed_key(stream_id)))
        except Exception as e:
            self._mark_redis_down("is_closed", e)
            return False

    def get_final_result(self, stream_id: str) -> dict:
        """Fetch the persistent final result/error event, if any."""
        if not self._memory_mode():
            try:
                res = self._redis.get(self._result_key(stream_id))
                if res:
                    return json.loads(res)
            except Exception as e:
                self._mark_redis_down("get_final_result", e)
        with self._mem_lock:
            res = self._mem_results.get(stream_id)
        if res:
            return json.loads(res)
        return None

    # ── Pub/Sub interface ──────────────────────────────────────────────────

    def subscribe(self, stream_id: str) -> queue.Queue:
        """
        Subscribe to a stream and return a Queue that receives events.
        Redis mode spawns a dedicated pub/sub listener thread; while the
        circuit breaker is open the Queue is fed directly by emit()'s memory
        path instead. The Queue yields dicts like {"event": <type>, "data": <payload>}.
        A None sentinel signals the stream is closed.
        """
        q: queue.Queue = queue.Queue()

        if self._memory_mode():
            with self._mem_lock:
                self._mem_subs.setdefault(stream_id, []).append(q)
                self._mem_touch(stream_id)
            with self._lock:
                self._subscriptions.setdefault(stream_id, []).append((q, None, None))
            return q

        stop_event = threading.Event()

        def _listener():
            try:
                client = _make_redis()
                pubsub = client.pubsub()
                pubsub.subscribe(self._channel(stream_id))
                try:
                    while not stop_event.is_set():
                        msg = pubsub.get_message(timeout=1.0)
                        if msg and msg["type"] == "message":
                            raw = msg["data"]
                            try:
                                parsed = json.loads(raw)
                            except Exception:
                                continue
                            if parsed is None:
                                q.put(None)  # sentinel — tells SSE handler to close
                                break
                            q.put({
                                "event": parsed.get("type", "message"),
                                "data": parsed.get("data", {}),
                            })
                finally:
                    try:
                        pubsub.unsubscribe()
                        pubsub.close()
                        client.close()
                    except Exception:
                        pass
            except Exception as e:
                # Fail over instead of closing the SSE: register this queue as
                # a memory subscriber so emit()'s fallback path keeps feeding it.
                self._mark_redis_down("pub/sub listener", e)
                with self._mem_lock:
                    self._mem_subs.setdefault(stream_id, []).append(q)
                    self._mem_touch(stream_id)

        t = threading.Thread(target=_listener, daemon=True)
        t.start()

        with self._lock:
            self._subscriptions.setdefault(stream_id, []).append((q, t, stop_event))

        return q

    def unsubscribe(self, stream_id: str, q: queue.Queue) -> None:
        """Stop the pub/sub listener thread associated with the given Queue."""
        with self._lock:
            subs = self._subscriptions.get(stream_id, [])
            for i, (sq, t, stop_event) in enumerate(subs):
                if sq is q:
                    if stop_event is not None:
                        stop_event.set()
                    subs.pop(i)
                    break
        with self._mem_lock:
            lst = self._mem_subs.get(stream_id)
            if lst and q in lst:
                lst.remove(q)


# Global singleton — imported everywhere as `progress_tracker`
progress_tracker = ProgressTracker()


def emit_progress(stream_id: str, event_type: str, data: Any) -> None:
    """Convenience wrapper around progress_tracker.emit()."""
    progress_tracker.emit(stream_id, event_type, data)
