"""
services/tile_runner.py — run per-tile vision-LLM calls concurrently.

A median fixture drawing needs about 57 symbol-tile and 40 line-tile calls, and
both loops ran them one at a time, which made tile I/O the dominant cost of a
page. The calls are independent network requests, so they run on a bounded
thread pool here.

Results come back in INPUT order, and each call's failure is captured
individually, so aggregation downstream is byte-for-byte the same as the
sequential loop it replaces; only wall-clock time changes. The text detector
already ran its crops on a pool of eight, so the provider clients are known to
be used concurrently in this application.

Concurrency is `STUDIO_TILE_CONCURRENCY`, else the `tile_concurrency` setting,
else 4, clamped to 1..16. Set it to 1 to restore strictly sequential calls,
for example when a provider's rate limit is tight.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_CONCURRENCY = 4
MAX_CONCURRENCY = 16


def tile_concurrency() -> int:
    raw = (os.getenv("STUDIO_TILE_CONCURRENCY") or "").strip()
    if not raw:
        try:
            from adapters.config import load_config
            raw = str(load_config().get("tile_concurrency") or "").strip()
        except Exception:
            raw = ""
    try:
        value = int(raw) if raw else DEFAULT_CONCURRENCY
    except ValueError:
        value = DEFAULT_CONCURRENCY
    return max(1, min(MAX_CONCURRENCY, value))


def run_ordered(fn: Callable[[T], R], items: Iterable[T],
                workers: int | None = None) -> list[tuple[R | None, BaseException | None]]:
    """Apply `fn` to every item; return (result, error) pairs in input order."""
    items = list(items)
    workers = max(1, min(workers or tile_concurrency(), len(items) or 1))

    def _safe(item: T) -> tuple[R | None, BaseException | None]:
        try:
            return fn(item), None
        except Exception as exc:          # one tile failing never fails the page
            return None, exc

    if workers == 1:
        return [_safe(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tile") as pool:
        return list(pool.map(_safe, items))
