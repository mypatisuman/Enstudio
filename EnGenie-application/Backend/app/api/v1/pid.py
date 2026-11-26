"""
P&ID session routes - the engineer's side of a persisted P&ID.

Endpoints:
  GET  /api/pid/active?session_id=...  the session's current drawing and its
                                       revision history
  POST /api/pid/confirm                apply or cancel deletions the retrofit
                                       agent queued: {session_id, revision,
                                       confirmed}
  POST /api/pid/clarify                answer "which subsystem?" and run the
                                       modification waiting on it:
                                       {session_id, revision, answer}

Every decision names the revision it was made against; a stale revision gets
409 with the current drawing so the page can reload and ask again. The work is
blocking (database, and for /clarify the retrofit tool loop), so it runs in
the threadpool, never on the event loop.
"""

import logging

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.security import login_required, optional_login
from common.helpers.azure_session import get_session
from common.helpers.responses import JSONResponse
from domain.solution.services import pid_session_service as PS

logger = logging.getLogger(__name__)

blueprint = APIRouter(prefix="/api/pid", tags=["P&ID"])


def _error(exc: PS.PIDActionError) -> JSONResponse:
    return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _session_id(data: dict) -> str:
    # The solution page sends its session as search_session_id; accept the
    # plain name too.
    return str(data.get("session_id") or data.get("search_session_id") or "").strip()


@blueprint.get("/active")
@optional_login
async def get_active_pid(request: Request):
    user_id = get_session(request).get("user_id") or "desktop_user"
    session_id = _session_id(dict(request.query_params))
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    def _load():
        graph = get_graph_for_pid(session_id, user_id=user_id, session_id=session_id)
        history = []
        try:
            from common.infra.repositories.pid_graph_repository import pid_graph_repository
            history = pid_graph_repository.history(user_id, session_id) if graph else []
        except Exception:
            pass
        return graph, history

    try:
        graph, history = await run_in_threadpool(_load)
    except Exception as exc:
        logger.exception(f"[PID_API] load failed for session {session_id}")
        return JSONResponse({"error": "Could not load the P&ID", "detail": str(exc)[:200]},
                            status_code=503)
    if graph is None:
        return JSONResponse({"error": "No P&ID is stored for this session"}, status_code=404)
    return JSONResponse({"pid_graph": graph, "history": history})


@blueprint.post("/confirm")
@optional_login
async def confirm_pid_action(request: Request):
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    if not isinstance(data.get("confirmed"), bool):
        return JSONResponse({"error": "confirmed must be true or false"}, status_code=400)
    try:
        graph = await run_in_threadpool(
            PS.confirm_pending, user_id, _session_id(data), data.get("revision"),
            data["confirmed"])
    except PS.PIDActionError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("[PID_API] confirm failed")
        return JSONResponse({"error": "Could not apply the decision", "detail": str(exc)[:200]},
                            status_code=500)
    return JSONResponse({"pid_graph": graph})


@blueprint.post("/clarify")
@optional_login
async def clarify_pid_action(request: Request):
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    answer = str(data.get("answer") or "").strip()
    if not answer:
        return JSONResponse({"error": "answer is required"}, status_code=400)
    try:
        graph = await run_in_threadpool(
            PS.clarify_pending, user_id, _session_id(data), data.get("revision"), answer)
    except PS.PIDActionError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("[PID_API] clarify failed")
        return JSONResponse({"error": "Could not apply the answer", "detail": str(exc)[:200]},
                            status_code=500)
    return JSONResponse({"pid_graph": graph})


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


def _drawing_meta(conn, pid: str) -> dict | None:
    """The digitised sheet's frame and file, written by rebuild_digital_pid."""
    import json
    try:
        row = conn.execute("SELECT page_w, page_h, image_path, meta_json FROM pid_drawing_meta WHERE pid = ?",
                           (pid,)).fetchone()
    except Exception:
        return None                         # table absent: nothing digitised yet
    if not row:
        return None
    meta = {"page_w": row["page_w"], "page_h": row["page_h"], "image_path": row["image_path"]}
    try:
        meta.update(json.loads(row["meta_json"] or "{}"))
    except Exception:
        pass
    return meta


def _servable_image(path: str | None) -> bool:
    from pathlib import Path
    return bool(path) and Path(path).suffix.lower() in _IMAGE_TYPES and Path(path).is_file()


