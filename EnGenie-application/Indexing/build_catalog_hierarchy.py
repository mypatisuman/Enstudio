"""
REBUILD-INTO-PARALLEL: build the full clean 5-tier hierarchy from Products Catalog.xlsx
into a NEW collection `catalog_hierarchy` (both clusters), coexisting with the existing
harvest-built `unified_product_hierarchy`. Fresh hierarchical codes (no merge -> no
collisions). Equipment->null schema+units, Accessory->enriched.

  --phase structure : write all L0-L4 nodes (codes, type, names, L3 device+spec_doc_url,
                      L4 model details). Fast, no LLM. Idempotent.
  --phase schema    : generate 3-tier parameters (LLM) for every L0/L1/L2 that lacks it.
                      Resumable (skips nodes already done).

Connections: cluster A = Backend/.env MONGODB_URI (engenie); cluster B = global cluster;
documents/vendors read from cluster A product-recommender; GOOGLE keys from Indexing/.env.

Run: cd Indexing && uv run --no-project --with pandas --with openpyxl --with pymongo \
  --with python-dotenv --with dnspython [--with langchain-google-genai] python \
  build_catalog_hierarchy.py --phase structure --apply
"""
import argparse
import os
import re
import sys
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from level_based_indexer import parse_catalog, assign_codes, norm, clean  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
# NOTE: the level_based_indexer import above already ran load_dotenv(Indexing/.env) which set
# MONGODB_URI=cluster B; force Backend's MONGODB_URI (cluster A engenie) with override=True.
load_dotenv(os.path.join(_HERE, ".env"))                                  # GOOGLE keys
load_dotenv(os.path.join(os.path.dirname(_HERE), "Backend", ".env"), override=True)   # cluster A MONGODB_URI
CLUSTER_A = os.getenv("MONGODB_URI")
CATALOG = "catalog_hierarchy"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("catalog")
STOP = {"the", "and", "of", "for", "a", "to", "with", "series", "system", "type", ""}
UNIT_EXCLUDE = ("behavior", "mode", "status", "principle", "protocol", "certification", "approval",
                "compliance", "material", "color", "led", "description", "series", "class", "category",
                "option", "version", "fault", "function", "feature", "application", "media", "element",
                "method", "step", "parameter", "marking", "design", "housing", "mounting", "connection",
                "connector", "thread", "ingress", "protection", "enclosure", "signal", "_no", "_id",
                "date", "required", "vibration", "shock", "type", "name", "model", "number", "capability",
                "compensation", "traceability", "percentage", "accuracy", "ratio", "rating")
UNIT_RULES = [("temperature", "°C"), ("frequency", "Hz"), ("voltage", "V"), ("pressure", "bar"),
              ("dp_range", "bar"), ("dp_span", "bar"), ("humidity", "%"), ("resistance", "Ω"),
              ("current", "A"), ("flow", "l/min"), ("weight", "kg"), ("diameter", "mm"),
              ("length", "mm"), ("response_time", "ms"), ("power_consumption", "W")]


def ck(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def toks(t):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", str(t or "").lower()).split() if w not in STOP and len(w) > 1}


def infer_unit(f):
    if any(x in f for x in UNIT_EXCLUDE):
        return ""
    for kw, u in UNIT_RULES:
        if kw in f:
            return u
    return ""


def conns():
    a = MongoClient(CLUSTER_A, serverSelectionTimeoutMS=60000)
    return a["Restructured"], a["Restructured"]


def _w(A, doc):
    A[CATALOG].update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)


def spec_doc(docs_by_vendor, vendor, fam):
    ven = norm(vendor)
    ft = toks(fam)
    best, bs = None, 0
    for d in docs_by_vendor.get(ven, []):
        s = len(ft & (toks(d.get("model_family")) | toks(d.get("pdf_title")) | toks(d.get("filename"))))
        if s > bs:
            bs, best = s, d
    return (str(best["_id"]), best.get("blob_url")) if best and bs >= 1 else (None, None)


