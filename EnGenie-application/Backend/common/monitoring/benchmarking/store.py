"""
MongoDB persistence for benchmark runs and per-test results.

Two collections:
  - ``benchmark_runs``    : one document per run (lifecycle + summary metrics)
  - ``benchmark_results`` : one document per test case within a run

Run lifecycle: create_run (status=running) -> save_result/update_progress (xN)
-> complete_run / fail_run.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)

RUNS = "benchmark_runs"
RESULTS = "benchmark_results"
USAGE = "benchmark_llm_usage"


def resolve_environment_models() -> dict[str, Any]:
    """Snapshot which provider AND models are configured right now.

    ``LLM_PROVIDER`` alone cannot identify a run's models: each tier (pro/flash/
    lite) maps to its own model id, and a run may fail over to a second
    provider mid-flight. Recording the resolved per-tier model ids makes a run
    document self-describing for later model comparisons.
    """
    import os
    try:
        from common.ai.llm.config import (
            FALLBACK_LLM_PROVIDER,
            LLM_PROVIDER,
            PROVIDER_MODELS,
            SOLUTION_LLM_PROVIDER,
        )
        provider = LLM_PROVIDER
        return {
            "provider": provider,
            "solution_provider": SOLUTION_LLM_PROVIDER,
            "fallback_provider": FALLBACK_LLM_PROVIDER or None,
            "models": dict(PROVIDER_MODELS.get(provider, {})),
            "solution_models": dict(PROVIDER_MODELS.get(SOLUTION_LLM_PROVIDER, {})),
        }
    except Exception as e:  # config import must never break a run
        logger.debug("[BENCHMARK] could not resolve model environment: %s", e)
        return {"provider": os.getenv("LLM_PROVIDER", "unknown"), "models": {}}


def create_run(run_id: str, suite_key: str, suite: dict[str, Any], environment: dict[str, Any]) -> None:
    """Insert a new suite run document in the ``running`` state."""
    mongodb_manager.get_collection(RUNS).insert_one({
        "run_id": run_id,
        "suite_key": suite_key,
        "suite_name": suite.get("suite_name", suite_key),
        "agent_type": suite.get("agent_type", suite_key),
        "source": "suite",
        "is_baseline": False,
        "status": "running",
        "started_at": datetime.now(UTC),
        "completed_at": None,
        "duration_ms": 0,
        "total_tests": len(suite.get("test_cases", [])),
        "passed": 0,
        "failed": 0,
        "environment": environment,
        "summary": {},
        "error": None,
    })


def create_live_run(run_id: str, agent_type: str, input_snippet: str, user_id: Any = None) -> None:
    """Insert a single-test ``live`` run for one real user workflow execution."""
    environment = resolve_environment_models()
    environment["triggered_by"] = user_id
    mongodb_manager.get_collection(RUNS).insert_one({
        "run_id": run_id,
        "suite_key": f"live_{agent_type}",
        "suite_name": f"Live {agent_type} run",
        "agent_type": agent_type,
        "source": "live",
        "input": input_snippet,
        "status": "running",
        "started_at": datetime.now(UTC),
        "completed_at": None,
        "duration_ms": 0,
        "total_tests": 1,
        "passed": 0,
        "failed": 0,
        "environment": environment,
        "summary": {},
        "error": None,
    })


def complete_live_run(run_id: str, status: str, duration_ms: float, summary: dict[str, Any], error: str | None) -> None:
    """Finalize a live run (status = 'completed' or 'failed')."""
    ok = status == "completed"
    mongodb_manager.get_collection(RUNS).update_one(
        {"run_id": run_id},
        {"$set": {
            "status": status,
            "completed_at": datetime.now(UTC),
            "duration_ms": duration_ms,
            "passed": 1 if ok else 0,
            "failed": 0 if ok else 1,
            "summary": summary,
            "error": error,
        }},
    )


def update_progress(run_id: str, passed: int, failed: int) -> None:
    """Update the running pass/fail counters (drives the UI progress bar)."""
    mongodb_manager.get_collection(RUNS).update_one(
        {"run_id": run_id}, {"$set": {"passed": passed, "failed": failed}}
    )


def save_result(result: dict[str, Any]) -> None:
    """Persist a single test-case result document."""
    mongodb_manager.get_collection(RESULTS).insert_one(dict(result))


def complete_run(run_id: str, passed: int, failed: int, duration_ms: float, summary: dict[str, Any]) -> None:
    """Mark a run completed and store aggregated summary metrics."""
    mongodb_manager.get_collection(RUNS).update_one(
        {"run_id": run_id},
        {"$set": {
            "status": "completed",
            "completed_at": datetime.now(UTC),
            "duration_ms": duration_ms,
            "passed": passed,
            "failed": failed,
            "summary": summary,
        }},
    )


def fail_run(run_id: str, error: str) -> None:
    """Mark a run failed with an error message."""
    mongodb_manager.get_collection(RUNS).update_one(
        {"run_id": run_id},
        {"$set": {"status": "failed", "completed_at": datetime.now(UTC), "error": error}},
    )


def cancel_run(run_id: str) -> bool:
    """Mark a still-running run as cancelled. Returns True if a run was updated.

    Note: the background worker thread (if still executing) is not force-killed;
    this just stops the UI from tracking it and flags the record.
    """
    res = mongodb_manager.get_collection(RUNS).update_one(
        {"run_id": run_id, "status": "running"},
        {"$set": {"status": "cancelled", "completed_at": datetime.now(UTC),
                  "error": "Cancelled by user"}},
    )
    return res.modified_count > 0


def cleanup_stale_runs(max_age_minutes: int = 30) -> int:
    """Flag runs stuck in 'running' past the cutoff as failed. Returns count updated.

    Catches orphans from a server restart or an aborted launch that will never
    transition on their own.
    """
    from datetime import timedelta
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    res = mongodb_manager.get_collection(RUNS).update_many(
        {"status": "running", "started_at": {"$lt": cutoff}},
        {"$set": {"status": "failed", "completed_at": datetime.now(UTC),
                  "error": f"Marked stale (no progress for >{max_age_minutes}m)"}},
    )
    return res.modified_count


def delete_run(run_id: str) -> dict[str, int]:
    """Delete a run and its per-test results. Returns deleted counts."""
    runs = mongodb_manager.get_collection(RUNS).delete_one({"run_id": run_id}).deleted_count
    results = mongodb_manager.get_collection(RESULTS).delete_many({"run_id": run_id}).deleted_count
    return {"runs": runs, "results": results}


def set_baseline(run_id: str, is_baseline: bool = True) -> bool:
    """Mark/unmark a run as the baseline for its suite.

    Setting a baseline clears the flag on other runs of the same suite so each
    suite has at most one baseline.
    """
    coll = mongodb_manager.get_collection(RUNS)
    run = coll.find_one({"run_id": run_id})
    if not run:
        return False
    if is_baseline:
        coll.update_many({"suite_key": run.get("suite_key"), "run_id": {"$ne": run_id}},
                         {"$set": {"is_baseline": False}})
    res = coll.update_one({"run_id": run_id}, {"$set": {"is_baseline": is_baseline}})
    return res.matched_count > 0


def get_baseline(suite_key: str) -> dict[str, Any] | None:
    """Return the baseline run for a suite, if one is set."""
    return _clean(mongodb_manager.get_collection(RUNS).find_one(
        {"suite_key": suite_key, "is_baseline": True}))


def _clean(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def list_runs(limit: int = 50, suite_key: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
    """Most-recent-first list of runs (without per-test detail).

    ``source`` filters by "suite" or "live"; None returns both.
    """
    query: dict[str, Any] = {}
    if suite_key:
        query["suite_key"] = suite_key
    if source:
        query["source"] = source
    cursor = mongodb_manager.get_collection(RUNS).find(query).sort("started_at", -1).limit(limit)
    return [_clean(d) for d in cursor]


def get_run(run_id: str) -> dict[str, Any] | None:
    """Fetch a single run document."""
    return _clean(mongodb_manager.get_collection(RUNS).find_one({"run_id": run_id}))


def get_results(run_id: str) -> list[dict[str, Any]]:
    """Fetch all test-case results for a run, ordered by test_id."""
    cursor = mongodb_manager.get_collection(RESULTS).find({"run_id": run_id})
    results = [_clean(d) for d in cursor]
    results.sort(key=lambda r: r.get("test_id", ""))
    return results


# ── Per-model tracking ────────────────────────────────────────────────────────

def aggregate_by_model(
    days: int = 30,
    agent_type: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Leaderboard: one row per (model, provider) across all benchmark runs.

    Answers "how do our models actually compare" — the per-run ``model_breakdown``
    only ever described a single run. Aggregates ``benchmark_llm_usage`` (every
    LLM call, already tagged with model + provider) and joins run status so each
    model also carries a success rate.

    ``days`` bounds the window, ``agent_type`` narrows to solution/search/chat,
    ``source`` to "live" or "suite" runs.
    """
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(days=days)
    match: dict[str, Any] = {"timestamp": {"$gte": since}}
    if agent_type:
        match["agent_type"] = agent_type

    # When filtering by run source, resolve the matching run_ids first — the
    # usage rows carry no source field.
    if source:
        run_ids = [
            r["run_id"]
            for r in mongodb_manager.get_collection(RUNS).find(
                {"source": source, "started_at": {"$gte": since}}, {"run_id": 1, "_id": 0}
            )
        ]
        if not run_ids:
            return []
        match["run_id"] = {"$in": run_ids}

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"model": "$model_name", "provider": "$provider"},
            "llm_calls": {"$sum": 1},
            "runs": {"$addToSet": "$run_id"},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "total_cost_usd": {"$sum": "$estimated_cost"},
            "avg_response_time_ms": {"$avg": "$response_time_ms"},
            "max_response_time_ms": {"$max": "$response_time_ms"},
            "last_used": {"$max": "$timestamp"},
        }},
        {"$sort": {"total_tokens": -1}},
    ]

    try:
        rows = list(mongodb_manager.get_collection(USAGE).aggregate(pipeline))
    except Exception as e:
        logger.error("[BENCHMARK] aggregate_by_model failed: %s", e)
        return []

    # Success rate per model: share of that model's runs that completed.
    run_status: dict[str, str] = {}
    all_run_ids = {rid for row in rows for rid in row.get("runs", [])}
    if all_run_ids:
        try:
            for r in mongodb_manager.get_collection(RUNS).find(
                {"run_id": {"$in": list(all_run_ids)}}, {"run_id": 1, "status": 1, "_id": 0}
            ):
                run_status[r["run_id"]] = r.get("status", "unknown")
        except Exception as e:
            logger.debug("[BENCHMARK] run status join failed: %s", e)

    out: list[dict[str, Any]] = []
    for row in rows:
        run_ids = row.get("runs", [])
        completed = sum(1 for rid in run_ids if run_status.get(rid) == "completed")
        total_runs = len(run_ids)
        total_tokens = row.get("total_tokens", 0) or 0
        cost = round(row.get("total_cost_usd", 0.0) or 0.0, 6)
        out.append({
            "model_name": row["_id"].get("model") or "unknown",
            "provider": row["_id"].get("provider") or "unknown",
            "llm_calls": row.get("llm_calls", 0),
            "runs": total_runs,
            "input_tokens": row.get("input_tokens", 0),
            "output_tokens": row.get("output_tokens", 0),
            "total_tokens": total_tokens,
            "total_cost_usd": cost,
            "cost_per_1k_tokens": round((cost / total_tokens) * 1000, 6) if total_tokens else 0.0,
            "avg_tokens_per_call": round(total_tokens / row["llm_calls"], 1) if row.get("llm_calls") else 0.0,
            "avg_response_time_ms": round(row.get("avg_response_time_ms", 0.0) or 0.0, 2),
            "max_response_time_ms": round(row.get("max_response_time_ms", 0.0) or 0.0, 2),
            "success_rate": round((completed / total_runs) * 100, 1) if total_runs else 0.0,
            "last_used": row.get("last_used"),
        })
    return out