@blueprint.get("/page-image")
@optional_login
async def get_page_image(request: Request):
    """The scanned drawing a session was digitised from, for the canvas's
    background layer. Only the file recorded for that drawing is served."""
    from pathlib import Path
    from fastapi import Response
    from adapters.db import get_db
    session_id = _session_id(dict(request.query_params))
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    def _read():
        meta = _drawing_meta(get_db(), session_id)
        path = (meta or {}).get("image_path")
        if not _servable_image(path):
            return None, None
        return Path(path).read_bytes(), _IMAGE_TYPES[Path(path).suffix.lower()]

    data, media_type = await run_in_threadpool(_read)
    if data is None:
        return JSONResponse({"error": "No drawing image is stored for this session"}, status_code=404)
    return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


def get_graph_for_pid(pid: str, user_id: str = "desktop_user", session_id: str = "") -> dict | None:
    """Load the current P&ID graph for `pid` or `session_id` from SQLite or MongoDB.
    Returns format expected by PIDCanvasView: { sessionId, pid, nodes, edges, pageImage, ... }
    """
    import json
    from adapters.db import get_db

    pids_to_try = [p for p in (pid, session_id) if p]

    for p in pids_to_try:
        try:
            conn = get_db()
            node_rows = conn.execute(
                "SELECT * FROM nodes WHERE pid = ? ORDER BY id", (p,)
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM edges WHERE pid = ? ORDER BY id", (p,)
            ).fetchall()
            pos_rows = conn.execute(
                "SELECT node_id, x, y FROM canvas_positions WHERE pid = ?", (p,)
            ).fetchall()
            pos_map = {r["node_id"]: (r["x"], r["y"]) for r in pos_rows}

            src_row = conn.execute(
                "SELECT filename FROM sources WHERE pid = ? ORDER BY id DESC LIMIT 1", (p,)
            ).fetchone()
            page_image = src_row["filename"] if src_row else None

            if node_rows:
                nodes = []
                for r in node_rows:
                    nid = r["id"]
                    n = {
                        "id": nid,
                        "label": r["label"] or nid,
                        "kind": r["kind"] or "instrument",
                        "area": r["area"] or "",
                    }
                    if r["kind_detail"]:
                        n["kind_detail"] = r["kind_detail"]
                    if r["x"] is not None:
                        n["x"] = float(r["x"])
                    elif nid in pos_map and pos_map[nid][0] is not None:
                        n["x"] = float(pos_map[nid][0])
                    if r["y"] is not None:
                        n["y"] = float(r["y"])
                    elif nid in pos_map and pos_map[nid][1] is not None:
                        n["y"] = float(pos_map[nid][1])
                    if r["extra_json"]:
                        try:
                            n.update(json.loads(r["extra_json"]))
                        except Exception:
                            pass
                    nodes.append(n)

                edges = []
                for r in edge_rows:
                    e = {
                        "from": r["from_id"],
                        "to": r["to_id"],
                        "source": r["from_id"],
                        "target": r["to_id"],
                        "kind": r["kind"] or "stream",
                        "label": r["label"] or "",
                    }
                    if r["extra_json"]:
                        try:
                            e.update(json.loads(r["extra_json"]))
                        except Exception:
                            pass
                    edges.append(e)

                graph = {
                    "sessionId": session_id or p,
                    "pid": p,
                    "nodes": nodes,
                    "edges": edges,
                    "pageImage": page_image,
                }
                meta = _drawing_meta(conn, p)
                if meta:
                    # node x/y are in this frame (x 0..1000); the canvas scales the
                    # scanned page to it so the symbols sit on their drawing
                    graph["page_w"], graph["page_h"] = meta["page_w"], meta["page_h"]
                    graph["warnings"] = meta.get("warnings") or []
                    if _servable_image(meta.get("image_path")):
                        graph["pageImage"] = f"/api/pid/page-image?session_id={p}"
                return graph
        except Exception as exc:
            logger.warning(f"[PID_API] SQLite get_graph_for_pid failed for {p}: {exc}")

    # Fallback to MongoDB repository
    try:
        from common.infra.repositories.pid_graph_repository import pid_graph_repository
        for p in pids_to_try:
            graph = pid_graph_repository.load_graph(user_id, p)
            if graph and graph.get("nodes"):
                return graph
    except Exception as exc:
        logger.warning(f"[PID_API] Mongo get_graph_for_pid failed: {exc}")

    return None


