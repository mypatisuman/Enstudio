"""Run extraction on labelled drawings and score it.

Usage:
    python benchmarks/run_benchmark.py --dry-run
    python benchmarks/run_benchmark.py --pipeline agentic --limit 1 --confirm-cost

Each ground-truth file in fixtures/ground_truth names its drawing image. For
every drawing the runner creates a throwaway hub, runs the chosen extraction
pipeline on the image, exports the result as a connectivity graph, scores it
against the truth file (benchmarks/scoring.py), and records wall-clock seconds,
tokens and cost from the pipeline's own "done" event.

THIS CALLS THE CONFIGURED VISION MODEL AND COSTS MONEY. A live run requires
--confirm-cost. The configured provider, model and API key come from the real
hub's settings (--settings-hub), copied into each throwaway hub.

Results go to benchmarks/results/<UTC timestamp>/: results.json with per-drawing
and aggregate metrics, and summary.md for a quick read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from benchmarks.scoring import aggregate, score  # noqa: E402


def _done_event(stdout_text: str) -> dict:
    done = {}
    for line in stdout_text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("stage") == "done":
                done = ev
    return done


def _prepare_hub(hub: Path, pid: str, settings_hub: Path | None) -> None:
    from adapters import db
    (hub / "projects" / pid).mkdir(parents=True, exist_ok=True)
    db.reset_for_path(hub / "studio.db")
    db.init_db()
    conn = db.get_db()
    conn.execute("INSERT OR IGNORE INTO projects (id, title) VALUES (?, ?)", (pid, pid))
    if settings_hub and (settings_hub / "studio.db").exists():
        src = sqlite3.connect(settings_hub / "studio.db")
        for key, value in src.execute("SELECT key, value FROM settings").fetchall():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        src.close()
    conn.commit()


def run_one(truth_path: Path, fixtures: Path, pipeline: str, out_dir: Path,
            settings_hub: Path | None) -> dict:
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    image = fixtures / truth["truth"]["image"]
    pid = truth_path.stem.replace(" ", "_")
    hub = out_dir / "hubs" / pid
    if hub.exists():
        shutil.rmtree(hub)
    _prepare_hub(hub, pid, settings_hub)

    # The pipelines write NDJSON straight to the process stdout, so run them the
    # way the desktop app does: as a child process.
    script = "run_agentic.py" if pipeline == "agentic" else "extract_cli.py"
    cmd = [sys.executable, str(BACKEND / script), str(hub), pid, str(image)]
    if pipeline == "agentic":
        cmd.append("--no-checkpoint")
    env = {**os.environ, "ENGINEERING_HUB": str(hub), "PYTHONIOENCODING": "utf-8"}
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    seconds = round(time.perf_counter() - started, 1)
    (out_dir / f"{pid}_log.ndjson").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    done = _done_event(proc.stdout)
    error = None if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[-400:]}"
    usage = done.get("usage") or done                      # classic nests usage; agentic is flat

    from adapters import db
    db.reset_for_path(hub / "studio.db")
    from adapters.connectivity_export import build_connectivity_graph
    from services.geometry_store import load
    prediction = build_connectivity_graph(pid)
    pages = load(pid).get("pages") or {}
    # Extraction may have worked on a resized raster; bring its pixels to the
    # truth image's scale before comparing boxes.
    scale = 1.0
    width = (next(iter(pages.values())).get("width") if pages else 0) or 0
    truth_width = truth["truth"].get("image_width")
    if width and truth_width:
        scale = float(truth_width) / float(width)
    (out_dir / f"{pid}_prediction.json").write_text(json.dumps(prediction, indent=2), encoding="utf-8")
    return {"drawing": pid, "image": str(image), "pipeline": pipeline, "seconds": seconds,
            "error": error, "status": done.get("status"),
            "tokens_in": int(usage.get("tokens_in", 0) or 0),
            "tokens_out": int(usage.get("tokens_out", 0) or 0),
            "cost_usd": float(usage.get("cost_usd", 0.0) or 0.0),
            "score": score(prediction, truth, prediction_scale=scale)}


def _summary(results: list[dict], agg: dict, meta: dict) -> str:
    lines = [f"# Extraction benchmark - {meta['started']}", "",
             f"Pipeline: `{meta['pipeline']}` | tile concurrency: {meta['tile_concurrency']} | "
             f"zoom refine: {meta['zoom_refine']} | flow annotations: {meta['flow_annotations']}", "",
             "| Drawing | Tag F1 | Tag recall | Conn. F1 | Conn. F1 (found tags) | Mean IoU | Seconds | Cost $ |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        s = r["score"]
        lines.append(f"| {r['drawing']} | {s['tags']['f1']} | {s['tags']['recall']} | "
                     f"{s['connections']['f1']} | {s['connections_among_found_tags']['f1']} | "
                     f"{s['boxes']['mean_iou']} | {r['seconds']} | {r['cost_usd']} |")
    lines += ["", f"**Aggregate** tag F1 {agg['tags']['f1']}, connection F1 {agg['connections']['f1']}, "
                  f"{agg['seconds_per_drawing']} s per drawing, ${agg['cost_usd']} total.", ""]
    errors = [r for r in results if r["error"]]
    if errors:
        lines += ["Errors:"] + [f"- {r['drawing']}: {r['error']}" for r in errors]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score extraction against labelled drawings")
    ap.add_argument("--fixtures", type=Path, default=REPO / "fixtures")
    ap.add_argument("--truth-dir", type=Path, default=None)
    ap.add_argument("--pipeline", choices=["agentic", "classic"], default="agentic")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--settings-hub", type=Path,
                    default=REPO / "EngineeringHub" / "EngineeringHub")
    ap.add_argument("--dry-run", action="store_true", help="validate truth files; no model calls")
    ap.add_argument("--confirm-cost", action="store_true",
                    help="required for a live run: this calls the vision model and costs money")
    args = ap.parse_args()

    truth_dir = args.truth_dir or (args.fixtures / "ground_truth")
    truths = sorted(truth_dir.glob("*.json"))
    if args.limit:
        truths = truths[:args.limit]
    if not truths:
        print(f"no ground-truth files in {truth_dir}")
        return 1

    problems = []
    for t in truths:
        doc = json.loads(t.read_text(encoding="utf-8"))
        image = args.fixtures / (doc.get("truth") or {}).get("image", "")
        if not image.is_file():
            problems.append(f"{t.name}: image not found ({image})")
        if not (doc.get("truth") or {}).get("verified_by"):
            print(f"note: {t.name} is not verified by hand yet")
    if problems:
        print("\n".join(problems))
        return 1
    if args.dry_run:
        print(f"{len(truths)} truth file(s) valid; a live run would call the model "
              f"{len(truths)} time(s) through the {args.pipeline} pipeline.")
        return 0
    if not args.confirm_cost:
        print("Refusing to run: a live benchmark calls the vision model and costs money. "
              "Re-run with --confirm-cost.")
        return 2

    from services.tile_runner import tile_concurrency
    started = dt.datetime.now(dt.timezone.utc)
    out_dir = BACKEND / "benchmarks" / "results" / started.strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [run_one(t, args.fixtures, args.pipeline, out_dir, args.settings_hub) for t in truths]
    agg = aggregate(results)
    meta = {"started": started.isoformat(), "pipeline": args.pipeline,
            "tile_concurrency": tile_concurrency(),
            "zoom_refine": os.getenv("STUDIO_ZOOM_REFINE", "on"),
            "flow_annotations": os.getenv("STUDIO_FLOW_ANNOTATIONS", "on")}
    (out_dir / "results.json").write_text(json.dumps({"meta": meta, "aggregate": agg,
                                                      "drawings": results}, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(_summary(results, agg, meta), encoding="utf-8")
    print(_summary(results, agg, meta))
    print(f"results: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
