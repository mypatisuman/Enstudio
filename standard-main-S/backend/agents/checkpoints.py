"""Checkpointer factory.

Uses a dedicated langgraph.db next to studio.db — never the studio.db
connection itself (it runs WAL mode with a single shared connection that
must not be contended by checkpoint writes).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def checkpoint_db_path(hub: str | Path) -> Path:
    return Path(hub) / "langgraph.db"


def make_checkpointer(hub: str | Path):
    """Return a SqliteSaver for this hub, or None if unavailable."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        return None
    conn = sqlite3.connect(str(checkpoint_db_path(hub)), check_same_thread=False)
    return SqliteSaver(conn)


def thread_id(pid: str, file_hash: str) -> str:
    return f"{pid}:{file_hash}"
