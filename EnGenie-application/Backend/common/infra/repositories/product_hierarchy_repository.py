"""
Active MongoDB repository for the 5-layer product hierarchy and its
specification system.

Structure (in the `Restructured` database):
  unified_product_hierarchy  — flat source of truth; one doc per node, `_id` = UUID,
                               linked by `parent_id`. Levels L0..L4.
  L0..L4                      — relational level views (derived from the tree).
  SPEC_GROUP/SPEC_DEFINITION  — the spec catalog.
  NODE_SPEC                   — node <-> spec relationships (DEFINES demands + FULFILLS values).

All writes go to the flat hierarchy (the source of truth); `sync_level_views()`
regenerates the L0..L4 collections. IDs are deterministic (stable_node_uuid) so
upserts are idempotent.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from common.infra.mongodb_config import (
    RestructuredCollections as RC,
    ensure_restructured_indexes,
    get_restructured_db,
    mongodb_manager,
    RESTRUCTURED_DATABASE,
)
from domain.solution.agents.harness_agent import HierarchyNode, LEVEL_NAMES, stable_node_uuid

logger = logging.getLogger(__name__)

# level -> (relational collection, primary name field).
# NOTE: L0 now exposes its label as `name` (was `category`); the whole tree —
# views + flat hierarchy — uses a single `name` field at every level.
_LEVEL_VIEW = {
    "L0": (RC.L0, "name"),
    "L1": (RC.L1, "name"),
    "L2": (RC.L2, "name"),
    "L3": (RC.L3, "name"),
    "L4": (RC.L4, "name"),
}


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", str(t or "").lower()).split())


def _slug(level: str, name: str, category: str = "", vendor: str = "", parent_slug: str = "") -> str:
    """Deterministic natural key used to derive the node UUID."""
    if level == "L0": return f"L0_{_norm(name)}"
    if level in ("L1", "L2"): return f"{level}_{_norm(category)}_{_norm(name)}"
    if level == "L3": return f"L3_{_norm(vendor)}_{_norm(name)}"
    return f"L4_{_norm(vendor)}_{_norm(parent_slug)}_{_norm(name)}"


# ---------------------------------------------------------------------------
# SchemaSpec shape (L0/L1/L2): {id, safety:[SpecParameter], electrical:[SpecParameter], ...}
# Each SpecParameter: {id, name, value, level:"Required"|"Optional"|"Advanced", units}
# The agents consume a flat 3-tier shape (mandatory/optional/latest), so we
# project the per-category Parameter lists back into that shape.
# ---------------------------------------------------------------------------
_SCHEMA_SPEC_CATEGORIES = (
    "safety", "electrical", "mechanical", "process",
    "environmental", "performance", "certifications", "materials",
    "communication", "product_info", "applications", "other",
)
_LEVEL_TO_TIER = {"Required": "mandatory", "Optional": "optional", "Advanced": "latest"}


def _is_schema_spec(spec: Any) -> bool:
    """True when spec carries at least one of the SchemaSpec category keys or a parameters dictionary."""
    if not isinstance(spec, dict):
        return False
    if isinstance(spec.get("parameters"), dict):
        return True
    for cat in _SCHEMA_SPEC_CATEGORIES:
        val = spec.get(cat)
        if isinstance(val, list):
            return True
        if isinstance(val, dict) and isinstance(val.get("parameters"), list):
            return True
    return False


def _flatten_schema_spec(spec: dict) -> tuple[dict, dict, dict]:
    """Project SchemaSpec category buckets -> (mandatory, optional, latest) tiers.

    Supports:
    - safety: [SpecParameter]
    - safety: {parameters: [SpecParameter]}
    - specifications.parameters: {key: value} (direct key-value pairs)
    - specifications.parameters: {mandatoryRequirements: {...}, optionalRequirements: {...}}
    """
    mandatory: dict[str, Any] = {}
    optional: dict[str, Any] = {}
    latest: dict[str, Any] = {}
    tier_map = {"Required": mandatory, "Optional": optional, "Advanced": latest}

    if not spec:
        return mandatory, optional, latest

    # Support specifications.parameters.x format
    params = spec.get("parameters")
    if isinstance(params, dict):
        has_tiers = any(tk in params for tk in ("mandatoryRequirements", "optionalRequirements", "latestRequirements", "essential", "optional", "latest"))
        if has_tiers:
            mandatory.update(params.get("mandatoryRequirements") or params.get("essential") or {})
            optional.update(params.get("optionalRequirements") or params.get("optional") or {})
            latest.update(params.get("latestRequirements") or params.get("latest") or params.get("advanced") or {})
        else:
            # Direct key-value dictionary under specifications.parameters
            for k, v in params.items():
                optional[k] = v or ""

    for cat in _SCHEMA_SPEC_CATEGORIES:
        val = spec.get(cat)
        params_list = []
        if isinstance(val, list):
            params_list = val
        elif isinstance(val, dict) and isinstance(val.get("parameters"), list):
            params_list = val["parameters"]
            
        for param in params_list:
            if not isinstance(param, dict):
                continue
            name = param.get("name") or param.get("id") or ""
            if not name:
                continue
            value = param.get("value") or ""
            tier = tier_map.get(param.get("level", "Optional"), optional)
            tier[name] = value
    return mandatory, optional, latest


# Legacy grouped shape kept for backward-compat with older DB documents.
#   {<group>: {parameters: {essential:{f:v}, optional:{f:v}, latest:{f:v}}}, units:{f:u}}
def _is_grouped_specs(spec: Any) -> bool:
    return isinstance(spec, dict) and any(
        isinstance(v, dict) and isinstance(v.get("parameters"), dict) for v in spec.values()
    )


def _flatten_grouped_specs(spec: dict) -> tuple[dict, dict, dict]:
    """Union every group's parameters.{essential,optional,latest} -> (mandatory, optional, latest)."""
    mandatory, optional, latest = {}, {}, {}
    for group, blk in (spec or {}).items():
        if group == "units" or not isinstance(blk, dict):
            continue
        params = blk.get("parameters")
        if not isinstance(params, dict):
            continue
        mandatory.update(params.get("essential") or {})
        optional.update(params.get("optional") or {})
        latest.update(params.get("latest") or {})
    return mandatory, optional, latest


_standards_metadata_cache = None