@blueprint.post("/describe")
@optional_login
async def describe_pid_turn(request: Request):
    """Run a conversational P&ID editing turn using the Describe multi-agent copilot."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data) or f"user_{user_id}"
    pid = str(data.get("pid") or data.get("project_id") or session_id).strip()
    message = str(data.get("message") or "").strip()
    history = data.get("history") or []
    attachments = data.get("attachments") or []
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    # Save attached drawings/scans to the extraction directory & register in SQLite sources
    if attachments:
        from pathlib import Path
        import base64
        import tempfile
        from adapters.db import get_db
        temp_dir = Path(tempfile.gettempdir()) / "engenie_extraction"
        temp_dir.mkdir(parents=True, exist_ok=True)
        db = get_db()
        for att in attachments:
            b64_str = att.get("base64") or ""
            name = att.get("name") or "uploaded_pid.png"
            if b64_str and ("base64," in b64_str or len(b64_str) > 100):
                if "base64," in b64_str:
                    b64_str = b64_str.split("base64,")[1]
                try:
                    file_bytes = base64.b64decode(b64_str)
                    saved_path = temp_dir / f"{pid}_{name}"
                    saved_path.write_bytes(file_bytes)
                    db.execute(
                        "INSERT OR REPLACE INTO sources (pid, filename, uploaded, cached) VALUES (?, ?, datetime('now'), 1)",
                        (pid, str(saved_path))
                    )
                    db.commit()
                except Exception as e:
                    logger.warning(f"[PID_API] Failed to save attachment {name}: {e}")

    # Proactive digitisation if drawing attached or image rebuild requested
    import re
    clean_msg = re.sub(r"^\[mode:[^\]]+\]\s*", "", message.strip(), flags=re.IGNORECASE).strip().lower()
    is_image_build = (
        "extract" in clean_msg
        or "diagram" in clean_msg
        or "uploaded" in clean_msg
        or "build canvas" in clean_msg
        or "build from image" in clean_msg
        or len(attachments) > 0
    )
    if is_image_build:
        try:
            from agents.describe.services import repository as _R
            from domain.solution.services.brownfield_vision_service import resolve_uploaded_drawing, rebuild_digital_pid
            has_drawing = resolve_uploaded_drawing(pid)[0] is not None
            if has_drawing and not _R.digitisation_status(pid).get("digitised"):
                logger.info(f"[PID_API] Proactively digitizing drawing for {pid}...")
                rebuild_digital_pid(pid)
        except Exception as e:
            logger.warning(f"[PID_API] Proactive drawing rebuild notice: {e}")

    def _run():
        from domain.describe.workflows.describe_workflow import run_describe_turn
        from agents.checkpoints import make_checkpointer
        import tempfile
        hub = tempfile.gettempdir()
        checkpointer = make_checkpointer(hub)
        return run_describe_turn(pid, message, session_id=session_id,
                                 history=history, checkpointer=checkpointer)

    try:
        final = await run_in_threadpool(_run)
        graph = get_graph_for_pid(pid, user_id=user_id, session_id=session_id)
        if "__interrupt__" in final:
            return JSONResponse({
                "pending_delete": final["__interrupt__"][0].value,
                "reply": final.get("reply", "Please confirm this deletion."),
                "pid_graph": graph,
            })
        return JSONResponse({
            "reply": final.get("reply"),
            "title": final.get("title"),
            "solution_design": final.get("solution_design"),
            "ops": final.get("ops") or [],
            "status": final.get("status", "success"),
            "agent": final.get("agent"),
            # input analysis and grounded answers (build / update / question / mixed)
            "mode": final.get("mode"),
            "analysis": final.get("analysis"),
            "citations": final.get("citations") or [],
            "sources": final.get("sources") or [],
            "steps": final.get("steps"),
            "pid_graph": graph,
        })
    except Exception as exc:
        logger.exception(f"[PID_API] describe turn failed: {exc}")
        return JSONResponse({"error": "Failed to process describe turn", "detail": str(exc)[:200]},
                            status_code=500)


@blueprint.post("/describe/resolve")
@optional_login
async def describe_pid_resolve(request: Request):
    """Resolve a pending deletion or confirmation in the Describe copilot."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data) or f"user_{user_id}"
    pid = str(data.get("pid") or data.get("project_id") or session_id).strip()
    confirmed = bool(data.get("confirmed"))

    def _run():
        from domain.describe.workflows.describe_workflow import resolve_describe_turn
        from agents.checkpoints import make_checkpointer
        import tempfile
        hub = tempfile.gettempdir()
        checkpointer = make_checkpointer(hub)
        return resolve_describe_turn(pid, session_id, confirmed, checkpointer=checkpointer)

    try:
        final = await run_in_threadpool(_run)
        graph = get_graph_for_pid(pid, user_id=user_id, session_id=session_id)
        if "__interrupt__" in final:
            return JSONResponse({
                "pending_delete": final["__interrupt__"][0].value,
                "pid_graph": graph,
            })
        return JSONResponse({
            "reply": final.get("reply"),
            "ops": final.get("ops") or [],
            "status": final.get("status", "success"),
            "pid_graph": graph,
        })
    except Exception as exc:
        logger.exception(f"[PID_API] describe resolve failed: {exc}")
        return JSONResponse({"error": "Failed to resolve describe turn", "detail": str(exc)[:200]},
                            status_code=500)


