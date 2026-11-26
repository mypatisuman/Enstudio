"""
Benchmark execution context.

Marks a block of code as running inside a benchmark so the LLM tracking
callback (``common.ai.llm.tracking``) ALSO routes token/cost/latency metrics to
the benchmark collections, tagged with the run/test ids.

    with benchmark_context(run_id, test_id):
        run_search_agent(...)   # every LLM call is attributed to this test

THREAD PROPAGATION
------------------
Backed by a :class:`contextvars.ContextVar`, not ``threading.local()``. The
agents fan work out across ``ThreadPoolExecutor`` pools (parallel inference,
vendor analysis, chunked holistic analysis, …) and a thread-local does not
cross that boundary — every pooled LLM call silently missed the benchmark
totals, which is precisely where most tokens are spent.

A ContextVar alone does not fix ``ThreadPoolExecutor`` either: pool worker
threads start with an empty context. Use :func:`benchmark_pool` (or
:func:`propagate`) so each submitted task re-enters the caller's context:

    from common.monitoring.benchmarking.context import benchmark_pool
    with benchmark_pool(max_workers=6) as executor:
        futures = [executor.submit(fn, item) for item in items]

``benchmark_pool`` is a drop-in for ``ThreadPoolExecutor`` and costs nothing
when no benchmark is active.
"""
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# (active, run_id, test_id) — a single var keeps enter/exit atomic.
_CTX: contextvars.ContextVar[tuple[bool, str | None, str | None]] = contextvars.ContextVar(
    "benchmark_ctx", default=(False, None, None)
)


@contextmanager
def benchmark_context(run_id: str, test_id: str):
    """Enter benchmark mode for the duration of the block (re-entrant safe)."""
    token = _CTX.set((True, run_id, test_id))
    logger.debug("[BENCHMARK] enter run=%s test=%s", run_id, test_id)
    try:
        yield
    finally:
        _CTX.reset(token)
        logger.debug("[BENCHMARK] exit run=%s test=%s", run_id, test_id)


def is_benchmark_mode() -> bool:
    """True when the current context is executing inside a benchmark_context."""
    return _CTX.get()[0]


def get_benchmark_context() -> dict | None:
    """Return {'run_id', 'test_id'} when in benchmark mode, else None."""
    active, run_id, test_id = _CTX.get()
    if not active:
        return None
    return {"run_id": run_id, "test_id": test_id}


def propagate(fn):
    """Bind *fn* to the CURRENT context so it keeps benchmark attribution when
    it runs on another thread.

    Use when submitting to a plain executor you do not control:

        ctx_fn = propagate(worker)
        executor.submit(ctx_fn, item)
    """
    ctx = contextvars.copy_context()

    def _runner(*args, **kwargs):
        return ctx.run(fn, *args, **kwargs)

    return _runner


class BenchmarkThreadPoolExecutor(ThreadPoolExecutor):
    """``ThreadPoolExecutor`` that re-enters the submitting thread's context.

    Each :meth:`submit` captures the caller's context at submit time, so LLM
    calls made in pool workers stay attributed to the active benchmark run.
    Behaves exactly like the stdlib executor when no benchmark is active.
    """

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


def benchmark_pool(*args, **kwargs) -> BenchmarkThreadPoolExecutor:
    """Context-propagating drop-in for ``ThreadPoolExecutor(...)``."""
    return BenchmarkThreadPoolExecutor(*args, **kwargs)
