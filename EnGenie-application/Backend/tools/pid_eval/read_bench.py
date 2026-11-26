"""Reading-pass benchmark of one model on one drawing (live calls, no verification):
python read_bench.py <pid13|pid15> <model> <out-suffix>  ->  runs/<pid><suffix>_analysis.json
Prints tag recall/precision (hand truth) and the median position error against the
cached OCR boxes of the same drawing (an offline answer key; nothing runs OCR)."""
import hashlib, json, math, os, re, statistics, sys, time
from pathlib import Path
SP = Path(__file__).resolve().parent
BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(SP))
os.chdir(BACKEND)
from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")
import domain.solution.services.brownfield_vision_service as V


def drawing_path(n):
    real = BACKEND / f"PID-Images/PID-Images/{n}.png"
    return real if real.exists() else Path(__file__).resolve().parent / "synth" / "out" / f"{n}.png"

from truth_manual import TRUTH

pid, model, suffix = sys.argv[1], sys.argv[2], sys.argv[3]
V.READ_MODEL = "" if model == "default" else model
path = drawing_path(pid)
img, _w = V._load_image(path.read_bytes(), "image/png")
W, H = img.size
tiles = [{**t, "index": gi * V.GRID_STRIDE + t["index"], "grid": gi}
         for gi, target in enumerate(V.TILE_GRIDS) for t in V.plan_tiles(W, H, target)]
stats = {"calls": 0, "failed_tiles": [], "dropped_not_a_tag": [], "dropped_unverified": [], "verify_errors": 0,
         "dropped_edges_unknown_tag": 0}
t0 = time.time()
readings = V._read_tiles(img, tiles, stats)
objects = V._merge_readings(readings, tiles, W, stats)
objects = V._dedupe_names(V._drop_title_callouts(objects, H), W)
objects = V.drop_references_and_line_fragments(objects, stats.get("_texts", []), W, stats)
objects = V.drop_port_labels(objects, W, stats)
secs = time.time() - t0

pos = lambda o: (round(o["x"] / W * 1000, 1), round(o["y"] / W * 1000, 1))
A = {"equipment": [], "instruments": [], "tie_ins": [], "lines": [], "loops": [], "stats": {"calls": stats["calls"]}}
for o in objects:
    x, y = pos(o)
    if o["node_kind"] == "tie_in":
        A["tie_ins"].append({"tag": o["tag"], "x": x, "y": y})
    elif o["node_kind"] in V.EQUIPMENT_KINDS:
        A["equipment"].append({"tag": o["tag"], "kind": o["node_kind"], "x": x, "y": y})
    else:
        A["instruments"].append({"tag": o["tag"], "kind": o["node_kind"], "x": x, "y": y})
(SP / "runs" / f"{pid}{suffix}_analysis.json").write_text(json.dumps(A))

# tags
from truth_manual import truth_key
T = TRUTH[truth_key(pid, TRUTH)]
truth = set(T["equipment"]) | set(T["instruments"])
got = {o["tag"] for o in objects if o["node_kind"] != "tie_in"}
got = {t if t in truth else re.sub(r"(\d)[A-Z]$", r"\1", t) for t in got} - set(T.get("optional", []))
tp = got & truth
# positions: distance to the cached OCR box spelling the tag (only where one exists)
digest = hashlib.sha256(path.read_bytes()).hexdigest()
key = (SP / "runs" / "answer_key" / f"ocr2_{digest}.json")
toks = json.loads(key.read_text()) if key.exists() else []      # optional position answer key
norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
by_text = {}
for t in toks:
    by_text.setdefault(norm(t["text"]), []).append((t["x"], t["y"]))
errs = []
for o in objects:
    cands = by_text.get(norm(o["tag"]))
    if cands:
        errs.append(min(math.dist((o["x"], o["y"]), c) for c in cands) / W * 1000)
print(f"{pid} {model}: {secs:.0f}s calls={stats['calls']} failed={len(stats['failed_tiles'])} | "
      f"tags recall {len(tp)}/{len(truth)}={len(tp)/len(truth)*100:.1f}% precision {len(tp)}/{len(got)}="
      f"{len(tp)/max(1,len(got))*100:.1f}% | position error median {statistics.median(errs) if errs else -1:.1f} "
      f"p90 {sorted(errs)[int(0.9*len(errs))] if errs else -1:.1f} (/1000 W, n={len(errs)})")
print("   missed:", sorted(truth - got))
print("   extra :", sorted(got - truth))
