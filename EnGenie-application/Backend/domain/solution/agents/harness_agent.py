import os
import re
import json
import logging
import random
import threading
import uuid as _uuid
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from common.ai.llm import SOLUTION_LLM_PROVIDER, get_solution_flash_llm, with_json_mode
from domain.solution.schemas import SolutionResponse

# === 5-Tier Unified Product Hierarchy Validation Models ===
def stable_node_uuid(natural_key: str, seed: int = 42) -> str:
    """Deterministic UUID for a hierarchy node."""
    rng = random.Random(f"{seed}:{natural_key}")
    return str(_uuid.UUID(int=rng.getrandbits(128), version=4))

LEVELS: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4")
LEVEL_NAMES: dict[str, str] = {
    "L0": "Category",
    "L1": "Product Type",
    "L2": "Sub-category",
    "L3": "Model Family",
    "L4": "Vendor Product",
}
SCHEMA_LEVELS = ("L0", "L1", "L2")
VENDOR_LEVELS = ("L3", "L4")

_CONFIG = ConfigDict(
    extra="allow",
    populate_by_name=True,
    str_strip_whitespace=True,
    protected_namespaces=(),
)

# The specification categories that appear at L0/L1/L2 nodes.
SPEC_CATEGORIES: tuple[str, ...] = (
    "safety", "electrical", "mechanical", "process",
    "environmental", "performance", "certifications", "materials",
    "communication", "product_info", "applications", "other",
)


class SpecParameter(BaseModel):
    """A single named parameter inside a specification category."""
    model_config = _CONFIG
    id: str = Field(description="Unique parameter identifier")
    name: str = Field(description="Parameter name")
    value: Optional[str] = Field(default=None, description="Parameter value")
    level: Literal["Required", "Optional", "Advanced"] = Field(
        default="Optional", description="Required / Optional / Advanced"
    )
    units: Optional[str] = Field(default=None, description="Unit of measurement (e.g. V, HZ)")


class SchemaSpec(BaseModel):
    """L0 / L1 / L2 specification template — parameter-category buckets."""
    model_config = _CONFIG
    id: str = Field(default="", description="Unique specifications block identifier")
    safety: list[SpecParameter] = Field(default_factory=list)
    electrical: list[SpecParameter] = Field(default_factory=list)
    mechanical: list[SpecParameter] = Field(default_factory=list)
    process: list[SpecParameter] = Field(default_factory=list)
    environmental: list[SpecParameter] = Field(default_factory=list)
    performance: list[SpecParameter] = Field(default_factory=list)
    certifications: list[SpecParameter] = Field(default_factory=list)
    materials: list[SpecParameter] = Field(default_factory=list)
    communication: list[SpecParameter] = Field(default_factory=list)
    product_info: list[SpecParameter] = Field(default_factory=list)
    applications: list[SpecParameter] = Field(default_factory=list)
    other: list[SpecParameter] = Field(default_factory=list)

    def all_parameters(self) -> list[SpecParameter]:
        """Flat list of every parameter across all categories."""
        result: list[SpecParameter] = []
        for cat in SPEC_CATEGORIES:
            result.extend(getattr(self, cat))
        return result

    def required_parameters(self) -> list[SpecParameter]:
        return [p for p in self.all_parameters() if p.level == "Required"]

    def optional_parameters(self) -> list[SpecParameter]:
        return [p for p in self.all_parameters() if p.level == "Optional"]

    def advanced_parameters(self) -> list[SpecParameter]:
        return [p for p in self.all_parameters() if p.level == "Advanced"]


class FamilySpec(BaseModel):
    """L3 specifications — values shared across all of the family's sub-models."""
    model_config = _CONFIG
    shared_specifications: dict[str, Any] = Field(default_factory=dict)
    common_spec_fields: list[str] = Field(default_factory=list)
    sub_model_count: int = 0
    description: str = ""

