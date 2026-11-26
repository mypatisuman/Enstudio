"""
LEVEL-BASED INDEXER (replaces the flat product_type flattening in
products_catalog_builder.main). The Products Catalog Excel already encodes the
5-tier hierarchy column-for-column:

  Classification (Device/Accessory)  -> L0 Category   (type: Equipment | Accessory)
  Device / Product                   -> L1 Product Type
  Specific Device / Product Type     -> L2 Sub-category
  Model Family                       -> L3 Model Family
  Model                              -> L4 Vendor Product   (+ Vendor)

  sheet "All Instruments"  -> type = Equipment
  sheet "All Accessories"  -> type = Accessory
"""
import os
import re
import logging
from collections import defaultdict

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("level_indexer")

DST_DB = "Restructured"

# ── SHEET CONFIGURATIONS ──────────────────────────────────────────────────────
# Maps target Excel sheet names -> (Fallback classification column name, ntype default value).
# This establishes whether rows represent Equipment (instruments) or Accessories.
SHEETS = {"All Instruments": ("Device Classification", "Equipment"),
          "All Accessories": ("Accessory Classification", "Accessory")}


# ── STRING CLEANING HELPERS ────────────────────────────────────────────────────
def clean(v):
    """
    Standardize Excel cell values: strip whitespaces and convert common empty-value
    placeholders (like NaN, none, empty strings) into standard empty strings.
    """
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none") else s


def norm(t):
    """
    Normalize strings to a standard, lowercase alphanumeric format.
    Strips away special symbols and extra spaces to prevent matching mismatch.
    """
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(t or "").lower()).split())