def build_structure():
    src, A = conns()
    dbv = defaultdict(list)
    for d in src["documents"].find({}, {"vendor_name": 1, "model_family": 1, "pdf_title": 1, "filename": 1, "blob_url": 1}):
        dbv[norm(d.get("vendor_name"))].append(d)
    coded = assign_codes(parse_catalog(), {})       # fresh codes, no merge
    c = Counter()
    
    docs_to_write = []
    for level_0 in coded.values():
        docs_to_write.append({"_id": level_0["_id"], "level": "L0", "name": level_0["name"], "type": level_0["type"], "parent_id": None})
        c["L0"] += 1
        for n1 in level_0["l1"].values():
            docs_to_write.append({"_id": n1["_id"], "level": "L1", "name": n1["name"], "type": level_0["type"], "parent_id": level_0["_id"]})
            c["L1"] += 1
            for j, (l2name, n2) in enumerate(sorted(n1["l2"].items()), 1):
                docs_to_write.append({"_id": n2["_id"], "level": "L2", "name": n2["name"], "type": level_0["type"], "parent_id": n1["_id"]})
                c["L2"] += 1
                for fam, n3 in n2["l3"].items():
                    did, url = spec_doc(dbv, n3.get("vendor"), fam)
                    docs_to_write.append({"_id": n3["_id"], "level": "L3", "name": fam, "parent_id": n2["_id"],
                              "manufacturer": n3.get("vendor"), "spec_doc_url": url,
                              "device": {"oem": n3.get("vendor"), "model_series": fam, "model_number": None,
                                         "specs_Doc_Id": did, "spec_doc_url": url}})
                    c["L3"] += 1
                    for model, m_code in sorted(n3["models"].items()):
                        docs_to_write.append({"_id": m_code, "level": "L4", "name": model,
                                  "parent_id": n3["_id"], "vendor": n3.get("vendor")})
                        c["L4"] += 1
                        
    from pymongo import UpdateOne
    BATCH_SIZE = 200
    log.info("Bulk writing %d docs to Restructured database...", len(docs_to_write))
    ops = []
    for doc in docs_to_write:
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
        if len(ops) >= BATCH_SIZE:
            A[CATALOG].bulk_write(ops, ordered=False)
            ops = []
    if ops:
        A[CATALOG].bulk_write(ops, ordered=False)
            
    withdoc = A[CATALOG].count_documents({"level": "L3", "spec_doc_url": {"$nin": [None, ""]}})
    log.info("[structure] wrote %s to %s | L3 with spec_doc_url=%d", dict(c), CATALOG, withdoc)


def _llm():
    _HERE = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.join(os.path.dirname(_HERE), "Backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from common.ai.llm.manager import get_flash_llm
    return get_flash_llm(temperature=0.2)


# ── specification category classifier ────────────────────────────────────────
# Maps snake_case field-name keywords → one of the 8 SchemaSpec categories.
_CAT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("overpressure", "burst", "proof_pressure", "isolation_voltage", "fuse",
      "cat_rating", "max_allowable", "safety", "explosion", "intrinsic",
      "atex", "iecex", "nec_class", "fm_approv", "hazardous"), "safety"),
    (("power_supply", "output_signal", "current", "voltage", "loop_resistance",
      "electrical_connection", "cable_entry", "terminal", "grounding",
      "power_consumption", "supply_voltage"), "electrical"),
    (("process_connection", "diaphragm", "gasket", "flange", "pipe_size", "weight", "dimension",
      "mounting", "enclosure", "installation", "insertion_depth",
      "face_to_face", "thread"), "mechanical"),
    (("measurement_range", "dp_range", "dp_span", "flow_range", "flow_rate",
      "level_range", "turndown", "rangeability", "static_pressure",
      "process_pressure", "process_temperature", "measurement_principle",
      "probe_length", "dead_band", "blanking", "valve_size", "cv_value",
      "stroke", "shutoff"), "process"),
    (("operating_temperature", "ambient_temperature", "storage_temperature",
      "ingress_protection", "humidity", "vibration", "shock", "corrosion",
      "weather", "altitude", "ip_rating"), "environmental"),
    (("accuracy", "repeatability", "response_time", "linearity", "hysteresis",
      "resolution", "sensitivity", "drift", "stability", "zero_offset",
      "reference_accuracy", "total_error", "long_term", "turndown_ratio"), "performance"),
    (("certification", "approval", "sil_rating", "sil", "ce_marking",
      "ul_listing", "csa_approval", "marine", "standard", "rohs",
      "directive", "compliance", "iecex"), "certifications"),
    (("material", "body_material", "housing_material", "wetted_material",
      "antenna_material", "ball_material", "disc_material", "electrode_material",
      "liner_material", "probe_material", "seat_material", "stem_material"), "materials"),
    (("communication_protocol", "fieldbus", "profibus", "hart", "foundation",
      "protocol", "digital"), "communication"),
    (("model", "series", "manufacturer", "oem", "vendor", "version", "brand", "identification"), "product_info"),
    (("media", "application", "fluid", "liquid", "gas", "compatibility"), "applications"),
]
_DEFAULT_CAT = "product_info"

