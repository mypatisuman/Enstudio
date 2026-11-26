"""
Node-level resilience for LangGraph workflow nodes.

A workflow node is a function ``(state) -> state``. Today, when a node raises,
the whole workflow aborts and the user sees a generic "an error occurred"
message — even work already completed by earlier nodes is lost.

This module adds **classified, bounded** retry so that a node which fails on a
TRANSIENT error (LLM timeout, rate-limit/429, 5xx, connection reset) is re-run a
few times with backoff — i.e. "rerun the function that failed" — while
DETERMINISTIC errors (validation, bad data, code bugs) are NOT retried (no retry
storm) and surface immediately.

On exhausted retries a node may **degrade gracefully** via an ``on_exhausted``
hook: record a per-node warning in state and return the (partial) state so the
pipeline continues and partial results survive, instead of aborting.

Pure module — only stdlib imports — safe to import and unit-test anywhere.
"""
import functools
import logging
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Exception class names that indicate a transient/retryable condition. Matched by
# name (not import) so we don't hard-depend on every provider SDK.
_TRANSIENT_TYPE_NAMES = {
    "TimeoutError", "ConnectTimeout", "ReadTimeout", "ConnectTimeoutError",
    "ConnectionError", "ConnectionResetError", "ConnectionAbortedError",
    "RemoteDisconnected", "ProtocolError", "IncompleteRead",
    "ServiceUnavailable", "ResourceExhausted", "DeadlineExceeded",
    "TooManyRequests", "RateLimitError", "APITimeoutError", "APIConnectionError",
    "InternalServerError", "ServerError", "OverloadedError",
    "ServerSelectionTimeoutError", "AutoReconnect", "NetworkTimeout",
}

# Substrings (lowercased) that indicate a transient condition in the message.
_TRANSIENT_MSG_PATTERNS = (
    "timeout", "timed out", "rate limit", "ratelimit", "too many requests",
    "temporarily unavailable", "service unavailable", "connection reset",
    "connection aborted", "connection error", "deadline exceeded",
    "resource exhausted", "overloaded", "please try again", "try again later",
    "quota exceeded", "throttl",
)

# HTTP status codes (as whole tokens) that indicate a transient condition.
_TRANSIENT_STATUS_RE = re.compile(r"\b(429|500|502|503|504)\b")


def is_transient_error(exc: BaseException) -> bool:
    """Heuristic: True if *exc* looks like a transient/retryable failure.

    Conservative by design — anything not clearly transient is treated as
    deterministic (not retried). Walks the exception cause/context chain once.
    """
    seen = 0
    cur: BaseException | None = exc
    while cur is not None and seen < 5:
        seen += 1
        if isinstance(cur, (TimeoutError, ConnectionError)):
            return True
        if type(cur).__name__ in _TRANSIENT_TYPE_NAMES:
            return True
        msg = str(cur).lower()
        if any(p in msg for p in _TRANSIENT_MSG_PATTERNS):
            return True
        if _TRANSIENT_STATUS_RE.search(msg):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _should_retry(retry_on: Any, exc: BaseException) -> bool:
    if isinstance(retry_on, tuple):
        return isinstance(exc, retry_on)
    if callable(retry_on):
        try:
            return bool(retry_on(exc))
        except Exception:  # noqa: BLE001
            return False
    return False


def degrade_with_warning(
    message_fn: Callable[[BaseException], str] | None = None,
    *,
    agent_path_tag: str | None = None,
    state_updates: dict | None = None,
) -> Callable[[dict, BaseException], dict]:
    """Build an ``on_exhausted`` hook that degrades gracefully: append a warning
    to ``state['warnings']`` (and optionally a tag to ``state['agent_path']`` and
    default keys via *state_updates*) and return the partial state so the
    pipeline can continue instead of aborting."""
    def _on_exhausted(state: dict, exc: BaseException) -> dict:
        warning = message_fn(exc) if message_fn else f"A processing step failed and was skipped: {exc}"
        if isinstance(state, dict):
            state.setdefault("warnings", []).append(warning)
            if agent_path_tag:
                state.setdefault("agent_path", []).append(agent_path_tag)
            if state_updates:
                for key, val in state_updates.items():
                    state.setdefault(key, val)
        logger.error("[NODE_RETRY] degrading gracefully: %s", warning)
        return state
    return _on_exhausted


def retryable_node(
    *,
    max_attempts: int = 2,
    backoff_base: float = 1.0,
    backoff_factor: float = 2.0,
    max_backoff: float = 30.0,
    retry_on: Any = is_transient_error,
    on_exhausted: Callable[[dict, BaseException], Any] | None = None,
    label: str = "",
):
    """Decorate a workflow node ``(state, ...) -> state`` with classified retry.

    - Retries only when *retry_on* matches the exception (default: transient).
    - Up to *max_attempts* with exponential backoff (capped at *max_backoff*).
    - Non-retryable exceptions are raised immediately (no retry storm).
    - On exhaustion: call *on_exhausted(state, exc)* if given (graceful
      degradation), else re-raise.
    """
    def decorator(fn):
        node_label = label or getattr(fn, "__name__", "node")

        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(state, *args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    retry = _should_retry(retry_on, exc)
                    if not retry:
                        logger.warning(
                            "[NODE_RETRY] %s failed with non-retryable error — not retrying: %s",
                            node_label, exc,
                        )
                        break
                    if attempt >= max_attempts:
                        logger.error(
                            "[NODE_RETRY] %s exhausted %d attempt(s): %s",
                            node_label, max_attempts, exc,
                        )
                        break
                    delay = min(max_backoff, backoff_base * (backoff_factor ** (attempt - 1)))
                    logger.warning(
                        "[NODE_RETRY] %s transient failure (attempt %d/%d): %s — retrying in %.1fs",
                        node_label, attempt, max_attempts, exc, delay,
                    )
                    if delay > 0:
                        time.sleep(delay)
            # Retries exhausted or non-retryable error.
            if on_exhausted is not None:
                return on_exhausted(state, last_exc)
            raise last_exc

        return wrapper

    return decorator
