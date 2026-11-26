"""
Vendor utilities for Indexing pipeline.

  get_vendor_and_model_families(db, output_dir)
      Aggregate distinct vendor↔model_family pairs from db.vendors,
      apply name canonicalisation, and export JSON / CSV / TXT.

  normalize_vendor_name(name) -> str
      Canonicalise known vendor names (ABB, Emerson, …).
      NOTE: verified low-value for current L4 data (names already canonical).
      Only call when ingesting external data with messy vendor names.
"""

import csv
import json
import logging
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── name canonicalisation ─────────────────────────────────────────────────────

_VENDOR_MAP: Dict[str, str] = {
    "ABB": "ABB",
    "AMETEK": "AMETEK",
    "ANTON PAAR": "Anton Paar",
    "BAUMER": "Baumer",
    "METTLER TOLEDO": "METTLER TOLEDO",
    "METTLER-TOLEDO": "METTLER TOLEDO",
    "GE ": "GE",
    "KYOWA": "Kyowa",
    "IMI": "IMI",
    "LEM": "LEM",
    "EMERSON": "Emerson",
    "ENDRESS+HAUSER": "Endress+Hauser",
    "ENDRESS + HAUSER": "Endress+Hauser",
    "YOKOGAWA": "Yokogawa",
    "SIEMENS": "Siemens",
    "HONEYWELL": "Honeywell",
    "SCHNEIDER": "Schneider Electric",
    "VEGA": "VEGA",
    "KROHNE": "KROHNE",
    "BÜRKERT": "Bürkert",
    "BURKERT": "Bürkert",
    "HACH": "Hach",
    "OMEGA": "OMEGA",
    "FLUKE": "Fluke",
}


def normalize_vendor_name(name: Optional[str]) -> str:
    """
    Return canonical vendor name for known vendors; otherwise return name unchanged.
    NOTE: verified low-value for current L4 catalog data — call only when ingesting
    raw external data that may have messy vendor names.
    """
    if not name or str(name) in ("None", ""):
        return "Unknown"
    n = str(name).strip()
    upper = n.upper()
    for prefix, canonical in _VENDOR_MAP.items():
        if upper.startswith(prefix):
            return canonical
    return n


# ── aggregation ───────────────────────────────────────────────────────────────

def get_vendor_and_model_families(
    db,
    output_dir: Optional[str] = None,
    apply_normalization: bool = False,
) -> List[Dict[str, str]]:
    """
    Query db.vendors for distinct vendor↔model_family pairs via aggregation pipeline.
    Falls back to a document scan if the pipeline returns nothing.

    db: pymongo Database (product-recommender).
    output_dir: directory to write JSON / CSV / TXT files (None = no file output).
    apply_normalization: if True, canonicalise vendor names via normalize_vendor_name.

    Returns sorted list of {"vendor_name": ..., "model_family": ...} dicts.
    """
    vendors_col = db["vendors"]

    pipeline = [
        {"$project": {
            "vendor_name": {"$ifNull": ["$vendor_name",
                            {"$ifNull": ["$vendor", "$metadata.vendor_name"]}]},
            "model_family": {"$ifNull": ["$model_family",
                             {"$ifNull": ["$model_series",
                              {"$ifNull": ["$metadata.model_family",
                                           "$metadata.model_series"]}]}]},
        }},
        {"$match": {"$or": [{"vendor_name": {"$ne": None}},
                             {"model_family": {"$ne": None}}]}},
        {"$group": {"_id": {"vendor_name": "$vendor_name",
                             "model_family": "$model_family"}}},
        {"$project": {"_id": 0, "vendor_name": "$_id.vendor_name",
                      "model_family": "$_id.model_family"}},
        {"$sort": {"vendor_name": 1, "model_family": 1}},
    ]

    results = list(vendors_col.aggregate(pipeline))
    log.info("[VENDOR] Aggregation returned %d pairs", len(results))

    if not results:
        # Fallback: scan documents
        log.warning("[VENDOR] No aggregation results — falling back to document scan")
        seen: set = set()
        for doc in vendors_col.find(
                {}, {"vendor": 1, "vendor_name": 1, "metadata": 1,
                     "model_family": 1, "model_series": 1}):
            v = (doc.get("vendor_name") or doc.get("vendor")
                 or (doc.get("metadata") or {}).get("vendor_name"))
            m = (doc.get("model_family") or doc.get("model_series")
                 or (doc.get("metadata") or {}).get("model_family"))
            if v or m:
                seen.add((str(v) if v else "Unknown", str(m) if m else "Unknown"))
        results = [{"vendor_name": v, "model_family": m} for v, m in seen]
        results.sort(key=lambda x: (x["vendor_name"], x["model_family"]))

    if apply_normalization:
        seen_norm: set = set()
        normed: List[Dict[str, str]] = []
        for r in results:
            vn = normalize_vendor_name(r.get("vendor_name"))
            mf = r.get("model_family", "Unknown")
            if (vn, mf) not in seen_norm:
                seen_norm.add((vn, mf))
                normed.append({"vendor_name": vn, "model_family": mf})
        normed.sort(key=lambda x: (x["vendor_name"], x["model_family"]))
        results = normed
        log.info("[VENDOR] After normalization: %d unique pairs", len(results))

    if output_dir:
        _write_outputs(results, output_dir)

    # Return as {vendor: [model_families]} summary
    summary: Dict[str, List[str]] = defaultdict(list)
    for r in results:
        v = r.get("vendor_name", "Unknown")
        m = r.get("model_family", "")
        if m and m != "Unknown":
            summary[v].append(m)
    for v in summary:
        summary[v].sort()
    log.info("[VENDOR] %d unique vendors", len(summary))
    return results


def _write_outputs(results: List[Dict[str, str]], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, "vendor_model_families.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    log.info("[VENDOR] Saved JSON: %s", json_path)

    # CSV
    csv_path = os.path.join(output_dir, "vendor_model_families.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vendor Name", "Model Family"])
        for r in results:
            writer.writerow([r.get("vendor_name", ""), r.get("model_family", "")])
    log.info("[VENDOR] Saved CSV: %s", csv_path)

    # TXT (hierarchical)
    summary: Dict[str, List[str]] = defaultdict(list)
    for r in results:
        v = r.get("vendor_name", "Unknown")
        m = r.get("model_family", "")
        if m and m not in ("Unknown", "None"):
            summary[v].append(m)

    txt_path = os.path.join(output_dir, "vendor_model_families_hierarchical.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("Vendor Model Families\n===================\n\n")
        for v in sorted(summary):
            models = sorted(summary[v])
            f.write(f"Vendor: {v} ({len(models)} model families)\n")
            f.write("-" * 40 + "\n")
            for m in models:
                f.write(f"  - {m}\n")
            f.write("\n")
    log.info("[VENDOR] Saved TXT: %s", txt_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from infra.storage import mongo_src

    ap = argparse.ArgumentParser(description="Export vendor↔model family pairs")
    ap.add_argument("--output-dir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--normalize", action="store_true",
                    help="Apply vendor name canonicalisation")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    db = mongo_src()
    get_vendor_and_model_families(db, output_dir=args.output_dir,
                                  apply_normalization=args.normalize)
