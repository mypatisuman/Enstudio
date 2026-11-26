"""Score a live analysis against the hand-read truth: tags, symbol types, inferred valves, line labels."""
import json, re, sys
from pathlib import Path
SP = Path(__file__).resolve().parent
sys.path.insert(0, str(SP))
from truth_manual import TRUTH, truth_key

FAM = {"vessel": {"vessel", "tank", "column"}, "compressor": {"compressor"}, "mixer": {"equipment"},
       "heat_exchanger": {"heat_exchanger"}, "filter": {"equipment", "filter"}, "other": None}


def expected_instr_kind(tag):
    p = tag.split("-")[0]
    if p in ("HV", "XV", "CK", "NV", "PSV", "PCV", "BPR", "FV", "FCV"): return "valve"
    if p.endswith("IC") or p in ("FTC", "FRC"): return "controller"
    if p.endswith("T") and len(p) >= 2: return "transmitter"
    if p.endswith("E") and len(p) == 2: return "element"
    if p.endswith("I") and len(p) == 2: return "indicator"
    return None


name = sys.argv[1]
import re as _re
T = TRUTH[truth_key(name, TRUTH)]
A = json.loads((SP / "runs" / f"{name}_analysis.json").read_text())
ours = {n["tag"]: n for n in A["equipment"] + A["instruments"]}
base = lambda t: t if t in truth_tags or t in set(T.get("optional", [])) else re.sub(r"(\d)[A-Z]$", r"\1", t)
truth_tags = set(T["equipment"]) | set(T["instruments"])
got = {}
for t, n in ours.items():
    got.setdefault(base(t), n)
opt = set(T.get("optional", []))
real = {t for t in got if not got[t].get("inferred") and t not in opt}
tp = real & truth_tags
print(f"{name}: TAGS recall {len(tp)}/{len(truth_tags)} = {len(tp)/len(truth_tags)*100:.1f}%  "
      f"precision {len(tp)}/{len(real)} = {len(tp)/max(1,len(real))*100:.1f}%")
print("  missed:", sorted(truth_tags - real))
print("  extra :", sorted(real - truth_tags))
wrong_type = []
for t in tp:
    k = got[t].get("kind")
    if t in T["equipment"]:
        if FAM[T["equipment"][t]] is not None and k not in FAM[T["equipment"][t]]:
            wrong_type.append((t, T["equipment"][t], k))
    else:
        e = expected_instr_kind(t)
        if e and k != e:
            wrong_type.append((t, e, k))
print(f"  SYMBOL TYPE: {len(tp)-len(wrong_type)}/{len(tp)} right; wrong: {wrong_type}")
inf = sorted(t for t, n in got.items() if n.get("inferred"))
print(f"  INFERRED: {inf} expected {T['inferred']}")
print(f"  NOT-SYMBOLS read as symbols: {[t for t in T['not_symbols'] if t in got]}")
lab = [l for l in A["lines"] if l.get("printed_line_no")]
print(f"  LINE LABELS attached: {len(lab)}: {[l['line_id'] + ' ' + str(l.get('size')) + ' ' + str(l.get('spec')) for l in lab]}")
norm = lambda x: x.replace("PL/", "").split("-")[:2]
printed = {tuple(norm(l["printed_line_no"])) for l in lab}
hit = [e for e in T["line_labels"] if tuple(norm(e)) in printed]
print(f"  LINE NUMBERS found {len(hit)}/{len(T['line_labels'])}; missing {[e for e in T['line_labels'] if e not in hit]}")
print(f"  OPTIONAL read: {sorted(t for t in got if t in opt)}")
print(f"  expected headers: {T.get('headers')}")
print(f"  headers: {sorted(t['tag'] for t in A['tie_ins'])}")
print(f"  connections: {len(A['lines'])}  types: {dict((k, sum(1 for l in A['lines'] if l['kind'] == k)) for k in ('process','signal','impulse','utility'))}")
print(f"  warnings: {A.get('warnings')}")