class HierarchyNode(BaseModel):
    """A single node (one MongoDB document) in the 5-tier hierarchy."""
    model_config = _CONFIG
    uuid: str = Field(description="Deterministic UUID identifying the node")
    level: str = Field(description="One of L0, L1, L2, L3, L4")
    name: str = Field(description="Display name of the category/type/family/product")
    parent_id: Optional[str] = Field(default=None, description="parent node's UUID (None only for L0)")
    vendor: Optional[str] = Field(default=None, description="Manufacturer (L3/L4 only)")
    specifications: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_structure(self) -> "HierarchyNode":
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {self.level!r}")
        if self.level == "L0" and self.parent_id is not None:
            raise ValueError("L0 (Category) nodes must have parent_id=None")
        if self.level != "L0" and not self.parent_id:
            raise ValueError(f"{self.level} nodes require a parent_id")
        if self.level in ("L0", "L1", "L2") and self.vendor:
            raise ValueError(f"{self.level} nodes must not carry a vendor")
        if self.level in VENDOR_LEVELS and not self.vendor:
            raise ValueError(f"{self.level} nodes require a vendor")
        return self

    def coerce_specifications(self) -> dict[str, Any]:
        s = self.specifications or {}
        if self.level in SCHEMA_LEVELS:
            if not s:
                return {}
            return SchemaSpec.model_validate(s).model_dump(exclude_none=True)
        if self.level == "L3": return FamilySpec.model_validate(s).model_dump()
        return dict(s)

    def coerce_metadata(self) -> dict[str, Any]:
        m = dict(self.metadata or {})
        if self.level == "L4":
            m.setdefault("datasheet_url", None)
            m.setdefault("model_number", None)
            m.setdefault("certifications", [])
        return m

    def to_doc(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "level": self.level,
            "name": self.name,
            "parent_id": self.parent_id,
            "vendor": self.vendor,
            "specifications": self.coerce_specifications(),
            "metadata": self.coerce_metadata(),
        }

    @classmethod
    def category(cls, uuid: str, name: str, **meta: Any) -> "HierarchyNode":
        return cls(uuid=uuid, level="L0", name=name, parent_id=None, metadata=meta)

    @classmethod
    def product_type(cls, uuid: str, name: str, parent_id: str,
                     spec: SchemaSpec | dict | None = None, **meta: Any) -> "HierarchyNode":
        return cls(uuid=uuid, level="L1", name=name, parent_id=parent_id,
                   specifications=_as_dict(spec), metadata=meta)

    @classmethod
    def sub_category(cls, uuid: str, name: str, parent_id: str,
                     spec: SchemaSpec | dict | None = None, **meta: Any) -> "HierarchyNode":
        return cls(uuid=uuid, level="L2", name=name, parent_id=parent_id,
                   specifications=_as_dict(spec), metadata=meta)

    @classmethod
    def model_family(cls, uuid: str, name: str, parent_id: str, vendor: str,
                     spec: FamilySpec | dict | None = None, **meta: Any) -> "HierarchyNode":
        return cls(uuid=uuid, level="L3", name=name, parent_id=parent_id, vendor=vendor,
                   specifications=_as_dict(spec), metadata=meta)

    @classmethod
    def vendor_product(cls, uuid: str, name: str, parent_id: str, vendor: str,
                       specifications: dict | None = None, **meta: Any) -> "HierarchyNode":
        return cls(uuid=uuid, level="L4", name=name, parent_id=parent_id, vendor=vendor,
                   specifications=specifications or {}, metadata=meta)

def _as_dict(spec: Any) -> dict[str, Any]:
    if spec is None: return {}
    if isinstance(spec, BaseModel): return spec.model_dump(by_alias=True, exclude_none=True)
    return dict(spec)

# ==========================================================


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PARALLEL BATCH RUNNER
# ---------------------------------------------------------------------------