# ── PATH SELECTOR ─────────────────────────────────────────────────────────────
def get_excel_path():
    """
    Locates the target spreadsheet Products Catalog.xlsx inside the workspace 
    by checking local, indexing, and scripts directories.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [
        os.path.join(base_dir, "MongoDB_Instruments_and_Accessories.xlsx"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "MongoDB_Instruments_and_Accessories.xlsx"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "Products Catalog.xlsx"),
        os.path.join(base_dir, "Indexing", "Products Catalog.xlsx"),
        os.path.join(base_dir, "indexing", "Products Catalog.xlsx"),
        os.path.join(base_dir, "scripts", "all_products.xlsx"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]  # default fallback


# ── CATALOG SHEET PARSER ──────────────────────────────────────────────────────
def parse_catalog():
    """
    Reads the Excel sheets using pandas and builds the hierarchical dictionary 
    tree mirroring the L0 -> L1 -> L2 -> L3 -> L4 structure.
    
    Structure:
    { l0_name: {"type": ..., "l1": { l1_name: { "l2": { l2_name: { "l3": { family_name: ... } } } } } } }
    """
    tree = {}
    excel_path = get_excel_path()
    log.info("Using Excel catalog: %s", excel_path)
    
    xl = pd.ExcelFile(excel_path)
    sheet_names = xl.sheet_names
    
    for sheet, (cls_col, default_ntype) in SHEETS.items():
        if sheet not in sheet_names:
            log.warning("Expected sheet '%s' not found in %s", sheet, excel_path)
            continue
        df = pd.read_excel(excel_path, sheet_name=sheet)
        for _, r in df.iterrows():
            l0 = clean(r.get("L0 Category") or r.get("Classification") or r.get(cls_col))
            row_ntype = clean(r.get("Classification")) or clean(r.get("Type")) or default_ntype
            l1 = clean(r.get("L1 Product Type") or r.get("Product") or r.get("Device"))
            l2 = clean(r.get("L2 Subcategory") or r.get("Specific Product Type") or r.get("Specific Device Type")) or l1
            fam = clean(r.get("L3 Model Family") or r.get("Model Family"))
            model = clean(r.get("L4 Vendor Product") or r.get("Model"))
            vendor = clean(r.get("Vendor"))
            
            if not (l0 and l1):
                continue
                
            t = tree.setdefault(l0, {"type": row_ntype, "l1": {}})
            n1 = t["l1"].setdefault(l1, {"l2": {}})
            n2 = n1["l2"].setdefault(l2, {"l3": {}})
            if fam:
                n3 = n2["l3"].setdefault(fam, {"vendor": vendor, "models": {}})
                if model:
                    n3["models"][model] = None
    return tree


# ── DATABASE L0 KEY RESOLUTION ─────────────────────────────────────────────────
def existing_l0_map(db):
    """
    Queries MongoDB for existing L0 category mappings (norm(name) -> _id code).
    This helps reuse existing codes (e.g. C01, C02) for matching L0 groups.
    """
    out = {}
    for n in db["L0"].find({}, {"name": 1}):
        nm = n.get("name") or n.get("key")
        if nm:
            out[norm(nm)] = n["_id"]
    return out


# ── CODE ASSIGNMENT ENGINE ────────────────────────────────────────────────────
def assign_codes(tree, db=None, l0map=None):
    """
    Iterates through the in-memory tree hierarchy and attaches unique,
    sequenced ID codes to L1, L2, L3, and L4 nodes. It checks the database 
    and reuses existing keys for matches to maintain historical code alignment.
    """
    if isinstance(db, dict):
        l0map = db
        db = None
        
    if l0map is None:
        l0map = existing_l0_map(db) if db is not None else {}
        
    l1_map = {}
    l2_map = {}
    l3_map = {}
    l4_map = {}
    
    if db is not None:
        for n in db["L1"].find({}, {"name": 1, "parent_id": 1}):
            nm, p = n.get("name"), n.get("parent_id")
            if nm and p:
                l1_map[(p, norm(nm))] = n["_id"]
                
        for n in db["L2"].find({}, {"name": 1, "parent_id": 1}):
            nm, p = n.get("name"), n.get("parent_id")
            if nm and p:
                l2_map[(p, norm(nm))] = n["_id"]
                
        for n in db["L3"].find({}, {"name": 1, "parent_id": 1}):
            nm, p = n.get("name"), n.get("parent_id")
            if nm and p:
                l3_map[(p, norm(nm))] = n["_id"]
                
        for n in db["L4"].find({}, {"name": 1, "parent_id": 1}):
            nm, p = n.get("name"), n.get("parent_id")
            if nm and p:
                l4_map[(p, norm(nm))] = n["_id"]

    used = set(l0map.values()) | set(l1_map.values()) | set(l2_map.values()) | set(l3_map.values()) | set(l4_map.values())
    
    c_indices = []
    for c in used:
        m = re.match(r"C(\d+)$", c)
        if m:
            c_indices.append(int(m.group(1)))
    nextc = max(c_indices + [0]) + 1
    
    coded = {}
    for l0name, t in sorted(tree.items()):
        c0 = l0map.get(norm(l0name))
        if not c0:
            while True:
                c0 = f"C{nextc:02d}"
                nextc += 1
                if c0 not in used:
                    break
            used.add(c0)
            
        node = {"_id": c0, "name": l0name, "type": t["type"], "l1": {}}
        
        next_p = 1
        for l1name, n1 in sorted(t["l1"].items()):
            c1 = l1_map.get((c0, norm(l1name)))
            if not c1:
                while True:
                    c1 = f"{c0}-P{next_p:02d}"
                    next_p += 1
                    if c1 not in used:
                        break
                used.add(c1)
            node["l1"][l1name] = {"_id": c1, "name": l1name, "l2": {}}
            
            next_s = 1
            for l2name, n2 in sorted(n1["l2"].items()):
                c2 = l2_map.get((c1, norm(l2name)))
                if not c2:
                    while True:
                        c2 = f"{c1}-S{next_s:02d}"
                        next_s += 1
                        if c2 not in used:
                            break
                    used.add(c2)
                
                l3 = {}
                next_f = 1
                for fam, v in sorted(n2["l3"].items()):
                    c3 = l3_map.get((c2, norm(fam)))
                    if not c3:
                        while True:
                            c3 = f"{c2}-F{next_f:03d}"
                            next_f += 1
                            if c3 not in used:
                                break
                        used.add(c3)
                    
                    models_dict = {}
                    next_v = 1
                    for model_name in sorted(v["models"].keys()):
                        m_code = l4_map.get((c3, norm(model_name)))
                        if not m_code:
                            while True:
                                m_code = f"{c3}-V{next_v:03d}"
                                next_v += 1
                                if m_code not in used:
                                    break
                            used.add(m_code)
                        models_dict[model_name] = m_code
                        
                    l3[fam] = {
                        "_id": c3,
                        "name": fam,
                        "vendor": v.get("vendor"),
                        "models": models_dict
                    }
                    
                node["l1"][l1name]["l2"][l2name] = {"_id": c2, "name": l2name, "l3": l3}
        coded[l0name] = node
    return coded