# ── Guided review of a digitised drawing (domain/solution/services/digitise_review) ──

@blueprint.get("/review")
@optional_login
async def get_review_queue(request: Request):
    """The items the digitiser was unsure about, least certain first, with counts by
    status. Query: session_id (or pid), status (pending | confirmed | rejected | corrected)."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    params = dict(request.query_params)
    session_id = _session_id(params) or f"user_{user_id}"
    pid = str(params.get("pid") or session_id).strip()

    def _run():
        from domain.solution.services import digitise_review as DR
        return {"pid": pid, **DR.list_queue(pid, params.get("status") or None)}

    try:
        return JSONResponse(await run_in_threadpool(_run))
    except Exception as exc:
        logger.exception(f"[PID_API] review queue failed: {exc}")
        return JSONResponse({"error": "Failed to load the review queue", "detail": str(exc)[:200]},
                            status_code=500)


@blueprint.post("/review/resolve")
@optional_login
async def resolve_review_item(request: Request):
    """The engineer's decision on one review item, applied to the drawing.
    Body: {session_id|pid, item_id, action: confirm | reject | rename | add_link | remove_link,
    correction?: {tag} | {from, to, kind}}. Returns the decision and the updated graph."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data) or f"user_{user_id}"
    pid = str(data.get("pid") or data.get("project_id") or session_id).strip()
    item_id, action = str(data.get("item_id") or ""), str(data.get("action") or "")
    if not item_id or not action:
        return JSONResponse({"error": "item_id and action are required"}, status_code=400)

    def _run():
        from domain.solution.services import digitise_review as DR
        out = DR.resolve(pid, item_id, action, data.get("correction") or {})
        if "error" not in out:
            out["counts"] = DR.list_queue(pid)["counts"]
            out["pid_graph"] = get_graph_for_pid(pid, user_id=user_id, session_id=session_id)
        return out

    try:
        out = await run_in_threadpool(_run)
        return JSONResponse(out, status_code=400 if "error" in out else 200)
    except Exception as exc:
        logger.exception(f"[PID_API] review resolve failed: {exc}")
        return JSONResponse({"error": "Failed to apply the decision", "detail": str(exc)[:200]},
                            status_code=500)


# ── Questions about the built P&ID (retrieval-augmented, domain/pid_rag) ─────

def _rag_target(pid: str, user_id, session_id: str) -> tuple[str, dict | None]:
    """(index key, snapshot): the describe drawing in studio.db when the project
    has one, else the solution session's PIDGraph from Mongo."""
    from domain.pid_rag.snapshot import load_snapshot, snapshot_from_pid_graph
    snap = load_snapshot(pid)
    if snap["nodes"] or not session_id:
        return pid, snap
    try:
        from common.infra.repositories.pid_graph_repository import pid_graph_repository
        graph = pid_graph_repository.load_graph(user_id, session_id)
    except Exception as exc:
        logger.warning(f"[PID_API] could not load the session P&ID for questions: {exc}")
        graph = None
    if graph:
        key = f"session:{session_id}"
        return key, snapshot_from_pid_graph(graph, pid=key)
    return pid, snap


