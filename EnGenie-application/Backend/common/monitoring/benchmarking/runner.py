"""
Benchmark runner — orchestration + terminal logging.

For a given suite it:
  1. creates a run document,
  2. executes each test case inside a benchmark_context (so LLM metrics are
     captured per test),
  3. validates the output against the suite's ``expected_behavior``,
  4. logs **live per-test metrics** to the terminal as it goes, and
  5. logs a **run summary** (totals, averages, per-model breakdown) at the end.

Designed to run synchronously in a single thread (CLI or API subprocess) so the
thread-local benchmark context reliably wraps every LLM call.
"""
import logging
import platform
import sys
import time
from datetime import UTC, datetime
from typing import Any

from common.monitoring.benchmarking import agents, store, suites
from common.monitoring.benchmarking.context import benchmark_context
from common.monitoring.usage.benchmark_usage_tracker import benchmark_usage_tracker

logger = logging.getLogger(__name__)


def _now_run_id() -> str:
    return "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _environment() -> dict[str, Any]:
    """Capture the provider/model the run executes against (for the report header)."""
    import os
    return {
        "provider": os.getenv("LLM_PROVIDER", "unknown"),
        "solution_provider": os.getenv("SOLUTION_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "unknown")),
        "kimi_pro_downgrade_disabled": os.getenv("DISABLE_KIMI_PRO_DOWNGRADE", "false"),
        "python_version": platform.python_version(),
    }


def _validate(output: dict[str, Any], expected: dict[str, Any], metrics: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    """Check output against expected_behavior. Returns pass/fail with reasons."""
    failed: list[str] = []

    if output.get("error"):
        failed.append(f"execution_error: {output['error']}")

    exp_intent = expected.get("intent")
    if exp_intent and output.get("intent") != exp_intent:
        failed.append(f"intent expected={exp_intent} got={output.get('intent')}")

    expected_path = expected.get("agent_path_contains", [])
    actual_path = [p.split(".")[-1] for p in output.get("agent_path", [])]
    missing_nodes = [n for n in expected_path if n not in actual_path]
    if missing_nodes:
        failed.append(f"agent_path missing: {', '.join(missing_nodes)}")

    if "has_missing_fields" in expected and output.get("has_missing_fields") != expected["has_missing_fields"]:
        failed.append(f"has_missing_fields expected={expected['has_missing_fields']}")

    min_len = expected.get("min_response_length")
    if min_len and output.get("response_length", 0) < min_len:
        failed.append(f"response_length {output.get('response_length', 0)} < {min_len}")

    for kw in expected.get("should_contain_keywords", []):
        if kw.lower() not in (output.get("response", "") or "").lower():
            failed.append(f"missing keyword: {kw}")

    max_calls = expected.get("max_llm_calls")
    if max_calls and metrics.get("total_llm_calls", 0) > max_calls:
        failed.append(f"llm_calls {metrics['total_llm_calls']} > {max_calls}")

    max_tokens = expected.get("max_tokens")
    if max_tokens and metrics.get("total_tokens", 0) > max_tokens:
        failed.append(f"tokens {metrics['total_tokens']} > {max_tokens}")

    max_rt = expected.get("max_response_time_ms")
    if max_rt and elapsed_ms > max_rt:
        failed.append(f"time {elapsed_ms:.0f}ms > {max_rt}ms")

    return {"all_passed": not failed, "failed_checks": failed}


def _log_test_line(idx: int, total: int, test_id: str, status: str, elapsed_ms: float, metrics: dict[str, Any], failed: list[str]) -> None:
    """Emit one live per-test metrics line to the terminal."""
    icon = "PASS" if status == "passed" else "FAIL"
    line = (
        f"[BENCHMARK] ({idx}/{total}) {test_id:<16} {icon}  "
        f"{elapsed_ms:7.0f}ms  calls={metrics.get('total_llm_calls', 0):>2}  "
        f"tokens={metrics.get('total_tokens', 0):>7,}  "
        f"cost=${metrics.get('total_cost_usd', 0):.6f}"
    )
    print(line, flush=True)
    if failed:
        print(f"           └─ failed: {'; '.join(failed)}", flush=True)


def _log_summary(run_id: str, suite: dict[str, Any], env: dict[str, Any], passed: int, failed: int, duration_ms: float, summary: dict[str, Any]) -> None:
    """Print the end-of-run summary table to the terminal."""
    total = passed + failed
    bar = "=" * 72
    print(f"\n{bar}", flush=True)
    print(f"  BENCHMARK SUMMARY  ·  {run_id}", flush=True)
    print(f"  Suite : {suite.get('suite_name')}  ({suite.get('agent_type', '').upper()} agent)", flush=True)
    print(f"  Model : {env.get('provider')} / solution={env.get('solution_provider')}", flush=True)
    print(f"  {'-' * 68}", flush=True)
    pass_rate = (passed / total * 100) if total else 0.0
    print(f"  Tests       : {total}   Passed: {passed} ({pass_rate:.0f}%)   Failed: {failed}", flush=True)
    print(f"  Duration    : {duration_ms / 1000:.1f}s", flush=True)
    print(f"  LLM calls   : {summary.get('total_llm_calls', 0)}", flush=True)
    print(f"  Tokens      : {summary.get('total_tokens', 0):,}  "
          f"(in {summary.get('total_input_tokens', 0):,} / out {summary.get('total_output_tokens', 0):,})", flush=True)
    print(f"  Total cost  : ${summary.get('total_cost_usd', 0):.6f}", flush=True)
    print(f"  Avg resp ms : {summary.get('avg_response_time_ms', 0):.0f}", flush=True)

    models = summary.get("model_breakdown", {})
    if models:
        print(f"  {'-' * 68}", flush=True)
        print(f"  {'Model':<34}{'Calls':>7}{'Tokens':>12}{'Cost':>13}", flush=True)
        for name, m in models.items():
            print(f"  {name:<34}{m.get('llm_calls', 0):>7}{m.get('total_tokens', 0):>12,}"
                  f"   ${m.get('total_cost_usd', 0):>9.6f}", flush=True)
    print(f"{bar}\n", flush=True)


# Human-readable descriptions for the nodes that appear in agent_path, used to
# build the per-test workflow-steps table in the detailed report.
_NODE_DESCRIPTIONS = {
    # chat
    "classify_chat_query": "Classify chat query (new / follow-up / invalid)",
    "chat_rag": "Retrieve context + generate answer (RAG)",
    # search
    "search_intent": "Classify search intent",
    "extract_requirements": "Extract structured requirements",
    "validation_agent": "Validate requirements + detect product type",
    "filter_vendors_by_strategy": "Filter vendors by strategy",
    "search_products": "Search products in catalog",
    "load_pdf_content": "Load vendor datasheet PDFs",
    "format_requirements": "Format requirements for analysis",
    "perform_deep_analysis": "Initialize deep vendor analysis",
    "deep_analysis_agent": "Parallel vendor analysis (Pro/Flash)",
    "generate_final_response": "Compile ranked final response",
    "summary_agent": "Generate conversational summary",
    # solution
    "project_intent": "Classify project intent",
    "instrument_identification": "Identify instruments (deep analysis)",
    "identify_instruments": "Identify instruments from requirements",
    "standards_application": "Apply engineering standards",
    "apply_standards": "Apply engineering standards",
    "holistic_agent": "Judge requirement holism + extract structured requirements",
    "expansion_agent": "Apply engineering standards (retrieval & expansion)",
    "infer_agent": "Infer product catalog mapping",
    "format_results": "Format structured specifications",
    "final_response": "Build final structured response",
}


def _derive_workflow_steps(agent_path: list[str]) -> list[dict[str, Any]]:
    """Build an ordered per-node breakdown from agent_path for the report."""
    steps = []
    for i, entry in enumerate(agent_path, 1):
        node = entry.split(".")[-1] if "." in entry else entry
        steps.append({
            "step_num": i,
            "node": node,
            "description": _NODE_DESCRIPTIONS.get(node, f"Executed node: {node}"),
            "output": {},
        })
    return steps


def run_suite(suite_key: str, run_id: str | None = None, limit_tests: int | None = None) -> dict[str, Any]:
    """
    Execute a benchmark suite end-to-end. Returns the run summary dict.

    Args:
        suite_key:   "search" | "solution" | "chat"
        run_id:      optional pre-created run id (API passes one in); generated if None
        limit_tests: cap to the first N test cases (handy for quick checks / quota)
    """
    suite = suites.load_suite(suite_key)
    agent_type = suite.get("agent_type", suite_key)
    test_cases = suite.get("test_cases", [])
    if limit_tests:
        test_cases = test_cases[:limit_tests]

    run_id = run_id or _now_run_id()
    env = _environment()

    # The API may have already created the run doc; create it only if absent.
    if store.get_run(run_id) is None:
        store.create_run(run_id, suite_key, {**suite, "test_cases": test_cases}, env)

    print(f"\n[BENCHMARK] Starting run {run_id}  suite={suite_key}  "
          f"tests={len(test_cases)}  provider={env.get('provider')}\n", flush=True)

    start = time.time()
    passed = failed = 0
    try:
        for idx, tc in enumerate(test_cases, 1):
            test_id = tc["test_id"]
            t0 = time.time()
            with benchmark_context(run_id, test_id):
                output = agents.execute(agent_type, tc.get("input", {}))
            elapsed_ms = (time.time() - t0) * 1000

            metrics = benchmark_usage_tracker.aggregate_test(run_id, test_id)
            validation = _validate(output, tc.get("expected_behavior", {}), metrics, elapsed_ms)
            status = "passed" if validation["all_passed"] else "failed"
            passed += status == "passed"
            failed += status == "failed"

            # Derive a per-node workflow breakdown from the captured agent_path
            # so the detailed PDF can render a step-by-step table.
            steps = _derive_workflow_steps(output.get("agent_path", []))
            output["workflow_steps_analysis"] = steps
            output["total_workflow_steps"] = len(steps)

            store.save_result({
                "run_id": run_id,
                "test_id": test_id,
                "test_name": tc.get("name", test_id),
                "agent_type": agent_type,
                "executed_at": datetime.now(UTC),
                "status": status,
                "execution_time_ms": elapsed_ms,
                "llm_metrics": metrics,
                "output": output,
                "validation": validation,
                "error": output.get("error"),
            })
            store.update_progress(run_id, passed, failed)
            _log_test_line(idx, len(test_cases), test_id, status, elapsed_ms, metrics, validation["failed_checks"])

        duration_ms = (time.time() - start) * 1000
        summary = benchmark_usage_tracker.aggregate_run(run_id)
        # Run-level averages for the report.
        n = passed + failed
        if n:
            summary["avg_tokens_per_test"] = round(summary.get("total_tokens", 0) / n, 1)
            summary["avg_llm_calls_per_test"] = round(summary.get("total_llm_calls", 0) / n, 2)
        store.complete_run(run_id, passed, failed, duration_ms, summary)
        _log_summary(run_id, suite, env, passed, failed, duration_ms, summary)
        return {"run_id": run_id, "status": "completed", "passed": passed, "failed": failed,
                "duration_ms": duration_ms, "summary": summary}

    except Exception as e:
        logger.error("[BENCHMARK] run %s failed: %s", run_id, e, exc_info=True)
        store.fail_run(run_id, str(e))
        print(f"[BENCHMARK] run {run_id} FAILED: {e}", file=sys.stderr, flush=True)
        raise
