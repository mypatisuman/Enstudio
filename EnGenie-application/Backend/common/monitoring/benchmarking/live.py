"""
Live-run benchmark capture.

Wraps a real user workflow execution (search / solution / chat) so its LLM
metrics are recorded as a benchmark run **in addition to** normal production
usage — the tracking callback records both. Enabled by default; set
``BENCHMARK_LIVE_CAPTURE=false`` to disable without code changes.

    from common.monitoring.benchmarking import live
    with live.capture("search", user_input=query, user_id=uid):
        result = run_search_workflow(...)

Capture never interferes with the real request: if setup fails the workflow runs
without capture, and if the workflow raises, the exception propagates unchanged
while the (failed) run is still finalized.

Limitation: metrics are attributed via a thread-local context, so LLM calls made
in worker threads the workflow spawns internally (e.g. parallel analysis) are
recorded in production usage but may be undercounted in the benchmark totals.
"""
import logging
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """Whether live-run capture is turned on (default: yes)."""
    return os.getenv("BENCHMARK_LIVE_CAPTURE", "true").strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def capture(agent_type: str, user_input: str = "", user_id: Any = None):
    """Record the wrapped workflow execution as a one-test live benchmark run."""
    if not is_enabled():
        yield None
        return

    from common.monitoring.benchmarking import store
    from common.monitoring.benchmarking.context import benchmark_context
    from common.monitoring.usage.benchmark_usage_tracker import benchmark_usage_tracker

    run_id = f"live_{datetime.now():%Y%m%d_%H%M%S_%f}_{agent_type}"
    test_id = "live_001"
    snippet = (user_input or "").strip()[:200]

    try:
        store.create_live_run(run_id, agent_type, snippet, user_id)
    except Exception as e:  # don't let benchmarking break the real request
        logger.warning("[BENCH_LIVE] create failed (%s) — running without capture", e)
        yield None
        return

    t0 = time.time()
    status, error = "completed", None
    try:
        with benchmark_context(run_id, test_id):
            yield run_id
    except Exception as e:
        status, error = "failed", str(e)
        raise  # preserve the real request's error behavior
    finally:
        try:
            elapsed_ms = (time.time() - t0) * 1000
            metrics = benchmark_usage_tracker.aggregate_test(run_id, test_id)
            store.save_result({
                "run_id": run_id,
                "test_id": test_id,
                "test_name": snippet or "(live run)",
                "agent_type": agent_type,
                "executed_at": datetime.now(UTC),
                "status": status,
                "execution_time_ms": elapsed_ms,
                "llm_metrics": metrics,
                "output": {},
                "validation": {"all_passed": status == "completed", "failed_checks": []},
                "error": error,
            })
            summary = benchmark_usage_tracker.aggregate_run(run_id)
            store.complete_live_run(run_id, status, elapsed_ms, summary, error)
        except Exception as e:
            logger.warning("[BENCH_LIVE] finalize failed for %s: %s", run_id, e)