@blueprint.post("/ask")
@optional_login
async def ask_pid(request: Request):
    """Answer a question about the built P&ID from its knowledge cards, with tag
    citations. Body: {question, session_id?, pid?}. Keeps a chat memory per
    (drawing, session) so follow-up questions resolve."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data) or f"user_{user_id}"
    pid = str(data.get("pid") or data.get("project_id") or session_id).strip()
    question = str(data.get("question") or data.get("message") or "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)

    def _run():
        from agents.describe.services import chat_memory as CM
        from agents.describe.services.turn_analysis import analyze_turn
        from domain.pid_rag.answer import answer_question
        key, snap = _rag_target(pid, user_id, session_id)
        from agents.describe.prompts.catalog import DESCRIBE_RAG_ANSWER_V1
        from domain.pid_rag.retriever import MAX_CONTEXT_CHARS
        mem = CM.load(key, session_id)
        # what the answer prompt leaves free after its instructions and the retrieved cards
        budget = CM.budget_for(CM.tokens(DESCRIBE_RAG_ANSWER_V1) + CM.tokens("x" * MAX_CONTEXT_CHARS))
        context = CM.context_block(mem, max_tokens=int(0.5 * budget), query=question)
        analysis = analyze_turn(key, question, memory_context=context, focus=CM.focus_tags(mem))
        standalone = " ".join(s["message"] for s in analysis["steps"] if s["kind"] == "question") or question
        out = answer_question(key, standalone, snapshot=snap, memory_context=context)
        CM.record_turn(key, session_id, mem, message=question, analysis=analysis,
                       results=[{"agent": "rag", "citations": out["citations"]}],
                       known_tags=(snap or {}).get("tags") or set())
        changes = [s["message"] for s in analysis["steps"] if s["kind"] == "change"]
        if changes:
            out["reply"] += ("\n\nI only answer questions here; send this as a design request in the "
                             "P&ID chat: " + " ".join(changes))
        return {**out, "mode": analysis["mode"], "standalone": standalone, "index": key}

    try:
        return JSONResponse(await run_in_threadpool(_run))
    except Exception as exc:
        logger.exception(f"[PID_API] ask failed: {exc}")
        return JSONResponse({"error": "Failed to answer the question", "detail": str(exc)[:200]},
                            status_code=500)


@blueprint.post("/rag/reindex")
@optional_login
async def reindex_pid_rag(request: Request):
    """Rebuild the question index of a drawing now (it also refreshes itself on
    the first question after any change). Body: {pid?, session_id?, full?}."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data) or f"user_{user_id}"
    pid = str(data.get("pid") or data.get("project_id") or session_id).strip()

    def _run():
        from domain.pid_rag.index import drop_index, ensure_index
        key, snap = _rag_target(pid, user_id, session_id)
        if data.get("full"):
            drop_index(key)
        return {"index": key, **ensure_index(key, snap)}

    try:
        return JSONResponse(await run_in_threadpool(_run))
    except Exception as exc:
        logger.exception(f"[PID_API] reindex failed: {exc}")
        return JSONResponse({"error": "Failed to index the P&ID", "detail": str(exc)[:200]},
                            status_code=500)


# Digitisation jobs by session. A read takes minutes, so it runs on a thread
# and the upload page polls; process-local like the progress tracker (the
# backend runs as one replica).
_DIGITISE_JOBS: dict[str, dict] = {}
_DIGITISE_LOCK = __import__("threading").Lock()


