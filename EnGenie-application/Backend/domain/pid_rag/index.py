"""The card index of each drawing, kept next to the graph in studio.db.

    pid_rag_chunks   one row per card: its text, tags, text hash and embedding
    pid_rag_state    per drawing: the snapshot hash the index was built from

ensure_index() is cheap when nothing changed (one hash comparison) and
incremental when something did: only cards whose text changed are sent to
the hosted embedding model. A card whose embedding failed is still indexed
(exact-tag and keyword retrieval keep working) and is retried next time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

from domain.pid_rag.cards import build_cards
from domain.pid_rag.snapshot import load_snapshot

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS pid_rag_chunks (
  pid        TEXT,
  chunk_id   TEXT,
  kind       TEXT,
  tags_json  TEXT,
  text       TEXT,
  text_hash  TEXT,
  embedding  TEXT,
  model      TEXT,
  PRIMARY KEY (pid, chunk_id)
);
CREATE TABLE IF NOT EXISTS pid_rag_state (
  pid          TEXT PRIMARY KEY,
  content_hash TEXT,
  model        TEXT,
  complete     INTEGER,
  updated_at   TEXT
);
"""

_lock = threading.Lock()
#: (pid, content_hash) -> loaded chunks, so a question does not re-parse vectors
_cache: dict[tuple[str, str], list[dict]] = {}


def _db():
    from adapters.db import get_db
    db = get_db()
    db.executescript(_DDL)                  # IF NOT EXISTS: a no-op once created
    return db


def _model() -> str:
    try:
        from common.ai.embedding_manager import EMBEDDING_MODEL
        return EMBEDDING_MODEL
    except Exception:
        return "none"


def _embed(texts: list[str]) -> list[list[float] | None]:
    """Module-level so tests can replace it."""
    if not texts:
        return []
    try:
        from common.ai.embedding_manager import generate_embeddings_batch
        return generate_embeddings_batch(texts)
    except Exception as exc:
        logger.warning("[pid_rag] embeddings unavailable: %s", exc)
        return [None] * len(texts)


def ensure_index(pid: str, snapshot: dict | None = None) -> dict:
    """Bring the drawing's index up to date. Returns
    {"chunks": n, "embedded": k, "changed": bool, "content_hash": h}."""
    with _lock:
        snap = snapshot or load_snapshot(pid)
        db = _db()
        model = _model()
        state = db.execute("SELECT content_hash, model, complete FROM pid_rag_state WHERE pid=?", (pid,)).fetchone()
        if state and state[0] == snap["content_hash"] and state[1] == model and state[2]:
            n = db.execute("SELECT COUNT(*) FROM pid_rag_chunks WHERE pid=?", (pid,)).fetchone()[0]
            return {"chunks": n, "embedded": 0, "changed": False, "content_hash": snap["content_hash"]}

        cards = build_cards(snap)
        have = {r[0]: (r[1], r[2], r[3]) for r in db.execute(
            "SELECT chunk_id, text_hash, embedding IS NOT NULL, model FROM pid_rag_chunks WHERE pid=?", (pid,))}
        todo = []
        for c in cards:
            c["text_hash"] = hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
            old = have.get(c["id"])
            if not old or old[0] != c["text_hash"] or not old[1] or old[2] != model:
                todo.append(c)
        vectors = _embed([c["text"] for c in todo])
        for c, v in zip(todo, vectors):
            db.execute(
                "INSERT INTO pid_rag_chunks (pid, chunk_id, kind, tags_json, text, text_hash, embedding, model) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(pid, chunk_id) DO UPDATE SET kind=excluded.kind, "
                "tags_json=excluded.tags_json, text=excluded.text, text_hash=excluded.text_hash, "
                "embedding=excluded.embedding, model=excluded.model",
                (pid, c["id"], c["kind"], json.dumps(c["tags"]), c["text"], c["text_hash"],
                 json.dumps(v) if v else None, model if v else None))
        # tags may change without the text (a renamed neighbour): keep them current
        for c in cards:
            if c not in todo:
                db.execute("UPDATE pid_rag_chunks SET tags_json=?, kind=? WHERE pid=? AND chunk_id=?",
                           (json.dumps(c["tags"]), c["kind"], pid, c["id"]))
        gone = set(have) - {c["id"] for c in cards}
        for cid in gone:
            db.execute("DELETE FROM pid_rag_chunks WHERE pid=? AND chunk_id=?", (pid, cid))
        complete = all(v for v in vectors)
        db.execute("INSERT INTO pid_rag_state (pid, content_hash, model, complete, updated_at) VALUES (?,?,?,?,?) "
                   "ON CONFLICT(pid) DO UPDATE SET content_hash=excluded.content_hash, model=excluded.model, "
                   "complete=excluded.complete, updated_at=excluded.updated_at",
                   (pid, snap["content_hash"], model, 1 if complete else 0, time.strftime("%Y-%m-%dT%H:%M:%S")))
        db.commit()
        for key in [k for k in _cache if k[0] == pid]:
            _cache.pop(key, None)
        embedded = sum(1 for v in vectors if v)
        logger.info("[pid_rag] %s: %d cards, %d re-embedded, %d removed", pid, len(cards), embedded, len(gone))
        return {"chunks": len(cards), "embedded": embedded, "changed": True, "content_hash": snap["content_hash"]}


def load_chunks(pid: str, content_hash: str = "") -> list[dict[str, Any]]:
    key = (pid, content_hash)
    if content_hash and key in _cache:
        return _cache[key]
    rows = _db().execute("SELECT chunk_id, kind, tags_json, text, embedding FROM pid_rag_chunks WHERE pid=?",
                         (pid,)).fetchall()
    out = []
    for cid, kind, tags, text, emb in rows:
        try:
            vec = json.loads(emb) if emb else None
        except ValueError:
            vec = None
        out.append({"id": cid, "kind": kind, "tags": json.loads(tags or "[]"), "text": text, "embedding": vec})
    if content_hash:
        _cache[key] = out
    return out


def refresh_in_background(pid: str) -> None:
    """After an edit: rebuild the index off the request path, so the next
    question does not wait for it. Never raises."""
    def _run():
        try:
            ensure_index(pid)
        except Exception as exc:
            logger.debug("[pid_rag] background refresh of %s failed: %s", pid, exc)
    threading.Thread(target=_run, name=f"pid-rag-{pid}", daemon=True).start()


def drop_index(pid: str) -> None:
    db = _db()
    db.execute("DELETE FROM pid_rag_chunks WHERE pid=?", (pid,))
    db.execute("DELETE FROM pid_rag_state WHERE pid=?", (pid,))
    db.commit()
    for key in [k for k in _cache if k[0] == pid]:
        _cache.pop(key, None)
