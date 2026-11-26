"""
Benchmark LLM usage tracking.

When code runs inside a ``benchmark_context``, the LLM tracking callback
(``common.ai.llm.tracking``) calls :meth:`record_benchmark_usage` instead of
writing to production usage. Each call is one row in ``benchmark_llm_usage``,
tagged with run_id + test_id, so per-test and per-run metrics can be aggregated
afterwards.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)

COLLECTION = "benchmark_llm_usage"


class BenchmarkUsageTracker:
    """Records and aggregates per-call LLM usage for benchmark runs."""

    def record_benchmark_usage(
        self,
        run_id: str,
        test_id: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        estimated_cost: float,
        response_time_ms: float,
        agent_type: str | None = None,
        feature_type: str | None = None,
        request_type: str | None = None,
    ) -> bool:
        """Insert one LLM-call usage record for a benchmark test."""
        try:
            mongodb_manager.get_collection(COLLECTION).insert_one({
                "run_id": run_id,
                "test_id": test_id,
                "timestamp": datetime.now(UTC),
                "provider": provider,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
                "response_time_ms": response_time_ms,
                "agent_type": agent_type,
                "feature_type": feature_type,
                "request_type": request_type,
            })
            return True
        except Exception as e:
            logger.error("[BENCHMARK_USAGE] record failed: %s", e)
            return False

    def aggregate_test(self, run_id: str, test_id: str) -> dict[str, Any]:
        """Aggregate all LLM calls for a single test case, with a per-model breakdown."""
        try:
            records = list(mongodb_manager.get_collection(COLLECTION).find(
                {"run_id": run_id, "test_id": test_id}, {"_id": 0}
            ).sort("timestamp", 1))
        except Exception as e:
            logger.error("[BENCHMARK_USAGE] aggregate_test failed: %s", e)
            records = []

        if not records:
            return {
                "total_llm_calls": 0, "total_tokens": 0, "total_input_tokens": 0,
                "total_output_tokens": 0, "total_cost_usd": 0.0, "avg_response_time_ms": 0.0,
                "model_breakdown": {}, "llm_call_breakdown": [],
            }

        models: dict[str, dict[str, Any]] = {}
        breakdown: list[dict[str, Any]] = []
        for idx, r in enumerate(records, 1):
            m = models.setdefault(r["model_name"] or "unknown", {
                "provider": r.get("provider", "unknown"), "llm_calls": 0,
                "total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "total_cost_usd": 0.0,
            })
            m["llm_calls"] += 1
            m["total_tokens"] += r["total_tokens"]
            m["input_tokens"] += r["input_tokens"]
            m["output_tokens"] += r["output_tokens"]
            m["total_cost_usd"] = round(m["total_cost_usd"] + r["estimated_cost"], 6)
            breakdown.append({
                "call_number": idx,
                "purpose": r.get("feature_type") or r.get("request_type") or "—",
                "model": r["model_name"], "provider": r.get("provider", "unknown"),
                "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                "total_tokens": r["total_tokens"], "response_time_ms": r["response_time_ms"],
                "cost_usd": round(r["estimated_cost"], 6),
            })

        total_rt = sum(r["response_time_ms"] for r in records)
        return {
            "total_llm_calls": len(records),
            "total_tokens": sum(r["total_tokens"] for r in records),
            "total_input_tokens": sum(r["input_tokens"] for r in records),
            "total_output_tokens": sum(r["output_tokens"] for r in records),
            "total_cost_usd": round(sum(r["estimated_cost"] for r in records), 6),
            "avg_response_time_ms": round(total_rt / len(records), 2),
            "model_breakdown": models,
            "llm_call_breakdown": breakdown,
        }

    def aggregate_run(self, run_id: str) -> dict[str, Any]:
        """Aggregate every LLM call in a run, plus a per-model breakdown."""
        try:
            records = list(mongodb_manager.get_collection(COLLECTION).find(
                {"run_id": run_id}, {"_id": 0}
            ))
        except Exception as e:
            logger.error("[BENCHMARK_USAGE] aggregate_run failed: %s", e)
            records = []

        if not records:
            return {
                "total_llm_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0,
                "avg_response_time_ms": 0.0, "model_breakdown": {},
            }

        models: dict[str, dict[str, Any]] = {}
        for r in records:
            m = models.setdefault(r["model_name"] or "unknown", {
                "provider": r.get("provider", "unknown"), "llm_calls": 0,
                "total_tokens": 0, "total_cost_usd": 0.0,
            })
            m["llm_calls"] += 1
            m["total_tokens"] += r["total_tokens"]
            m["total_cost_usd"] = round(m["total_cost_usd"] + r["estimated_cost"], 6)

        total_rt = sum(r["response_time_ms"] for r in records)
        return {
            "total_llm_calls": len(records),
            "total_tokens": sum(r["total_tokens"] for r in records),
            "total_input_tokens": sum(r["input_tokens"] for r in records),
            "total_output_tokens": sum(r["output_tokens"] for r in records),
            "total_cost_usd": round(sum(r["estimated_cost"] for r in records), 6),
            "avg_response_time_ms": round(total_rt / len(records), 2),
            "model_breakdown": models,
        }

    def delete_run(self, run_id: str) -> int:
        """Remove all usage rows for a run. Returns deleted count."""
        try:
            return mongodb_manager.get_collection(COLLECTION).delete_many({"run_id": run_id}).deleted_count
        except Exception as e:
            logger.error("[BENCHMARK_USAGE] delete_run failed: %s", e)
            return 0


benchmark_usage_tracker = BenchmarkUsageTracker()
