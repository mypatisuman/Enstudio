"""Aggregated application health — one report over both workflows."""
from __future__ import annotations


def check_app_health() -> dict:
    reports = []
    for check in ("agents.extraction.health.check_extraction_health",
                  "agents.describe.health.check_describe_health"):
        mod_name, fn_name = check.rsplit(".", 1)
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            reports.append(getattr(mod, fn_name)())
        except Exception as e:
            reports.append({"workflow": mod_name.split(".")[1],
                            "status": "error", "checks":
                            {"probe": f"FAIL: {str(e)[:150]}"}})
    overall = "healthy" if all(r["status"] == "healthy" for r in reports) \
        else "degraded"
    return {"status": overall, "workflows": reports}
