"""Live read of any fixture drawing: python live_any.py pid13 [label] -> runs/<label or pid13>_analysis.json

A label (e.g. pid13R5) keeps earlier runs; the scorers find the truth by the label's prefix."""
import json, os, sys, time
from pathlib import Path
SP = Path(__file__).resolve().parent
BACKEND = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(BACKEND)); os.chdir(BACKEND)
from dotenv import load_dotenv; load_dotenv(BACKEND / ".env")
OUT = SP / "runs"
import domain.solution.services.brownfield_vision_service as V


def drawing_path(n):
    real = BACKEND / f"PID-Images/PID-Images/{n}.png"
    return real if real.exists() else Path(__file__).resolve().parent / "synth" / "out" / f"{n}.png"

V._CACHE_DIR = OUT / "cache_any"
name = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else name
t = time.time()
a = V.analyze_uploaded_pid(f"{label}_probe", image_path=str(drawing_path(name)),
                           use_cache=False, use_ground_truth=False)
(OUT / f"{label}_analysis.json").write_text(json.dumps(a, indent=1))
if a.get("error"):
    print(label, a["error"]); sys.exit(1)
st = a["stats"]
print(f"{label}: {time.time()-t:.0f}s calls={st['calls']} failed={len(st['failed_tiles'])} "
      f"equipment={len(a['equipment'])} instruments={len(a['instruments'])} headers={len(a['tie_ins'])} "
      f"lines={len(a['lines'])} loops={len(a['loops'])}")
