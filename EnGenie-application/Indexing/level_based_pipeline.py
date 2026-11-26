"""
LEVEL-BASED INDEXING PIPELINE — two functionalities, both upserting the existing
5-tier `Restructured` DB (both clusters):

  MODE 1  index-new      : add products NOT yet in the DB ->
                           L0/L1/L2 3-tier schema (LLM) + L3 device.spec_doc_url +
                           L4 vendor-product details. (Equipment->null+units / Accessory->enriched)
  MODE 2  update-existing : refresh products ALREADY in the DB ->
                           re-gather specs/values from the latest vendor data and
                           update each Equipment/Accessory node's parameters.

Source hierarchy = Products Catalog.xlsx (Classification=L0, Device/Product=L1,
Specific Device/Product Type=L2, Model Family=L3, Model=L4, Vendor). Datasheets matched
from product-recommender.documents.

Run: cd Indexing && uv run --no-project --with pandas --with openpyxl --with pymongo \
     --with python-dotenv --with dnspython --with langchain-google-genai python \
     level_based_pipeline.py --mode index-new --limit 2 --apply
"""
import argparse
import os
import re
import sys
import json
import logging
from collections import Counter, defaultdict

from dotenv import load_dotenv
from pymongo import MongoClient

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

backend_path = os.path.join(os.path.dirname(_HERE), "Backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Load environment configurations from the Indexing folder itself
load_dotenv(os.path.join(_HERE, ".env"))

from level_based_indexer import parse_catalog, assign_codes, existing_l0_map, norm, clean  # noqa: E402
from common.ai.llm.manager import get_flash_llm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")
DST_DB = "Restructured"
from build_catalog_hierarchy import (
    ck, toks, infer_unit, gen_schema as build_gen_schema, _build_spec_block, SPEC_CATEGORIES
)

class Pipeline:
    def __init__(self):
        cli = MongoClient(os.getenv("MONGODB_URI"), serverSelectionTimeoutMS=60000)
        self.src = cli[DST_DB]
        self.A = cli[DST_DB]
        self.docs = self.src["documents"]
        self.by_name = {}
        for lvl in ("L1", "L2"):
            for n in self.A[lvl].find({}, {"name": 1, "level": 1, "type": 1}):
                self.by_name[norm(n["name"])] = n
        self.l0 = list(self.A["L0"].find({}, {"name": 1, "type": 1}))
        self.l0_tok = {n["_id"]: (toks(n.get("name") or ""), n.get("type", "Equipment")) for n in self.l0}
        self._llm = None
        # doc index by vendor
        self.docs_by_vendor = defaultdict(list)
        for d in self.docs.find({}, {"vendor_name": 1, "model_family": 1, "pdf_title": 1, "filename": 1, "blob_url": 1}):
            self.docs_by_vendor[norm(d.get("vendor_name"))].append(d)

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_flash_llm(temperature=0.2)
        return self._llm

    # ---------- schema generation (Stage B) ----------
    def gen_schema(self, name, ntype, l0):
        """Invoke LLM to generate list of technical spec keys for a category."""
        return build_gen_schema(self.llm, name, ntype, l0)

    def params(self, node_id, name, ntype, l0):
        """Generate both legacy parameter and modern functional specification blocks."""
        mand, opt, lat = self.gen_schema(name, ntype, l0)
        p = {"mandatoryRequirements": {f: None for f in mand},
             "optionalRequirements": {f: None for f in opt},
             "latestRequirements": {f: None for f in lat}}
        if ntype == "Equipment":
            p["units"] = {f: u for f in (mand + opt + lat) if (u := infer_unit(f))}
        s = _build_spec_block(node_id, mand, opt, lat)
        return p, s

    # ---------- datasheet match (L3) ----------
    def spec_doc(self, vendor, fam, product_type=None, harvest=False):
        ven = norm(vendor)
        best, bs = None, 0
        if ven in self.docs_by_vendor:
            ft = toks(fam)
            for d in self.docs_by_vendor[ven]:
                dt = toks(d.get("model_family")) | toks(d.get("pdf_title")) | toks(d.get("filename"))
                s = len(ft & dt)
                if s > bs:
                    bs, best = s, d
        if best and bs >= 1:
            return str(best["_id"]), best.get("blob_url")
            
        if harvest and product_type:
            log.info("  [spec_doc] datasheet not in database for %s %s. Attempting web harvest...", vendor, fam)
            res = self._harvest_pdf(vendor, product_type, fam)
            if res:
                return res
        return None, None

    def _w(self, nid, lvl, setdoc):
        self.A[lvl].update_one({"_id": nid}, {"$set": setdoc}, upsert=True)

    def resolve_l0(self, l0name):
        """existing L0 code best-matching this Excel category by stem token overlap, else None."""
        nt = toks(l0name)
        best, score = None, 0
        for nid, (lt, _ty) in self.l0_tok.items():
            s = sum(1 for x in nt if any(x == y or (len(x) >= 4 and len(y) >= 4 and x[:4] == y[:4]) for y in lt))
            if s > score:
                score, best = s, nid
        return best if score >= 1 else None

    # ---------- MODE 1: index new ----------
    def index_new(self, limit, apply, harvest=False, collect_images=False):
        """
        Index new L0-L4 chains from the Excel catalog.

        harvest=True:       when no spec_doc_url is found in blob for an L3 node,
                            attempt to discover and download a datasheet via web search.
        collect_images=True: after writing each L3/L4, collect product images for
                            the model family via image_harvester.
        """
        tree = parse_catalog()
        l0map = {norm(name): code for name, t in tree.items() if (code := self.resolve_l0(name))}
        coded = assign_codes(tree, self.A, l0map)
        done = 0
        for l0node in coded.values():
            for n1 in l0node["l1"].values():
                for n2 in n1["l2"].values():
                    if norm(n2["name"]) in self.by_name:
                        continue                                  # already indexed
                    ntype = l0node["type"]
                    # L1 (create if new) + L2 schema
                    msg = [f"L0 {l0node['_id']} {l0node['name']}[{ntype}]"]
                    if apply:
                        if norm(n1["name"]) not in self.by_name:
                            p_block, s_block = self.params(n1["_id"], n1["name"], ntype, l0node["name"])
                            self._w(n1["_id"], "L1", {"name": n1["name"], "level": "L1", "type": ntype,
                                                      "parent_id": l0node["_id"],
                                                      "parameters": p_block,
                                                      "specifications": s_block})
                        p_block, s_block = self.params(n2["_id"], n2["name"], ntype, l0node["name"])
                        self._w(n2["_id"], "L2", {"name": n2["name"], "level": "L2", "type": ntype,
                                                  "parent_id": n1["_id"],
                                                  "parameters": p_block,
                                                  "specifications": s_block})
                        for fam, n3 in n2["l3"].items():
                            did, url = self.spec_doc(n3.get("vendor"), fam, product_type=n2["name"], harvest=harvest)
                            self._w(n3["_id"], "L3", {"name": fam, "level": "L3", "parent_id": n2["_id"],
                                                      "manufacturer": n3.get("vendor"), "spec_doc_url": url,
                                                      "device": {"oem": n3.get("vendor"), "model_series": fam,
                                                                 "model_number": None, "specs_Doc_Id": did,
                                                                 "spec_doc_url": url}})
                            for model, m_code in sorted(n3["models"].items()):
                                self._w(m_code, "L4",
                                        {"name": model, "level": "L4", "parent_id": n3["_id"],
                                         "vendor": n3.get("vendor")})
                            # --images: collect product image for this model family
                            if collect_images and n3.get("vendor"):
                                self._collect_images(n3.get("vendor"), fam,
                                                     n2["name"], n3["models"])
                    msg.append(f"L1 {n1['_id']} {n1['name']} | L2 {n2['_id']} {n2['name']} "
                               f"| L3x{len(n2['l3'])} | L4x{sum(len(x['models']) for x in n2['l3'].values())}")
                    log.info("  %s %s", "CREATE" if apply else "WOULD-CREATE", " -> ".join(msg))
                    done += 1
                    if limit and done >= limit:
                        log.info("%s %d new L2 chains.", "indexed" if apply else "(dry) would index", done)
                        return
        log.info("%s %d new L2 chains.", "indexed" if apply else "(dry) would index", done)

    # ---------- harvest helpers ----------
    def _harvest_pdf(self, vendor, product_type, model_family):
        """Discover and download a datasheet via web search; return (doc_id, blob_url)."""
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from harvesting.web_search import _search_pdfs, _download_to_blob
            pdfs = _search_pdfs(vendor or "", product_type, [model_family])
            for entry in pdfs:
                for pdf in entry.get("pdfs", []):
                    url = pdf.get("pdf_url")
                    if not url:
                        continue
                    import re as _re
                    fname = _re.sub(r'[<>:"/\\|?*]', "_",
                                    os.path.basename(url.split("?")[0]) or
                                    f"{vendor}_{model_family}.pdf")
                    ok, _, doc_id = _download_to_blob(url, {
                        "product_type": product_type,
                        "vendor_name": vendor or "",
                        "model_family": model_family,
                        "filename": fname,
                        "collection_type": "documents",
                    })
                    if ok and doc_id:
                        # Re-look up blob_url from MongoDB documents
                        try:
                            from infra.storage import mongo_src
                            doc = mongo_src()["documents"].find_one({"_id": __import__("bson").ObjectId(doc_id)},
                                                                    {"blob_url": 1})
                            blob_url = doc.get("blob_url") if doc else None
                        except Exception:
                            blob_url = None
                        log.info("  [harvest] discovered PDF for %s %s -> %s",
                                 vendor, model_family, blob_url)
                        return doc_id, blob_url
        except Exception as e:
            log.warning("  [harvest] _harvest_pdf failed for %s %s: %s",
                        vendor, model_family, e)
        return None, None

    def _collect_images(self, vendor, model_family, product_type, models):
        """Trigger image collection for a model family (non-fatal)."""
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from harvesting.image_harvester import collect_product_images
            model_families = [{"model_series": model_family,
                                "sub_models": [{"name": m} for m in models]}]
            collect_product_images(product_type, vendor, model_families)
        except Exception as e:
            log.warning("  [images] collect_images failed for %s %s: %s",
                        vendor, model_family, e)

    # ---------- MODE 2: update existing ----------
    def update_existing(self, limit, apply):
        n = 0
        for lvl in ("L1", "L2"):
            for node in self.A[lvl].find({}, {"name": 1, "level": 1, "type": 1, "parameters": 1, "specifications": 1}):
                ntype = node.get("type", "Equipment")
                if ntype != "Accessory":
                    continue                                          # Equipment stay null templates
                fields = set()
                for t in ("mandatoryRequirements", "optionalRequirements", "latestRequirements"):
                    fields |= set((node.get("parameters") or {}).get(t, {}).keys())
                if not fields:
                    continue
                vals = self._enrich(node["name"], fields)
                
                # Align specifications categories nested parameters list values
                spec = node.get("specifications") or {}
                updated_spec = False
                for cat in SPEC_CATEGORIES:
                    cat_obj = spec.get(cat) or {}
                    if isinstance(cat_obj, dict) and isinstance(cat_obj.get("parameters"), list):
                        for param in cat_obj["parameters"]:
                            if isinstance(param, dict) and param.get("name"):
                                f_key = ck(param["name"])
                                if f_key in vals and vals[f_key] is not None:
                                    param["value"] = vals[f_key]
                                    updated_spec = True

                if apply:
                    setdoc = {f"parameters.{t}.{f}": vals[f]
                              for t in ("mandatoryRequirements", "optionalRequirements", "latestRequirements")
                              for f in (node.get("parameters") or {}).get(t, {}) if vals.get(f) is not None}
                    if updated_spec:
                        setdoc["specifications"] = spec
                    if setdoc:
                        self._w(node["_id"], node["level"], setdoc)
                        
                filled = sum(1 for v in vals.values() if v is not None)
                log.info("  %s %s %s [%s] refreshed %d/%d field values",
                         "UPDATE" if apply else "WOULD-UPDATE", node["level"], node["name"], ntype, filled, len(fields))
                n += 1
                if limit and n >= limit:
                    break
        log.info("%s %d existing accessory nodes.", "updated" if apply else "(dry) would update", n)

    def _enrich(self, pt, fields):
        vals = defaultdict(Counter)
        for d in self.src["vendors"].find({"product_type": {"$regex": re.escape(pt), "$options": "i"}}, {"data.models": 1}):
            for m in ((d.get("data") or {}).get("models") or []):
                for sm in (m.get("sub_models") or []):
                    for k, v in (sm.get("specifications") or {}).items():
                        if v not in (None, "", [], {}):
                            vals[ck(k)][str(v)[:120]] += 1
        return {f: (vals[f].most_common(1)[0][0] if vals.get(f) else None) for f in fields}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["index-new", "update-existing"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--harvest", action="store_true",
                    help="(index-new) discover and download datasheets via web search "
                         "for L3 nodes with no existing spec_doc_url")
    ap.add_argument("--images", action="store_true",
                    help="(index-new) collect product images after writing each L3/L4")
    args = ap.parse_args()
    p = Pipeline()
    log.info("MODE=%s  %s  harvest=%s images=%s",
             args.mode, "APPLY" if args.apply else "DRY-RUN",
             args.harvest, args.images)
    if args.mode == "index-new":
        p.index_new(args.limit, args.apply,
                    harvest=args.harvest, collect_images=args.images)
    else:
        p.update_existing(args.limit, args.apply)


if __name__ == "__main__":
    main()
