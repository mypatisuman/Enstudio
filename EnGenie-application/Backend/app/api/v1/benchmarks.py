"""
Benchmarks domain routes.

The UI triggers a run here; execution happens **in-process** in a background
thread that drives the live solution / search / chat workflow graphs directly
(no subprocess). Live per-test metrics stream to the backend terminal, results
land in MongoDB, and the browser polls for status and auto-downloads a PDF it
renders client-side.

Note on provider: an in-process run uses whichever LLM provider the server was
started with. To benchmark Kimi specifically, start the backend with
LLM_PROVIDER=kimi (and SOLUTION_LLM_PROVIDER=kimi).
"""
import logging
import os
import threading
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.core.errors import notify_failure
from app.core.security import login_required
from common.helpers.azure_session import get_session
from common.helpers.responses import JSONResponse

logger = logging.getLogger(__name__)
blueprint = APIRouter()


@blueprint.get("/api/benchmarks/suites")
@login_required
async def list_suites(request: Request):
    """List runnable suites and the provider/models in-process runs will use."""
    from common.monitoring.benchmarking import store, suites
    env = store.resolve_environment_models()
    provider = env.get("provider", "unknown")
    solution_provider = env.get("solution_provider", provider)
    return JSONResponse({
        "suites": suites.available_suites(),
        "provider": provider,
        "solution_provider": solution_provider,
        "fallback_provider": env.get("fallback_provider"),
        "models": env.get("models", {}),
        "solution_models": env.get("solution_models", {}),
        # True only when both relevant providers are Kimi.
        "is_kimi": provider.lower() == "kimi" and solution_provider.lower() == "kimi",
    })


def _int_param(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(request.query_params.get(name, default)), hi))
    except (TypeError, ValueError):
        return default


@blueprint.get("/api/benchmarks/models")
@login_required
async def model_leaderboard(request: Request):
    """Per-model benchmark leaderboard across all runs.

    Query: ?days=30 &agent_type=solution|search|chat &source=live|suite
    """
    from common.monitoring.benchmarking import store
    days = _int_param(request, "days", 30, 1, 365)
    agent_type = request.query_params.get("agent_type") or None
    source = request.query_params.get("source") or None

    models = await run_in_threadpool(
        store.aggregate_by_model, days=days, agent_type=agent_type, source=source,
    )
    totals = {
        "models": len(models),
        "llm_calls": sum(m["llm_calls"] for m in models),
        "total_tokens": sum(m["total_tokens"] for m in models),
        "total_cost_usd": round(sum(m["total_cost_usd"] for m in models), 6),
    }
    env = store.resolve_environment_models()
    return JSONResponse({
        "models": models,
        "totals": totals,
        "days": days,
        "agent_type": agent_type,
        "source": source,
        "active_provider": env.get("provider"),
        "active_models": env.get("models", {}),
    })


@blueprint.post("/api/benchmarks/models/compare")
@login_required
async def compare_two_models(request: Request):
    """Head-to-head comparison of two models. Body: {model_a, model_b, days?}"""
    from common.monitoring.benchmarking import store
    try:
        data = await request.json()
    except Exception:
        data = {}

    model_a = (data.get("model_a") or "").strip()
    model_b = (data.get("model_b") or "").strip()
    if not model_a or not model_b:
        return JSONResponse({"error": "model_a and model_b are required"}, status_code=400)
    if model_a == model_b:
        return JSONResponse({"error": "Pick two different models"}, status_code=400)

    try:
        days = max(1, min(int(data.get("days", 30)), 365))
    except (TypeError, ValueError):
        days = 30

    result = await run_in_threadpool(store.compare_models, model_a, model_b, days)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)


def _run_jobs_in_background(jobs: list[tuple[str, str]], limit_tests: int | None) -> None:
    """Execute (suite_key, run_id) jobs sequentially in a worker thread."""
    from common.monitoring.benchmarking import runner

    def _worker():
        for suite_key, run_id in jobs:
            try:
                runner.run_suite(suite_key, run_id=run_id, limit_tests=limit_tests)
            except Exception as e:  # run_suite already marks the run failed
                logger.error("[BENCHMARKS] run %s (%s) crashed: %s", run_id, suite_key, e)

    threading.Thread(target=_worker, daemon=True, name="benchmark-runner").start()


@blueprint.post("/api/benchmarks/run")
@login_required
async def start_run(request: Request):
    """Create run record(s) and execute the benchmark in a background thread.

    Body: {"suite": "search"|"solution"|"chat"|"all", "limit_tests"?: int}
    """
    session = get_session(request)
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        suite_param = (data.get("suite") or "all").strip().lower()
        limit_tests = int(data["limit_tests"]) if data.get("limit_tests") else None

        from common.monitoring.benchmarking import store, suites
        available = suites.available_suites()
        if suite_param == "all":
            targets = available
        elif suite_param in available:
            targets = [suite_param]
        else:
            return JSONResponse({"error": f"Unknown suite: {suite_param}"}, status_code=400)

        # Resolved per-tier model ids travel with the run so it stays
        # self-describing when models are compared later.
        environment = store.resolve_environment_models()
        environment.update({
            "kimi_pro_downgrade_disabled": os.getenv("DISABLE_KIMI_PRO_DOWNGRADE", "false"),
            "triggered_by": session.get("user_id"),
        })

        # Pre-create one run record per target suite so the UI can poll immediately.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        jobs: list[tuple[str, str]] = []
        for suite_key in targets:
            suite = suites.load_suite(suite_key)
            test_cases = suite.get("test_cases", [])
            if limit_tests:
                test_cases = test_cases[:limit_tests]
            run_id = f"run_{ts}_{suite_key}"
            store.create_run(run_id, suite_key, {**suite, "test_cases": test_cases}, environment)
            jobs.append((suite_key, run_id))

        _run_jobs_in_background(jobs, limit_tests)
        run_ids = [rid for _, rid in jobs]
        logger.info("[BENCHMARKS] started in-process run(s): %s", run_ids)
        return JSONResponse({"run_ids": run_ids, "run_id": run_ids[0], "status": "running"})

    except Exception as e:
        logger.exception("[BENCHMARKS] failed to start run")
        notify_failure("Benchmarks Run", str(e), page="benchmarks", user_id=session.get("user_id"))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/benchmarks/runs")