SPEC_CATEGORIES = ("safety", "electrical", "mechanical", "process", "environmental",
                   "performance", "certifications", "materials", "communication",
                   "product_info", "applications")

CAT_PREFIXES = {
    "safety": "SF",
    "electrical": "EL",
    "mechanical": "MC",
    "process": "PR",
    "environmental": "EN",
    "performance": "PF",
    "certifications": "CT",
    "materials": "MT",
    "communication": "CM",
    "product_info": "PI",
    "applications": "AP"
}


def _field_to_category(field: str) -> str:
    """Map a snake_case spec field name to one of the SchemaSpec categories."""
    f = field.lower()
    for keywords, cat in _CAT_RULES:
        if any(kw in f for kw in keywords):
            return cat
    return _DEFAULT_CAT


def _infer_type(field_name: str, category: str, units: str | None) -> str:
    """Infer parameter type: certification, measurement, or other."""
    f = field_name.lower()
    cat = category.lower()
    if cat in ("certifications",) or any(k in f for k in ("approval", "certification", "compliance", "directive", "standard", "sil", "hazard", "atex", "iecex", "class", "rating")):
        return "certification"
    if units or any(k in f for k in ("range", "span", "accuracy", "repeatability", "linearity", "hysteresis", "resolution", "sensitivity", "drift", "stability", "error", "time", "pressure", "temperature", "voltage", "current", "frequency", "flow", "velocity", "displacement", "dimension", "size", "weight", "diameter", "supply")):
        return "measurement"
    return "other"


def _build_spec_block(node_id: str,
                      mandatory: list[str],
                      optional: list[str],
                      advanced: list[str]) -> dict:
    """
    Convert three tier lists (field name strings) into the nested SchemaSpec 11-spec_category
    structure:

      { id, safety: { parameters: [Parameter] }, electrical: { parameters: [Parameter] }, ... }

    Each Parameter = { id, name, value, level, units, type }
    """
    spec_categories: dict[str, dict] = {c: {"parameters": []} for c in SPEC_CATEGORIES}
    counters: dict[str, int] = {c: 0 for c in SPEC_CATEGORIES}

    for tier_fields, tier_level in (
        (mandatory, "Required"),
        (optional,  "Optional"),
        (advanced,  "Advanced"),
    ):
        for field in tier_fields:
            cat = _field_to_category(field)
            counters[cat] += 1
            prefix = CAT_PREFIXES[cat]
            name = field.replace("_", " ").title()
            units_val = infer_unit(field) or None
            spec_categories[cat]["parameters"].append({
                "id":    f"{prefix}-{counters[cat]}",
                "name":  name,
                "value": None,
                "level": tier_level,
                "units": units_val,
                "type":  _infer_type(name, cat, units_val)
            })

    return {"id": f"SPEC-{node_id}", **spec_categories}



# ── LLM schema generation (10-category output) ────────────────────────────────