def _parallel_batch_run(
    items: list,
    fn,
    label: str = "HARNESS_AGENT",
) -> None:
    """Run fn(item) for every item using a dynamically-sized thread pool.

    Worker count = len(items), so all items are executed in parallel at once.

    fn must mutate each item in-place; return values are discarded.
    Thread safety: each `item` is a distinct dict so cross-item races
    cannot occur; only shared counters need an external lock.
    """
    if not items:
        return
    n = len(items)
    if n <= 1:
        # Avoid ThreadPoolExecutor overhead for trivial workloads
        for item in items:
            try:
                fn(item)
            except Exception as exc:
                logger.warning(f"[{label}] Item processing failed (sequential): {exc}")
        return
    logger.info(f"[{label}] Parallel batch: {n} item(s) at once")
    with ThreadPoolExecutor(max_workers=n) as executor:
        futures = {executor.submit(fn, item): item for item in items}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                logger.warning(f"[{label}] Batch item failed: {exc}")


_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

def _load_prompt(filename: str) -> str:
    try:
        with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {filename}")
        return ""

def escape_newlines_in_serialized_mapping(s: str) -> str:
    """Escapes literal newlines, carriage returns, and tabs inside serialized string values."""
    result = []
    in_string = False
    escaped = False
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
            result.append(char)
        elif char == '\\' and in_string:
            escaped = not escaped
            result.append(char)
        else:
            if escaped:
                escaped = False
            if in_string and char in ('\n', '\r', '\t'):
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
            else:
                result.append(char)
    return "".join(result)

