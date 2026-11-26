import logging
import json
from datetime import datetime, UTC
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.core.security import login_required
from app.services.system_service import execute_deep_health_check
from common.helpers.standardization_helpers import enhance_submodel_mapping
from common.helpers.responses import JSONResponse

blueprint = APIRouter()

def _handle_health_check(request: Request):
    """Core logic for health check shared by multiple routes."""
    if request.query_params.get("deep") not in ("1", "true", "yes"):
        from common.monitoring.health.health_monitor import is_system_officially_down
        return JSONResponse({
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": "liveness",
            "system_officially_down": is_system_officially_down(),
        }, status_code=200)

    try:
        from app.services.system_service import execute_deep_health_check
        components = execute_deep_health_check()

        critical_failures = []
        if components.get("database", {}).get("sql_database", {}).get("status") == "disconnected":
            critical_failures.append("sql_database")
        if components.get("database", {}).get("mongodb", {}).get("status") == "disconnected":
            critical_failures.append("mongodb")

        if critical_failures:
            overall_status = "unhealthy"
        elif any(comp.get("status") == "unhealthy" for comp in components.values()):
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        from common.monitoring.health.health_monitor import is_system_officially_down
        system_down = is_system_officially_down()
        api_keys_failed = components.get("api_keys", {}).get("status") == "unhealthy"

        result = {
            "status": overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "components": components,
            "system_officially_down": system_down,
            "api_keys_failed": api_keys_failed
        }

        status_code = 200 if overall_status in ["healthy", "degraded"] else 503
        return JSONResponse(result, status_code=status_code)

    except Exception as e:
        logging.error(f"Health check failed: {str(e)}")
        return JSONResponse({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat()
        }, status_code=503)

@blueprint.get("/health")
async def health_check(request: Request):
    return _handle_health_check(request)

@blueprint.get("/ready")
async def readiness_check():
    return JSONResponse({"status": "ready"}, status_code=200)

@blueprint.get("/api/health")
async def api_health_check(request: Request):
    return _handle_health_check(request)


@blueprint.post("/standardization/submodel-mapping")
@login_required
async def enhance_submodel_mapping_endpoint(request: Request):
    """Enhance submodel-to-model-series mapping with standardization."""
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not data:
            return JSONResponse({"error": "No data provided"}, status_code=400)

        submodel_data = data.get("submodel_data")
        if not submodel_data:
            return JSONResponse({"error": "Missing submodel_data parameter"}, status_code=400)

        enhanced_result = enhance_submodel_mapping(submodel_data)
        return JSONResponse(enhanced_result, status_code=200)
    except Exception as e:
        logging.error(f"Failed to enhance submodel mapping: {e}")
        return JSONResponse({"error": "Failed to enhance submodel mapping"}, status_code=500)


@blueprint.get("/api/stream/{stream_id}")
@login_required
async def stream_progress(request: Request, stream_id: str):
    """Legacy polling endpoint for agent progress events.

    Superseded by the SSE push endpoint /api/events/{stream_id}. Kept as a
    fallback; safe to remove once no client polls it.
    """
    from common.helpers.progress_tracker import progress_tracker

    events = progress_tracker.consume_events(stream_id)
    is_closed = progress_tracker.is_closed(stream_id)

    final_result = progress_tracker.get_final_result(stream_id)
    if final_result and not any(e.get("type") in ("result", "error") for e in events):
        events.append(final_result)

    return JSONResponse({
        "events": events,
        "closed": is_closed,
    })


