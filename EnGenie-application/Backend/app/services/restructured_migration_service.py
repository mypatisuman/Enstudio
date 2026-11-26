"""
Restructured DB Migration Service
==================================
Migrates all documents in the `Restructured` database so that:

  L0 / L1 / L2  — specifications field → SchemaSpec shape
                   {id, safety:[SpecParameter], electrical:[SpecParameter],
                    mechanical, process, environmental, performance,
                    certifications, other}

  L3 / L4        — device block normalised to
                   {id, oem, model_series, model_number, specs_doc_id,
                    spec_doc_url, parent_id, key}

The migration is IDEMPOTENT: running it on an already-migrated DB is a no-op.
Each document is processed individually so a single failure never blocks the rest.

Usage (run from Backend/):
    python -m app.services.restructured_migration_service
    python -m app.services.restructured_migration_service --apply   # write changes
"""

import argparse
import logging
import uuid
from typing import Any

from common.infra.mongodb_config import RestructuredCollections as RC, get_restructured_db
from domain.solution.agents.harness_agent import (
    SPEC_CATEGORIES,
    SCHEMA_LEVELS,
    SchemaSpec,
    SpecParameter,
    FamilySpec,
    stable_node_uuid,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPEC_CATEGORIES = list(SPEC_CATEGORIES)


def _new_param_id(node_id: str, category: str, index: int) -> str:
    """Deterministic param id so re-runs produce the same IDs."""
    return f"PARAM-{stable_node_uuid(f'{node_id}:{category}:{index}')[:8].upper()}"


def _coerce_parameter(raw: Any, node_id: str, category: str, index: int) -> dict | None:
    """Convert any legacy parameter shape to a SpecParameter dict.

    Accepts:
      - already-correct dict {id, name, value, level, units}
      - old tuple/list [name, value]
      - flat string  "param_name=value"
      - {key: value, level: ...} flat k/v pair from the old grouped format
    """
    if raw is None:
        return None

    if isinstance(raw, SpecParameter):
        return raw.model_dump(exclude_none=True)

    if isinstance(raw, dict):
        # Already in the new shape — validate and return.
        if "name" in raw and "id" in raw and "level" in raw:
            level = raw.get("level", "Optional")
            if level not in ("Required", "Optional", "Advanced"):
                level = "Optional"
            return {
                "id": raw["id"],
                "name": raw["name"],
                "value": raw.get("value"),
                "level": level,
                "units": raw.get("units"),
            }
        # Legacy {field_name: field_value} pairs (from old grouped essential/optional/latest dicts)
        # Skip meta-keys
        skip = {"id", "units", "level", "parameters", "description"}
        entries = [(k, v) for k, v in raw.items() if k not in skip and isinstance(v, (str, int, float))]
        if not entries:
            return None
        name, value = entries[0]
        inferred_level = _infer_level_from_tier(raw)
        return {
            "id": _new_param_id(node_id, category, index),
            "name": name,
            "value": str(value) if value is not None else None,
            "level": inferred_level,
            "units": raw.get("units"),
        }

    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return {
            "id": _new_param_id(node_id, category, index),
            "name": str(raw[0]),
            "value": str(raw[1]) if raw[1] is not None else None,
            "level": "Optional",
            "units": None,
        }

    if isinstance(raw, str) and "=" in raw:
        name, _, value = raw.partition("=")
        return {
            "id": _new_param_id(node_id, category, index),
            "name": name.strip(),
            "value": value.strip() or None,
            "level": "Optional",
            "units": None,
        }

    return None


def _infer_level_from_tier(raw: dict) -> str:
    """Guess Required/Optional/Advanced from legacy tier context clues."""
    t = str(raw.get("_tier", raw.get("tier", "optional"))).lower()
    if t in ("essential", "required", "mandatory"):
        return "Required"
    if t in ("latest", "advanced"):
        return "Advanced"
    return "Optional"


def _flatten_legacy_grouped(spec: dict, node_id: str) -> dict[str, list[dict]]:
    """Convert old grouped format {<group>: {parameters: {essential, optional, latest}}}
    into the new {<category>: [SpecParameter]} bucketed shape.
    """
    buckets: dict[str, list[dict]] = {cat: [] for cat in _SPEC_CATEGORIES}
    idx = 0

    for group, blk in (spec or {}).items():
        if group == "units" or not isinstance(blk, dict):
            continue
        params = blk.get("parameters")
        if not isinstance(params, dict):
            # The whole blk might already be a list (partially migrated)
            if isinstance(blk, list):
                cat = group if group in _SPEC_CATEGORIES else "other"
                for item in blk:
                    p = _coerce_parameter(item, node_id, cat, idx)
                    if p:
                        buckets[cat].append(p)
                        idx += 1
            continue

        # Map old tier names to SpecParameter.level
        tier_level = {"essential": "Required", "optional": "Optional", "latest": "Advanced"}
        for tier, level in tier_level.items():
            tier_data = params.get(tier) or {}
            if not isinstance(tier_data, dict):
                continue
            for field_name, field_value in tier_data.items():
                # Guess which category bucket this field belongs in
                cat = _guess_category(group, field_name)
                p = {
                    "id": _new_param_id(node_id, cat, idx),
                    "name": field_name,
                    "value": str(field_value) if field_value is not None else None,
                    "level": level,
                    "units": (spec.get("units") or {}).get(field_name),
                }
                buckets[cat].append(p)
                idx += 1

    return buckets


def _guess_category(group: str, field_name: str) -> str:
    """Map a legacy group name / field to the nearest SchemaSpec category."""
    g = group.lower()
    f = field_name.lower()
    if g in _SPEC_CATEGORIES:
        return g
    # Heuristic keyword matching
    if any(k in g or k in f for k in ("safe", "hazard", "protection", "atex", "iec")):
        return "safety"
    if any(k in g or k in f for k in ("volt", "amp", "watt", "hz", "power", "signal", "output", "input", "loop", "electric")):
        return "electrical"
    if any(k in g or k in f for k in ("weight", "dimension", "size", "material", "housing", "mount", "ip")):
        return "mechanical"
    if any(k in g or k in f for k in ("pressure", "temperature", "flow", "level", "process", "medium", "fluid")):
        return "process"
    if any(k in g or k in f for k in ("ambient", "environment", "humidity", "weather", "outdoor", "ingress")):
        return "environmental"
    if any(k in g or k in f for k in ("accuracy", "range", "resolution", "repeatab", "performance", "drift", "response")):
        return "performance"
    if any(k in g or k in f for k in ("certif", "approv", "standard", "comply", "csa", "ul", "fm", "atex")):
        return "certifications"
    return "other"


def _build_schema_spec(node_id: str, old_spec: dict) -> dict:
    """Convert any legacy specifications dict to the new SchemaSpec shape."""
    # Already in the new shape — just ensure `id` is present.
    is_new = isinstance(old_spec, dict) and any(
        isinstance(old_spec.get(cat), list) for cat in _SPEC_CATEGORIES
    )
    if is_new:
        result = dict(old_spec)
        if not result.get("id"):
            result["id"] = f"SPEC-{stable_node_uuid(node_id)[:12].upper()}"
        return result

    # Old grouped shape → new
    is_grouped = isinstance(old_spec, dict) and any(
        isinstance(v, dict) and isinstance(v.get("parameters"), dict)
        for v in old_spec.values()
    )
    if is_grouped:
        buckets = _flatten_legacy_grouped(old_spec, node_id)
    else:
        # Unknown / empty — start with empty buckets
        buckets = {cat: [] for cat in _SPEC_CATEGORIES}

    return {
        "id": f"SPEC-{stable_node_uuid(node_id)[:12].upper()}",
        **{cat: buckets.get(cat, []) for cat in _SPEC_CATEGORIES},
    }


def _build_device_block(doc: dict) -> dict:
    """Build / normalise the device identity block for L3/L4 nodes."""
    existing = doc.get("device") or {}
    meta = doc.get("metadata") or {}
    parent_dev: dict = {}
    if doc.get("level") == "L4" and doc.get("parent_id"):
        try:
            par = get_restructured_db()[RC.HIERARCHY].find_one(
                {"_id": doc["parent_id"]}, {"device": 1}
            )
            parent_dev = (par or {}).get("device") or {}
        except Exception:
            pass

    return {
        "id": existing.get("id") or doc.get("_id"),
        "oem": existing.get("oem") or doc.get("manufacturer") or doc.get("vendor"),
        "model_series": (
            existing.get("model_series")
            or parent_dev.get("model_series")
            or doc.get("name")
        ),
        "model_number": (
            existing.get("model_number")
            or doc.get("model_number")
            or meta.get("model_number")
            or (doc.get("name") if doc.get("level") == "L4" else None)
        ),
        "specs_doc_id": (
            existing.get("specs_doc_id")
            or existing.get("specs_Doc_Id")
            or parent_dev.get("specs_Doc_Id")
            or meta.get("specs_Doc_Id")
        ),
        "spec_doc_url": (
            existing.get("spec_doc_url")
            or parent_dev.get("spec_doc_url")
            or doc.get("spec_doc_url")
        ),
        "parent_id": doc.get("parent_id"),
        "key": doc.get("key"),
    }


# ---------------------------------------------------------------------------
# Per-document migration
# ---------------------------------------------------------------------------

def _migrate_document(doc: dict, apply: bool, db) -> tuple[bool, str]:
    """Migrate a single flat-hierarchy document.

    Returns (changed: bool, reason: str).
    """
    node_id = doc.get("_id", "")
    level = doc.get("level", "")

    update: dict[str, Any] = {}

    if level in SCHEMA_LEVELS:
        old_spec = doc.get("specifications") or {}
        new_spec = _build_schema_spec(node_id, old_spec)
        # Only update if something actually changed
        if new_spec != old_spec:
            update["specifications"] = new_spec

    elif level in ("L3", "L4"):
        new_device = _build_device_block(doc)
        old_device = doc.get("device") or {}
        if new_device != old_device:
            update["device"] = new_device

    if not update:
        return False, "no-change"

    if apply:
        try:
            db[RC.HIERARCHY].update_one({"_id": node_id}, {"$set": update})
            # Mirror to the relational view
            view_coll = {"L0": RC.L0, "L1": RC.L1, "L2": RC.L2,
                         "L3": RC.L3, "L4": RC.L4}.get(level)
            if view_coll:
                db[view_coll].update_one({"_id": node_id}, {"$set": update}, upsert=False)
        except Exception as exc:
            logger.error("[restructured_migration] Failed to update %s (%s): %s", node_id, level, exc)
            return False, f"error: {exc}"

    return True, "migrated"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_restructured_migration(apply: bool = False) -> dict:
    """Run the full migration.  Returns summary counts."""
    db = get_restructured_db()
    total = changed = errors = 0
    level_counts: dict[str, int] = {}

    logger.info("[restructured_migration] Starting (apply=%s)", apply)

    for doc in db[RC.HIERARCHY].find({}):
        total += 1
        level = doc.get("level", "?")
        try:
            did_change, reason = _migrate_document(doc, apply, db)
            if did_change:
                changed += 1
                level_counts[level] = level_counts.get(level, 0) + 1
                logger.debug("[restructured_migration] %s %s -> %s", level, doc.get("_id"), reason)
        except Exception as exc:
            errors += 1
            logger.error("[restructured_migration] Unhandled error on %s: %s", doc.get("_id"), exc)

    summary = {
        "apply": apply,
        "total_documents": total,
        "changed": changed,
        "errors": errors,
        "changed_by_level": level_counts,
    }
    logger.info("[restructured_migration] Done: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Migrate Restructured DB to new SchemaSpec shape")
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes (default is dry-run)"
    )
    args = parser.parse_args()
    result = run_restructured_migration(apply=args.apply)
    print("\nMigration summary:")
    for k, v in result.items():
        print(f"  {k}: {v}")
