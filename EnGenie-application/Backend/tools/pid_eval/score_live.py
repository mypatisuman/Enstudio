"""Score a live run's connections against conn_truth (tags: run score_manual.py).
python score_live.py pid13"""
import itertools, json, math, re, sys
from pathlib import Path
SP = Path(__file__).resolve().parent
sys.path.insert(0, str(SP))
from conn_truth import CONN
from truth_manual import truth_key

name = sys.argv[1]
T = CONN[truth_key(name, CONN)]
A = json.loads((SP / "runs" / f"{name}_analysis.json").read_text())
if A.get("error"):
    sys.exit(f"{name}: {A['error']}")

# flags by position
rename = {}
for t in A["tie_ins"]:
    best = min(T["flags"].items(), key=lambda kv: math.dist(kv[1], (t["x"], t["y"])))
    if math.dist(best[1], (t["x"], t["y"])) < 60:
        rename[t["tag"]] = best[0]
untagged = {n["tag"] for n in A["equipment"] + A["instruments"] if n.get("untagged")}

adj = {}
for l in A["lines"]:
    a, b = rename.get(l["from_tag"], l["from_tag"]), rename.get(l["to_tag"], l["to_tag"])
    if a != b:
        adj.setdefault(a, set()).add(b); adj.setdefault(b, set()).add(a)
for u in [n for n in adj if n in untagged]:           # through an unlabelled symbol
    nb = adj.pop(u)
    for x in nb:
        adj.get(x, set()).discard(u)
    for x, y in itertools.combinations(nb, 2):
        adj.setdefault(x, set()).add(y); adj.setdefault(y, set()).add(x)
E = {tuple(sorted((x, y))) for x in adj for y in adj[x] if x != y}
R, O = T["required"], T["optional"] - T["required"]
scored = E - O
tp = scored & R
p, r = len(tp) / max(1, len(scored)), len(tp) / len(R)
st = A["stats"]
print(f"{name} CONNECTIONS: F1 {2*p*r/max(1e-9,p+r)*100:.1f}%  precision {p*100:.1f}% ({len(tp)}/{len(scored)})  "
      f"recall {r*100:.1f}% ({len(tp)}/{len(R)})  [{len(E & O)} optional links not counted]")
print(f"  traced {st.get('traced_edges')} | model fill {st.get('model_fill_edges')} | "
      f"untagged symbols {st.get('traced_untagged')} | tracer {st.get('line_tracer_s')}s | "
      f"run {st.get('seconds')}s, {st.get('calls')} calls, failed tiles {len(st.get('failed_tiles') or [])}")
print("  flags:", rename)
print("  missed:", sorted(R - E))
print("  wrong :", sorted(scored - R))
