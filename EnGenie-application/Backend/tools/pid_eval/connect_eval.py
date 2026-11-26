"""Connection-only evaluation: re-run connect_graph (the live model calls) on the
objects of a finished analysis and write <src>c<tag>_analysis.json for score_live.

usage: python connect_eval.py <analysis name, e.g. pid13L1> <out suffix> [ENV=VALUE ...]
"""
import json
import re
import os
import sys
import time
from pathlib import Path

SP = Path(__file__).parent
BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")
src, suffix = sys.argv[1], sys.argv[2]
for kv in sys.argv[3:]:
    k, v = kv.split("=", 1)
    os.environ[k] = v
import domain.solution.services.brownfield_vision_service as V


def drawing_path(n):
    real = BACKEND / f"PID-Images/PID-Images/{n}.png"
    return real if real.exists() else Path(__file__).resolve().parent / "synth" / "out" / f"{n}.png"

from PIL import Image

for kv in sys.argv[3:]:                     # module-level switches read at import
    k, v = kv.split("=", 1)
    if hasattr(V, k):
        cur = getattr(V, k)
        setattr(V, k, type(cur)(v) if not isinstance(cur, bool) else v.lower() in ("1", "true", "yes"))

A = json.loads((SP / "runs" / f"{src}_analysis.json").read_text())
name = re.match(r"(pid\d+|syn[cds]\d{3})", src).group(0)
img, _w = V._load_image((drawing_path(name)).read_bytes(), "image/png")
W, H = img.size
objects = []
for g in ("equipment", "instruments", "tie_ins"):
    for n in A[g]:
        objects.append({"tag": n["tag"], "node_kind": "tie_in" if g == "tie_ins" else n["kind"],
                        "kind_detail": n.get("kind_detail", ""), "x": n["x"] / 1000 * W, "y": n["y"] / 1000 * W,
                        "inferred": n.get("inferred"), "untagged": n.get("untagged"), "raw": n["tag"]})
class _Stats(dict):
    def __missing__(self, key):          # counters the pipeline pre-creates default to 0
        self[key] = 0
        return 0


stats = _Stats(calls=0, failed_tiles=[])
t = time.time()
_hp = V._header_pass
header_edges = []
def _capture(*a, **k):
    out_ = _hp(*a, **k)
    header_edges.extend(out_)
    return out_
V._header_pass = _capture
edges = V.connect_graph(img, objects, stats)
hdr = {tuple(sorted(e[:2])) for e in header_edges}
before = [e for e in edges if tuple(sorted(e[:2])) not in hdr]
for tag_, es in ((suffix, edges), (suffix + "nh", before)):
    B = dict(A)
    B["lines"] = [{"from_tag": a, "to_tag": b, "kind": k} for a, b, k in es]
    B["stats"] = {**A["stats"], "connect_eval": {"calls": stats["calls"], "failed": len(stats["failed_tiles"]),
                                                   "seconds": round(time.time() - t)}}
    (SP / "runs" / f"{name}{tag_}_analysis.json").write_text(json.dumps(B))
if "_neighbour_votes" in stats:          # every combination from the one run
    tile, votes = stats["_tile_edges"], stats["_neighbour_votes"]
    combos = {"T": tile, "TM": V.combine_neighbours(tile, votes, objects, "mutual"),
              "TA": V.combine_neighbours(tile, votes, objects, "any"),
              "M": V.combine_neighbours([], votes, objects, "mutual"),
              "A": V.combine_neighbours([], votes, objects, "any")}
    for tag_, es in combos.items():
        es = V._graph_rules(es, objects, _Stats(calls=0, failed_tiles=[]))
        B = dict(A)
        B["lines"] = [{"from_tag": a, "to_tag": b, "kind": k} for a, b, k in es]
        (SP / "runs" / f"{name}{suffix}{tag_}_analysis.json").write_text(json.dumps(B))
print(name + suffix, len(edges), "edges", len(hdr), "from headers", stats["calls"], "calls",
      len(stats["failed_tiles"]), "failed", f"{time.time() - t:.0f}s")