@blueprint.post("/digitise")
@optional_login
async def start_digitise(request: Request):
    """Start digitising an uploaded drawing image into the session's P&ID:
    the brownfield vision read (tags, symbols, connections, line labels), then
    the graph is stored for the canvas. Poll GET /api/pid/digitise/status."""
    import io
    import tempfile
    import threading
    import time
    from pathlib import Path

    form = await request.form()
    upload = form.get("file")
    session_id = str(form.get("session_id") or "").strip() or "default"
    if not upload or not hasattr(upload, "filename"):
        return JSONResponse({"error": "A drawing image is required"}, status_code=400)
    content = await upload.read()
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return JSONResponse({"error": "The file is not a readable image; PDF sheets go to /api/pid/extract"},
                            status_code=400)

    with _DIGITISE_LOCK:
        job = _DIGITISE_JOBS.get(session_id)
        if job and job.get("state") == "running":
            return JSONResponse({"error": "A drawing is already being digitised for this session", **job},
                                status_code=409)
        job = {"state": "running", "stage": "upload", "started": time.time(), "file": upload.filename}
        _DIGITISE_JOBS[session_id] = job

    # every scan is kept as PNG, so any format the reader accepts can also be
    # served back as the canvas background
    folder = Path(tempfile.gettempdir()) / "engenie_extraction"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(upload.filename).stem)[:60]
    path = folder / f"{session_id}_{safe}.png"
    img.convert("RGB").save(path, "PNG")

    def _run():
        from adapters.db import get_db
        from domain.solution.services import brownfield_vision_service as BV
        try:
            db = get_db()
            db.execute("INSERT OR REPLACE INTO sources (pid, filename, uploaded, cached) "
                       "VALUES (?, ?, datetime('now'), 1)", (session_id, str(path)))
            db.commit()
            analysis = BV.analyze_uploaded_pid(session_id, image_path=str(path),
                                               progress=lambda s: job.update(stage=s))
            if analysis.get("error"):
                job.update(state="error", error=analysis["error"])
                return
            job["stage"] = "store"
            result = BV.rebuild_digital_pid(session_id, analysis=analysis, session_id=session_id)
            job.update(state="done", stage="done", finished=time.time(),
                       summary=(result or {}).get("summary") if isinstance(result, dict) else str(result),
                       counts={"equipment": len(analysis.get("equipment") or []),
                               "instruments": len(analysis.get("instruments") or []),
                               "headers": len(analysis.get("tie_ins") or []),
                               "connections": len(analysis.get("lines") or []),
                               "labelled_lines": sum(1 for l in analysis.get("lines") or []
                                                     if l.get("printed_line_no"))},
                       warnings=analysis.get("warnings") or [])
        except Exception as exc:
            logger.exception(f"[PID_API] digitise failed for {session_id}")
            job.update(state="error", error=str(exc)[:300])

    threading.Thread(target=_run, name=f"digitise-{session_id}", daemon=True).start()
    return JSONResponse({"session_id": session_id, **job}, status_code=202)


@blueprint.get("/digitise/status")
@optional_login
async def digitise_status(request: Request):
    """Where a digitisation job is; with the stored graph once it is done."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    session_id = _session_id(dict(request.query_params))
    job = _DIGITISE_JOBS.get(session_id)
    if not job:
        return JSONResponse({"error": "No digitisation has been started for this session"}, status_code=404)
    out = {"session_id": session_id, **job}
    if job.get("state") == "done":
        out["pid_graph"] = await run_in_threadpool(get_graph_for_pid, session_id, user_id, session_id)
    return JSONResponse(out)


@blueprint.post("/extract")
@optional_login
async def extract_pid_drawing(request: Request):
    """Ingest a scanned drawing/PDF and digitize it via the 9-agent vision extraction pipeline."""
    from fastapi import UploadFile, Form
    from pathlib import Path
    import tempfile

    form = await request.form()
    upload = form.get("file")
    session_id = str(form.get("session_id") or "").strip() or "default"

    if not upload or not hasattr(upload, "filename"):
        return JSONResponse({"error": "A file is required for extraction"}, status_code=400)

    filename = upload.filename
    temp_dir = Path(tempfile.gettempdir()) / "engenie_extraction"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / filename

    content = await upload.read()
    temp_file.write_bytes(content)

    def _run_extract():
        from domain.extraction.workflows.extraction_workflow import run_extraction_agentic
        return run_extraction_agentic(str(temp_dir), session_id, str(temp_file))

    try:
        result = await run_in_threadpool(_run_extract)
        return JSONResponse({"status": "success", "result": result})
    except Exception as exc:
        logger.exception(f"[PID_API] extraction failed: {exc}")
        return JSONResponse({"error": "Extraction failed", "detail": str(exc)[:200]},
                            status_code=500)


@blueprint.get("/export/{fmt}")
@optional_login
async def export_pid(request: Request, fmt: str):
    """Export the active session's P&ID graph as SVG, DXF, or YMPL."""
    from fastapi import Response
    user_id = get_session(request).get("user_id") or "desktop_user"
    session_id = _session_id(dict(request.query_params))
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    from common.infra.repositories.pid_graph_repository import pid_graph_repository
    graph = pid_graph_repository.load_graph(user_id, session_id)
    if not graph:
        return JSONResponse({"error": "No P&ID found for this session"}, status_code=404)

    fmt_lower = fmt.lower().strip()
    if fmt_lower == "svg":
        from adapters.svg_pid import generate_svg_pid
        svg_content = generate_svg_pid(graph, project_name=f"PID_{session_id}")
        return Response(content=svg_content, media_type="image/svg+xml",
                        headers={"Content-Disposition": f'attachment; filename="pid_{session_id}.svg"'})
    elif fmt_lower == "ympl":
        import yaml
        ympl_text = yaml.safe_dump(graph, sort_keys=False)
        return Response(content=ympl_text, media_type="text/yaml",
                        headers={"Content-Disposition": f'attachment; filename="pid_{session_id}.ympl"'})
    elif fmt_lower == "json":
        import json
        return JSONResponse(graph)
    else:
        return JSONResponse({"error": f"Unsupported export format: {fmt}. Use svg, ympl, or json."},
                            status_code=400)