def _get_standards_metadata() -> dict:
    """Lazily load standards metadata from MongoDB and cache in-memory.

    standards_metadata lives on Cluster A (main client) under the Restructured DB,
    not on Cluster B (restructured_client) where the hierarchy nodes live.
    """
    global _standards_metadata_cache
    if _standards_metadata_cache is None:
        try:
            # Always read from Cluster A — that's where standards_metadata is populated.
            db = mongodb_manager.client[RESTRUCTURED_DATABASE]
            docs = list(db["standards_metadata"].find({}, {"code": 1, "title": 1}))
            _standards_metadata_cache = {d["code"]: d["title"] for d in docs if "code" in d and "title" in d}
            logger.info(f"Loaded {len(_standards_metadata_cache)} standard titles from MongoDB 'standards_metadata'.")
        except Exception as exc:
            logger.warning(f"Failed to fetch standards_metadata from DB: {exc}")
            _standards_metadata_cache = {}
    return _standards_metadata_cache


def _format_parameter_value(value: Any, units: Any = None) -> str:
    """Format a parameter value as `value (units)` when units are present."""
    display_value = str(value or "").strip()
    if not display_value:
        return ""

    display_units = str(units or "").strip()
    if not display_units:
        return display_value

    normalized_value = display_value.lower()
    normalized_units = display_units.lower()
    if normalized_value.endswith(f"({normalized_units})") or normalized_value.endswith(normalized_units):
        return display_value

    return f"{display_value} ({display_units})"


