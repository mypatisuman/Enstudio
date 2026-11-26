"""Database re-exports and helpers."""
import logging

# Re-export infrastructure objects so router files can import from one place
from app.models.db.base import db
from app.models.db.user_model import User  # noqa: F401
from common.infra.database import (  # noqa: F401
    db_run,
    db_session_factory as db_session,
    redis_client,
    redis_otp_client,
)

# Attach session to db wrapper
db.session = db_session

def create_db():
    """Initialize SQL and MongoDB schemas/indexes."""
    from common.infra.database import init_db
    init_db()