def gen_schema(llm, name: str, ntype_or_manufacturer: str, l0: Optional[str] = None, doc_text: Optional[str] = None) -> tuple[list, list, list]:
    """
    Generate or extract technical specification field names (not values) for a product or category.
    
    - If doc_text is provided, it extracts fields grounded in the datasheet text (2 tiers).
    - If doc_text is NOT provided, it generates general template fields (3 tiers) based on LLM knowledge.
    
    Returns:
        tuple[list[str], list[str], list[str]]: (mandatory_fields, optional_fields, latest_fields)
    """
    from langchain_core.messages import HumanMessage
    
    if doc_text:
        # Grounded extraction from datasheet text (L3 nodes)
        prompt = (
            f"You are an industrial instrumentation specification expert.\n"
            f"Below is the text of a datasheet for the model family \"{name}\" by \"{ntype_or_manufacturer}\".\n"
            f"Extract ALL TECHNICAL SPECIFICATION FIELD NAMES that ACTUALLY APPEAR in this document "
            f"(NOT values, NOT invented fields) across two importance tiers:\n\n"
            f"- mandatory: core selection specs present in the doc that MUST be defined for this "
            f"product to be usable (include as many as are present — no artificial limits).\n"
            f"- optional: secondary specs present in the doc (include all that are present).\n\n"
            f"Rules:\n"
            f"  • Use concise snake_case keys (e.g. measurement_range, supply_voltage).\n"
            f"  • No field may appear in more than one tier.\n"
            f"  • Do NOT invent fields not mentioned in the text.\n"
            f"  • Return ONLY valid JSON with no commentary:\n"
            f"    {{\"mandatory\":[...],\"optional\":[...]}}\n\n"
            f"--- DATASHEET TEXT ---\n{doc_text}"
        )
    else:
        # Generative schema creation based on category template (L1/L2 nodes)
        prompt = (
            f"As an instrumentation expert, list all relevant spec field names (not values) "
            f"for the {ntype_or_manufacturer} \"{name}\" (category: \"{l0}\") in three tiers:\n"
            f"- mandatory: essential/required datasheet fields\n"
            f"- optional: secondary/common fields\n"
            f"- latest: advanced/cutting-edge fields\n\n"
            f"Rules:\n"
            f"1. Use concise snake_case keys with no duplicates across tiers.\n"
            f"2. Only include fields specific and relevant to {name}.\n"
            f"3. Return ONLY valid JSON: {{\"mandatory\":[],\"optional\":[],\"latest\":[]}}"
        )

    txt = llm.invoke([HumanMessage(content=prompt)]).content
    if isinstance(txt, list):
        txt = "".join(c.get("text", "") for c in txt if isinstance(c, dict))
    txt = re.sub(r"^```[a-z]*\n?|```$", "", str(txt).strip())
    
    # Safe regex JSON loading
    match = re.search(r"\{.*\}", txt, re.DOTALL)
    d = json.loads(match.group(0) if match else txt)
    
    mand = [ck(x) for x in d.get("mandatory", []) if ck(x)]
    opt  = [ck(x) for x in d.get("optional",  []) if ck(x) and ck(x) not in mand]
    
    if doc_text:
        return mand, opt, []
    else:
        lat = [ck(x) for x in d.get("latest", []) if ck(x) and ck(x) not in mand and ck(x) not in opt]
        return mand, opt, lat



