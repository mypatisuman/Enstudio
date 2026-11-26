"""
Core SQL & Redis Infrastructure
Manages SQLAlchemy connection pooling and Azure Redis caching connections.
"""

import asyncio
import logging
import os
import ssl as _ssl
from functools import partial
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

logger = logging.getLogger(__name__)

# =========================================================================
# === SQLALCHEMY CONNECTION POOL ===
# =========================================================================

database_url = os.getenv('DATABASE_URL')
_db_url = database_url or os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///fallback.db')

if database_url:
    logger.info("✅ Using MySQL via DATABASE_URL")
else:
    logger.warning("⚠ DATABASE_URL not set. Using SQLite fallback.")

_engine_kwargs = dict(pool_recycle=1800, pool_pre_ping=True)
if not _db_url.startswith('sqlite'):
    _engine_kwargs.update(pool_size=10, max_overflow=20)


def _sanitize_mysql_url(db_url: str) -> tuple[str, bool]:
    """Normalize MySQL SSL query params to avoid invalid cafile errors.

    Some env files set `ssl_ca=require`, which PyMySQL interprets as a local
    certificate file path and raises FileNotFoundError. We strip that sentinel
    and keep ssl_verify_cert/ssl_verify_identity=false in the URL so PyMySQL
    still opens a TLS connection without requiring a CA bundle on disk.
    """
    if not db_url.startswith("mysql+"):
        return db_url, False

    parts = urlsplit(db_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True)) if parts.query else {}

    ssl_ca = (q.get("ssl_ca") or "").strip().lower()
    tls_required = ssl_ca in {"require", "required", "true", "1"}

    # Remove the bad sentinel value that PyMySQL treats as a file path
    if ssl_ca in {"require", "required", "true", "false", "1", "0", ""}:
        q.pop("ssl_ca", None)

    if tls_required:
        # Keep TLS enabled but skip certificate validation (Azure MySQL uses
        # a self-signed chain that varies by region/tier)
        q.setdefault("ssl_verify_cert", "false")
        q.setdefault("ssl_verify_identity", "false")

    new_query = urlencode(q)
    sanitized = urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    return sanitized, tls_required


_db_url, _tls_required = _sanitize_mysql_url(_db_url)
if _tls_required and _db_url.startswith("mysql+"):
    # Build a real SSLContext so PyMySQL actually opens an encrypted channel.
    # We disable hostname/cert verification because Azure MySQL's cert chain
    # is not always accessible from local dev environments.
    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE
    _engine_kwargs.setdefault("connect_args", {})["ssl"] = _ssl_ctx

engine = create_engine(_db_url, **_engine_kwargs)

from contextvars import ContextVar

request_id_ctx = ContextVar("request_id", default=None)

def _db_scope() -> object:
    """Scope key: request context token if inside HTTP request,
    asyncio task when inside event loop, otherwise current thread.
    This gives each request/task its own SQLAlchemy session, preventing
    session sharing across concurrent requests."""
    req_id = request_id_ctx.get()
    if req_id is not None:
        return req_id
    try:
        task = asyncio.current_task()
        if task is not None:
            return task
    except RuntimeError:
        pass
    import threading
    return threading.current_thread()

_SessionFactory = sessionmaker(bind=engine)
db_session_factory = scoped_session(_SessionFactory, scopefunc=_db_scope)

async def db_run(fn, *args, **kwargs):
    """Run a synchronous SQLAlchemy call in a threadpool so it never
    blocks the asyncio event loop."""
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(fn, *args, **kwargs)

def init_db():
    """
    Initialize database tables safely at startup.
    Must be called after all models are imported.
    """
    global engine
    try:
        from app.models.db.base import Base, db
        from app.models.db.user_model import User
        from common.auth.password import hash_password
        
        # 1. Create SQL Tables
        try:
            Base.metadata.create_all(engine)
            # Test connection with a simple query to ensure database is reachable
            with db_session_factory() as session:
                session.query(User).first()
            logger.info("[DB_INIT] SQL database tables created/verified")
        except Exception as conn_err:
            logger.warning(f"⚠️ [DB_INIT] Primary database connection failed: {conn_err}. Falling back to SQLite.")
            fallback_db_url = 'sqlite:///fallback.db'
            engine = create_engine(fallback_db_url, pool_recycle=1800, pool_pre_ping=True)
            db_session_factory.configure(bind=engine)
            Base.metadata.create_all(engine)
            logger.info("[DB_INIT] SQLite fallback database tables created/verified")
        
        # 2. Create Default Admin User
        with db_session_factory() as session:
            if not session.query(User).filter_by(role='admin').first():
                hashed_pw = hash_password("Daman@123")
                admin = User(
                    username="Daman",
                    email="daman.chundi@ensarsolutions.com",
                    password_hash=hashed_pw,
                    first_name="Daman",
                    last_name="Reddy",
                    status='active',
                    role='admin'
                )
                session.add(admin)
                session.commit()
                logger.info("✅ [DB_INIT] Admin user 'Daman' created successfully")
            else:
                logger.info("[DB_INIT] Admin user already exists, skipping creation")
                
    except Exception as e:
        logger.error(f"❌ [DB_INIT] Database initialization failed: {e}")
        logger.warning("⚠️  [DB_INIT] Continuing without MySQL - authentication features may not work")

# =========================================================================
# === REDIS SESSION & OTP STORAGE ===
# =========================================================================

redis_url = os.getenv("REDIS_URL")

redis_client = None
redis_otp_client = None

if redis_url:
    try:
        # Connect timeout kept short: this module-level init runs during app
        # startup, and with the Azure cache unreachable (firewall/IP change)
        # the old 30s connect timeout stalled boot for 40+ seconds before the
        # filesystem-session fallback kicked in. 5s is ample for a healthy
        # cache; operations keep the longer socket_timeout.
        _redis_connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "5"))
        redis_client = Redis.from_url(
            redis_url,
            decode_responses=False,  # Binary for sessions
            socket_timeout=30,
            socket_connect_timeout=_redis_connect_timeout,
            retry_on_timeout=True,
            health_check_interval=30,
            ssl_cert_reqs=None
        )

        redis_otp_client = Redis.from_url(
            redis_url,
            decode_responses=True,  # String mode for OTP data
            socket_timeout=30,
            socket_connect_timeout=_redis_connect_timeout,
            retry_on_timeout=True,
            health_check_interval=30,
            ssl_cert_reqs=None
        )

        # Test connection before using
        try:
            redis_client.ping()
            redis_otp_client.ping()
        except Exception as e:
            logger.exception("Redis initialization failed, falling back to filesystem sessions: %s", e)
            redis_client = None
            redis_otp_client = None

        if redis_client:
            logger.info("✅ Redis session storage enabled (Azure Redis)")
            logger.info("✅ Redis OTP storage enabled")

    except Exception as e:
        logger.warning(f"❌ Redis connection failed: {e}")
        logger.warning("⚠️ This is likely due to Azure Redis firewall blocking your local IP")
        logger.warning("⚠️ Falling back to filesystem sessions for local development")
        redis_client = None
        redis_otp_client = None
else:
    logger.warning("⚠️ REDIS_URL not found. Using filesystem sessions.")
    logger.warning("⚠️ Using in-memory OTP storage (not recommended for production)")
