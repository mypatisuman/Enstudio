"""Digitise synthetic drawings live and score them in one go.

python tools/pid_eval/bench_synth.py [names...]       (default: every drawing in synth/out)
    BROWNFIELD_* settings in the environment choose the models, e.g.
    BROWNFIELD_READ_MODEL=anthropic/claude-sonnet-5-5 python tools/pid_eval/bench_synth.py syns001

Spends provider credit: one full digitisation per drawing (~100-130 vision calls).
Prints per drawing tag recall / precision, connection F1 and how many errors the
review queue holds, then the averages.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

D = Path(__file__).resolve().parent
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def run(script: str, name: str) -> str:
    return subprocess.run([PY, str(D / script), name], capture_output=True, text=True, env=ENV).stdout


def number(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


names = sys.argv[1:] or sorted(p.stem for p in (D / "synth" / "out").glob("*.png"))
rows = []
for name in names:
    out = run("live_any.py", name)
    if "ERROR" in out or not (D / "runs" / f"{name}_analysis.json").exists():
        print(f"{name}: failed: {out.strip()[-200:]}")
        continue
    tags, conn, review = run("score_manual.py", name), run("score_live.py", name), run("score_review.py", name)
    row = {"name": name,
           "recall": number(r"TAGS recall \d+/\d+ = ([\d.]+)%", tags),
           "precision": number(r"precision \d+/\d+ = ([\d.]+)%", tags),
           "conn_f1": number(r"CONNECTIONS: F1 ([\d.]+)%", conn),
           "in_queue": number(r"errors in the queue \d+/\d+ = (\d+)%", review),
           "queue": number(r"review queue (\d+) items", review)}
    rows.append(row)
    print(f"{name:10} tags {row['recall']}% / {row['precision']}%  links F1 {row['conn_f1']}%  "
          f"errors in review queue {row['in_queue']}% ({row['queue']:.0f} items)" if row["queue"] is not None
          else f"{name:10} {row}")
if rows:
    def avg(k):
        vals = [r[k] for r in rows if r[k] is not None]
        return sum(vals) / len(vals) if vals else float("nan")
    print(f"\nAVERAGE of {len(rows)}: tags {avg('recall'):.1f}% / {avg('precision'):.1f}%  links F1 {avg('conn_f1'):.1f}%  "
          f"errors in review queue {avg('in_queue'):.0f}%  queue {avg('queue'):.0f} items")
