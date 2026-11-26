"""Uniform node-retry decorator (reference `@retryable_node` contract).

Retries a node function on EXCEPTION, then calls its per-node
degradation hook. This is orthogonal to the QC retry loops, which are
metric-driven graph edges, not exception handling.

    @retryable_node(max_attempts=2, label="llm_a",
                    on_exhausted=lambda state, err: {"status": "degraded"})
    def llm_a_node(state): ...

Rules:
- GraphInterrupt (human-in-the-loop pauses) is ALWAYS re-raised —
  an interrupt is control flow, never a failure.
- FatalAgentError is re-raised (the workflow-level handler owns it).
- on_exhausted(state, error) returns the node's state-delta; if it is
  None, the last error is re-raised.
"""
from __future__ import annotations

import functools
from typing import Callable

from agents.streaming import FatalAgentError, stage as emit_stage


def retryable_node(max_attempts: int = 2, label: str = "",
                   on_exhausted: Callable | None = None):
    def decorate(fn):
        node_label = label or fn.__name__

        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            last_err: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(state, *args, **kwargs)
                except FatalAgentError:
                    raise
                except Exception as e:
                    if type(e).__name__ == "GraphInterrupt" or \
                            e.__class__.__module__.startswith("langgraph"):
                        raise                     # interrupts are control flow
                    last_err = e
                    if attempt < max_attempts:
                        emit_stage(node_label, "retry", attempt=attempt,
                                   error=str(e)[:200])
            emit_stage(node_label, "exhausted", error=str(last_err)[:200])
            if on_exhausted is not None:
                return on_exhausted(state, last_err)
            raise last_err  # type: ignore[misc]
        return wrapper
    return decorate