def harness_evaluate_standards_grounding(standards_result: dict, category: str) -> dict:
    """
    Evaluates standard specifications grounding against the full source document text using LLM.

    Mirrors the three validation sections of harness_grounding_evaluation.md:
      1. SCOPE AND INPUT HANDLING   - split out [INFERRED] values, bound the
         evaluatable key set, and short-circuit on empty inputs.
      2. GROUNDING VERIFICATION     - LLM grounding pass (+ re-extraction fallback)
         keeping only values traceable to the source document.
      3. OUTPUT SCHEMA COMPLIANCE / PYDANTIC VALIDATION - validate/normalize
         against the TechnicalSpecifications object model and coerce to a flat
         string->string mapping: drop invented keys (scope) plus any non-scalar
         (nested/list) or empty values, while keeping grounded scalar keys even
         when they are not predefined model properties.

    If they are grounded, returns the grounded specifications. Otherwise, returns empty specifications.
    """
    if not standards_result or not standards_result.get("found"):
        return standards_result

    standards_specs = standards_result.get('specifications', {})
    if "specifications" in standards_specs and isinstance(standards_specs["specifications"], dict):
        spec_dict = standards_specs["specifications"]
    else:
        spec_dict = standards_specs

    full_text = standards_result.get("_full_text", "")
    if not full_text:
        return standards_result

    try:
        # ============================================================
        # SECTION 1: SCOPE AND INPUT HANDLING
        # Split [INFERRED] values (not re-evaluated) from the specs that
        # require grounding, and capture the allowed key set so the LLM
        # cannot introduce keys it was never given.
        # ============================================================
        inferred_specs = {}
        specs_to_evaluate = {}
        for k, v in spec_dict.items():
            if isinstance(v, str) and "[INFERRED]" in v:
                inferred_specs[k] = v
            else:
                specs_to_evaluate[k] = v

        def _norm_key(k: str) -> str:
            return str(k).lower().replace("_", "").replace(" ", "")

        allowed_keys = {_norm_key(k) for k in specs_to_evaluate}

        grounded_specs = {}
        is_pydantic_valid = True

        def _ground_and_validate(to_eval: dict) -> tuple[dict, bool]:
            """One grounding pass (SECTION 2) + Pydantic normalization (SECTION 3).
            Returns (grounded_scalar_specs, pydantic_valid)."""
            eval_prompt = _load_prompt("harness_grounding_evaluation.md")
            if not eval_prompt:
                logger.error("[HARNESS_AGENT] Harness grounding evaluation prompt could not be loaded.")
                return {}, True
            llm_flash = get_solution_flash_llm(temperature=0.1)
            chain = (
                ChatPromptTemplate.from_template(eval_prompt)
                | with_json_mode(llm_flash, SOLUTION_LLM_PROVIDER)
                | StrOutputParser()
            )
            raw = chain.invoke({
                "document_text": full_text,
                "specifications": json.dumps(to_eval, indent=2),
            })
            out = json.loads(raw.strip())
            # SECTION 3: schema compliance / Pydantic validation
            from common.models.standards import TechnicalSpecifications
            try:
                out = {k: v for k, v in out.items() if _norm_key(k) in allowed_keys}
                validated = TechnicalSpecifications.model_validate(out)
                normalized = validated.model_dump(exclude_none=True)
                scalar = {
                    k: str(v).strip() for k, v in normalized.items()
                    if isinstance(v, (str, int, float)) and str(v).strip()
                }
                return scalar, True
            except Exception:
                return {}, False

        if specs_to_evaluate:
            # ========================================================
            # SECTION 2+3: GROUNDING + PYDANTIC, run as a BOUNDED ITERATIVE
            # loop. Each round re-grounds ONLY the still-ungrounded keys; the
            # loop stops when nothing new gets grounded, all keys are grounded,
            # or MAX_ROUNDS is reached (prevents infinite loops / runaway cost).
            # ========================================================
            MAX_ROUNDS = 3
            remaining = dict(specs_to_evaluate)
            for round_i in range(1, MAX_ROUNDS + 1):
                round_grounded, round_valid = _ground_and_validate(remaining)
                is_pydantic_valid = round_valid
                if round_grounded:
                    grounded_specs.update(round_grounded)
                # which input keys are still not grounded?
                grounded_norm = {_norm_key(k) for k in grounded_specs}
                remaining = {k: v for k, v in specs_to_evaluate.items()
                             if _norm_key(k) not in grounded_norm}
                logger.info(
                    f"[HARNESS_AGENT] Grounding round {round_i}/{MAX_ROUNDS} for '{category}': "
                    f"grounded={len(grounded_specs)} remaining={len(remaining)} valid={round_valid}"
                )
                if not remaining or not round_grounded:
                    break   # fully grounded, or this round added nothing -> stop

        # SECTION 2 (continued): grounding re-extraction fallback for THIS
        # product type when nothing got grounded, original specs are empty, or
        # validation failed. Also bounded-iterative: retry re-extraction up to
        # MAX_FB_ROUNDS, accepting any newly grounded values each round.
        if full_text and (not spec_dict or not grounded_specs or not is_pydantic_valid):
            logger.warning(
                f"[HARNESS_AGENT] Standards specs for '{category}' failed validation criteria "
                f"(grounded_count={len(grounded_specs)}, pydantic_valid={is_pydantic_valid}). "
                f"Triggering iterative standards re-extraction fallback..."
            )
            try:
                from common.ai.rag.standard_rag import _grounding_fallback_extraction
                MAX_FB_ROUNDS = 3
                chunks = [full_text[i:i + 50000] for i in range(0, len(full_text), 50000)]
                for fb_round in range(1, MAX_FB_ROUNDS + 1):
                    try:
                        fb_grounded, fb_specs, fb_applicable, fb_summaries, fb_dropped = _grounding_fallback_extraction(
                            category, chunks, standards_result.get("source_document", ""), full_text
                        )
                    except Exception as fb_exc:
                        logger.error(f"[HARNESS_AGENT] Re-extraction fallback round {fb_round} failed for '{category}': {fb_exc}")
                        break
                    before = len(grounded_specs)
                    if fb_grounded:
                        # Adopt only the grounding-filtered subset (honors the grounding contract).
                        grounded_specs.update(fb_grounded)
                        standards_result["applicable_standards"] = fb_applicable or standards_result.get("applicable_standards", [])
                        if fb_summaries:
                            standards_result["requirements_summary"] = " ".join(fb_summaries)
                    logger.info(
                        f"[HARNESS_AGENT] Fallback round {fb_round}/{MAX_FB_ROUNDS} for '{category}': "
                        f"+{len(grounded_specs) - before} grounded (total={len(grounded_specs)})"
                    )
                    if grounded_specs:
                        break   # got something grounded -> stop retrying
            except ImportError:
                logger.debug("[HARNESS_AGENT] standard_rag re-extraction fallback not available.")

        # SECTION 1 (continued): re-merge the untouched [INFERRED] values
        # back into the final grounded dict.
        final_specs = {**grounded_specs, **inferred_specs}

        # Update specifications and ensure found is always True (we do not drop)
        if "specifications" in standards_specs and isinstance(standards_specs["specifications"], dict):
            standards_specs["specifications"] = final_specs
        else:
            standards_result["specifications"] = final_specs
        
        standards_result["found"] = True

    except Exception as exc:
        logger.error(f"[HARNESS_AGENT] Grounding evaluation failed for '{category}': {exc}")
        # Keep original specs on error as a fallback
        pass

    return standards_result

