"""
Benchmarking system for LLM agent performance testing.

Measures token usage, cost, latency and pass/fail across the chat, search and
solution agent workflows — primarily to compare model providers (e.g. Kimi).

Public surface:
  - benchmark_context / is_benchmark_mode / get_benchmark_context — execution context
    used by the LLM tracking callback to attribute metrics to a run/test.
  - runner.run_suite — execute a suite end-to-end (used by the CLI and API).
"""
from common.monitoring.benchmarking.context import (
    benchmark_context,
    get_benchmark_context,
    is_benchmark_mode,
)

__all__ = ["benchmark_context", "get_benchmark_context", "is_benchmark_mode"]