class ProductHierarchyRepository:
    """CRUD + spec access for the 5-layer product taxonomy hierarchy."""

    # ------------------------------------------------------------------ read
    @staticmethod
    def get_node(node_uuid: str) -> Optional[dict]:
        return get_restructured_db()[RC.HIERARCHY].find_one({"_id": node_uuid})

    @staticmethod
    def get_categories() -> list[dict]:
        """All L0 (Instrument/Category) nodes."""
        return list(get_restructured_db()[RC.HIERARCHY].find({"level": "L0"}))

    @staticmethod
    def get_children(parent_id: str, level: str | None = None) -> list[dict]:
        q = {"parent_id": parent_id}
        if level: q["level"] = level
        return list(get_restructured_db()[RC.HIERARCHY].find(q))

    @staticmethod
    def get_by_level(level: str, node_type: str | None = None) -> list[dict]:
        q = {"level": level}
        if node_type: q["metadata.node_type"] = node_type
        return list(get_restructured_db()[RC.HIERARCHY].find(q))

    @staticmethod
    def get_path(node_uuid: str) -> list[dict]:
        """[node, parent, ..., L0] following parent_id."""
        db, chain, cur = get_restructured_db()[RC.HIERARCHY], [], node_uuid
        while cur:
            doc = db.find_one({"_id": cur})
            if not doc:
                # Fallback: search in level views (L4 -> L3 -> L2 -> L1 -> L0)
                for lvl in RC.LEVELS:
                    doc = get_restructured_db()[lvl].find_one({"_id": cur})
                    if doc:
                        doc.setdefault("level", lvl)
                        break
            if not doc: break
            chain.append(doc)
            cur = doc.get("parent_id")
        return chain

    # ----------------------------------------------------------------- write
    @staticmethod
    def upsert_node(level: str, name: str, *, parent_id: str | None = None,
                    category: str = "", vendor: str | None = None,
                    specifications: dict | None = None, metadata: dict | None = None,
                    node_type: str | None = None, parent_slug: str = "") -> str:
        """Idempotently create/update a hierarchy node; returns its UUID.

        Validates the node shape via HierarchyNode and mirrors it into the
        matching L0..L4 relational view.
        """
        slug = _slug(level, name, category, vendor or "", parent_slug)
        uid = stable_node_uuid(slug)
        meta = dict(metadata or {})
        meta.setdefault("level_name", LEVEL_NAMES.get(level, level))
        if category: meta.setdefault("category", category)
        if node_type: meta["node_type"] = node_type
        node = HierarchyNode(uuid=uid, level=level, name=name, parent_id=parent_id,
                             vendor=vendor, specifications=specifications or {}, metadata=meta)
        doc = node.to_doc()
        doc["_id"] = doc.pop("uuid")
        doc["parent_id"] = doc.pop("parent_id", None)
        doc["key"] = slug
        if level in ("L3", "L4"):  # carry the consolidated identity block on the flat node too
            doc["device"] = ProductHierarchyRepository._build_device(level, doc)
        get_restructured_db()[RC.HIERARCHY].update_one({"_id": uid}, {"$set": doc}, upsert=True)
        ProductHierarchyRepository._mirror_to_view(level, doc)
        logger.info("[ProductHierarchyRepo] upserted %s '%s' (%s)", level, name, uid)
        return uid

    # device-group fields (L3/L4 carry a single consolidated identity block).
    _DEVICE_FIELDS = ("id", "oem", "model_series", "model_number",
                      "specs_Doc_Id", "spec_doc_url", "parent_id", "key")

    @staticmethod
    def _build_device(level: str, doc: dict) -> dict:
        """Consolidated `device` identity block for an L3/L4 node.

        If the flat node already carries a `device` group (the normal case after
        migration) it is reused verbatim; otherwise it is synthesised from the
        node's own fields, inheriting model_series / spec-doc from the parent L3
        for L4 nodes. `source_vendor_id` is intentionally absent — the vendor is
        resolved via `device.oem` and parent traversal.
        """
        existing = doc.get("device")
        if isinstance(existing, dict) and existing.get("id"):
            return {k: existing.get(k) for k in ProductHierarchyRepository._DEVICE_FIELDS}
        parent_dev = {}
        if level == "L4" and doc.get("parent_id"):
            par = get_restructured_db()[RC.HIERARCHY].find_one(
                {"_id": doc["parent_id"]}, {"device": 1})
            parent_dev = (par or {}).get("device") or {}
        meta = doc.get("metadata") or {}
        return {
            "id": doc["_id"],
            "oem": doc.get("manufacturer") or doc.get("vendor"),
            "model_series": parent_dev.get("model_series") or doc.get("name"),
            # model_number is a PER-PRODUCT (L4) value. At L3 (a model family) there is
            # no single model number, so don't fall back to the family name — that made
            # model_number duplicate model_series. Keep it null at L3.
            "model_number": (doc.get("model_number") or meta.get("model_number")
                             or (doc.get("name") if level == "L4" else None)),
            "specs_Doc_Id": parent_dev.get("specs_Doc_Id") or meta.get("specs_Doc_Id"),
            "spec_doc_url": parent_dev.get("spec_doc_url") or doc.get("spec_doc_url"),
            "parent_id": doc.get("parent_id"),
            "key": doc.get("key"),
        }

    # Internal/source-only fields that never appear in a relational view.
    # The view is otherwise a faithful passthrough of the flat node (so every
    # ER-diagram field — type/category_code/tag_number/output_signal/etc. —
    # is preserved on a rebuild). Per-level extras strip identity now folded
    # into `device` (L3/L4 `key`), the redundant `level`, and the L4 display name.
    _VIEW_DROP = {
        "L0": ("key", "parameters"),
        "L1": ("key", "parameters"),
        "L2": ("key", "parameters"),
        "L3": ("key", "parameters", "level"),
        "L4": ("key", "parameters", "level", "name"),
    }

    @staticmethod
    def _mirror_to_view(level: str, doc: dict) -> None:
        """Project a flat-hierarchy node into its L0..L4 relational view.

        Passthrough of the flat node minus `_VIEW_DROP[level]`. For L3/L4 the
        consolidated `device` identity block is (re)built so it is always present
        and normalised. L0 exposes its label as `name` (not the legacy
        `category`); L0/L1/L2 keep grouped `specifications` + ER fields; L4 keeps
        its real product data (`specifications`/`normalized_specifications`/`certifications`).
        """
        coll_name = _LEVEL_VIEW[level][0]
        drop = ProductHierarchyRepository._VIEW_DROP.get(level, ())
        row = {k: v for k, v in doc.items() if k not in drop}
        if level in ("L3", "L4"):
            row["device"] = ProductHierarchyRepository._build_device(level, doc)
        get_restructured_db()[coll_name].update_one({"_id": doc["_id"]}, {"$set": row}, upsert=True)

    @staticmethod
    def update_specifications(node_uuid: str, specifications: dict) -> bool:
        db = get_restructured_db()
        r = db[RC.HIERARCHY].update_one({"_id": node_uuid}, {"$set": {"specifications": specifications}})
        node = db[RC.HIERARCHY].find_one({"_id": node_uuid}, {"level": 1})
        if node and node["level"] in _LEVEL_VIEW:
            db[_LEVEL_VIEW[node["level"]][0]].update_one({"_id": node_uuid}, {"$set": {"specifications": specifications}})
        return r.matched_count > 0

    @staticmethod
    def delete_node(node_uuid: str, cascade: bool = False) -> int:
        """Delete a node (and optionally its whole subtree) from the tree + views + NODE_SPEC."""
        db, targets = get_restructured_db(), [node_uuid]
        if cascade:
            frontier = [node_uuid]
            while frontier:
                kids = db[RC.HIERARCHY].distinct("_id", {"parent_id": {"$in": frontier}})
                targets.extend(kids)
                frontier = kids
        db[RC.HIERARCHY].delete_many({"_id": {"$in": targets}})
        for lv in RC.LEVELS: db[lv].delete_many({"_id": {"$in": targets}})
        db[RC.NODE_SPEC].delete_many({"source_node_id": {"$in": targets}})
        logger.info("[ProductHierarchyRepo] deleted %d node(s) (cascade=%s)", len(targets), cascade)
        return len(targets)

    # ------------------------------------------------------------- spec system
    @staticmethod
    def attach_spec_value(node_uuid: str, spec_code: str, value: Any, *,
                          requirement: str = "Optional", is_standard: bool = False,
                          source: str | None = None) -> str:
        """Attach an actual spec VALUE to a node (NODE_SPEC FULFILLS row)."""
        db = get_restructured_db()
        node = db[RC.HIERARCHY].find_one({"_id": node_uuid}, {"level": 1})
        nsid = stable_node_uuid(f"NODESPEC:{node_uuid}:{spec_code}:value")
        db[RC.NODE_SPEC].update_one({"_id": nsid}, {"$set": {
            "_id": nsid, "source_node_id": node_uuid,
            "source_node_type": (node or {}).get("level", "L4"),
            "spec_code": spec_code, "value": value,
            "requirement": requirement, "is_standard": is_standard,
            "relationship_type": "fulfills", "source": source,
            "effective_date": datetime.now(timezone.utc)}}, upsert=True)
        return nsid

    @staticmethod
    def get_node_specs(node_uuid: str) -> dict:
        """{'demands': [...], 'values': [...]} attached directly at this node."""
        rows = list(get_restructured_db()[RC.NODE_SPEC].find({"source_node_id": node_uuid}))
        return {"demands": [r for r in rows if r.get("value") is None],
                "values": [r for r in rows if r.get("value") is not None]}

    @staticmethod
    def resolve_demands(node_uuid: str) -> dict:
        """Effective demands for a node = own + inherited (nearest ancestor wins)."""
        db, demands = get_restructured_db(), {}
        for nd in reversed(ProductHierarchyRepository.get_path(node_uuid)):
            for ns in db[RC.NODE_SPEC].find({"source_node_id": nd["_id"], "value": None}):
                demands[ns["spec_code"]] = {"requirement": ns["requirement"],
                                            "base_requirement": ns.get("base_requirement") or ns["requirement"],
                                            "overrides_master": ns["requirement"] == "Latest",
                                            "source_node_id": nd["_id"], "source_level": nd["level"]}
        return demands

    @staticmethod
    def resolve_schema(node_uuid: str) -> dict:
        """Cascade-resolve a node's effective schema (mandatory + optional).

        Now derived from the new grouped `specifications` via
        `resolve_parameters_schema` (the legacy `spec_requirements` field is gone).
        """
        r = ProductHierarchyRepository.resolve_parameters_schema(node_uuid)
        return {"mandatoryRequirements": r["mandatoryRequirements"],
                "optionalRequirements": r["optionalRequirements"]}

    @staticmethod
    def resolve_parameters_schema(node_uuid: str) -> dict:
        """Cascade-resolve a node's 3-tier schema by walking L(n) -> ... -> L0.

        Sources each node's tiers from the new grouped `specifications` (flattened
        across groups); see `_own_params`.
        """
        path = ProductHierarchyRepository.get_path(node_uuid)
        if not path: return {"mandatoryRequirements": {}, "optionalRequirements": {}, "latestRequirements": {}}
        mandatory, optional, latest = ProductHierarchyRepository._own_params(path[0])
        seen = set(mandatory) | set(optional) | set(latest)
        for anc in path[1:]:
            am, ao, al = ProductHierarchyRepository._own_params(anc)
            for k, v in {**am, **ao, **al}.items():
                if k not in seen:
                    optional[k] = v
                    seen.add(k)
        return {"mandatoryRequirements": mandatory, "optionalRequirements": optional, "latestRequirements": latest}

    # --- cascade primitives ------------------------------------------------
    _BAND_LEVELS = {"L0", "L1", "L2"}

    @staticmethod
    def _fresh_specifications(n: dict) -> dict:
        """Prefer the level VIEW's `specifications` (where the enriched data lives)
        for a node; fall back to what the passed (hierarchy) node already carries."""
        lvl, nid = (n or {}).get("level"), (n or {}).get("_id")
        if lvl in _LEVEL_VIEW and nid:
            try:
                vdoc = get_restructured_db()[_LEVEL_VIEW[lvl][0]].find_one(
                    {"_id": nid}, {"specifications": 1})
                spec = (vdoc or {}).get("specifications")
                if spec and (_is_schema_spec(spec) or _is_grouped_specs(spec)):
                    return spec
            except Exception as exc:  # never let a view lookup break resolution
                logger.debug("[ProductHierarchyRepo] view spec lookup failed for %s: %s", nid, exc)
        return (n or {}).get("specifications") or {}

    @staticmethod
    def _own_params(n: dict) -> tuple[dict, dict, dict]:
        """Flat 3-tier (mandatory, optional, latest) for ONE node.

        Priority order:
          1. New SchemaSpec shape: {id, safety:[SpecParameter], electrical:[SpecParameter], ...}
          2. Legacy grouped shape: {<group>: {parameters: {essential, optional, latest}}}
          3. Legacy flat `parameters.{mandatoryRequirements, optionalRequirements, latestRequirements}`
        """
        spec = (n or {}).get("specifications")
        # Pull from the view when the node's own spec isn't in a known shape.
        if not _is_schema_spec(spec) and not _is_grouped_specs(spec):
            spec = ProductHierarchyRepository._fresh_specifications(n)
        if _is_schema_spec(spec):
            return _flatten_schema_spec(spec)
        if _is_grouped_specs(spec):
            return _flatten_grouped_specs(spec)
        p = (n or {}).get("parameters") or {}
        return (dict(p.get("mandatoryRequirements") or {}),
                dict(p.get("optionalRequirements") or {}),
                dict(p.get("latestRequirements") or {}))

    @staticmethod
    def _ancestors_in_band(node_uuid: str) -> list[dict]:
        return [n for n in ProductHierarchyRepository.get_path(node_uuid)[1:]
                if n.get("level") in ProductHierarchyRepository._BAND_LEVELS]

    @staticmethod
    def _descendants_in_band(node_uuid: str) -> list[dict]:
        db, out, frontier = get_restructured_db()[RC.HIERARCHY], [], [node_uuid]
        while frontier:
            kids = [k for k in db.find({"parent_id": {"$in": frontier},
                                        "level": {"$in": list(ProductHierarchyRepository._BAND_LEVELS)}})
                    if k.get("level") in ProductHierarchyRepository._BAND_LEVELS]
            out.extend(kids)
            frontier = [k["_id"] for k in kids]
        return out

    @staticmethod
    def _merge_cascade(matched: dict, related: list[dict]) -> dict:
        mandatory, optional, latest = ProductHierarchyRepository._own_params(matched)
        seen = set(mandatory) | set(optional) | set(latest)
        for n in related:
            am, ao, al = ProductHierarchyRepository._own_params(n)
            for k, v in {**am, **ao}.items():
                if k not in seen:
                    optional[k] = v
                    seen.add(k)
            for k, v in al.items():
                if k not in seen:
                    latest[k] = v
                    seen.add(k)
        return {"mandatoryRequirements": mandatory, "optionalRequirements": optional, "latestRequirements": latest}

    @staticmethod
    def resolve_upward_cascade(node_uuid: str) -> dict:
        matched = get_restructured_db()[RC.HIERARCHY].find_one({"_id": node_uuid})
        if not matched: return {"mandatoryRequirements": {}, "optionalRequirements": {}, "latestRequirements": {}}
        return ProductHierarchyRepository._merge_cascade(matched, ProductHierarchyRepository._ancestors_in_band(node_uuid))

    @staticmethod
    def resolve_downward_cascade(node_uuid: str) -> dict:
        matched = get_restructured_db()[RC.HIERARCHY].find_one({"_id": node_uuid})
        if not matched: return {"mandatoryRequirements": {}, "optionalRequirements": {}, "latestRequirements": {}}
        return ProductHierarchyRepository._merge_cascade(matched, ProductHierarchyRepository._descendants_in_band(node_uuid))

    @staticmethod
    def resolve_bidirectional_cascade(node_uuid: str) -> dict:
        matched = get_restructured_db()[RC.HIERARCHY].find_one({"_id": node_uuid})
        if not matched: return {"mandatoryRequirements": {}, "optionalRequirements": {}, "latestRequirements": {}}
        related = ProductHierarchyRepository._ancestors_in_band(node_uuid) + ProductHierarchyRepository._descendants_in_band(node_uuid)
        return ProductHierarchyRepository._merge_cascade(matched, related)

    @staticmethod
    def resolve_band_schema(node_uuid: str) -> dict:
        return ProductHierarchyRepository.resolve_bidirectional_cascade(node_uuid)

    # --- VIEW-based band traversal ---------------------------------------
    # The L0..L4 views (not the flat hierarchy) hold the current regrouped +
    # enriched `specifications`, and use their OWN coded _id space (which has
    # diverged from the hierarchy's). So band resolution traverses the views via
    # their `parent_id` links.
    _VIEW_PARENT = {"L1": "L0", "L2": "L1"}
    _VIEW_CHILD = {"L0": "L1", "L1": "L2"}

    @staticmethod
    def _view_coll(level: str):
        return get_restructured_db()[_LEVEL_VIEW[level][0]]

    @staticmethod
    def _find_band_node(name: str) -> Optional[dict]:
        """Match a product-type by name in the L0/L1/L2 VIEWS and the flat catalog_hierarchy.

        The L0 view indexes by ``category``; L1/L2 views index by ``name``.  If the
        level views do not contain a match, we fall back to the flat ``catalog_hierarchy``
        collection so that 5-tier data is always the source of truth.  The returned node
        is guaranteed to carry a ``level`` so the cascade direction is resolved.
        """
        if not name: return None
        exact = {"$regex": f"^{re.escape(name)}$", "$options": "i"}
        sub = {"$regex": re.escape(name), "$options": "i"}
        cands: list[dict] = []

        # 1. Level views (L2 most specific first, then L1, then L0).
        for lvl in ("L2", "L1", "L0"):
            field = "name"  # L0 view now uses `name` (was `category`)
            for doc in ProductHierarchyRepository._view_coll(lvl).find({field: exact}):
                doc.setdefault("level", lvl)
                cands.append(doc)
        if not cands:
            for lvl in ("L2", "L1", "L0"):
                field = "category" if lvl == "L0" else "name"
                for doc in ProductHierarchyRepository._view_coll(lvl).find({field: sub}).limit(10):
                    doc.setdefault("level", lvl)
                    cands.append(doc)

        # 2. Fallback: flat 5-tier catalog_hierarchy collection.
        if not cands:
            db = get_restructured_db()[RC.HIERARCHY]
            for field in ("name", "category"):
                doc = db.find_one({"level": {"$in": ["L0", "L1", "L2"]}, field: exact})
                if doc:
                    cands.append(ProductHierarchyRepository._coerce_to_view_node(doc))
                    break
        if not cands:
            db = get_restructured_db()[RC.HIERARCHY]
            for field in ("name", "category"):
                for doc in db.find({"level": {"$in": ["L0", "L1", "L2"]}, field: sub}).limit(10):
                    cands.append(ProductHierarchyRepository._coerce_to_view_node(doc))

        if not cands: return None
        # Prefer more specific levels (L2 -> L1 -> L0) when choosing the matched node
        for lvl in ("L2", "L1", "L0"):
            lvl_cands = [c for c in cands if c.get("level") == lvl]
            if lvl_cands:
                return max(lvl_cands, key=lambda n: sum(len(d) for d in ProductHierarchyRepository._own_params(n)))
        return max(cands, key=lambda n: sum(len(d) for d in ProductHierarchyRepository._own_params(n)))

    @staticmethod
    def _coerce_to_view_node(doc: dict) -> dict:
        """Return the corresponding view node for a flat-hierarchy doc if it exists.

        Views hold the regrouped/enriched ``specifications`` and the correct parent
        links for cascading.  If the view is missing, return the flat doc with a
        level field set so the cascade still works.
        """
        lvl = doc.get("level")
        if lvl in _LEVEL_VIEW:
            view_doc = ProductHierarchyRepository._view_coll(lvl).find_one({"_id": doc["_id"]})
            if view_doc:
                view_doc.setdefault("level", lvl)
                return view_doc
        doc.setdefault("level", lvl)
        return doc

    @staticmethod
    def _view_ancestors(node: dict) -> list[dict]:
        out, cur = [], node
        while cur:
            plvl = ProductHierarchyRepository._VIEW_PARENT.get(cur.get("level"))
            puid = cur.get("parent_id")
            if not plvl or not puid: break
            cur = ProductHierarchyRepository._view_coll(plvl).find_one({"_id": puid})
            if cur: out.append(cur)
        return out

    @staticmethod
    def _view_descendants(node: dict) -> list[dict]:
        out, lvl, ids = [], node.get("level"), [node["_id"]]
        while lvl and ids:
            clvl = ProductHierarchyRepository._VIEW_CHILD.get(lvl)
            if not clvl: break
            kids = list(ProductHierarchyRepository._view_coll(clvl).find({"parent_id": {"$in": ids}}))
            out += kids
            lvl, ids = clvl, [k["_id"] for k in kids]
        return out

    @staticmethod
    def _view_related(node: dict, direction: str) -> list[dict]:
        if direction == "upward": return ProductHierarchyRepository._view_ancestors(node)
        if direction == "downward": return ProductHierarchyRepository._view_descendants(node)
        return ProductHierarchyRepository._view_ancestors(node) + ProductHierarchyRepository._view_descendants(node)

    @staticmethod
    def _resolve_band_view(node: dict, direction: str = "auto") -> dict:
        if direction == "auto":
            direction = ProductHierarchyRepository._direction_for_level(node.get("level"))
        return ProductHierarchyRepository._merge_cascade(node, ProductHierarchyRepository._view_related(node, direction))

    @staticmethod
    def _view_standard_details(node: dict) -> dict[str, str]:
        """Standard code -> formatted value for one node's certifications bucket."""
        spec = ProductHierarchyRepository._fresh_specifications(node)
        if not spec:
            return {}

        out: dict[str, str] = {}
        cert_val = spec.get("certifications")
        params_list = []
        if isinstance(cert_val, list):
            params_list = cert_val
        elif isinstance(cert_val, dict) and isinstance(cert_val.get("parameters"), list):
            params_list = cert_val["parameters"]

        if params_list:
            for param in params_list:
                if not isinstance(param, dict):
                    continue
                pid = param.get("id") or ""
                if not pid.startswith("STD-"):
                    continue
                name = str(param.get("name") or "").strip()
                if not name:
                    continue
                value = str(param.get("value") or "").strip()
                if not value or value.lower() == name.lower():
                    value = str(_get_standards_metadata().get(name, "") or "").strip()
                # Always emit the standard name even when no title/value is found.
                # Units are intentionally omitted — standards are labelled [Standard]
                # in the UI so the units descriptor is redundant.
                out[name] = _format_parameter_value(value) or name
            return out

        std = ((spec or {}).get("standards") or {}).get("parameters") or {}
        for tier in ("essential", "optional", "latest"):
            for code, title in (std.get(tier) or {}).items():
                if not code:
                    continue
                value = str(title or "").strip()
                if not value or value.lower() == str(code).strip().lower():
                    value = str(_get_standards_metadata().get(str(code), "") or "").strip()
                out[str(code)] = _format_parameter_value(value) or str(code)
        return out

    @staticmethod
    def _view_standards(node: dict) -> list:
        """Standards extracted from the node's `certifications` spec category."""
        return sorted(ProductHierarchyRepository._view_standard_details(node))

    @staticmethod
    def get_standards_titles(name: str) -> dict:
        """{standard_code: title} from certifications SpecParameter list (name->value pairs)."""
        node = ProductHierarchyRepository._find_band_node(name)
        if not node:
            return {}
        spec = ProductHierarchyRepository._fresh_specifications(node)
        out: dict = {}

        # New shape: certifications carries a list of SpecParameter
        cert_val = (spec or {}).get("certifications")
        params_list = []
        if isinstance(cert_val, list):
            params_list = cert_val
        elif isinstance(cert_val, dict) and isinstance(cert_val.get("parameters"), list):
            params_list = cert_val["parameters"]

        if params_list:
            for param in params_list:
                if isinstance(param, dict) and param.get("name"):
                    pid = param.get("id") or ""
                    if not pid.startswith("STD-"):
                        continue
                    pname = param["name"]
                    val = param.get("value") or ""
                    if not val or val == pname:
                        val = _get_standards_metadata().get(pname, "")
                    # Always emit the standard name even when no title found.
                    out[pname] = val or pname
            return out

        # Legacy grouped fallback
        std = ((spec or {}).get("standards") or {}).get("parameters") or {}
        for tier in ("essential", "optional", "latest"):
            for code, title in (std.get(tier) or {}).items():
                if code:
                    val = title or ""
                    if not val or val == str(code):
                        val = _get_standards_metadata().get(str(code), "")
                    out[str(code)] = val or str(code)
        return out

    @staticmethod
    def resolve_standard_specifications_by_name(name: str) -> dict[str, str]:
        """Cascade-resolve standards as `standard_code -> value (units)` across L0/L1/L2."""
        node = ProductHierarchyRepository._find_band_node(name)
        if not node:
            return {}

        direction = ProductHierarchyRepository._direction_for_level(node.get("level"))
        ordered_nodes = [node, *ProductHierarchyRepository._view_related(node, direction)]
        out: dict[str, str] = {}
        for current in ordered_nodes:
            for code, value in ProductHierarchyRepository._view_standard_details(current).items():
                if code not in out and value:
                    out[code] = value
        return out

    @staticmethod
    def get_grouped_specifications_by_name(name: str) -> Optional[dict]:
        """Full grouped `specifications` (all groups + units) for a product type,
        read from the matching L0/L1/L2 view. Use when the caller wants the
        per-group structure rather than the flattened 3-tier."""
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return None
        return ProductHierarchyRepository._fresh_specifications(node)

    _LEVEL_DIRECTION = {"L0": "downward", "L1": "bidirectional", "L2": "upward"}

    @staticmethod
    def _direction_for_level(level: str) -> str:
        return ProductHierarchyRepository._LEVEL_DIRECTION.get(level, "bidirectional")

    @staticmethod
    def resolve_parameters_schema_by_name(name: str, direction: str = "auto") -> Optional[dict]:
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return None
        if direction == "auto":
            direction = ProductHierarchyRepository._direction_for_level(node.get("level"))
            logger.info("[ProductHierarchyRepo] '%s' matched %s %s -> auto cascade '%s'",
                        name, node.get("level"), node.get("_id"), direction)
        return ProductHierarchyRepository._resolve_band_view(node, direction)

    @staticmethod
    def resolve_upward_cascade_by_name(name: str) -> Optional[dict]:
        return ProductHierarchyRepository.resolve_parameters_schema_by_name(name, "upward")

    @staticmethod
    def resolve_downward_cascade_by_name(name: str) -> Optional[dict]:
        return ProductHierarchyRepository.resolve_parameters_schema_by_name(name, "downward")

    @staticmethod
    def resolve_bidirectional_cascade_by_name(name: str) -> Optional[dict]:
        return ProductHierarchyRepository.resolve_parameters_schema_by_name(name, "bidirectional")

    # --- split retrieval -------------------------------------------------
    @staticmethod
    def _adaptive_schema_for_node(node: dict) -> dict:
        return ProductHierarchyRepository._resolve_band_view(node, "auto")

    @staticmethod
    def get_standards_and_essential_by_name(name: str) -> dict:
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return {"standards": [], "essential": {}}
        return {"standards": ProductHierarchyRepository._view_standards(node),
                "essential": ProductHierarchyRepository._adaptive_schema_for_node(node)["mandatoryRequirements"]}

    @staticmethod
    def get_optional_by_name(name: str) -> dict:
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return {"optional": {}}
        return {"optional": ProductHierarchyRepository._adaptive_schema_for_node(node)["optionalRequirements"]}

    @staticmethod
    def get_latest_by_name(name: str) -> dict:
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return {"latest": {}}
        return {"latest": ProductHierarchyRepository._adaptive_schema_for_node(node)["latestRequirements"]}

    @staticmethod
    def resolve_as_spec(node_uuid: str):
        node = ProductHierarchyRepository.get_node(node_uuid)
        if not node: return None
        resolved = ProductHierarchyRepository.resolve_schema(node_uuid)
        requirements = {**resolved["mandatoryRequirements"], **resolved["optionalRequirements"]}
        standards = (node.get("specifications") or {}).get("standards") or []
        name = node.get("name") or node.get("category") or node_uuid
        meta = node.get("metadata") or {}
        node_type = str(meta.get("node_type", "equipment")).lower()
        from domain.solution.schemas import InstrumentSpec, AccessorySpec
        if node_type == "equipment":
            return InstrumentSpec(name=name, requirements=requirements, standards=standards)
        return AccessorySpec(name=name, requirements=requirements, standards=standards,
                             parent_instrument_category=meta.get("category", ""))

    @staticmethod
    def find_node_by_name(name: str, levels: tuple = ("L2", "L1")):
        """Resolve a product-type name to its node, preferring the enriched L0/L1/L2
        VIEWS (where Accessory `value`/`units` are populated) over the flat
        `catalog_hierarchy`/`unified_product_hierarchy` collection, which is largely
        unenriched and only partially overlaps the views by `_id`/name. Delegates to
        `_find_band_node`, the same view-first lookup used by the cascade-resolution
        methods, so a node's `type` (Equipment/Accessory) and `specifications` are
        always read from the same source the rest of the repository trusts.
        """
        if not name: return None
        node = ProductHierarchyRepository._find_band_node(name)
        if node and node.get("level") in levels:
            return node
        # Fall back to the original flat-hierarchy-only search for levels outside
        # the L0/L1/L2 band (e.g. callers that pass L3/L4) or when _find_band_node
        # found nothing at all.
        db = get_restructured_db()[RC.HIERARCHY]
        exact = db.find_one({"level": {"$in": list(levels)}, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
        if exact: return exact
        n = " ".join(re.sub(r"[^a-z0-9\s]", " ", name.lower()).split())
        for lvl in levels:
            for d in db.find({"level": lvl}, {"name": 1, "level": 1, "parent_id": 1, "metadata": 1, "specifications": 1, "spec_requirements": 1}):
                dn = " ".join(re.sub(r"[^a-z0-9\s]", " ", str(d.get("name") or "").lower()).split())
                if dn and (n == dn or n in dn or dn in n): return d
        return None

    @staticmethod
    def resolve_generic_image_id(name: str) -> Optional[str]:
        """Resolve a product-type name to its L2 node's ``metadata.generic_image_id``.

        Generic images are attached at L2 (the level that represents one
        visually-coherent product shape — see plan generic-images-l2-plan.md).
        Callers today (frontend ``instrument.category``, LLM-assigned
        categories) send L1-style names, so this resolves via the same
        L2-before-L1 lookup used elsewhere (``find_node_by_name``) and, when
        the match lands on an L1, borrows the image from that L1's first L2
        child that has one set — this is the common case where an L1 has a
        single, identically-named L2 child with no real sub-type distinction.

        Logs which physical Restructured cluster/db was actually consulted --
        this repository's reads go through ``get_restructured_db()``, whose
        target depends on RESTRUCTURED_DB_URI (falls back to MONGODB_URI when
        unset). A silent mismatch there (code/data correct but pointed at the
        wrong cluster) is exactly what cost the most time diagnosing this
        feature, so the resolution path is logged at debug level to make that
        visible in application logs instead of requiring a manual DB probe.
        """
        if not name:
            return None

        node = ProductHierarchyRepository.find_node_by_name(name, levels=("L2", "L1"))
        if not node:
            logger.debug(f"[ProductHierarchyRepo] resolve_generic_image_id: no hierarchy node for '{name}'")
            return None

        if node.get("level") == "L2":
            image_id = (node.get("metadata") or {}).get("generic_image_id")
            logger.debug(
                f"[ProductHierarchyRepo] resolve_generic_image_id: '{name}' -> L2 node "
                f"'{node.get('name')}' ({node.get('_id')}) generic_image_id={image_id!r}"
            )
            return image_id or None

        # L1 match: borrow the first L2 child's image.
        for child in ProductHierarchyRepository._view_coll("L2").find(
            {"parent_id": node["_id"]}, {"name": 1, "metadata": 1}
        ):
            image_id = (child.get("metadata") or {}).get("generic_image_id")
            if image_id:
                logger.debug(
                    f"[ProductHierarchyRepo] resolve_generic_image_id: '{name}' -> L1 node "
                    f"'{node.get('name')}' ({node.get('_id')}) borrowed from L2 child "
                    f"'{child.get('name')}' generic_image_id={image_id!r}"
                )
                return image_id

        logger.debug(
            f"[ProductHierarchyRepo] resolve_generic_image_id: '{name}' -> L1 node "
            f"'{node.get('name')}' ({node.get('_id')}) has no L2 child with an image attached"
        )
        return None

    @staticmethod
    def resolve_standards(node_uuid: str) -> list:
        """Cascade-resolve applicable standards for a node across L0/L1/L2.

        Uses the same directional band cascade as parameter schema resolution so that
        standards are collected from every relevant tier (L0 category, L1 product type,
        and L2 subtypes) instead of only the ancestor path.

        The current 5-tier grouped specs store standards inside the ``certifications``
        group (extracted by ``_view_standards``).  The legacy ``specifications.schema.
        standards`` path is kept as a fallback for older hierarchy data.
        """
        node = ProductHierarchyRepository.get_node(node_uuid)
        if not node:
            return []
        direction = ProductHierarchyRepository._direction_for_level(node.get("level"))
        out = set()
        for nd in [node, *ProductHierarchyRepository._view_related(node, direction)]:
            out.update(ProductHierarchyRepository._view_standards(nd))
            out.update(((nd.get("specifications") or {}).get("schema") or {}).get("standards") or [])
        return sorted(out)

    @staticmethod
    def resolve_standards_by_name(name: str) -> list:
        """Resolve standards by product-type name, searching L0/L1/L2 views and the flat
        ``catalog_hierarchy`` collection so category-level (L0) standards are also found."""
        node = ProductHierarchyRepository._find_band_node(name)
        if not node: return []
        # Use the view-based cascade directly — resolve_standards() re-fetches from
        # catalog_hierarchy by _id, but view node IDs may diverge from that space.
        direction = ProductHierarchyRepository._direction_for_level(node.get("level"))
        out = set()
        for nd in [node, *ProductHierarchyRepository._view_related(node, direction)]:
            out.update(ProductHierarchyRepository._view_standards(nd))
            out.update(((nd.get("specifications") or {}).get("schema") or {}).get("standards") or [])
        return sorted(out)

    @staticmethod
    def get_l3_spec_doc_url(name: str) -> Optional[str]:
        """Return a datasheet/spec-doc URL for the matched product category.

        Mirrors get_vendor_products_by_name's proven L2->L3->L4 traversal (the
        dedicated RC.L3/RC.L4 collections, not the generic level-tagged
        HIERARCHY collection) since that is where these fields are actually
        populated in practice: L4.datasheet_url (per-vendor-product PDF) is
        checked first, falling back to L3.spec_doc_url (model-family PDF).
        A prior version queried HIERARCHY for a "level" field and only ever
        checked L3.spec_doc_url, which is empty in this DB — it never found a
        URL even though L4.datasheet_url is populated on 100% of matching
        products (confirmed via get_vendor_products_by_name for the same
        category).
        """
        node = ProductHierarchyRepository._find_band_node(name)
        if not node:
            return None

        db = get_restructured_db()

        # Broaden narrow L2 matches to their L1 ancestor + sibling L2 nodes,
        # same rationale as get_vendor_products_by_name: a narrow L2 subtype
        # can have zero or one L3 family, starving the search for a URL that
        # exists under a sibling subtype of the same product line.
        band_ids = {node["_id"]}
        if node.get("level") == "L2":
            parent_l1_id = node.get("parent_id")
            if parent_l1_id:
                band_ids.add(parent_l1_id)
                for sib in ProductHierarchyRepository._view_coll("L2").find(
                    {"parent_id": parent_l1_id}, {"_id": 1}
                ):
                    band_ids.add(sib["_id"])

        l3_docs = list(db[RC.L3].find(
            {"parent_id": {"$in": list(band_ids)}}, {"_id": 1, "spec_doc_url": 1}
        ))
        if not l3_docs:
            return None
        l3_by_id = {d["_id"]: d for d in l3_docs}

        l4_docs = list(db[RC.L4].find(
            {"parent_id": {"$in": list(l3_by_id.keys())}}, {"parent_id": 1, "datasheet_url": 1}
        ))
        for l4 in l4_docs:
            url = l4.get("datasheet_url")
            if url:
                return url

        for l3 in l3_docs:
            url = l3.get("spec_doc_url")
            if url:
                return url
        return None

    @staticmethod
    def get_vendor_products_by_name(name: str) -> list[dict]:
        """Walk L2 band node → L3 children → L4 grandchildren and return all vendor
        products as a flat list ready for the vendor analysis agent.

        Each item has the shape the vendor analysis agent expects:
            {vendor, model_number, model_family, product_type, datasheet_url}

        Traversal path (uses the L3/L4 collections directly — faster than the flat
        catalog_hierarchy which has no `level` field on L3/L4 nodes):
          1. _find_band_node → L0/L1/L2 match (e.g. "Pressure Transmitter" → L2 node)
             When the match is a narrow L2 subtype, the L1 ancestor and its sibling
             L2 subtypes are added so the full category vendor pool is gathered.
          2. L3 collection: find all docs where parent_id IN {band node ids}
          3. L4 collection: find all docs where parent_id IN {L3 _ids}

        Returns [] if the band node is not found or has no L4 descendants.
        """
        node = ProductHierarchyRepository._find_band_node(name)
        if not node:
            return []

        db = get_restructured_db()

        # Determine the set of parent ids to gather L3 families under.
        #
        # A generic product-type name (e.g. "Flow Meter") can match a *narrow*
        # L2 subtype whose only L3 family belongs to a single vendor. Restricting
        # retrieval to that one L2 node starves the vendor pool (observed: "Flow
        # Meter" → 1 KROHNE family only, so a user requesting other vendors got 0
        # products). When the matched node is an L2 subtype, broaden the search to
        # the L1 ancestor and *all* of its L2 children so sibling subtypes (and
        # their vendors) are included for the category-level query.
        band_ids = {node["_id"]}
        if node.get("level") == "L2":
            parent_l1_id = node.get("parent_id")
            if parent_l1_id:
                band_ids.add(parent_l1_id)
                for sib in ProductHierarchyRepository._view_coll("L2").find(
                    {"parent_id": parent_l1_id}, {"_id": 1}
                ):
                    band_ids.add(sib["_id"])

        # Step 2: all L3 nodes whose parent is any of the band ids
        l3_docs = list(db[RC.L3].find({"parent_id": {"$in": list(band_ids)}}, {
            "_id": 1, "oem": 1, "model_series": 1, "spec_doc_url": 1
        }))
        if not l3_docs:
            return []

        l3_ids = [d["_id"] for d in l3_docs]
        # Build a lookup: L3 _id → {oem, model_series, spec_doc_url}
        l3_by_id = {d["_id"]: d for d in l3_docs}

        # Step 3: all L4 nodes whose parent is one of the L3 nodes
        l4_docs = list(db[RC.L4].find({"parent_id": {"$in": l3_ids}}, {
            "_id": 1, "vendor": 1, "model_number": 1, "name": 1,
            "datasheet_url": 1, "parent_id": 1
        }))

        products = []
        for l4 in l4_docs:
            l3 = l3_by_id.get(l4.get("parent_id"), {})
            vendor = l4.get("vendor") or l3.get("oem") or ""
            model_number = l4.get("model_number") or ""
            model_family = l3.get("model_series") or ""
            # L4.datasheet_url is the per-product PDF; fall back to L3.spec_doc_url
            datasheet_url = l4.get("datasheet_url") or l3.get("spec_doc_url") or ""
            if not vendor:
                continue
            products.append({
                "vendor": vendor,
                "vendor_name": vendor,
                "model_number": model_number,
                "model_family": model_family,
                "product_type": name,
                "datasheet_url": datasheet_url,
            })

        logger.info(
            "[ProductHierarchyRepo] get_vendor_products_by_name('%s'): "
            "%d L3 families → %d L4 products",
            name, len(l3_docs), len(products),
        )
        return products

    @staticmethod
    def resolve_spec_by_name(name: str):
        node = ProductHierarchyRepository.find_node_by_name(name)
        return ProductHierarchyRepository.resolve_as_spec(node["_id"]) if node else None

    @staticmethod
    def standards_for(node_uuid: str) -> dict:
        db = get_restructured_db()
        required = {c: d for c, d in ProductHierarchyRepository.resolve_demands(node_uuid).items()
                    if db[RC.SPEC_DEFINITION].count_documents({"spec_code": c, "is_standard": True})}
        fulfilled = {ns["spec_code"]: ns["value"] for ns in db[RC.NODE_SPEC].find(
            {"source_node_id": node_uuid, "is_standard": True, "value": {"$ne": None}})}
        return {"required": required, "fulfilled": fulfilled}

    @staticmethod
    def get_standards_for_category(user_id: int | None = None, category: str = "") -> dict:
        """Retrieve standards for a category from the 5-tier product hierarchy database.

        Traverses L0..L2 hierarchy nodes and resolves standard certifications (e.g. API, IEC, ATEX)
        and associated engineering specifications.
        """
        if not category:
            return {"found": False, "category": "", "specifications": {}, "applicable_standards": []}

        stds = ProductHierarchyRepository.resolve_standard_specifications_by_name(category) or {}
        if not stds:
            node = ProductHierarchyRepository._find_band_node(category)
            if node:
                stds = ProductHierarchyRepository._view_standard_details(node) or {}

        if not stds:
            return {
                "found": False,
                "category": category,
                "specifications": {},
                "applicable_standards": [],
                "requirements_summary": f"No specific standards defined for '{category}' in catalog.",
                "source_document": "5-Tier Product Hierarchy Database"
            }

        titles = ProductHierarchyRepository.get_standards_titles(category) or {}
        return {
            "found": True,
            "category": category,
            "category_match": category,
            "_is_tier_standards": True,
            "specifications": stds,
            "applicable_standards": list(stds.keys()),
            "standard_titles": titles,
            "requirements_summary": f"Standards resolved for '{category}' from 5-tier product hierarchy database.",
            "source_document": "5-Tier Product Hierarchy Database"
        }

    @staticmethod
    def get_complete_specifications(category: str, user_id: int | None = None) -> dict:
        """Unified specification resolver: merges 5-tier catalog technical specs
        and catalog standards into a single comprehensive payload.

        Returns:
            {
                "category": category,
                "catalog_technical_specifications": {
                    "mandatoryRequirements": {...},
                    "optionalRequirements": {...},
                    "latestRequirements": {...}
                },
                "catalog_standards": {"API 670": "Compliant", ...},
                "standards_info": {"found": bool, "specifications": {...}, ...},
                "merged_specifications": {...}
            }
        """
        # 1. 5-tier catalog technical specifications
        catalog_schema = ProductHierarchyRepository.resolve_parameters_schema_by_name(category) or {
            "mandatoryRequirements": {},
            "optionalRequirements": {},
            "latestRequirements": {}
        }

        # 2. 5-tier catalog standards
        catalog_stds = ProductHierarchyRepository.resolve_standard_specifications_by_name(category) or {}

        # 3. Standards summary
        standards_info = ProductHierarchyRepository.get_standards_for_category(user_id=user_id, category=category)

        # 4. Synthesize merged specifications
        merged: dict = {}
        # Start with catalog optional and mandatory
        merged.update(catalog_schema.get("optionalRequirements") or {})
        merged.update(catalog_schema.get("mandatoryRequirements") or {})

        # Add catalog standards tagged with [STANDARD]
        for std_code, std_val in catalog_stds.items():
            if std_code not in merged:
                val_str = str(std_val).strip() if std_val else std_code
                if "[STANDARD]" not in val_str:
                    val_str = f"{val_str} [STANDARD]"
                merged[std_code] = val_str

        return {
            "category": category,
            "catalog_technical_specifications": catalog_schema,
            "catalog_standards": catalog_stds,
            "standards_info": standards_info,
            "merged_specifications": merged,
        }

    # ------------------------------------------------------------- maintenance
    @staticmethod
    def ensure_indexes() -> None:
        ensure_restructured_indexes()

    @staticmethod
    def sync_level_views() -> dict[str, int]:
        db, counts = get_restructured_db(), {}
        for lv in RC.LEVELS: db[lv].delete_many({})
        for node in db[RC.HIERARCHY].find({}):
            ProductHierarchyRepository._mirror_to_view(node["level"], node)
        for lv in RC.LEVELS: counts[lv] = db[lv].count_documents({})
        logger.info("[ProductHierarchyRepo] synced level views: %s", counts)
        return counts