def build_schema():
    """
    Generate SchemaSpec specifications for every
    L1/L2 node that lacks one, then derive L0 specs from the union of its
    L1 children.

    Writes `specifications` field (SchemaSpec shape) — NOT the old `parameters`.
    """
    src, A = conns()
    llm = _llm()
    todo = list(A[CATALOG].find(
        {"level": {"$in": ["L1", "L2"]}, "specifications": {"$exists": False}},
        {"name": 1, "type": 1, "parent_id": 1}))
    log.info("[schema] %d L1/L2 need specifications", len(todo))

    level0_names = {n["_id"]: n["name"] for n in A[CATALOG].find({"level": "L0"}, {"name": 1})}
    done = 0
    for n in todo:
        # resolve L0 category name for LLM context
        cur = n["parent_id"]
        while cur and cur not in level0_names:
            p = A[CATALOG].find_one({"_id": cur}, {"parent_id": 1})
            cur = p["parent_id"] if p else None
        cat = level0_names.get(cur, n["name"])
        try:
            mand, opt, adv = gen_schema(llm, n["name"], n["type"], cat)
        except Exception as e:
            log.warning("  schema fail %s %s: %s", n["_id"], n["name"], e)
            continue

        spec_block = _build_spec_block(n["_id"], mand, opt, adv)
        p_block = {
            "mandatoryRequirements": {f: None for f in mand},
            "optionalRequirements": {f: None for f in opt},
            "latestRequirements": {f: None for f in adv}
        }
        if n.get("type") == "Equipment":
            p_block["units"] = {f: u for f in (mand + opt + adv) if (u := infer_unit(f))}

        A[CATALOG].update_one({"_id": n["_id"]}, {"$set": {"parameters": p_block, "specifications": spec_block}})
        done += 1
        if done % 25 == 0:
            log.info("  ... %d/%d schemas done", done, len(todo))

    # ── derive L0 specifications from frequency union of its L1 children ──
    # Collect all Parameter names from children's specifications spec_categories,
    # pick those that appear in >=35% of children, build a merged spec block.
    for level_0 in A[CATALOG].find({"level": "L0"}, {"name": 1}):
        kids = list(A[CATALOG].find(
            {"parent_id": level_0["_id"], "level": "L1"},
            {"specifications": 1}))
        if not kids:
            continue
        nk = len(kids)
        # count how often each (category, field_name) appears across children
        freq: dict[str, Counter] = {c: Counter() for c in SPEC_CATEGORIES}
        for k in kids:
            spec = k.get("specifications") or {}
            for cat in SPEC_CATEGORIES:
                params = (spec.get(cat) or {}).get("parameters") or []
                for param in params:
                    if isinstance(param, dict) and param.get("name"):
                        freq[cat][param["name"]] += 1
        threshold = max(1, 0.35 * nk)
        # rebuild per-category lists keeping only frequent fields,
        # preserving the first child's level/units as the template
        child_specs = [k.get("specifications") or {} for k in kids]
        def _first_param(cat, name):
            for cs in child_specs:
                for p in (cs.get(cat) or {}).get("parameters") or []:
                    if isinstance(p, dict) and p.get("name") == name:
                        return p
            return None

        spec_categories: dict[str, dict] = {}
        for cat in SPEC_CATEGORIES:
            seq = 0
            spec_category = []
            for name, cnt in freq[cat].most_common():
                if cnt < threshold:
                    break
                seq += 1
                proto = _first_param(cat, name) or {}
                units_val = proto.get("units")
                spec_category.append({
                    "id":    f"{CAT_PREFIXES[cat]}-{seq}",
                    "name":  name,
                    "value": None,
                    "level": proto.get("level", "Optional"),
                    "units": units_val,
                    "type":  _infer_type(name, cat, units_val)
                })
            spec_categories[cat] = {"parameters": spec_category}

        l0_spec = {"id": f"SPEC-{level_0['_id']}", **spec_categories}
        A[CATALOG].update_one({"_id": level_0["_id"]}, {"$set": {"specifications": l0_spec}})

    log.info("[schema] done: %d L1/L2 specifications generated + L0 derived", done)


def _blob_container():
    """Container client for product-documents (where L3 spec_doc_url PDFs live)."""
    # Silence azure SDK's per-request HTTP logging (very verbose at INFO).
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.storage").setLevel(logging.WARNING)
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(
        os.getenv("AZURE_STORAGE_CONNECTION_STRING")).get_container_client("product-documents")


def _pdf_text(cc, spec_doc_url, max_chars=120000):
    """Download a spec_doc_url PDF from blob and extract its text (capped)."""
    import io
    import fitz  # PyMuPDF
    bn = spec_doc_url.split("/product-documents/")[-1]
    data = cc.download_blob(bn).readall()
    doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    text = "".join(p.get_text() for p in doc)[:max_chars]
    doc.close()
    return text