@login_required
async def list_runs(request: Request, suite: str = None, source: str = None, limit: int = 50):
    """List recent benchmark runs. ``source`` filters by 'suite' or 'live'."""
    from common.monitoring.benchmarking import store
    return JSONResponse(store.list_runs(limit=limit, suite_key=suite, source=source))


@blueprint.post("/api/benchmarks/runs/cleanup")
@login_required
async def cleanup_runs(request: Request):
    """Mark runs stuck in 'running' past the cutoff (default 30m) as failed."""
    from common.monitoring.benchmarking import store
    try:
        data = await request.json()
    except Exception:
        data = {}
    max_age = int(data.get("max_age_minutes", 30))
    updated = store.cleanup_stale_runs(max_age_minutes=max_age)
    return JSONResponse({"cleaned": updated})


@blueprint.post("/api/benchmarks/runs/{run_id}/cancel")
@login_required
async def cancel_run(request: Request, run_id: str):
    """Cancel a still-running run (flags the record; UI stops tracking it)."""
    from common.monitoring.benchmarking import store
    return JSONResponse({"cancelled": store.cancel_run(run_id), "run_id": run_id})


@blueprint.delete("/api/benchmarks/runs/{run_id}")
@login_required
async def delete_run(request: Request, run_id: str):
    """Delete a run plus its results and LLM-usage rows."""
    from common.monitoring.benchmarking import store
    from common.monitoring.usage.benchmark_usage_tracker import benchmark_usage_tracker
    counts = store.delete_run(run_id)
    counts["usage"] = benchmark_usage_tracker.delete_run(run_id)
    return JSONResponse({"deleted": counts, "run_id": run_id})


@blueprint.post("/api/benchmarks/compare")
@login_required
async def compare(request: Request):
    """Compare two runs. Body: {run_new, run_baseline, threshold_pct?}."""
    from common.monitoring.benchmarking import comparator
    try:
        data = await request.json()
    except Exception:
        data = {}
    run_new = data.get("run_new")
    run_baseline = data.get("run_baseline")
    if not run_new or not run_baseline:
        return JSONResponse({"error": "run_new and run_baseline are required"}, status_code=400)
    result = comparator.compare_runs(run_new, run_baseline, float(data.get("threshold_pct", 5.0)))
    status = 404 if "error" in result else 200
    return JSONResponse(result, status_code=status)


@blueprint.post("/api/benchmarks/runs/{run_id}/baseline")
@login_required
async def set_baseline(request: Request, run_id: str):
    """Mark/unmark a run as its suite's baseline. Body: {is_baseline?: bool}."""
    from common.monitoring.benchmarking import store
    try:
        data = await request.json()
    except Exception:
        data = {}
    ok = store.set_baseline(run_id, bool(data.get("is_baseline", True)))
    if not ok:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return JSONResponse({"run_id": run_id, "is_baseline": bool(data.get("is_baseline", True))})


@blueprint.get("/api/benchmarks/runs/{run_id}/status")
@login_required
async def run_status(request: Request, run_id: str):
    """Lightweight polling endpoint: status + progress counters."""
    from common.monitoring.benchmarking import store
    run = store.get_run(run_id)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return JSONResponse({
        "run_id": run_id,
        "status": run.get("status"),
        "passed": run.get("passed", 0),
        "failed": run.get("failed", 0),
        "total_tests": run.get("total_tests", 0),
    })


@blueprint.get("/api/benchmarks/runs/{run_id}")
@login_required
async def run_detail(request: Request, run_id: str):
    """Full run + per-test results (the frontend renders the PDF from this)."""
    from common.monitoring.benchmarking import reporter
    report = reporter.build_report(run_id)
    if report is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return JSONResponse(report)


@blueprint.get("/api/benchmarks/runs/{run_id}/export.json")
@login_required
async def export_json(request: Request, run_id: str):
    """Download the run + results bundle as a JSON attachment."""
    from common.monitoring.benchmarking import reporter
    from fastapi.responses import JSONResponse as FastJSON
    report = reporter.build_report(run_id)
    if report is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return FastJSON(report, headers={
        "Content-Disposition": f'attachment; filename="benchmark_{run_id}.json"'})


@blueprint.get("/api/benchmarks/runs/{run_id}/report.pdf")
@login_required
async def report_pdf(request: Request, run_id: str):
    """Server-side PDF report (requires reportlab). 501 if the dep is missing."""
    from fastapi import Response
    from common.monitoring.benchmarking import reporter
    pdf, error = reporter.generate_pdf_bytes(run_id)
    if pdf is None:
        status = 404 if error == "Run not found" else 501
        return JSONResponse({"error": error}, status_code=status)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="benchmark_{run_id}.pdf"'})
