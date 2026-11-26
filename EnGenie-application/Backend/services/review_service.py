"""
services/review_service.py — proposal-review workflow coordination.

Extracted from main.py (Phase 6): _record_proposal_rejection() — moved
verbatim. Thin coordination on top of the project repository's review-state
CRUD (_db_write_review): adds the try/except-and-log behavior the Pass 3/4
proposal routes rely on, while persistence itself stays in
repositories.project_repository (Phase 5).

`espx`/`espx_path` are accepted-but-unused — preserved verbatim for
signature compatibility with existing call sites (the DB-only rejection
ledger never needed them; see the original comment).

Coordinates: repositories.project_repository. No Flask, no SQL, no CV/LLM.
"""
from __future__ import annotations

from pathlib import Path

from repositories.project_repository import _db_write_review


def _record_proposal_rejection(espx: dict, espx_path: Path, pid: str,
                                key: str) -> None:
    """Mark a proposal as rejected. DB-only — review.json is no longer
    maintained; rebuild_espx_from_cache reads the rejection ledger from the
    `review` table (see _tag_rejected_ids / _conn_rejected_ids below)."""
    try:
        _db_write_review(pid, key, 'rejected')
    except Exception as e:
        print(f'_record_proposal_rejection DB write failed: {e}')
