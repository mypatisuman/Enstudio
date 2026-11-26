"""
Schema field matching and tier-aware value assignment for search enrichment.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_EMPTY_VALUES = {"", "not specified", "not requested", "none specified", "n/a", "na", ","}


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _EMPTY_VALUES
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False

_ASSIGN_THRESHOLD = 0.72
_REASSIGN_MARGIN = 0.18

# Normalized alias groups (union-find style sets as frozensets)
_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"turndownratio", "turndown", "spandown", "turnratio", "ratioturndown"}),
    frozenset({"ingressprotection", "iprating", "ip", "enclosurerating", "nema", "ipratingclass"}),
    frozenset({"wettedmaterial", "diaphragmmaterial", "processwettedmaterial", "materialwetted", "wettedparts"}),
    frozenset({"communicationprotocol", "fieldbus", "outputprotocol", "protocoltype", "bussprotocol"}),
    frozenset({"measurementprinciple", "measuringprinciple", "sensortype", "technology", "instrumenttype"}),
    frozenset({"processconnection", "connectionsize", "threadsize", "endconnection", "processfitting"}),
    frozenset({"measuringrange", "calibratedrange", "span", "range", "spans", "measurementrange"}),
    frozenset({"processtemperature", "ambienttemperature", "temperature", "temperaturelimits", "ambienttemperaturerange"}),
    frozenset({"processpressure", "operatingpressure", "pressure", "workingpressure", "pressurerange"}),
    frozenset({"areaclassification", "hazardousarearating", "explosionproof", "explosionproofrating", "zoneclassification"}),
    frozenset({"accuracy", "accuracyclass", "setpointaccuracy", "measurementaccuracy"}),
    frozenset({"responsetime", "responsetimeconstant", "damping"}),
    frozenset({"housingmaterial", "bodymaterial", "enclosurematerial", "casematerial"}),
    frozenset({"antennatype", "probetype", "sensorstyle"}),
    frozenset({"flowrange", "flowrate", "flowcapacity"}),
    frozenset({"outputsignal", "outputsignaltype", "transmitteroutput"}),
)


_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_LOCK = threading.Lock()
_EMBEDDING_CACHE_ACCESS: dict[str, float] = {}  # key -> last-access epoch seconds
_EMBEDDING_CACHE_MAX_ENTRIES = int(os.environ.get("EMBEDDING_CACHE_MAX_ENTRIES", "5000"))
_EMBEDDING_CACHE_IDLE_TTL_SECONDS = int(os.environ.get("EMBEDDING_CACHE_IDLE_TTL_SECONDS", str(24 * 3600)))


def _split_camel_case(s: str) -> str:
    """Split camelCase or PascalCase into space-separated words."""
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(s))
    return cleaned.replace("_", " ").strip().lower()


def _get_cached_embedding(text: str) -> list[float] | None:
    """Lazy-load embedding generation with local caching."""
    if not text:
        return None
    cleaned = _split_camel_case(text)
    with _EMBEDDING_CACHE_LOCK:
        if cleaned in _EMBEDDING_CACHE:
            _EMBEDDING_CACHE_ACCESS[cleaned] = time.time()
            return _EMBEDDING_CACHE[cleaned]

    try:
        from common.ai.embedding_manager import generate_embedding

        emb = generate_embedding(cleaned)
        if emb:
            with _EMBEDDING_CACHE_LOCK:
                _EMBEDDING_CACHE[cleaned] = emb
                _EMBEDDING_CACHE_ACCESS[cleaned] = time.time()
            return emb
    except Exception as exc:
        logger.debug("[SCHEMA_FIELD_MATCHING] Failed to generate embedding for '%s': %s", cleaned, exc)
    return None


def evict_stale_embedding_cache() -> int:
    """Evict idle-expired entries first; if still over the cap, evict the
    oldest-accessed entries until back under _EMBEDDING_CACHE_MAX_ENTRIES.
    Returns count evicted. Called from the periodic memory sweep
    (common/ai/memory/maintenance.py) — this cache is not session-scoped
    (keyed by normalized field name), so it's managed independently of the
    session-eviction callback registry.
    """
    now = time.time()
    evicted = 0
    with _EMBEDDING_CACHE_LOCK:
        stale = [k for k, t in _EMBEDDING_CACHE_ACCESS.items() if now - t > _EMBEDDING_CACHE_IDLE_TTL_SECONDS]
        for k in stale:
            _EMBEDDING_CACHE.pop(k, None)
            _EMBEDDING_CACHE_ACCESS.pop(k, None)
            evicted += 1

        if len(_EMBEDDING_CACHE) > _EMBEDDING_CACHE_MAX_ENTRIES:
            overflow = len(_EMBEDDING_CACHE) - _EMBEDDING_CACHE_MAX_ENTRIES
            oldest = sorted(_EMBEDDING_CACHE_ACCESS.items(), key=lambda kv: kv[1])[:overflow]
            for k, _ in oldest:
                _EMBEDDING_CACHE.pop(k, None)
                _EMBEDDING_CACHE_ACCESS.pop(k, None)
                evicted += 1

    if evicted:
        logger.info(f"[SCHEMA_FIELD_MATCHING] Evicted {evicted} stale/overflow embedding cache entries")
    return evicted


def normalize_field_name(name: str) -> str:
    from domain.search.agents.validation_agent import _normalize_field_name as fuzzy_normalize
    return fuzzy_normalize(name)


def normalize_value(value: Any) -> str:
    return re.sub(r"\s+", "", str(value).replace(" (STANDARD)", "").strip().lower())


def field_match_score(schema_key: str, provided_key: str) -> float:
    """
    Score how well an extracted key matches a schema field name (0.0–1.0).
    Combines exact/synonym keyword mapping and semantic context mapping.
    """
    sn = normalize_field_name(schema_key)
    pn = normalize_field_name(provided_key)
    if not sn or not pn:
        return 0.0
    if sn == pn:
        return 1.0

    # 1. Exact Synonym Group Match
    keyword_score = 0.0
    for group in _SYNONYM_GROUPS:
        if sn in group and pn in group:
            keyword_score = 0.95
            break

    # 2. Semantic context similarity
    semantic_score = 0.0
    try:
        emb_s = _get_cached_embedding(schema_key)
        emb_p = _get_cached_embedding(provided_key)
        if emb_s and emb_p:
            from common.ai.embedding_manager import cosine_similarity

            # cosine_similarity normalizes cosine output to [0.0, 1.0]
            sim = cosine_similarity(emb_s, emb_p)
            
            # Apply thresholding: if similarity is too low, we ignore it to prevent false associations
            # 0.80 in cosine_similarity maps to raw similarity of 0.60, which is a sensible threshold
            if sim >= 0.80:
                semantic_score = sim
    except Exception as exc:
        logger.debug("[SCHEMA_FIELD_MATCHING] Semantic similarity calculation failed: %s", exc)

    return max(keyword_score, semantic_score)


def fuzzy_field_name_match(schema_key: str, provided_key: str) -> bool:
    return field_match_score(schema_key, provided_key) >= _ASSIGN_THRESHOLD


def resolve_provided_value_for_schema_field(
    schema_key: str,
    provided: dict[str, Any],
) -> Any | None:
    if not provided:
        return None
    best_val = None
    best_score = 0.0
    for pk, pv in provided.items():
        if is_empty_value(pv):
            continue
        score = field_match_score(schema_key, pk)
        if score > best_score:
            best_score = score
            best_val = pv
    return best_val if best_score >= _ASSIGN_THRESHOLD else None


@dataclass(frozen=True)
class SchemaLeaf:
    tier: str
    path: tuple[str, ...]
    field_key: str


def iter_schema_leaves(schema: dict[str, Any]) -> Iterator[SchemaLeaf]:
    for tier in (
        "mandatoryRequirements",
        "optionalRequirements",
        "latestRequirements",
        "advancedRequirements",
    ):
        tier_node = schema.get(tier) or {}
        if not isinstance(tier_node, dict):
            continue

        def _walk(node: dict, path: tuple[str, ...]):
            for key, val in node.items():
                if isinstance(val, dict):
                    yield from _walk(val, path + (key,))
                else:
                    yield SchemaLeaf(tier=tier, path=path + (key,), field_key=key)

        yield from _walk(tier_node, ())


def _ensure_path(node: dict, path: tuple[str, ...]) -> dict:
    cur = node
    for part in path[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    return cur


def _get_leaf(mapped: dict, leaf: SchemaLeaf) -> Any:
    tier = mapped.get(leaf.tier) or {}
    cur: Any = tier
    for part in leaf.path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_leaf(mapped: dict, leaf: SchemaLeaf, value: Any) -> None:
    mapped.setdefault(leaf.tier, {})
    if not isinstance(mapped[leaf.tier], dict):
        mapped[leaf.tier] = {}
    parent = _ensure_path(mapped[leaf.tier], leaf.path)
    parent[leaf.path[-1]] = value


def _clear_leaf(mapped: dict, leaf: SchemaLeaf) -> None:
    parent_path = leaf.path[:-1]
    tier = mapped.get(leaf.tier) or {}
    cur = tier
    for part in parent_path:
        if not isinstance(cur, dict):
            return
        cur = cur.get(part)
    if isinstance(cur, dict) and leaf.path[-1] in cur:
        cur[leaf.path[-1]] = ""


def _best_leaf_for_provided_key(
    schema: dict[str, Any],
    provided_key: str,
) -> tuple[SchemaLeaf | None, float]:
    best_leaf: SchemaLeaf | None = None
    best_score = 0.0
    for leaf in iter_schema_leaves(schema):
        score = field_match_score(leaf.field_key, provided_key)
        if score > best_score:
            best_score = score
            best_leaf = leaf
    return best_leaf, best_score


def _best_provided_key_for_value(
    provided: dict[str, Any],
    value: Any,
) -> tuple[str | None, float]:
    nv = normalize_value(value)
    if not nv:
        return None, 0.0
    for pk, pv in provided.items():
        if normalize_value(pv) == nv:
            return pk, 1.0
    return None, 0.0


def assign_provided_to_schema_catalog(
    mapped: dict[str, Any],
    schema: dict[str, Any],
    provided: dict[str, Any],
) -> None:
    """
    Tier-aware assignment: map each extracted key to the best matching schema
    leaf across mandatory / optional / advanced tiers.
    """
    if not provided or not schema:
        return

    assignments: list[tuple[SchemaLeaf, str, str, float]] = []

    for pk, pv in provided.items():
        if is_empty_value(pv):
            continue
        leaf, score = _best_leaf_for_provided_key(schema, pk)
        if leaf and score >= _ASSIGN_THRESHOLD:
            assignments.append((leaf, pk, str(pv).strip(), score))

    assignments.sort(key=lambda x: x[3], reverse=True)
    claimed_values: set[str] = set()

    for leaf, pk, pv, score in assignments:
        nv = normalize_value(pv)
        current = _get_leaf(mapped, leaf)
        current_score = 0.0
        if not is_empty_value(current):
            cpk, _ = _best_provided_key_for_value(provided, current)
            if cpk:
                current_score = field_match_score(leaf.field_key, cpk)
            if current_score >= score and normalize_value(current) == nv:
                continue
            if current_score >= score + _REASSIGN_MARGIN and normalize_value(current) != nv:
                continue

        if nv in claimed_values and score < 0.95:
            continue

        _set_leaf(mapped, leaf, pv)
        claimed_values.add(nv)


def _iter_empty_schema_leaves(
    schema: dict[str, Any],
    mapped: dict[str, Any],
) -> list[SchemaLeaf]:
    empty: list[SchemaLeaf] = []
    for leaf in iter_schema_leaves(schema):
        if is_empty_value(_get_leaf(mapped, leaf)):
            empty.append(leaf)
    return empty


def resolve_value_only_update(
    user_input: str,
    detected_schema: dict[str, Any],
    mapped_requirements: dict[str, Any],
    provided_requirements: dict[str, Any] | None = None,
    missing_mandatory: list[str] | None = None,
    missing_optional: list[str] | None = None,
) -> tuple[dict[str, str], bool]:
    """
    Parse simple chat edits into flat provided_requirements updates.
    Returns (updates, needs_clarification).
    """
    text = (user_input or "").strip()
    if not text or not detected_schema:
        return {}, False

    updates: dict[str, str] = {}
    lower = text.lower()

    remove_match = re.match(
        r"^(?:remove|delete|clear|drop)\s+(?:the\s+)?(.+)$",
        text,
        re.I,
    )
    if remove_match:
        field_hint = remove_match.group(1).strip()
        for leaf in iter_schema_leaves(detected_schema):
            if field_match_score(leaf.field_key, field_hint) >= _ASSIGN_THRESHOLD:
                updates[field_hint.replace(" ", "_").lower()] = ""
                return updates, False
        return {}, False

    change_match = re.match(
        r"^(?:change|set|update|make)\s+(.+?)\s+(?:to|=)\s+(.+)$",
        text,
        re.I,
    )
    if change_match:
        field_hint = change_match.group(1).strip()
        value = change_match.group(2).strip()
        # Both outcomes of the original score check assigned the same key, so the
        # schema-matching loop's result was unused — key is always derived from field_hint.
        updates[field_hint.replace(" ", "_").lower()] = value
        return updates, False

    kv_match = re.match(r"^(.+?)[:=]\s*(.+)$", text)
    if kv_match:
        key_hint = kv_match.group(1).strip()
        value = kv_match.group(2).strip()
        updates[key_hint.replace(" ", "_").lower()] = value
        return updates, False

    if re.search(r"\s", text) and len(text) > 40:
        return {}, False

    # Natural-language spec lists: "accuracy 3mm, IP67, 4-20mA"
    segments = [s.strip() for s in re.split(r"[,;]\s*|\s+and\s+", text) if s.strip()]
    if len(segments) >= 2:
        for segment in segments:
            seg_kv = re.match(r"^(.+?)[:=]\s*(.+)$", segment)
            if seg_kv:
                updates[seg_kv.group(1).strip().replace(" ", "_").lower()] = seg_kv.group(2).strip()
                continue
            seg_change = re.match(r"^(.+?)\s+(.+)$", segment)
            if seg_change:
                field_hint = seg_change.group(1).strip()
                value = seg_change.group(2).strip()
                _leaf, best_score = _best_leaf_for_provided_key(detected_schema, field_hint)
                if best_score >= _ASSIGN_THRESHOLD:
                    updates[field_hint.replace(" ", "_").lower()] = value
        if updates:
            return updates, False

    empty_leaves = _iter_empty_schema_leaves(detected_schema, mapped_requirements)
    if len(empty_leaves) == 1:
        leaf = empty_leaves[0]
        updates[leaf.field_key.replace(" ", "_").lower()] = text
        return updates, False

    candidate_keys = list(missing_mandatory or []) + list(missing_optional or [])
    if len(candidate_keys) == 1:
        updates[candidate_keys[0].replace(" ", "_").lower()] = text
        return updates, False

    if len(text.split()) <= 4 and not re.search(r"[=:]", text):
        return {}, True

    return {}, False


def reassign_misplaced_mapped_values(
    mapped: dict[str, Any],
    schema: dict[str, Any],
    provided: dict[str, Any],
) -> None:
    """
    Move values sitting on weakly-matched fields to better schema targets.
    Clears duplicate placements of the same normalized value.
    """
    if not provided or not schema:
        return

    filled: list[tuple[SchemaLeaf, str, float]] = []
    for leaf in iter_schema_leaves(schema):
        val = _get_leaf(mapped, leaf)
        if is_empty_value(val):
            continue
        pk, _ = _best_provided_key_for_value(provided, val)
        if not pk:
            pk = next(
                (k for k, v in provided.items() if field_match_score(leaf.field_key, k) >= _ASSIGN_THRESHOLD),
                "",
            )
        score = field_match_score(leaf.field_key, pk) if pk else 0.0
        filled.append((leaf, str(val).strip(), score))

    value_to_best: dict[str, tuple[SchemaLeaf, float]] = {}
    for leaf, val, score in filled:
        nv = normalize_value(val)
        pk, _ = _best_provided_key_for_value(provided, val)
        if pk:
            target_leaf, target_score = _best_leaf_for_provided_key(schema, pk)
            if target_leaf and target_score > score + _REASSIGN_MARGIN:
                _clear_leaf(mapped, leaf)
                _set_leaf(mapped, target_leaf, val)
                leaf, score = target_leaf, target_score

        prev = value_to_best.get(nv)
        if prev is None or score > prev[1]:
            value_to_best[nv] = (leaf, score)

    for leaf, val, score in filled:
        nv = normalize_value(val)
        best_leaf, best_score = value_to_best.get(nv, (leaf, score))
        if best_leaf.field_key == leaf.field_key:
            continue
        if best_leaf.path != leaf.path or best_leaf.tier != leaf.tier:
            if best_score > score + _REASSIGN_MARGIN or score < 0.55:
                _clear_leaf(mapped, leaf)
        elif score < 0.55 and not is_empty_value(_get_leaf(mapped, leaf)):
            cpk, _ = _best_provided_key_for_value(provided, val)
            if cpk and field_match_score(leaf.field_key, cpk) < 0.55:
                _clear_leaf(mapped, leaf)
