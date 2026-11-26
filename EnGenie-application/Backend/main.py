"""
Engenie — FastAPI Entry Point
==============================
Pure FastAPI app.
Run with:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import logging
import os
import json
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Configure logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# pypdf logs unsupported-CMap notices (e.g. Korean /UniKS-UTF16-H) at ERROR once
# per page — pure log spam; extraction fallbacks already handle degraded text.
logging.getLogger("pypdf._cmap").setLevel(logging.CRITICAL)

# ── Config validation & startup initializations ───────────────────────────────
from dotenv import load_dotenv
load_dotenv()

from common.helpers.config_validator import validate_config
validate_config()

try:
    from app.core.database import create_db
    create_db()
    logging.info("[STARTUP] Database initialized")
except Exception as e:
    logging.error(f"[STARTUP] Database initialization error: {e}")

try:
    from common.infra.mongodb_config import ensure_indexes as _ensure_mongo_indexes
    _ensure_mongo_indexes()
    logging.info("[STARTUP] MongoDB indexes ensured")
except Exception as e:
    logging.error(f"[STARTUP] MongoDB index creation error: {e}")

if not os.getenv("LOGO_URL"):
    os.environ["LOGO_URL"] = (
        "https://productrecommener2.blob.core.windows.net/email-assets/engenie-logo.jpeg"
        "?se=2127-01-01T00%3A00%3A00Z&sp=r&sv=2026-02-06&sr=b"
        "&sig=Fqezxsng2rh9GmeExAjbhKpfNEpJ9vDnLqBxpKP4my4%3D"
    )
    logging.info("[STARTUP] LOGO_URL set from built-in blob SAS URL")

# ── Create FastAPI app ────────────────────────────────────────────────────────
app = FastAPI(
    title="EnGenie API",
    description="EnGenie Backend — AI-powered industrial procurement assistant",
    version="2.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
_allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Database Session Cleanup Middleware ───────────────────────────────────────
@app.middleware("http")
async def db_session_middleware(request, call_next):
    from common.infra.database import request_id_ctx
    import uuid
    token = request_id_ctx.set(uuid.uuid4())
    try:
        response = await call_next(request)
        return response
    finally:
        try:
            from app.core.database import db
            db.session.remove()
        except Exception as e:
            logging.error(f"[MIDDLEWARE] Failed to remove DB session: {e}")


# ── Global Exception Handler with Guaranteed CORS ────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """
    Catch-all exception handler that ensures 500 errors always return structured
    JSON with CORS headers, preventing browser 'blocked by CORS policy' misleading errors.
    """
    import traceback
    logging.exception(f"[GLOBAL_EXCEPTION_HANDLER] Unhandled error: {exc}")
    origin = request.headers.get("origin") or "*"
    headers = {
        "Access-Control-Allow-Origin": origin if (_allowed_origins == ["*"] or origin in _allowed_origins or "*" in _allowed_origins) else _allowed_origins[0] if _allowed_origins else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": str(exc),
            "message": "An unexpected server error occurred. Please try again.",
        },
        headers=headers,
    )



# ── Register all API routers ──────────────────────────────────────────────────
from app.api.auth.routes import blueprint as auth_bp
from app.api.system.routes import blueprint as system_bp
from app.api.v1.admin import blueprint as admin_bp
from app.api.v1.analytics import blueprint as analytics_bp
from app.api.v1.asset_configs import blueprint as asset_configs_bp
from app.api.v1.assets import blueprint as assets_bp
from app.api.v1.benchmarks import blueprint as benchmarks_bp
from app.api.v1.callbacks import blueprint as callbacks_bp
from app.api.v1.catalog import blueprint as catalog_bp
from app.api.v1.chat import blueprint as chat_bp
from app.api.v1.credits import blueprint as credits_bp
from app.api.v1.diagnostics import blueprint as diagnostics_bp
from app.api.v1.notifications import blueprint as notifications_bp
from app.api.v1.projects import blueprint as projects_bp
from app.api.v1.search import blueprint as search_bp
from app.api.v1.simulator import blueprint as simulator_bp
from app.api.v1.solution import blueprint as solution_bp
from app.api.v1.uploads import blueprint as uploads_bp
from app.api.v1.taxonomy import blueprint as taxonomy_bp
from app.api.v1.experion import blueprint as experion_bp
from app.api.v1.pid import blueprint as pid_bp

app.include_router(auth_bp)
app.include_router(system_bp)
app.include_router(admin_bp)
app.include_router(analytics_bp)
app.include_router(asset_configs_bp)
app.include_router(assets_bp)
app.include_router(benchmarks_bp)
app.include_router(callbacks_bp)
app.include_router(catalog_bp)
app.include_router(chat_bp)
app.include_router(credits_bp)
app.include_router(diagnostics_bp)
app.include_router(notifications_bp)
app.include_router(projects_bp)
app.include_router(search_bp)
app.include_router(simulator_bp)
app.include_router(solution_bp)
app.include_router(uploads_bp)
app.include_router(taxonomy_bp)
app.include_router(experion_bp)
app.include_router(pid_bp)

logging.info("[STARTUP] Registered all API routers successfully.")


# ── Hourly storage snapshot ───────────────────────────────────────────────────
def _start_storage_snapshot_scheduler():
    """Start APScheduler to run storage snapshot every hour."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def _capture_snapshot():
            try:
                from common.monitoring.usage import storage_metrics
                logging.info("[STORAGE_TIMER] Starting scheduled storage snapshot...")
                success = storage_metrics.capture_storage_snapshot()
                logging.info(f"[STORAGE_TIMER] Snapshot {'succeeded' if success else 'failed'}")
            except Exception as e:
                logging.error(f"[STORAGE_TIMER] Error capturing snapshot: {e}")

        scheduler = BackgroundScheduler()
        scheduler.add_job(_capture_snapshot, "interval", hours=1, id="storage_snapshot")
        scheduler.start()
        # Run once immediately on startup
        _capture_snapshot()
        logging.info("[STARTUP] Storage snapshot scheduler started")
    except ImportError:
        logging.warning("[STARTUP] apscheduler not installed — storage snapshot timer disabled. Install with: pip install apscheduler")
    except Exception as e:
        logging.error(f"[STARTUP] Failed to start storage snapshot scheduler: {e}")


