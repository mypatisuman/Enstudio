"""How much of what the digitiser got wrong lands in its review queue.

python score_review.py pid13      (runs/<name>_analysis.json, written by live_any.py)

    wrong tags    read but not on the drawing: captured when a tag item names them
    wrong links   traced but not drawn: captured when a link item names the pair,
                  or a tag item names one of its ends
    missed links  drawn but not traced: pointed at when a "possibly missing" item
                  names one of their ends (the engineer adds the link there)
    missed tags   never read: no item can name them (reported, not scored)

The target is every error inside the queue, with as short a queue as possible.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SP = Path(__file__).resolve().parent
name = sys.argv[1]
A = json.loads((SP / "runs" / f"{name}_analysis.json").read_text())
queue = A.get("review") or []
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def lines_of(script):
    return subprocess.run([sys.executable, str(SP / script), name], capture_output=True, text=True, env=env).stdout


def listed(text, label):
    m = re.search(rf"^\s*{label}\s*:\s*(\[.*\])\s*$", text, re.M)
    return ast.literal_eval(m.group(1)) if m else []


tags_out = lines_of("score_manual.py")
conn_out = lines_of("score_live.py")
flags = {}
m = re.search(r"^\s*flags:\s*(\{.*\})\s*$", conn_out, re.M)
if m:
    flags = ast.literal_eval(m.group(1))                 # analysis tag -> truth flag name
to_truth = lambda t: flags.get(t, t)

tag_items = {to_truth(t) for i in queue if i["kind"] == "tag" for t in i["tags"][:1]}
link_items = {tuple(sorted(map(to_truth, i["tags"][:2]))) for i in queue if i["kind"] == "link"}
missing_items = {to_truth(t) for i in queue if i["kind"] == "missing" for t in i["tags"]}

extra_tags, missed_tags = listed(tags_out, "extra"), listed(tags_out, "missed")
wrong_links, missed_links = listed(conn_out, "wrong"), listed(conn_out, "missed")
cap_tags = [t for t in extra_tags if t in tag_items]
cap_wrong = [p for p in wrong_links if tuple(sorted(p)) in link_items or p[0] in tag_items or p[1] in tag_items]
cap_missed = [p for p in missed_links if p[0] in missing_items or p[1] in missing_items]


def pct(a, b):
    return f"{len(a)}/{len(b)}" + (f" = {len(a) / len(b) * 100:.0f}%" if b else "")


errors = len(extra_tags) + len(wrong_links) + len(missed_links)
caught = len(cap_tags) + len(cap_wrong) + len(cap_missed)
print(f"{name}: review queue {len(queue)} items | errors in the queue {caught}/{errors}"
      + (f" = {caught / errors * 100:.0f}%" if errors else " (no errors)"))
print(f"  wrong tags caught   {pct(cap_tags, extra_tags)}  not caught: {sorted(set(extra_tags) - set(cap_tags))}")
print(f"  wrong links caught  {pct(cap_wrong, wrong_links)}  not caught: {[p for p in wrong_links if p not in cap_wrong]}")
print(f"  missed links pointed at {pct(cap_missed, missed_links)}  not: {[p for p in missed_links if p not in cap_missed]}")
print(f"  missed tags (no item can name them): {missed_tags}")
by_code = {}
for i in queue:
    by_code[i["code"]] = by_code.get(i["code"], 0) + 1
print(f"  queue by reason: {by_code}")