@blueprint.post("/identify-accessories")
@optional_login
async def identify_pid_accessories(request: Request):
    """Run Solution Agent workflow over the active P&ID graph to identify
    instruments and infer mandatory & optional accessories (e.g. manifolds, thermowells, positioners).
    """
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    session_id = _session_id(data)
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    tags = data.get("tags")
    if tags and not isinstance(tags, list):
        tags = [str(tags)]

    def _run_bridge():
        from domain.solution.services.pid_solution_bridge import enrich_pid_with_solution_bom
        return enrich_pid_with_solution_bom(session_id=session_id, user_id=user_id, target_tags=tags)

    try:
        result = await run_in_threadpool(_run_bridge)
        return JSONResponse(result)
    except Exception as exc:
        logger.exception(f"[PID_API] identify-accessories failed for session {session_id}: {exc}")
        return JSONResponse(
            {"error": "Failed to identify accessories", "detail": str(exc)[:200]},
            status_code=500
        )


@blueprint.get("/accessories")
@optional_login
async def get_pid_accessories(request: Request):
    """Retrieve all identified accessories stored on the active P&ID graph."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    session_id = _session_id(dict(request.query_params))
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    def _extract_accessories():
        from domain.solution.services.pid_solution_bridge import load_active_pid_graph
        graph = load_active_pid_graph(session_id, user_id)
        if not graph:
            return []
        accessories = []
        for n in graph.get("nodes") or []:
            accs = n.get("accessories") or n.get("extra_json", {}).get("accessories") or []
            tag = n.get("tag") or n.get("label") or n.get("id")
            for a in accs:
                if isinstance(a, dict):
                    accessories.append({**a, "parent_tag": tag})
        return accessories

    try:
        accessories = await run_in_threadpool(_extract_accessories)
        return JSONResponse({"accessories": accessories, "total": len(accessories)})
    except Exception as exc:
        logger.exception(f"[PID_API] get accessories failed: {exc}")
        return JSONResponse({"error": "Failed to fetch accessories", "detail": str(exc)[:200]}, status_code=500)


@blueprint.get("/accuracy/history")
@optional_login
async def get_accuracy_history_endpoint(request: Request):
    """Retrieve historical accuracy records saved locally (0 LLM credits)."""
    pid = request.query_params.get("pid")
    limit = int(request.query_params.get("limit", 50))

    def _read():
        from domain.solution.services.pid_accuracy_service import get_accuracy_history
        return get_accuracy_history(pid=pid, limit=limit)

    try:
        res = await run_in_threadpool(_read)
        return JSONResponse({"history": res, "count": len(res)})
    except Exception as exc:
        logger.exception(f"[PID_API] get accuracy history failed: {exc}")
        return JSONResponse({"error": "Failed to retrieve history", "detail": str(exc)[:200]}, status_code=500)


@blueprint.get("/accuracy/analytics")
@optional_login
async def get_accuracy_analytics_endpoint(request: Request):
    """Analyze stored local accuracy metrics and generate actionable prompt/logic recommendations."""
    def _analyze():
        from domain.solution.services.pid_accuracy_service import analyze_stored_accuracy_metrics
        return analyze_stored_accuracy_metrics()

    try:
        res = await run_in_threadpool(_analyze)
        return JSONResponse(res)
    except Exception as exc:
        logger.exception(f"[PID_API] accuracy analytics failed: {exc}")
        return JSONResponse({"error": "Failed to analyze accuracy metrics", "detail": str(exc)[:200]}, status_code=500)


@blueprint.post("/accuracy/evaluate")
@optional_login
async def evaluate_and_save_accuracy_endpoint(request: Request):
    """Evaluate diagram accuracy (0 LLM credits) and persist locally to JSON and JSONL."""
    data = await _body(request)
    pid = str(data.get("pid") or "").strip()
    agent_type = str(data.get("agent_type") or "manual")
    user_message = str(data.get("user_message") or "")
    metadata = data.get("metadata") or {}
    if not pid:
        return JSONResponse({"error": "pid is required"}, status_code=400)

    def _eval_save():
        from domain.solution.services.pid_accuracy_service import save_accuracy_evaluation
        return save_accuracy_evaluation(pid=pid, agent_type=agent_type, user_message=user_message, metadata=metadata)

    try:
        res = await run_in_threadpool(_eval_save)
        return JSONResponse(res)
    except Exception as exc:
        logger.exception(f"[PID_API] evaluate and save accuracy failed for {pid}: {exc}")
        return JSONResponse({"error": "Evaluation failed", "detail": str(exc)[:200]}, status_code=500)


@blueprint.get("/accuracy/{pid}")
@optional_login
async def get_pid_accuracy(request: Request, pid: str):
    """Retrieve intrinsic accuracy metrics, loop completeness, orphan rates, and prompt refinement guidance."""
    def _calc():
        from domain.solution.services.pid_accuracy_service import evaluate_intrinsic_accuracy
        return evaluate_intrinsic_accuracy(pid, save_local=True)

    try:
        res = await run_in_threadpool(_calc)
        return JSONResponse(res)
    except Exception as exc:
        logger.exception(f"[PID_API] accuracy evaluation failed for {pid}: {exc}")
        return JSONResponse({"error": "Accuracy evaluation failed", "detail": str(exc)[:200]}, status_code=500)


@blueprint.post("/accuracy/benchmark")
@optional_login
async def benchmark_pid(request: Request):
    """Benchmark a digitized P&ID against ground-truth data (Precision, Recall, F1)."""
    data = await _body(request)
    pid = str(data.get("pid") or "").strip()
    ground_truth = data.get("ground_truth") or {}
    if not pid:
        return JSONResponse({"error": "pid is required"}, status_code=400)

    def _run_bench():
        from domain.solution.services.pid_accuracy_service import benchmark_against_ground_truth
        return benchmark_against_ground_truth(pid, ground_truth)

    try:
        res = await run_in_threadpool(_run_bench)
        return JSONResponse(res)
    except Exception as exc:
        logger.exception(f"[PID_API] benchmark failed for {pid}: {exc}")
        return JSONResponse({"error": "Benchmark failed", "detail": str(exc)[:200]}, status_code=500)


@blueprint.post("/accuracy/refine")
@optional_login
async def refine_pid(request: Request):
    """Trigger diagnostic-guided re-analysis with Qwen3-VL to resolve detected gaps and raise accuracy."""
    user_id = get_session(request).get("user_id") or "desktop_user"
    data = await _body(request)
    pid = str(data.get("pid") or "").strip()
    if not pid:
        return JSONResponse({"error": "pid is required"}, status_code=400)

    def _run_refine():
        from domain.solution.services.pid_accuracy_service import refine_and_reanalyze
        return refine_and_reanalyze(pid, user_id=user_id)

    try:
        res = await run_in_threadpool(_run_refine)
        return JSONResponse(res)
    except Exception as exc:
        logger.exception(f"[PID_API] refinement failed for {pid}: {exc}")
        return JSONResponse({"error": "Refinement failed", "detail": str(exc)[:200]}, status_code=500)


