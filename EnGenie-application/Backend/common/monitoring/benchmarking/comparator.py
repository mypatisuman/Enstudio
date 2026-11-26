"""
Benchmark run comparison / regression detection.

Compares two runs (typically a new run vs a baseline) and flags metrics that
moved beyond a percentage threshold. "Higher is worse" for tokens / cost /
latency; a test flipping passed->failed is always a regression (and failed->passed
an improvement).
"""
from typing import Any

from common.monitoring.benchmarking import store

# Run-level metrics where an INCREASE is a regression.
_HIGHER_IS_WORSE = [
    ("total_tokens", "Total tokens"),
    ("total_cost_usd", "Total cost (USD)"),
    ("avg_response_time_ms", "Avg response time (ms)"),
]


def _pct_change(new: float, old: float) -> float:
    """Percent change from old -> new. 0 when old is 0 and new is 0."""
    if old == 0:
        return 0.0 if new == 0 else 100.0
    return (new - old) / abs(old) * 100.0


def compare_runs(run_id_new: str, run_id_baseline: str, threshold_pct: float = 5.0) -> dict[str, Any]:
    """Compare two runs. Returns a structured diff or {"error": ...}."""
    new_run = store.get_run(run_id_new)
    base_run = store.get_run(run_id_baseline)
    if not new_run:
        return {"error": f"Run not found: {run_id_new}"}
    if not base_run:
        return {"error": f"Run not found: {run_id_baseline}"}

    new_sum = new_run.get("summary", {}) or {}
    base_sum = base_run.get("summary", {}) or {}

    metrics: list[dict[str, Any]] = []
    regressions: list[str] = []
    improvements: list[str] = []

    for key, label in _HIGHER_IS_WORSE:
        new_v = float(new_sum.get(key, 0) or 0)
        old_v = float(base_sum.get(key, 0) or 0)
        change = _pct_change(new_v, old_v)
        verdict = "neutral"
        if change > threshold_pct:
            verdict = "regression"
            regressions.append(f"{label}: +{change:.1f}%")
        elif change < -threshold_pct:
            verdict = "improvement"
            improvements.append(f"{label}: {change:.1f}%")
        metrics.append({"metric": label, "new": new_v, "baseline": old_v,
                        "change_pct": round(change, 2), "verdict": verdict})

    # Pass rate (higher is better).
    def _pass_rate(run: dict[str, Any]) -> float:
        total = (run.get("passed", 0) + run.get("failed", 0)) or 0
        return (run.get("passed", 0) / total * 100.0) if total else 0.0

    new_pr, base_pr = _pass_rate(new_run), _pass_rate(base_run)
    pr_change = new_pr - base_pr
    pr_verdict = "neutral"
    if pr_change < -threshold_pct:
        pr_verdict = "regression"
        regressions.append(f"Pass rate: {pr_change:.1f}pp")
    elif pr_change > threshold_pct:
        pr_verdict = "improvement"
        improvements.append(f"Pass rate: +{pr_change:.1f}pp")
    metrics.append({"metric": "Pass rate (%)", "new": round(new_pr, 1),
                    "baseline": round(base_pr, 1), "change_pct": round(pr_change, 2),
                    "verdict": pr_verdict})

    # Per-test status flips.
    new_results = {r["test_id"]: r for r in store.get_results(run_id_new)}
    base_results = {r["test_id"]: r for r in store.get_results(run_id_baseline)}
    test_flips: list[dict[str, Any]] = []
    for test_id in sorted(set(new_results) | set(base_results)):
        n = new_results.get(test_id)
        b = base_results.get(test_id)
        if not n or not b:
            continue
        if n["status"] != b["status"]:
            flip = {"test_id": test_id, "from": b["status"], "to": n["status"]}
            test_flips.append(flip)
            if b["status"] == "passed" and n["status"] == "failed":
                regressions.append(f"{test_id}: passed -> failed")
            elif b["status"] == "failed" and n["status"] == "passed":
                improvements.append(f"{test_id}: failed -> passed")

    return {
        "run_new": {"run_id": run_id_new, "suite_name": new_run.get("suite_name"),
                    "provider": (new_run.get("environment") or {}).get("provider")},
        "run_baseline": {"run_id": run_id_baseline, "suite_name": base_run.get("suite_name"),
                         "provider": (base_run.get("environment") or {}).get("provider")},
        "threshold_pct": threshold_pct,
        "metrics": metrics,
        "test_flips": test_flips,
        "regressions": regressions,
        "improvements": improvements,
        "has_regressions": bool(regressions),
    }