def _item_name(item: dict) -> str:
    """Resolve a solution item's product-type name from the keys it ACTUALLY uses.
    format_results items are keyed by `category` (not `name`); fall back through the
    common variants so the 5-tier lookups don't silently no-op on an empty `name`."""
    for k in ("name", "category", "product_name", "accessory_name", "category_mapped"):
        v = item.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _item_specs(item: dict) -> dict:
    """Resolve a solution item's filled spec/requirements dict from the keys it
    ACTUALLY uses (`specifications` in format_results; `requirements` in the Pydantic
    object model)."""
    for k in ("requirements", "specifications", "specs"):
        v = item.get(k)
        if isinstance(v, dict) and v:
            return v
    return {}


def _norm_spec_key(k: str) -> str:
    """Canonical form for spec field name comparison.

    Strips non-alphanumeric characters and lowercases so that
    ``"Output Signal"``, ``"output_signal"``, ``"OutputSignal"`` all compare equal.
    This bridges the gap between DB SpecParameter.name values (natural language,
    title-case) and LLM-generated keys (may use underscores, mixed case, or
    different punctuation).
    """
    return re.sub(r"[^a-z0-9]", "", str(k or "").lower())


def harness_validate_standards_match(response: dict) -> dict:
    """CORRECT-PRODUCT STANDARDS gate: ensure each equipment/accessory carries the
    standards that actually belong to ITS product, not standards bled in from another
    category. For every item, resolve the authoritative standards from its own 5-tier
    node (cascade L2->L1->L0 via resolve_standards_by_name(item.name)) and:
      - STRIP any attached standard not in the node's authoritative set, and
      - ATTACH the authoritative standards the item is missing.
    Records a per-item `standards_match` audit block {node, authoritative, kept,
    stripped, added}. No-op for items whose name resolves to no 5-tier node or whose
    node carries no standards yet (safe/additive).
    Runs in parallel across all items via _parallel_batch_run (dynamic worker count,
    capped at 20 since work is DB-bound, not LLM-bound)."""
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository as RR
    except Exception as imp_exc:
        logger.warning(f"[HARNESS_AGENT] correct-product standards gate unavailable: {imp_exc}")
        return response

    def _norm_std(s: str) -> str:
        return str(s).upper().replace(" ", "").replace("-", "")

    # Shared counters protected by a per-call lock (items are distinct dicts,
    # so cross-item dict mutations are race-free without a lock).
    _lock = threading.Lock()
    stats = {"checked": 0, "corrected": 0}

    def _process_item(item: dict) -> None:
        try:
            name = _item_name(item)
            authoritative = RR.resolve_standards_by_name(name)   # cascade for THIS product
            if not authoritative:
                return                                            # no node / no standards -> skip
            auth_norm = {_norm_std(s): s for s in authoritative}
            # read whatever standards are attached, from EITHER field name
            attached = item.get("standards") or item.get("applicable_standards") or []
            kept = [s for s in attached if _norm_std(s) in auth_norm]
            stripped = [s for s in attached if _norm_std(s) not in auth_norm]
            # authoritative set wins: keep matched + add any missing authoritative codes
            final = sorted(set(kept) | set(authoritative))
            # write BOTH the internal `standards` and the UI-facing `applicable_standards`
            item["standards"] = final
            item["applicable_standards"] = final
            corrected_flag = bool(stripped) or bool(set(authoritative) - set(attached))
            item["standards_match"] = {
                "authoritative_count": len(authoritative),
                "kept": kept, "stripped": stripped,
                "added": sorted(set(authoritative) - set(attached)),
                "corrected": corrected_flag,
            }
            with _lock:
                stats["checked"] += 1
                stats["corrected"] += corrected_flag
        except Exception:
            pass

    all_items: list[dict] = []
    for key in ("instruments", "accessories"):
        all_items.extend(response.get(key, []) or [])

    _parallel_batch_run(all_items, _process_item)

    if stats["checked"]:
        logger.info(
            f"[HARNESS_AGENT] correct-product standards gate: "
            f"{stats['corrected']}/{stats['checked']} items corrected"
        )
    return response


