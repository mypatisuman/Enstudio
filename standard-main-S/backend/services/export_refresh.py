"""
services/export_refresh.py — regenerate a project's exports after an edit.

A brownfield turn that changes the graph leaves the connectivity JSON and YMPL
on disk describing the plant as it was. After any Describe turn that applied
write operations, this writes fresh copies to <hub>/projects/<pid>/exports/:

  <pid>_connectivity.json         schema 2.0.0
  <pid>_connectivity_2_1_0.json   schema 2.1.0, with systems and subsystems
  <pid>.ympl                      the enableSim YMPL

On by default. Disable with STUDIO_AUTO_EXPORT=off or the settings key
`auto_export_after_edit` = "off". Never raises: an export failure is reported in
the result, and the engineer's edit stands either way.
"""

from __future__ import annotations

import os


def enabled() -> bool:
    if (os.getenv("STUDIO_AUTO_EXPORT") or "").strip().lower() in ("off", "0", "false", "no"):
        return False
    try:
        from adapters.config import load_config
        value = (load_config().get("auto_export_after_edit") or "").strip().lower()
        return value not in ("off", "0", "false", "no")
    except Exception:
        return True


def refresh_after_edit(pid: str) -> dict:
    if not enabled():
        return {"skipped": "auto export disabled"}
    from adapters.connectivity_export import SCHEMA_2_0, SCHEMA_2_1, write_export
    from adapters.ympl_export import projects_dir, write_ympl
    exports = projects_dir() / pid / "exports"
    written, errors = {}, {}
    for name, fn in (
        ("connectivity", lambda: write_export(pid, exports, SCHEMA_2_0)),
        ("connectivity_2_1_0", lambda: write_export(pid, exports, SCHEMA_2_1)),
        ("ympl", lambda: write_ympl(pid, exports)),
    ):
        try:
            written[name] = str(fn())
        except Exception as exc:
            errors[name] = str(exc)[:200]
    out = {"written": written}
    if errors:
        out["errors"] = errors
    return out