def compare_models(model_a: str, model_b: str, days: int = 30) -> dict[str, Any]:
    """Head-to-head comparison of two models on the metrics that matter.

    Unlike ``comparator.compare_runs`` (which diffs two individual runs), this
    compares every recorded call for each model over the window, so the two
    sides need not come from the same run or even the same day.
    """
    rows = {r["model_name"]: r for r in aggregate_by_model(days=days)}
    a, b = rows.get(model_a), rows.get(model_b)
    if not a or not b:
        missing = [m for m, r in ((model_a, a), (model_b, b)) if not r]
        return {"error": f"No benchmark data for: {', '.join(missing)}", "days": days}

    # (metric, lower_is_better)
    metrics = [
        ("avg_response_time_ms", True),
        ("cost_per_1k_tokens", True),
        ("avg_tokens_per_call", True),
        ("success_rate", False),
    ]
    comparison = []
    for key, lower_better in metrics:
        va, vb = a.get(key, 0) or 0, b.get(key, 0) or 0
        if va == vb:
            winner = "tie"
        elif (va < vb) == lower_better:
            winner = model_a
        else:
            winner = model_b
        delta_pct = round(((vb - va) / va) * 100, 1) if va else None
        comparison.append({
            "metric": key, "lower_is_better": lower_better,
            model_a: va, model_b: vb, "winner": winner, "delta_pct": delta_pct,
        })

    wins_a = sum(1 for c in comparison if c["winner"] == model_a)
    wins_b = sum(1 for c in comparison if c["winner"] == model_b)
    return {
        "days": days,
        "model_a": a,
        "model_b": b,
        "comparison": comparison,
        "verdict": model_a if wins_a > wins_b else model_b if wins_b > wins_a else "tie",
        "wins": {model_a: wins_a, model_b: wins_b},
    }