def harness_validate_against_schema(response: dict) -> dict:
    """5-tier SCHEMA-COMPLIANCE gate: for each identified equipment/accessory, resolve
    its cascade schema (L2->L1->L0) from the hierarchy and check the filled
    `requirements` cover the MANDATORY fields. Attaches a per-item `schema_compliance`
    block. Additive + safe: a no-op for items whose 5-tier node has no schema yet, so
    it activates automatically once catalog_hierarchy's schema phase is populated.
    Runs in parallel across all items via _parallel_batch_run (dynamic worker count,
    capped at 20 since work is DB-bound + Pydantic, not LLM-bound).
    """
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository as RR
    except Exception as imp_exc:
        logger.warning(f"[HARNESS_AGENT] 5-tier schema gate unavailable: {imp_exc}")
        return response
    # Per-item Pydantic models: validate each item's shape against the active
    # object model (EquipmentSpec for equipment, AccessorySpec for accessories).
    try:
        from domain.solution.schemas import InstrumentSpec as EquipmentSpec, AccessorySpec
    except Exception:
        EquipmentSpec = AccessorySpec = None

    # Shared counters protected by a per-call lock.
    _lock = threading.Lock()
    stats = {"checked": 0, "compliant": 0, "pyd_ok": 0, "pyd_checked": 0}

    def _process_item(args: tuple) -> None:
        item, model, key = args
        name = _item_name(item)
        specs = _item_specs(item)

        # --- Pydantic shape validation against the active object model ---
        # format_results items are keyed by category/specifications, so validate a
        # NORMALIZED projection (name + requirements + standards) rather than the
        # raw frontend-shaped dict, which would always fail on the required `name`.
        if model is not None:
            projection = {"name": name, "requirements": specs,
                          "standards": item.get("standards") or []}
            if key == "accessories":
                projection["parent_instrument_category"] = item.get("parent_instrument_category", "")
            try:
                model.model_validate(projection)
                item.setdefault("schema_compliance", {})["pydantic_valid"] = True
                pyd_ok_local = True
            except Exception as pe:
                item.setdefault("schema_compliance", {})["pydantic_valid"] = False
                item["schema_compliance"]["pydantic_error"] = str(pe)[:200]
                pyd_ok_local = False
            with _lock:
                stats["pyd_checked"] += 1
                if pyd_ok_local:
                    stats["pyd_ok"] += 1

        # --- Mandatory-field coverage against the 5-tier cascade ---
        # Use the level-adaptive PARAMETERS cascade (the populated schema lives
        # under `parameters`, not `spec_requirements` which resolve_schema reads).
        try:
            node = RR.find_node_by_name(name)
            if not node:
                return
            resolved = RR.resolve_parameters_schema_by_name(name) or {}
            mandatory_raw: dict = resolved.get("mandatoryRequirements") or {}
            if not mandatory_raw:          # no schema authored yet -> skip
                return

            # Normalize both sides to the same canonical form so that
            # "Output Signal" (DB) == "output_signal" (LLM key).
            # We keep the original DB key names for the missing-field report
            # so the compliance block is human-readable.
            norm_mandatory: dict[str, str] = {_norm_spec_key(k): k for k in mandatory_raw}
            norm_filled: set[str] = {_norm_spec_key(k) for k in specs}
            missing_norm = sorted(norm_mandatory[nk] for nk in norm_mandatory if nk not in norm_filled)

            # node_type drives how "missing mandatory" should be read: Equipment nodes
            # are null-value templates by design (real values are extracted from the
            # vendor PDF at query time, so gaps here are expected/in-progress, not a
            # data-quality fault). Accessory nodes ship pre-enriched from the catalog,
            # so a gap there means the catalog row itself is incomplete.
            node_type = node.get("type", "Equipment")
            item.setdefault("schema_compliance", {}).update({
                "node_id": node["_id"], "node_type": node_type,
                "mandatory_total": len(norm_mandatory),
                "missing_mandatory": missing_norm,
                "compliant": not missing_norm,
                "gap_severity": "informational" if node_type == "Equipment" else "data_gap",
            })
            with _lock:
                stats["checked"] += 1
                stats["compliant"] += (not missing_norm)
        except Exception:
            pass

    # Build tagged work list: each entry is (item, model, key) so _process_item
    # knows which Pydantic model to use without any shared mutable state.
    tagged: list[tuple] = []
    for key in ("instruments", "accessories"):
        model = EquipmentSpec if key == "instruments" else AccessorySpec
        for item in response.get(key, []) or []:
            tagged.append((item, model, key))

    _parallel_batch_run(tagged, _process_item)

    if stats["pyd_checked"]:
        logger.info(
            f"[HARNESS_AGENT] per-item Pydantic gate: "
            f"{stats['pyd_ok']}/{stats['pyd_checked']} items valid"
        )
    if stats["checked"]:
        logger.info(
            f"[HARNESS_AGENT] 5-tier schema gate: "
            f"{stats['compliant']}/{stats['checked']} items met all mandatory fields"
        )
    return response