# ── Periodic in-memory session sweep ────────────────────────────────────────
def _start_memory_sweep_scheduler():
    """Start APScheduler to actively sweep idle in-memory session data."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from common.ai.memory.maintenance import run_memory_sweep, SWEEP_INTERVAL_SECONDS

        def _run_sweep():
            try:
                logging.info("[MEMORY_SWEEP_TIMER] Starting scheduled memory sweep...")
                results = run_memory_sweep()
                logging.info(f"[MEMORY_SWEEP_TIMER] Sweep results: {results}")
            except Exception as e:
                logging.error(f"[MEMORY_SWEEP_TIMER] Error during memory sweep: {e}")

        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_sweep, "interval", seconds=SWEEP_INTERVAL_SECONDS, id="memory_sweep")
        scheduler.start()
        logging.info(f"[STARTUP] Memory sweep scheduler started (interval={SWEEP_INTERVAL_SECONDS}s)")
    except ImportError:
        logging.warning("[STARTUP] apscheduler not installed — memory sweep timer disabled. Install with: pip install apscheduler")
    except Exception as e:
        logging.error(f"[STARTUP] Failed to start memory sweep scheduler: {e}")


# ── Redis-based LLM background task worker ────────────────────────────────────
def _llm_background_worker():
    """
    Polls the Redis 'llm-tasks' list for background LLM processing tasks.
    Runs in a daemon thread so it exits when the main process exits.
    """
    import time
    try:
        import redis as _redis
        redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_CONNECTION_STRING", "redis://localhost:6379")
        client = _redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=30, health_check_interval=30)
        logging.info("[LLM_WORKER] Background LLM task worker started")

        while True:
            try:
                # Blocking pop with 5-second timeout so thread can be stopped cleanly
                item = client.brpop("llm-tasks", timeout=5)
                if item is None:
                    continue

                _, payload_bytes = item
                payload_str = payload_bytes if isinstance(payload_bytes, str) else payload_bytes.decode("utf-8")
                task_data = json.loads(payload_str)
                task_type = task_data.get("type")

                logging.info(f"[LLM_WORKER] Picked up task: {task_type}")

                if task_type == "standards_upload":
                    from app.services.upload_service import process_standards_blob_for_rag
                    process_standards_blob_for_rag(
                        user_id=task_data.get("user_id"),
                        filename=task_data.get("filename"),
                        blob_url=task_data.get("blob_url"),
                    )

                elif task_type == "strategy_upload":
                    from app.services.upload_service import process_strategy_blob_for_rag
                    process_strategy_blob_for_rag(
                        user_id=task_data.get("user_id"),
                        filename=task_data.get("filename"),
                        blob_url=task_data.get("blob_url"),
                    )

                elif task_type == "assets_upload":
                    from app.services.upload_service import process_assets_blob_for_rag
                    process_assets_blob_for_rag(
                        user_id=task_data.get("user_id"),
                        filename=task_data.get("filename"),
                        blob_url=task_data.get("blob_url"),
                    )

                else:
                    logging.warning(f"[LLM_WORKER] Unknown task type: {task_type}")

            except json.JSONDecodeError as e:
                logging.error(f"[LLM_WORKER] Failed to parse task payload: {e}")
            except (_redis.exceptions.TimeoutError, _redis.exceptions.ConnectionError):
                # Expected when idle or network hiccups; redis-py will auto-reconnect
                continue
            except Exception as e:
                logging.exception(f"[LLM_WORKER] Error processing task: {e}")
                # Emit progress error if stream_id is present
                try:
                    stream_id = task_data.get("stream_id") or task_data.get("kwargs", {}).get("stream_id")
                    if stream_id:
                        from common.helpers.progress_tracker import progress_tracker
                        progress_tracker.emit(stream_id, "error", {"message": f"Worker crashed: {str(e)}"})
                        progress_tracker.close_stream(stream_id, reason="llm-task-worker-crash")
                except Exception:
                    pass

    except Exception as startup_err:
        logging.error(f"[LLM_WORKER] Worker failed to start (Redis unavailable?): {startup_err}")


# ── Application startup event ─────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    """Start background services when the FastAPI app launches."""
    # Start storage snapshot scheduler
    _start_storage_snapshot_scheduler()

    # Start periodic in-memory session sweep scheduler
    _start_memory_sweep_scheduler()

    # Start LLM background task worker thread
    worker_thread = threading.Thread(target=_llm_background_worker, daemon=True, name="llm-worker")
    worker_thread.start()
    logging.info("[STARTUP] LLM background task worker thread started")


# ── Dev server entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
        log_level="info",
    )