def build_l3_schema(dry_run=False):
    """
    Populate L3 `specifications` (SchemaSpec 11-spec_category shape) by extracting
    field names from each L3's spec_doc_url datasheet. Doc-grounded.
    Only processes L3 nodes that have a spec_doc_url and no specifications yet.
    """
    src, A = conns()
    todo = list(A[CATALOG].find(
        {"level": "L3", "spec_doc_url": {"$nin": [None, ""]},
         "specifications": {"$exists": False}},
        {"name": 1, "manufacturer": 1, "spec_doc_url": 1, "parent_id": 1}))
    log.info("[l3schema] %d L3 with spec_doc_url need specifications", len(todo))
    cc = _blob_container()
    llm = _llm() if not dry_run else None
    done = fail = 0
    for n in todo:
        try:
            text = _pdf_text(cc, n["spec_doc_url"])
            if len(text) < 200:
                log.warning("  thin/empty PDF %s '%s' (%d chars) — skip",
                            n["_id"], n["name"], len(text))
                fail += 1
                continue
            if dry_run:
                log.info("  [dry] %s '%s' [%s] doc=%d chars -> would extract specifications",
                         n["_id"], n["name"], n.get("manufacturer"), len(text))
                done += 1
                continue
            mand, opt, _ = gen_schema(llm, n["name"], n.get("manufacturer"), doc_text=text)
            if not (mand or opt):
                log.warning("  no fields extracted %s '%s'", n["_id"], n["name"])
                fail += 1
                continue

            # Temporary block to pass to process_single_product
            temp_p_block = {
                "mandatoryRequirements": {f: None for f in mand},
                "optionalRequirements": {f: None for f in opt},
                "latestRequirements": {}
            }

            # Run advanced spec generation for this model family
            adv = []
            try:
                from advanced_specs import process_single_product
                process_single_product(n["name"], temp_p_block, A)
                norm_name = n["name"].lower().replace(" ", "").replace("_", "")
                adv_doc = A["advanced_specifications"].find_one({"normalized_product_type": norm_name})
                if adv_doc:
                    adv = [ck(spec["name"]) for spec in adv_doc.get("unique_specifications", [])]
            except Exception as adv_e:
                log.warning("  advanced spec gen failed for %s: %s", n["name"], adv_e)

            spec_block = _build_spec_block(n["_id"], mand, opt, adv)
            spec_block["source"] = "datasheet_extraction"
            
            # Find parent L2 type to determine if Equipment or Accessory
            # We default to "Equipment" if parent L2 is not found or lacks "type"
            parent_l2 = A[CATALOG].find_one({"_id": n.get("parent_id")}, {"type": 1})
            ntype = parent_l2.get("type", "Equipment") if parent_l2 else "Equipment"
            
            p_block = {
                "mandatoryRequirements": {f: None for f in mand},
                "optionalRequirements": {f: None for f in opt},
                "latestRequirements": {f: None for f in adv}
            }
            if ntype == "Equipment":
                p_block["units"] = {f: u for f in (mand + opt + adv) if (u := infer_unit(f))}
                
            A[CATALOG].update_one({"_id": n["_id"]},
                                   {"$set": {"parameters": p_block, "specifications": spec_block}})
            done += 1
            if done % 10 == 0:
                log.info("  ... %d/%d L3 schemas done", done, len(todo))
        except Exception as e:
            log.warning("  l3 schema fail %s '%s': %s", n["_id"], n.get("name"), e)
            fail += 1
    log.info("[l3schema] %s: %d extracted, %d failed/empty (of %d)",
             "dry-run" if dry_run else "done", done, fail, len(todo))