def harness_repair_final_response(response: dict) -> dict:
    """
    Checks final response dictionary compliance with SolutionResponse object model.
    If non-compliant, triggers LLM Repair Gate (Harness) using template solution_schema_reformat.md.
    """
    response = harness_validate_standards_match(response)  # correct-product standards gate (#2)
    response = harness_validate_against_schema(response)   # 5-tier schema-compliance gate (additive)
    if not SolutionResponse.is_compliant(response):
        logger.warning("[HARNESS_AGENT] Final response output is not compliant with SolutionResponse. Triggering LLM Repair Gate...")
        try:
            reformat_prompt = _load_prompt("solution_schema_reformat.md")
            if reformat_prompt:
                llm_flash = get_solution_flash_llm(temperature=0.1)
                chain = (
                    ChatPromptTemplate.from_template(reformat_prompt)
                    | with_json_mode(llm_flash, SOLUTION_LLM_PROVIDER)
                    | StrOutputParser()
                )
                reformatted_response_str = chain.invoke({"raw": json.dumps(response, default=str)})
                
                # Parse and clean the dictionary mapping representation
                cleaned_response = reformatted_response_str.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                elif cleaned_response.startswith("```"):
                    cleaned_response = cleaned_response[3:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                
                cleaned_response = escape_newlines_in_serialized_mapping(cleaned_response.strip())
                
                try:
                    reformatted_model = SolutionResponse.model_validate_json(cleaned_response)
                    logger.info("[HARNESS_AGENT] LLM Repair Gate successfully reformatted the output to conform to SolutionResponse.")
                    return reformatted_model.model_dump(exclude_none=True)
                except Exception:
                    logger.warning("[HARNESS_AGENT] LLM Repair Gate output is still non-compliant. Falling back to ensure_compliant defaults.")
        except Exception as repair_err:
            logger.error(f"[HARNESS_AGENT] LLM Repair Gate execution failed: {repair_err}")
            
    return SolutionResponse.ensure_compliant(response)