@blueprint.get("/api/events/{stream_id}")
@login_required
async def events_sse(request: Request, stream_id: str):
    """Server-Sent Events push stream for agent progress + results.

    Event-driven (no polling): events emitted onto the Redis progress stream —
    whether by an in-process worker or relayed from a server-to-server callback
    — are pushed to the browser the instant they arrive. Each connection:

      1. subscribes to the pub/sub channel (before backlog replay, so nothing
         emitted mid-setup is missed),
      2. replays any buffered backlog non-destructively (peek_events),
      3. handles the finished-before-connect case (get_final_result / closed),
      4. then pushes live events until a terminal event, close sentinel, or
         client disconnect, sending a heartbeat comment while idle.
    """
    import asyncio
    import queue as _queue

    from common.helpers.progress_tracker import progress_tracker

    def _sse(event_type: str, data) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    async def event_generator():
        q = progress_tracker.subscribe(stream_id)
        loop = asyncio.get_event_loop()
        try:
            yield ": connected\n\n"  # flush headers, open the stream

            # 1. Replay backlog (non-destructive) — events emitted before connect.
            terminal_seen = False
            for ev in progress_tracker.peek_events(stream_id):
                etype = ev.get("type", "message")
                yield _sse(etype, ev.get("data", {}))
                if etype in ("result", "error"):
                    terminal_seen = True
            if terminal_seen:
                return

            # 2. Job finished before this connection subscribed.
            final = progress_tracker.get_final_result(stream_id)
            if final:
                yield _sse(final.get("type", "result"), final.get("data", {}))
                return
            if progress_tracker.is_closed(stream_id):
                yield _sse("close", {})
                return

            # 3. Live push loop. Blocking queue.get is offloaded to a thread so
            #    it doesn't stall the event loop; 15s timeout drives heartbeats.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if item is None:  # close sentinel from close_stream
                    yield _sse("close", {})
                    break
                etype = item.get("event", "message")
                yield _sse(etype, item.get("data", {}))
                if etype in ("result", "error"):
                    break
        except Exception as e:
            logging.warning(f"[SSE] stream {stream_id} generator error: {e}")
        finally:
            progress_tracker.unsubscribe(stream_id, q)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )


@blueprint.websocket("/api/ws/{stream_id}")
async def ws_progress(websocket: WebSocket, stream_id: str):
    """Bidirectional WebSocket for agent progress + results.

    Server → client: pushes the same progress/result events as the SSE
    endpoint, sourced from the Redis progress stream.
    Client → server: accepts JSON commands (currently {"action": "cancel"}).

    Auth: the browser WebSocket API cannot set headers, so the JWT is passed
    as a `?token=` query param (use wss:// in production so it's encrypted in
    transit). Events are the same {type, data} envelope used elsewhere; the
    server also emits {"type": "ping"} every 15s as an app-level heartbeat.
    """
    import asyncio
    import queue as _queue

    from app.core.security import validate_jwt_token
    from common.helpers.progress_tracker import progress_tracker

    # 1. Authenticate before accepting the upgrade.
    token = websocket.query_params.get("token", "")
    if not validate_jwt_token(token).get("valid"):
        await websocket.close(code=4401)  # 4401 = app-defined "unauthorized"
        return

    await websocket.accept()

    q = progress_tracker.subscribe(stream_id)
    loop = asyncio.get_event_loop()

    async def push_events():
        """Server → client: replay backlog, then push live events to terminal."""
        try:
            # 1. Backlog emitted before this connection (non-destructive).
            terminal_seen = False
            for ev in progress_tracker.peek_events(stream_id):
                etype = ev.get("type", "message")
                await websocket.send_json({"type": etype, "data": ev.get("data", {})})
                if etype in ("result", "error"):
                    terminal_seen = True
            if terminal_seen:
                return

            # 2. Finished before this connection subscribed.
            final = progress_tracker.get_final_result(stream_id)
            if final:
                await websocket.send_json({"type": final.get("type", "result"), "data": final.get("data", {})})
                return
            if progress_tracker.is_closed(stream_id):
                await websocket.send_json({"type": "close", "data": {}})
                return

            # 3. Live push loop; 15s blocking get drives the heartbeat.
            while True:
                try:
                    item = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                except _queue.Empty:
                    await websocket.send_json({"type": "ping", "data": {}})  # heartbeat
                    continue
                if item is None:  # close sentinel
                    await websocket.send_json({"type": "close", "data": {}})
                    break
                etype = item.get("event", "message")
                await websocket.send_json({"type": etype, "data": item.get("data", {})})
                if etype in ("result", "error"):
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def receive_commands():
        """Client → server: handle commands sent over the same connection."""
        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("action") == "cancel":
                    logging.info(f"[WS] Client cancelled stream {stream_id}")
                    progress_tracker.close_stream(stream_id, reason="ws-client-cancel")
        except (WebSocketDisconnect, RuntimeError):
            pass

    push_task = asyncio.create_task(push_events())
    recv_task = asyncio.create_task(receive_commands())
    try:
        # Whichever finishes first (terminal pushed, or client disconnected)
        # ends the session; cancel the other side.
        _done, pending = await asyncio.wait(
            {push_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        # Cleanly await all tasks (including cancelled and errored ones)
        # so that exceptions are retrieved and not leaked.
        await asyncio.gather(*_done, *pending, return_exceptions=True)
    except Exception as e:
        logging.warning(f"[WS] stream {stream_id} error: {e}")
    finally:
        progress_tracker.unsubscribe(stream_id, q)
        try:
            await websocket.close()
        except Exception:
            pass