def build_l4_values(dry_run: bool = False) -> None:
    """
    Phase l4values: download each L3 spec_doc_url PDF, extract spec VALUES with LLM,
    and write them onto the L3 node's parameters (and propagate to child L4 nodes).

    Only processes L3 nodes that have a spec_doc_url and parameters already set.
    Idempotent: skips nodes whose parameters already contain non-None values.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from harvesting.pdf_harvester import enrich_l3_with_pdf_values

    src, A = conns()
    cc = _blob_container()
    llm_inst = _llm()

    def _blob_dl(url: str) -> bytes:
        bn = url.split("/product-documents/")[-1]
        return cc.download_blob(bn).readall()

    todo = list(A[CATALOG].find(
        {"level": "L3",
         "spec_doc_url": {"$nin": [None, ""]},
         "parameters": {"$exists": True}},
        {"name": 1, "manufacturer": 1, "spec_doc_url": 1, "parameters": 1, "parent_id": 1, "specifications": 1}))
    log.info("[l4values] %d L3 nodes to enrich", len(todo))

    done = fail = skipped = 0
    for n in todo:
        # Enforce rule: only enrich Accessories; Equipments remain null valued specifications.parameters
        parent_l2 = A[CATALOG].find_one({"_id": n.get("parent_id")}, {"type": 1})
        ntype = parent_l2.get("type", "Equipment") if parent_l2 else "Equipment"
        if ntype != "Accessory":
            skipped += 1
            continue

        params = n.get("parameters") or {}
        # Skip if any tier already has non-None values
        already_filled = any(
            v is not None
            for tier in ("mandatoryRequirements", "optionalRequirements", "latestRequirements")
            for v in params.get(tier, {}).values())
        if already_filled:
            skipped += 1
            continue

        if dry_run:
            log.info("  [dry] would enrich %s '%s'", n["_id"], n["name"])
            done += 1
            continue

        values = enrich_l3_with_pdf_values(n["_id"], n["spec_doc_url"], params, _blob_dl)
        if not values:
            fail += 1
            continue

        setdoc = {}
        for tier in ("mandatoryRequirements", "optionalRequirements", "latestRequirements"):
            for field in params.get(tier, {}):
                if values.get(field) is not None:
                    setdoc[f"parameters.{tier}.{field}"] = values[field]

        # Sync specifications values
        spec_block = n.get("specifications") or {}
        if spec_block:
            updated_spec = False
            for cat in SPEC_CATEGORIES:
                if cat in spec_block and isinstance(spec_block[cat], dict) and "parameters" in spec_block[cat]:
                    for param in spec_block[cat]["parameters"]:
                        param_key = ck(param["name"])
                        if values.get(param_key) is not None:
                            param["value"] = values[param_key]
                            updated_spec = True
            if updated_spec:
                setdoc["specifications"] = spec_block

        if setdoc:
            A[CATALOG].update_one({"_id": n["_id"]}, {"$set": setdoc})
            log.info("  ENRICHED %s '%s' — filled %d fields",
                     n["_id"], n["name"], len(setdoc))
            done += 1
        if done % 20 == 0:
            log.info("  ... %d/%d enriched", done, len(todo))

    log.info("[l4values] %s: %d enriched, %d failed, %d already-filled (of %d)",
             "dry-run" if dry_run else "done", done, fail, skipped, len(todo))


def build_advanced_specs(dry_run: bool = False, limit: int = 0) -> None:
    """
    Phase advspecs: generate and verify advanced spec names for every L1/L2 node
    that has parameters set, then store in Restructured.advanced_specifications.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from advanced_specs import run_for_all_nodes

    src, A = conns()
    log.info("[advspecs] Starting advanced spec generation (dry_run=%s limit=%d)",
             dry_run, limit)
    if dry_run:
        todo = list(A[CATALOG].find(
            {"level": {"$in": ["L1", "L2"]}, "parameters": {"$exists": True}},
            {"name": 1}))
        log.info("[advspecs] dry-run: would process %d nodes", len(todo))
        return
    results = run_for_all_nodes(A[CATALOG], A, limit=limit)
    ok = sum(1 for v in results.values() if v == "ok")
    log.info("[advspecs] done: %d/%d products processed", ok, len(results))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase",
                    choices=["structure", "schema", "l3schema", "l4values", "advspecs"],
                    required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N nodes (advspecs / l4values, 0=all)")
    args = ap.parse_args()

    if args.phase == "l3schema":
        build_l3_schema(dry_run=not args.apply)
    elif args.phase == "l4values":
        build_l4_values(dry_run=not args.apply)
    elif args.phase == "advspecs":
        build_advanced_specs(dry_run=not args.apply, limit=args.limit)
    else:
        if not args.apply:
            log.info("dry-run: pass --apply to write")
            return
        (build_structure if args.phase == "structure" else build_schema)()


if __name__ == "__main__":
    main()
