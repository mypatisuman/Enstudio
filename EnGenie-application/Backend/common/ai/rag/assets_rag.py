"""
Assets RAG
==========
Single-file consolidation of:
  - assets_rag        : CSV/blob extraction for raw asset entries
  - asset_config_rag  : Asset configuration CRUD, LLM extraction, YAML generation
  - diagnostics_rag   : Instrument diagnostic log analysis and semantic search

Shared utility
--------------
  build_user_id_filter(user_id) -> dict
      Builds a MongoDB filter that matches both string and int variants of user_id.
"""

import gzip
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_parent_dir = os.path.dirname(os.path.dirname(__file__))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from common.infra.mongodb_config import Collections, get_mongodb_connection
from common.ai.prompts.templates import (
    ASSET_CONFIG_EXTRACTION_PROMPT,
    ASSET_CONFIG_YAML_GENERATION_PROMPT,
)

logger = logging.getLogger(__name__)

# ============================================================================
# SHARED UTILITY
# ============================================================================

def build_user_id_filter(user_id, extra: dict | None = None) -> dict:
    """
    Build a MongoDB filter that matches user_id regardless of whether it is
    stored as a string or an integer.

    Args:
        user_id: The user ID (str or int).
        extra:   Additional filter clauses to merge into the result.

    Returns:
        A dict suitable for use as a MongoDB filter.
    """
    try:
        user_id_int = int(user_id)
        base = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
    except (ValueError, TypeError):
        base = {"user_id": user_id}

    if extra:
        base.update(extra)
    return base


# ============================================================================
# COLLECTION CONSTANTS
# ============================================================================

ASSETS_COLLECTION_NAME          = Collections.ASSETS
ASSET_CONFIGURATIONS_COLLECTION = Collections.ASSET_CONFIGURATIONS
INSTRUMENT_LOGS_COLLECTION      = Collections.INSTRUMENT_LOGS
DIAGNOSTIC_CODES_COLLECTION     = Collections.DIAGNOSTIC_CODES
DIAGNOSTIC_SESSIONS_COLLECTION  = Collections.DIAGNOSTIC_SESSIONS

# Log types
LOG_TYPE_READING    = "reading"
LOG_TYPE_ALARM      = "alarm"
LOG_TYPE_EVENT      = "event"
LOG_TYPE_DIAGNOSTIC = "diagnostic"

# Severity levels
SEVERITY_INFO      = "info"
SEVERITY_WARNING   = "warning"
SEVERITY_CRITICAL  = "critical"
SEVERITY_EMERGENCY = "emergency"

# Required / recommended fields for asset-config gap detection
REQUIRED_FIELDS = {
    "asset.asset_name":          "Asset name",
    "asset.asset_type":          "Asset type/category",
    "asset.model":               "Equipment model",
    "asset.serial_number":       "Serial number",
    "location.plant":            "Plant name",
    "location.site":             "Site name",
    "location.area":             "Area",
    "connected_system.name":     "Connected system name",
    "connected_system.protocol": "Connected system protocol",
}
RECOMMENDED_FIELDS = {
    "asset.tag_number":       "Asset tag number",
    "asset.manufacturer":     "Asset manufacturer",
    "target_system.name":     "Target system name",
    "target_system.type":     "Target system type",
    "target_system.protocol": "Target system protocol",
}

# ============================================================================
# INSTRUMENT CONFIG SCHEMA + DYNAMIC STANDARDS MAPPING
# ============================================================================

# Source-of-truth data model: sections → canonical snake_case field names.
# This is the ONLY place field names are defined; all mapping is derived from it.
INSTRUMENT_CONFIG_SCHEMA: dict[str, list[str]] = {
    "hart_identity": [
        "equipment_category", "hart_tag", "hart_long_tag", "message",
        "descriptor", "sensor_serial", "transmitter_serial", "device_revision",
    ],
    "calibration": [
        "flow_calibration_factor", "density_coeff_d1", "density_coeff_d2",
        "density_coeff_d3", "density_coeff_d4", "temperature_coefficient",
    ],
    "pv_mapping": [
        "primary_variable", "secondary_variable", "tertiary_variable",
        "quaternary_variable", "urv", "lrv", "pv_units",
    ],
    "measurement_control": [
        "damping", "low_flow_cutoff", "flow_direction",
        "fault_action", "totalizer", "measurement_units",
    ],
    "diagnostics_health": [
        "smv_frequency", "smv_integrity_enabled", "drive_gain_limit",
        "density_deviation_limit", "temp_high_limit", "electronics_temp_limit",
    ],
}

# Semantic aliases — ONLY for cases where camelCase→snake_case does NOT produce
# the canonical field name (e.g. a different concept name in the standards doc).
# These contain NO default values — they are pure name translations.
_FIELD_ALIASES: dict[str, str] = {
    # ── Primary camelCase variants ──────────────────────────────────────────
    "hart_revision":             "device_revision",       # hartRevision
    "communication_protocol":    "device_revision",       # communicationProtocol
    "default_damping":           "damping",               # defaultDamping
    "fail_safe_action":          "fault_action",          # failSafeAction
    "smv_verification_interval": "smv_frequency",         # smvVerificationInterval
    "smv_integrity":             "smv_integrity_enabled", # smvIntegrity (without _enabled)
    "density_dev_limit":         "density_deviation_limit", # densityDevLimit
    "electronics_limit":         "electronics_temp_limit",  # electronicsLimit
    "temp_high":                 "temp_high_limit",         # tempHigh without _limit
    # ── Suffix-level aliases for compound key resolution ────────────────────
    # These allow suffix matching to catch keys like:
    #   "magneticFlowmeterTransmitterCommunication" → suffix "Communication" → device_revision
    #   "coriolisDampingValue"       → suffix "DampingValue" → damping
    #   "magneticFlowmeterFailSafe"  → suffix "FailSafe"     → fault_action
    "communication":             "device_revision",       # ...Communication suffix
    "hart_protocol":             "device_revision",       # ...HartProtocol suffix
    "drive_gain":                "drive_gain_limit",      # ...DriveGain (without Limit)
    "fail_safe":                 "fault_action",          # ...FailSafe (without Action)
    "damping_value":             "damping",               # ...DampingValue
    "density_deviation":         "density_deviation_limit",  # ...DensityDeviation
    "smv_verification":          "smv_frequency",            # ...SmvVerification
    "electronics_temperature":   "electronics_temp_limit",   # ...ElectronicsTemperature
    "electronics_temp":          "electronics_temp_limit",   # ...ElectronicsTemp (short)
    "temp_high_level":           "temp_high_limit",           # ...TempHighLevel
    "calibration_factor":        "flow_calibration_factor",  # ...CalibrationFactor
}

# Fields whose values must be coerced to bool
_BOOLEAN_FIELDS: frozenset[str] = frozenset({"smv_integrity_enabled"})

# Build reverse lookup dynamically from the schema: snake_case → (section, field)
_FIELD_LOOKUP: dict[str, tuple[str, str]] = {
    field: (section, field)
    for section, fields in INSTRUMENT_CONFIG_SCHEMA.items()
    for field in fields
}


def _camel_to_snake(name: str) -> str:
    """Convert camelCase / PascalCase to snake_case without any imports at call time."""
    import re
    s1 = re.sub(r"([A-Z][a-z]+)", r"_\1", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower().lstrip("_")


def apply_standards_to_instrument_config(
    instrument_config: dict,
    standards_specs: dict,
) -> dict:
    """
    Apply standards specifications to instrument_config using dynamic schema lookup.

    Algorithm for each spec key:
      1. Convert camelCase → snake_case
      2. Resolve semantic alias if needed (small alias table — no default values)
      3. Look up canonical field in schema-derived _FIELD_LOOKUP
      4. Skip if the field already has a value (user input wins)
      5. Write value, coercing to bool for boolean fields

    No hardcoded default values are written here — every value comes from
    standards_specs which was fetched from the standards database.
    """
    if not standards_specs:
        return instrument_config

    # Ensure all sections exist
    for section in INSTRUMENT_CONFIG_SCHEMA:
        if section not in instrument_config or not isinstance(instrument_config[section], dict):
            instrument_config[section] = {}

    for spec_key, spec_value in standards_specs.items():
        if not spec_value:
            continue

        # Step 1 — camelCase → snake_case
        snake = _camel_to_snake(spec_key)

        # Step 2 — resolve semantic alias
        canonical = _FIELD_ALIASES.get(snake, snake)

        # Step 3 — look up in schema
        mapping = _FIELD_LOOKUP.get(canonical)

        # Step 3b — compound key suffix extraction
        # Handles keys like "magneticFlowmeterTransmitterCommunicationProtocol"
        # by splitting into capitalized words and trying each suffix starting
        # from position 1 (skipping the device-type prefix words).
        if not mapping:
            import re as _re
            words = _re.sub(r'([A-Z])', r' \1', spec_key).split()
            if len(words) > 1:
                for start in range(1, len(words)):
                    suffix_camel = ''.join(words[start:])
                    suffix_snake = _camel_to_snake(suffix_camel)
                    suffix_canon = _FIELD_ALIASES.get(suffix_snake, suffix_snake)
                    mapping = _FIELD_LOOKUP.get(suffix_canon)
                    if mapping:
                        logger.debug(
                            f"[STANDARDS_MAP] Compound key resolved: "
                            f"'{spec_key}' via suffix '{suffix_camel}' → {mapping}"
                        )
                        break

        if not mapping:
            continue  # key not in our data model — skip

        section_name, field_name = mapping
        section = instrument_config[section_name]

        # Step 4 — skip if already has a value (user or prior data wins)
        current = section.get(field_name)
        if current and current != "" and current is not False:
            continue

        # Step 5 — write with type coercion
        if field_name in _BOOLEAN_FIELDS:
            str_val = str(spec_value).lower()
            section[field_name] = str_val in ("true", "enabled", "yes", "1")
        else:
            section[field_name] = str(spec_value)

    return instrument_config


# Fields that are tied to physical hardware or process design — never infer these.
_HARDWARE_SPECIFIC_FIELDS: frozenset[str] = frozenset({
    "hart_tag", "hart_long_tag", "message", "descriptor",
    "sensor_serial", "transmitter_serial",
    "flow_calibration_factor",
    "density_coeff_d1", "density_coeff_d2", "density_coeff_d3", "density_coeff_d4",
    "temperature_coefficient",
    "urv", "lrv", "pv_units",
    "equipment_category",
})


def _has_empty_inferrable_fields(ic: dict) -> bool:
    """Return True if any non-hardware-specific, non-boolean HART config field is empty."""
    for section, fields in INSTRUMENT_CONFIG_SCHEMA.items():
        for field in fields:
            if field in _HARDWARE_SPECIFIC_FIELDS or field in _BOOLEAN_FIELDS:
                continue
            val = ic.get(section, {}).get(field)
            if not val or val == "":
                return True
    return False


def _infer_hart_config_defaults(
    instrument_config: dict,
    asset_type: str,
    equipment_category: str,
) -> dict:
    """
    Fill remaining empty HART instrument_config fields using LLM engineering inference.

    Called AFTER standards are applied so it only fills fields the standards docs
    didn't cover.  Every inferred string value is tagged with ' [inferred]' so the
    user knows the value is an engineering estimate rather than a document-sourced value.
    Hardware-specific fields (serials, calibration coefficients, tags) are never touched.
    """
    if not asset_type:
        return instrument_config
    if not _has_empty_inferrable_fields(instrument_config):
        logger.info("[ASSET_CONFIG_RAG] All inferrable HART fields already populated — skipping inference")
        return instrument_config

    try:
        from common.ai.prompts.templates import HART_CONFIG_INFERENCE_PROMPT
        from common.ai.llm import get_flash_llm

        ic_json = json.dumps(instrument_config, indent=2, default=str)
        prompt = HART_CONFIG_INFERENCE_PROMPT.format(
            asset_type=asset_type,
            equipment_category=equipment_category or asset_type,
            instrument_config_json=ic_json,
        )

        llm      = get_flash_llm(temperature=0.1)
        response = llm.invoke(prompt)
        raw_text = response.content if hasattr(response, "content") else str(response)

        logger.debug(f"[ASSET_CONFIG_RAG] HART inference raw response ({len(raw_text)} chars): {raw_text[:300]}")

        inferred = _extract_json_robust(raw_text)
        if not inferred:
            logger.warning(
                f"[ASSET_CONFIG_RAG] HART inference: could not parse LLM response "
                f"({len(raw_text)} chars). First 200: {raw_text[:200]!r}"
            )
            return instrument_config

        # Merge: only overwrite fields that are still empty
        for section in INSTRUMENT_CONFIG_SCHEMA:
            sec_inferred = inferred.get(section, {})
            if not isinstance(sec_inferred, dict):
                continue
            if section not in instrument_config or not isinstance(instrument_config[section], dict):
                instrument_config[section] = {}
            for field, inferred_val in sec_inferred.items():
                if field in _HARDWARE_SPECIFIC_FIELDS:
                    continue
                current = instrument_config[section].get(field)
                # Only write if currently empty (empty string, None, or default-false bool)
                if current and current != "":
                    continue
                if field in _BOOLEAN_FIELDS:
                    if current is False or current is None:
                        instrument_config[section][field] = bool(inferred_val)
                else:
                    if inferred_val and inferred_val != "":
                        instrument_config[section][field] = inferred_val

        populated = sum(
            1 for sec in INSTRUMENT_CONFIG_SCHEMA
            for fld in INSTRUMENT_CONFIG_SCHEMA[sec]
            if fld not in _HARDWARE_SPECIFIC_FIELDS
            and instrument_config.get(sec, {}).get(fld)
        )
        logger.info(f"[ASSET_CONFIG_RAG] HART inference complete — {populated} fields now populated")

    except Exception as e:
        logger.warning(f"[ASSET_CONFIG_RAG] HART inference failed (non-critical): {e}")

    return instrument_config


# ============================================================================
# COLLECTION HELPERS
# ============================================================================

def get_assets_collection():
    """Get MongoDB collection for raw assets documents."""
    try:
        conn = get_mongodb_connection()
        return conn['collections'][ASSETS_COLLECTION_NAME]
    except Exception as e:
        logger.error(f"[RAG] Failed to get assets collection: {e}")
        return None


def get_asset_config_collection():
    """Get MongoDB collection for asset configurations."""
    try:
        conn = get_mongodb_connection()
        return conn['collections']['asset_configurations']
    except Exception as e:
        logger.error(f"[RAG] Failed to get asset_configurations collection: {e}")
        return None


def get_instrument_logs_collection():
    """Get MongoDB collection for instrument logs."""
    try:
        conn = get_mongodb_connection()
        return conn['collections']['instrument_logs']
    except Exception as e:
        logger.error(f"[RAG] Failed to get instrument_logs collection: {e}")
        return None


def get_diagnostic_codes_collection():
    """Get MongoDB collection for diagnostic codes."""
    try:
        conn = get_mongodb_connection()
        return conn['collections']['diagnostic_codes']
    except Exception as e:
        logger.error(f"[RAG] Failed to get diagnostic_codes collection: {e}")
        return None


def get_diagnostic_sessions_collection():
    """Get MongoDB collection for diagnostic sessions."""
    try:
        conn = get_mongodb_connection()
        return conn['collections']['diagnostic_sessions']
    except Exception as e:
        logger.error(f"[RAG] Failed to get diagnostic_sessions collection: {e}")
        return None


# ============================================================================
# ASSETS RAG — blob/CSV extraction
# ============================================================================

def _load_assets_entries_from_embeddings_sas_url(sas_url: str, filename: str) -> list[dict[str, Any]] | None:
    """Load previously extracted asset entries (with embeddings) from a gzip-compressed JSON blob."""
    try:
        import requests
        logger.info(f"[ASSETS_RAG] Downloading embeddings payload: {filename}")
        response = requests.get(sas_url, timeout=120)
        response.raise_for_status()
        raw_bytes = response.content
        decompressed = gzip.decompress(raw_bytes)
        logger.info(
            f"[ASSETS_RAG] Decompressed: "
            f"{len(raw_bytes)/(1024*1024):.2f} MB → {len(decompressed)/(1024*1024):.2f} MB"
        )
        payload = json.loads(decompressed.decode('utf-8'))
        data = payload.get('data')
        if not isinstance(data, list):
            logger.warning(f"[ASSETS_RAG] Embeddings payload missing 'data' array: {filename}")
            return None
        return data
    except Exception as e:
        logger.error(f"[ASSETS_RAG] Failed to load embeddings payload: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _extract_csv_assets_from_sas_url(sas_url: str, filename: str) -> list[dict[str, Any]] | None:
    """Extract asset data from a CSV file via SAS URL (direct pandas parsing, no LLM)."""
    try:
        from io import StringIO

        import pandas as pd
        import requests

        logger.info(f"[ASSETS_RAG] Downloading CSV: {filename}")
        response = requests.get(sas_url, timeout=30)
        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))
        logger.info(f"[ASSETS_RAG] Parsed CSV: {len(df)} rows, {len(df.columns)} columns")

        df.columns = df.columns.str.strip().str.lower()
        column_mapping = {
            'asset': 'asset_name', 'name': 'asset_name', 'equipment_name': 'asset_name',
            'equipment': 'asset_name', 'type': 'asset_type', 'equipment_type': 'asset_type',
            'category': 'asset_type', 'vendor': 'manufacturer', 'supplier': 'manufacturer',
            'make': 'manufacturer', 'site': 'location', 'plant': 'location',
            'facility': 'location', 'model_number': 'model', 'serial': 'serial_number',
            'sn': 'serial_number', 'tag': 'tag_number', 'tag_no': 'tag_number',
            'tag_id': 'tag_number', 'tag number': 'tag_number', 'tag_num': 'tag_number',
            'tag no': 'tag_number', 'tag no.': 'tag_number', 'instrument_tag': 'tag_number',
            'instrument tag': 'tag_number', 'loop_tag': 'tag_number', 'loop tag': 'tag_number',
        }
        df.rename(columns=column_mapping, inplace=True)

        assets_entries = df.to_dict('records')
        for entry in assets_entries:
            for key in entry:
                value = entry[key]
                if pd.isna(value) or value is None:
                    entry[key] = ''
                else:
                    entry[key] = str(value).strip()

        logger.info(f"[ASSETS_RAG] Extracted {len(assets_entries)} entries from CSV")
        return assets_entries

    except Exception as e:
        logger.error(f"[ASSETS_RAG] Failed to extract CSV: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _get_or_refresh_sas_url(collection, doc, blob_url_key: str, cached_url_key: str,
                             cached_expiry_key: str, log_prefix: str) -> str | None:
    """
    Reusable SAS URL caching logic.
    Checks cached URL expiry, refreshes if stale, persists back to MongoDB.
    """
    from common.infra.blob_sas import generate_sas_url

    cached_sas    = doc.get('storage', {}).get(cached_url_key)
    cached_expiry = doc.get('storage', {}).get(cached_expiry_key)
    blob_url      = doc.get('storage', {}).get(blob_url_key)

    sas_url = None
    if cached_sas and cached_expiry:
        try:
            expiry_dt = datetime.fromisoformat(cached_expiry)
            if datetime.now(UTC) < expiry_dt:
                sas_url = cached_sas
                logger.info(f"[{log_prefix}] ✓ Reusing cached SAS URL")
        except Exception:
            pass

    if not sas_url and blob_url:
        sas_url = generate_sas_url(blob_url, expiry_hours=24)
        if sas_url:
            sas_expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
            collection.update_one(
                {'_id': doc['_id']},
                {'$set': {
                    f'storage.{cached_url_key}': sas_url,
                    f'storage.{cached_expiry_key}': sas_expiry,
                }}
            )
            logger.info(f"[{log_prefix}] ✓ Generated and cached new SAS URL")

    return sas_url


def extract_assets_on_demand(user_id: str) -> dict[str, Any]:
    """
    Extract assets data from blob storage on-demand for a user.
    Uses SAS URL caching to avoid regenerating URLs.
    """
    try:
        assets_collection = get_assets_collection()
        if assets_collection is None:
            return {"success": False, "error": "Collection not available"}

        documents = list(assets_collection.find(build_user_id_filter(user_id)))
        if not documents:
            logger.info(f"[ASSETS_RAG] No documents found for user {user_id}")
            return {"success": False, "error": "No assets documents found"}

        total_extracted = 0

        for doc in documents:
            data_array = doc.get('data', [])
            filename   = doc.get('filename', 'unknown')

            # --- Path 1: load from embeddings blob ---
            if (not data_array) and doc.get('storage', {}).get('embeddingsBlobUrl'):
                sas_url = _get_or_refresh_sas_url(
                    assets_collection, doc,
                    blob_url_key='embeddingsBlobUrl',
                    cached_url_key='cachedEmbeddingsSasUrl',
                    cached_expiry_key='embeddingsSasUrlExpiry',
                    log_prefix='ASSETS_RAG'
                )
                if not sas_url:
                    logger.error(f"[ASSETS_RAG] Failed to get embeddings SAS URL for {filename}")
                    continue
                extracted_data = _load_assets_entries_from_embeddings_sas_url(sas_url, filename)
                if extracted_data:
                    doc['data'] = extracted_data
                    total_extracted += len(extracted_data)
                    logger.info(f"[ASSETS_RAG] ✓ Loaded {len(extracted_data)} entries from embeddings blob")
                else:
                    logger.warning(f"[ASSETS_RAG] Failed to load embeddings payload for {filename}")
                continue

            # --- Path 2: extract from raw blob ---
            if (not data_array) and doc.get('storage', {}).get('blobUrl'):
                sas_url = _get_or_refresh_sas_url(
                    assets_collection, doc,
                    blob_url_key='blobUrl',
                    cached_url_key='cachedSasUrl',
                    cached_expiry_key='sasUrlExpiry',
                    log_prefix='ASSETS_RAG'
                )
                if not sas_url:
                    logger.error(f"[ASSETS_RAG] Failed to get SAS URL for {filename}")
                    continue

                file_ext = filename.lower().split('.')[-1] if '.' in filename else ''
                if file_ext != 'csv':
                    logger.warning(f"[ASSETS_RAG] Only CSV supported, got: {file_ext}")
                    continue

                extracted_data = _extract_csv_assets_from_sas_url(sas_url, filename)
                if extracted_data:
                    assets_collection.update_one(
                        {'_id': doc['_id']},
                        {'$set': {
                            'entry_count': len(extracted_data),
                            'extracted_at': datetime.now(UTC).isoformat(),
                            'extraction_method': 'csv_direct_parse',
                        }}
                    )
                    total_extracted += len(extracted_data)
                    logger.info(f"[ASSETS_RAG] ✓ Extracted {len(extracted_data)} entries from CSV")
                else:
                    logger.warning(f"[ASSETS_RAG] Failed to parse CSV: {filename}")

        return {
            "success": True,
            "message": f"Extracted {total_extracted} assets entries",
            "entry_count": total_extracted,
        }

    except Exception as e:
        logger.error(f"[ASSETS_RAG] Extraction failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


def delete_user_assets_data(user_id: str) -> dict[str, Any]:
    """Delete all assets data for a user."""
    try:
        assets_collection = get_assets_collection()
        if assets_collection is None:
            return {"success": False, "error": "Collection not available"}

        result = assets_collection.delete_many(build_user_id_filter(user_id))
        logger.info(f"[ASSETS_RAG] Deleted {result.deleted_count} documents for user {user_id}")
        return {"success": True, "deleted_count": result.deleted_count}
    except Exception as e:
        logger.error(f"[ASSETS_RAG] Deletion failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# ASSET CONFIG RAG — CRUD, LLM extraction, YAML generation
# ============================================================================

# --- Gap detection helpers ---------------------------------------------------

def _get_nested(obj: dict, dotted_key: str) -> str:
    """Get a nested dict value using dot notation, e.g. 'asset.asset_name'."""
    keys = dotted_key.split(".")
    val  = obj
    for k in keys:
        if not isinstance(val, dict):
            return ""
        val = val.get(k, "")
    return val if isinstance(val, str) else ""


def detect_config_gaps(config: dict) -> list[str]:
    """
    Detect missing or empty fields in a configuration.
    Returns a list of human-readable gap descriptions.
    """
    gaps = []
    for field_path, label in REQUIRED_FIELDS.items():
        if not _get_nested(config, field_path).strip():
            gaps.append(f"{label} not specified")
    for field_path, label in RECOMMENDED_FIELDS.items():
        if not _get_nested(config, field_path).strip():
            gaps.append(f"{label} not provided (recommended)")

    relationships = config.get("relationships", {})
    migration = relationships.get("migration", {})
    if migration.get("enabled") and not _get_nested(config, "target_system.name").strip():
        gaps.append("Migration enabled but target system not specified")
    integration = relationships.get("integration", {})
    if integration.get("enabled") and not _get_nested(config, "connected_system.protocol").strip():
        gaps.append("Integration enabled but connection protocol not specified")
    return gaps


# --- CRUD -------------------------------------------------------------------

def list_configurations(user_id) -> list[dict]:
    """List all saved configurations for a user, sorted by updated_at desc."""
    collection = get_asset_config_collection()
    if collection is None:
        return []
    docs = list(collection.find(build_user_id_filter(user_id)).sort("updated_at", -1))
    for doc in docs:
        doc['_id'] = str(doc['_id'])
    return docs


def create_configuration(user_id, config_data: dict) -> dict:
    """Create a new asset configuration document."""
    collection = get_asset_config_collection()
    if collection is None:
        return {"success": False, "error": "Database connection failed"}

    configuration_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    document = {
        "configuration_id": configuration_id,
        "user_id": user_id,
        "status": "draft",
        "asset":             config_data.get("asset", {}),
        "location":          config_data.get("location", {}),
        "connected_system":  config_data.get("connected_system", {}),
        "target_system":     config_data.get("target_system", {}),
        "relationships":     config_data.get("relationships", {}),
        "instrument_config": config_data.get("instrument_config", {}),
        "yaml_content":      None,
        "yaml_generated_at": None,
        "gaps":              [],
        "standards_applied": [],
        "created_at":        now,
        "updated_at":        now,
    }
    collection.insert_one(document)
    return {"success": True, "configuration_id": configuration_id}


def update_configuration(user_id, configuration_id: str, config_data: dict) -> dict:
    """Update an existing asset configuration."""
    collection = get_asset_config_collection()
    if collection is None:
        return {"success": False, "error": "Database connection failed"}

    update_fields = {"updated_at": datetime.now(UTC).isoformat()}
    for key in ("asset", "location", "connected_system", "target_system", "relationships", "instrument_config"):
        if key in config_data:
            update_fields[key] = config_data[key]

    search_filter = build_user_id_filter(user_id, {"configuration_id": configuration_id})
    result = collection.update_one(search_filter, {"$set": update_fields})
    if result.matched_count == 0:
        return {"success": False, "error": "Configuration not found"}
    return {"success": True}


def delete_configuration(user_id, configuration_id: str) -> dict:
    """Delete an asset configuration."""
    collection = get_asset_config_collection()
    if collection is None:
        return {"success": False, "error": "Database connection failed"}

    search_filter = build_user_id_filter(user_id, {"configuration_id": configuration_id})
    result = collection.delete_one(search_filter)
    if result.deleted_count == 0:
        return {"success": False, "error": "Configuration not found"}
    return {"success": True}


# --- LLM extraction helpers -------------------------------------------------

def _load_user_assets_from_db(user_id) -> list[dict]:
    """Load all asset entries for a user from the assets MongoDB collection (inline data only)."""
    try:
        conn = get_mongodb_connection()
        assets_col = conn['collections']['assets']
        documents  = list(assets_col.find(build_user_id_filter(user_id)))
        all_entries = []
        for doc in documents:
            data_array = doc.get("data", [])
            if isinstance(data_array, list) and data_array:
                all_entries.extend(data_array)
        logger.info(f"[ASSET_CONFIG_RAG] Loaded {len(all_entries)} asset entries for user {user_id}")
        return all_entries
    except Exception as e:
        logger.warning(f"[ASSET_CONFIG_RAG] Could not load assets from DB: {e}")
        return []


def _build_asset_inventory_context(user_id) -> str:
    """Build a summarised asset inventory string for LLM context."""
    try:
        all_assets = _load_user_assets_from_db(user_id)
        if not all_assets:
            return "(No existing assets found in inventory)"
        lines = []
        for i, asset in enumerate(all_assets[:50]):
            name         = asset.get("asset_name", asset.get("name", ""))
            tag          = asset.get("tag_number", asset.get("tag", ""))
            atype        = asset.get("asset_type", asset.get("type", asset.get("category", "")))
            manufacturer = asset.get("manufacturer", asset.get("vendor", ""))
            model        = asset.get("model", "")
            location     = asset.get("location", asset.get("site", ""))
            serial       = asset.get("serial_number", asset.get("serial", ""))
            parts = []
            if name:         parts.append(f"Name: {name}")
            if tag:          parts.append(f"Tag: {tag}")
            if atype:        parts.append(f"Type: {atype}")
            if manufacturer: parts.append(f"Mfr: {manufacturer}")
            if model:        parts.append(f"Model: {model}")
            if location:     parts.append(f"Location: {location}")
            if serial:       parts.append(f"Serial: {serial}")
            if parts:
                lines.append(f"  {i+1}. {' | '.join(parts)}")
        total  = len(all_assets)
        header = f"Total assets in inventory: {total}"
        if total > 50:
            header += " (showing first 50)"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"[ASSET_CONFIG_RAG] Could not build asset inventory context: {e}")
        return "(Could not load asset inventory)"


# Fields in the asset section that must NOT be auto-filled from the CSV inventory
# — they must come from the user directly.
_ASSET_SUGGEST_ONLY = frozenset({"model", "serial_number"})

# Location fields that must NOT be auto-filled from the CSV inventory
_LOCATION_SUGGEST_ONLY = frozenset({"plant", "site", "area"})

# Human-readable follow-up questions for each missing required identity field
_REQUIRED_FIELD_QUESTIONS: dict[str, str] = {
    "Equipment model": "What is the exact equipment model number?",
    "Serial number":   "What is the serial number of this device?",
    "Site":            "What site is this asset installed at?",
    "Plant":           "What is the plant name?",
    "Area":            "What area within the plant is the asset located in?",
}


def _build_follow_up_questions(missing_labels: list[str]) -> list[str]:
    """Return a list of natural-language questions for each missing required field label."""
    return [_REQUIRED_FIELD_QUESTIONS.get(label, f"Please provide the {label}.") for label in missing_labels]


def _find_matching_asset_from_db(user_id, asset_name: str, asset_type: str, tag_number: str = "") -> dict | None:
    """Search the user's assets for the best-matching entry (used to ground LLM extraction)."""
    try:
        all_assets = _load_user_assets_from_db(user_id)
        if not all_assets:
            return None

        name_lower = asset_name.strip().lower()
        type_lower = asset_type.strip().lower()
        tag_lower  = tag_number.strip().lower()
        best, best_score = None, 0

        for entry in all_assets:
            e_name = str(entry.get("asset_name", entry.get("name", ""))).strip().lower()
            e_type = str(entry.get("asset_type", entry.get("type", entry.get("category", "")))).strip().lower()
            e_tag  = str(entry.get("tag_number", entry.get("tag", ""))).strip().lower()
            score  = 0
            if tag_lower and e_tag and tag_lower == e_tag:
                score += 10
            if name_lower and e_name:
                if name_lower in e_name or e_name in name_lower:
                    score += 5
                elif any(w in e_name for w in name_lower.split() if len(w) > 3):
                    score += 2
            if type_lower and e_type:
                if type_lower in e_type or e_type in type_lower:
                    score += 3
            if score > best_score:
                best_score = score
                best = entry

        if best and best_score >= 2:
            logger.info(f"[ASSET_CONFIG_RAG] ✅ Grounded match (score={best_score}): {best.get('asset_name', best.get('name', ''))}")
            return best
        return None
    except Exception as e:
        logger.warning(f"[ASSET_CONFIG_RAG] Asset DB match failed: {e}")
        return None


def _extract_json_robust(raw_text: str) -> dict | None:
    """
    Extract a JSON object from LLM output that may contain:
      - Markdown code fences  (```json ... ```)
      - Preamble / postamble prose
      - Escaped unicode characters

    Strategy:
      1. Strip leading/trailing fences
      2. Find first '{'
      3. Walk character-by-character counting brace depth to find matching '}'
      4. json.loads() on the slice
      5. Fallback: ast.literal_eval() for edge cases
    Returns None if all strategies fail.
    """
    import ast
    import json
    import re

    if not raw_text:
        return None

    # Step 1 — strip markdown fences (opening and closing)
    text = raw_text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    # Step 2 — fast path: text already starts with '{'
    if not text.startswith("{"):
        m = re.search(r"\{", text)
        if not m:
            return None
        text = text[m.start():]

    # Step 3 — brace-balance walk to find the end of the outermost object
    depth, end_idx = 0, -1
    in_str, escape = False, False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break

    if end_idx != -1:
        text = text[: end_idx + 1]

    # Step 4 — json.loads
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Step 5 — ast.literal_eval (handles Python-style True/False/None)
    try:
        result = ast.literal_eval(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    return None


def _parse_llm_json(raw_text: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown fences and extra text."""
    result = _extract_json_robust(raw_text)
    if result is not None:
        return result
    # Legacy fallback: scan for any {...} substring
    import json
    brace_start = raw_text.find("{")
    brace_end   = raw_text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(raw_text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass
    return None


def extract_config_from_text(message: str, user_id, context: dict | None = None) -> dict:
    """
    Extract structured asset configuration from natural language using LLM.
    Cross-references with existing assets, fetches standards, and applies them.

    context (optional): dict with keys
        asset_type         — from prior extraction (used as fallback when follow-up
                             message doesn't re-state the device type)
        equipment_category — from prior taxonomy match
        instrument_config  — current frontend state; non-empty fields are merged
                             into the new extraction BEFORE inference so that
                             LLM-inferred defaults can be filled in a second turn
    """
    try:
        from common.ai.llm import get_flash_llm

        asset_inventory = _build_asset_inventory_context(user_id)

        # Phase 1: LLM extracts intent, asset type, and user-stated values.
        # Standards application is done separately after asset_type is known.
        prompt = ASSET_CONFIG_EXTRACTION_PROMPT.format(
            asset_inventory=asset_inventory,
            message=message,
        )
        llm      = get_flash_llm(temperature=0.1)
        response = llm.invoke(prompt)
        raw_text = response.content if hasattr(response, 'content') else str(response)

        parsed = _parse_llm_json(raw_text)
        if not parsed:
            logger.error(f"[ASSET_CONFIG_RAG] Failed to parse LLM response: {raw_text[:500]}")
            return {"success": False, "error": "Failed to parse extraction result"}

        extracted = {
            "asset":             parsed.get("asset", {}),
            "location":          parsed.get("location", {}),
            "connected_system":  parsed.get("connected_system", {}),
            "target_system":     parsed.get("target_system", {}),
            "relationships":     parsed.get("relationships", {}),
            "instrument_config": parsed.get("instrument_config", {}),
        }

        # Ground with DB data — protected fields go to csv_suggestions, NOT directly into extracted
        db_asset = _find_matching_asset_from_db(
            user_id,
            extracted.get("asset", {}).get("asset_name", ""),
            extracted.get("asset", {}).get("asset_type", ""),
            extracted.get("asset", {}).get("tag_number", ""),
        )
        csv_suggestions: dict = {}
        if db_asset:
            asset_section = extracted.get("asset", {})
            field_map = {
                "asset_name":    ["asset_name", "name"],
                "asset_type":    ["asset_type", "type", "category"],
                "tag_number":    ["tag_number", "tag", "tag_no"],
                "manufacturer":  ["manufacturer", "vendor"],
                "model":         ["model", "model_number"],
                "serial_number": ["serial_number", "serial", "sn"],
            }
            for target_key, source_keys in field_map.items():
                for sk in source_keys:
                    val = str(db_asset.get(sk, "")).strip()
                    if val:
                        if target_key in _ASSET_SUGGEST_ONLY:
                            # Surface to user for confirmation — do NOT silently write
                            if not asset_section.get(target_key):
                                csv_suggestions[target_key] = val
                        else:
                            asset_section[target_key] = val
                        break
            extracted["asset"] = asset_section

            location_section = extracted.get("location", {})
            for loc_key in ["plant", "site", "area", "unit", "location"]:
                val = str(db_asset.get(loc_key, "")).strip()
                if val:
                    if loc_key in _LOCATION_SUGGEST_ONLY:
                        # Surface to user for confirmation — do NOT silently write
                        if not location_section.get(loc_key):
                            csv_suggestions[loc_key] = val
                    elif not location_section.get(loc_key):
                        location_section[loc_key] = val
            if db_asset.get("location") and not location_section.get("site") and "site" not in csv_suggestions:
                csv_suggestions["site"] = str(db_asset.get("location", "")).strip()
            extracted["location"] = location_section

            ic = extracted.get("instrument_config", {})
            if not isinstance(ic, dict):
                ic = {}
            hi = ic.get("hart_identity", {})
            if not isinstance(hi, dict):
                hi = {}
            if db_asset.get("serial_number") and not hi.get("sensor_serial"):
                hi["sensor_serial"] = str(db_asset["serial_number"]).strip()
            if db_asset.get("hart_tag") and not hi.get("hart_tag"):
                hi["hart_tag"] = str(db_asset["hart_tag"]).strip()
            ic["hart_identity"] = hi
            extracted["instrument_config"] = ic
        else:
            logger.info("[ASSET_CONFIG_RAG] No DB asset match — using LLM extraction only")

        # ── Phase 2: Standards + taxonomy + inference ─────────────────────────
        # Run BEFORE the validation gate so HART config fields are filled even
        # when identity fields (model/serial/site) are missing.  Inference
        # results are included in BOTH the 'complete' and 'incomplete' responses.
        standards_result = None
        taxonomy_result  = None
        asset_type       = extracted.get("asset", {}).get("asset_type", "")

        # Context fallback: restore asset_type from a prior turn when the
        # follow-up message doesn't re-state the device type.
        if not asset_type and context:
            ctx_asset_type = (context.get("asset_type") or "").strip()
            if ctx_asset_type:
                asset_type = ctx_asset_type
                if not extracted.get("asset"):
                    extracted["asset"] = {}
                extracted["asset"]["asset_type"] = asset_type
                logger.info(f"[ASSET_CONFIG_RAG] asset_type restored from context: {asset_type!r}")

        if asset_type:
            import concurrent.futures

            from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
            from common.ai.rag.taxonomy_rag import get_taxonomy_for_category
            def _fetch_std():
                return ProductHierarchyRepository.get_standards_for_category(user_id, asset_type)

            def _fetch_tax():
                return get_taxonomy_for_category(asset_type)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_std = executor.submit(_fetch_std)
                f_tax = executor.submit(_fetch_tax)
                try:
                    standards_result = f_std.result()
                except Exception as e:
                    logger.warning(f"Parallel Standards RAG failed: {e}")
                try:
                    taxonomy_result = f_tax.result()
                except Exception as e:
                    logger.warning(f"Parallel Taxonomy RAG failed: {e}")

            ic = extracted.get("instrument_config", {})
            if not isinstance(ic, dict):
                ic = {}

            # Apply taxonomy for equipment_category
            if taxonomy_result and taxonomy_result.get("found"):
                if "hart_identity" not in ic:
                    ic["hart_identity"] = {}
                if isinstance(ic["hart_identity"], dict) and not ic["hart_identity"].get("equipment_category"):
                    ic["hart_identity"]["equipment_category"] = taxonomy_result.get("matched_category", "")

            # ═══════════════════════════════════════════════════════════════════
            # APPLY STANDARDS TO INSTRUMENT CONFIG
            # This is the key fix: populate instrument_config fields from standards DB
            # ═══════════════════════════════════════════════════════════════════
            if standards_result and standards_result.get("found"):
                standards_specs = standards_result.get("specifications", {})
                if standards_specs:
                    logger.info(f"[ASSET_CONFIG_RAG] Applying {len(standards_specs)} standards specs to instrument_config")
                    ic = apply_standards_to_instrument_config(ic, standards_specs)

            # ═══════════════════════════════════════════════════════════════════
            # MERGE PRIOR-TURN CONTEXT INTO ic (follow-up message support)
            # When this is a second/third turn (user provided only identity fields),
            # the new LLM extraction returns mostly-empty instrument_config.
            # Restore non-empty values from the frontend's current state so that
            # inference below gets the full picture and fills only truly-empty fields.
            # ═══════════════════════════════════════════════════════════════════
            if context and isinstance(context.get("instrument_config"), dict):
                ctx_ic = context["instrument_config"]
                for section in INSTRUMENT_CONFIG_SCHEMA:
                    ctx_sec = ctx_ic.get(section, {})
                    if not isinstance(ctx_sec, dict):
                        continue
                    if section not in ic or not isinstance(ic.get(section), dict):
                        ic[section] = {}
                    for field in INSTRUMENT_CONFIG_SCHEMA[section]:
                        ctx_val = ctx_sec.get(field)
                        cur_val = ic[section].get(field)
                        # Restore: only if current extraction is empty and context has a real value
                        cur_empty = not cur_val or cur_val == "" or cur_val is False
                        ctx_has_val = ctx_val and ctx_val != "" and ctx_val is not False
                        if cur_empty and ctx_has_val:
                            ic[section][field] = ctx_val
                logger.debug("[ASSET_CONFIG_RAG] Merged prior-turn instrument_config from context")

            # ═══════════════════════════════════════════════════════════════════
            # INFER REMAINING HART CONFIG DEFAULTS
            # For any HART fields still empty after standards, use LLM engineering
            # knowledge to fill in typical defaults (tagged as [inferred]).
            # ═══════════════════════════════════════════════════════════════════
            equipment_cat = ic.get("hart_identity", {}).get("equipment_category", "")
            ic = _infer_hart_config_defaults(ic, asset_type, equipment_cat or asset_type)

            extracted["instrument_config"] = ic

        # ── Phase 3: Validation gate ───────────────────────────────────────
        # Checked AFTER standards+inference so the incomplete response
        # still carries fully-populated HART config fields.
        from common.helpers.config_validator import validate_required_equipment_fields
        fields_valid, missing_req = validate_required_equipment_fields(extracted)
        if not fields_valid:
            follow_up_q = _build_follow_up_questions(missing_req)
            all_gaps = list(dict.fromkeys(parsed.get("gaps", []) + detect_config_gaps(extracted)))
            # Build standards_applied for the incomplete response too
            std_applied_incomplete = {}
            if standards_result and standards_result.get("found"):
                std_applied_incomplete = {
                    "source_document": standards_result.get("source_document"),
                    "specifications":  standards_result.get("specifications", {}),
                }
            return {
                "success":                True,
                "status":                 "incomplete",
                "extracted":              extracted,
                "csv_suggestions":        csv_suggestions,
                "standards_applied":      std_applied_incomplete,
                "missing_required_fields": missing_req,
                "follow_up_questions":    follow_up_q,
                "gaps":                   all_gaps,
                "reply": (
                    "I need a few more details before I can complete this configuration. "
                    + follow_up_q[0]
                    + (f" (I also need: {', '.join(follow_up_q[1:])})" if len(follow_up_q) > 1 else "")
                ),
            }

        # Detect gaps
        all_gaps = list(dict.fromkeys(parsed.get("gaps", []) + detect_config_gaps(extracted)))

        # Build standards info for response
        standards_applied = {}
        if standards_result and standards_result.get("found"):
            standards_applied = {
                "source_document": standards_result.get("source_document"),
                "specifications":  standards_result.get("specifications", {}),
            }

        # Auto-generate YAML if enough data
        yaml_content = None
        if extracted.get("asset", {}).get("asset_name") and asset_type:
            try:
                yaml_result = _generate_yaml_internal(
                    extracted, user_id,
                    standards_result=standards_result,
                    taxonomy_result=taxonomy_result,
                )
                if yaml_result.get("success"):
                    yaml_content = yaml_result.get("yaml_content")
            except Exception as e:
                logger.warning(f"[ASSET_CONFIG_RAG] YAML generation skipped: {e}")

        return {
            "success":           True,
            "status":            "complete",
            "extracted":         extracted,
            "csv_suggestions":   csv_suggestions,
            "standards_applied": standards_applied,
            "gaps":              all_gaps,
            "yaml_content":      yaml_content,
            "reply":             parsed.get("reply", "Configuration extracted from your description."),
        }

    except Exception as e:
        logger.error(f"[ASSET_CONFIG_RAG] Extraction failed: {e}", exc_info=True)
        return {"success": False, "error": f"Extraction failed: {str(e)}"}


def _generate_yaml_internal(config: dict, user_id, standards_result=None, taxonomy_result=None) -> dict:
    """Internal YAML generation logic — combines config with standards and taxonomy data."""
    import re

    from common.ai.llm import get_flash_llm

    asset_type      = config.get("asset", {}).get("asset_type", "")
    standards_specs = ""
    standards_applied = []
    taxonomy_info   = ""

    if asset_type:
        try:
            if not standards_result:
                from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
                standards_result = ProductHierarchyRepository.get_standards_for_category(user_id, asset_type)
            if standards_result.get("found"):
                specs = standards_result.get("specifications", {})
                standards_specs = json.dumps(specs, indent=2, default=str)
                source_doc = standards_result.get("source_document", "")
                if source_doc:
                    standards_applied.append(source_doc)
            else:
                standards_specs = f"({standards_result.get('message', 'No standards found')})"
        except Exception as e:
            logger.warning(f"[ASSET_CONFIG_RAG] Standards RAG failed: {e}")
            standards_specs = "(Standards lookup unavailable)"

        try:
            if not taxonomy_result:
                from common.ai.rag.taxonomy_rag import get_taxonomy_for_category
                taxonomy_result = get_taxonomy_for_category(asset_type)
            if taxonomy_result and taxonomy_result.get("found"):
                taxonomy_info = json.dumps(taxonomy_result, indent=2, default=str)
            else:
                taxonomy_info = "(No taxonomy mapping found)"
        except Exception as e:
            logger.warning(f"[ASSET_CONFIG_RAG] Taxonomy RAG failed: {e}")
            taxonomy_info = "(Taxonomy lookup unavailable)"

    if not standards_specs:
        standards_specs = "(No standards data available)"
    if not taxonomy_info:
        taxonomy_info = "(No taxonomy data available)"

    prompt = ASSET_CONFIG_YAML_GENERATION_PROMPT.format(
        config_json=json.dumps(config, indent=2, default=str),
        standards_specs=standards_specs,
        taxonomy_info=taxonomy_info,
    )
    llm      = get_flash_llm(temperature=0.1)
    response = llm.invoke(prompt)
    yaml_content = response.content if hasattr(response, 'content') else str(response)

    yaml_content = yaml_content.strip()
    if yaml_content.startswith("```"):
        lines = [line for line in yaml_content.split("\n") if not line.strip().startswith("```")]
        yaml_content = "\n".join(lines).strip()

    TODO_PATTERN = re.compile(r'\s*#\s*(TODO|Specify|TBD|Fill in|Placeholder)[^#\n]*', re.IGNORECASE)
    yaml_content = "\n".join(TODO_PATTERN.sub("", line).rstrip() for line in yaml_content.split("\n"))

    return {"success": True, "yaml_content": yaml_content, "standards_applied": standards_applied}


def generate_yaml_for_config(configuration_id: str, user_id) -> dict:
    """
    Generate YAML for a saved configuration, persist it to MongoDB, and return it.
    """
    collection = get_asset_config_collection()
    if collection is None:
        return {"success": False, "error": "Database connection failed"}

    search_filter = build_user_id_filter(user_id, {"configuration_id": configuration_id})
    config_doc    = collection.find_one(search_filter)
    if not config_doc:
        return {"success": False, "error": "Configuration not found"}

    config = {k: config_doc.get(k, {}) for k in
              ("asset", "location", "connected_system", "target_system", "relationships", "instrument_config")}

    from common.helpers.config_validator import validate_required_equipment_fields
    valid, missing = validate_required_equipment_fields(config)
    if not valid:
        return {
            "success": False,
            "error":   "missing_required_fields",
            "missing": missing,
            "message": "Cannot generate YAML until these fields are provided: " + ", ".join(missing),
        }

    result = _generate_yaml_internal(config, user_id)
    if result.get("success"):
        now = datetime.now(UTC).isoformat()
        collection.update_one(
            {"_id": config_doc["_id"]},
            {"$set": {
                "yaml_content":      result["yaml_content"],
                "yaml_generated_at": now,
                "standards_applied": result.get("standards_applied", []),
                "status":            "configured",
                "updated_at":        now,
            }}
        )
    return result


# ============================================================================
# DIAGNOSTICS RAG — instrument log analysis and semantic search
# ============================================================================

def _build_log_embedding_text(log_entry: dict) -> str:
    """Build searchable text from a log entry for embedding generation."""
    parts = []
    if log_entry.get('tag_number'):
        parts.append(f"Instrument {log_entry['tag_number']}")
    if log_entry.get('log_type'):
        parts.append(f"Type: {log_entry['log_type']}")
    if log_entry.get('value') is not None:
        unit = log_entry.get('unit', '')
        parts.append(f"Value: {log_entry['value']} {unit}".strip())
    if log_entry.get('alarm_type'):
        parts.append(f"Alarm: {log_entry['alarm_type']}")
    if log_entry.get('severity') and log_entry['severity'] != SEVERITY_INFO:
        parts.append(f"Severity: {log_entry['severity']}")
    if log_entry.get('message'):
        parts.append(log_entry['message'])
    return " | ".join(parts) if parts else "Log entry"


def ingest_instrument_logs(
    user_id: str,
    logs_data: list[dict[str, Any]],
    asset_id: str | None = None,
    source_file: str | None = None,
    generate_embeddings: bool = True,
) -> dict[str, Any]:
    """
    Ingest instrument log entries into MongoDB with optional embeddings.
    """
    try:
        collection = get_instrument_logs_collection()
        if collection is None:
            return {"success": False, "error": "Collection not available"}

        from common.ai.embedding_manager import generate_embeddings_batch

        processed_logs = []
        embedding_texts = []

        for log_entry in logs_data:
            timestamp = log_entry.get('timestamp')
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except ValueError:
                    timestamp = datetime.now(UTC)
            elif timestamp is None:
                timestamp = datetime.now(UTC)

            processed = {
                'user_id':      int(user_id) if str(user_id).isdigit() else user_id,
                'asset_id':     asset_id,
                'timestamp':    timestamp,
                'tag_number':   log_entry.get('tag_number', '').strip(),
                'log_type':     log_entry.get('log_type', LOG_TYPE_READING),
                'value':        log_entry.get('value'),
                'unit':         log_entry.get('unit', ''),
                'message':      log_entry.get('message', ''),
                'alarm_type':   log_entry.get('alarm_type'),
                'severity':     log_entry.get('severity', SEVERITY_INFO),
                'source_file':  source_file,
                'ingested_at':  datetime.now(UTC),
                'is_anomaly':   False,
                'anomaly_score': None,
            }
            embedding_texts.append(_build_log_embedding_text(processed))
            processed_logs.append(processed)

        if generate_embeddings and embedding_texts:
            logger.info(f"[DIAGNOSTICS_RAG] Generating embeddings for {len(embedding_texts)} entries")
            embeddings = generate_embeddings_batch(embedding_texts, show_progress=False)
            for i, embedding in enumerate(embeddings):
                if embedding:
                    processed_logs[i]['embedding'] = embedding

        if processed_logs:
            result = collection.insert_many(processed_logs)
            logger.info(f"[DIAGNOSTICS_RAG] ✓ Ingested {len(result.inserted_ids)} log entries for user {user_id}")
            return {
                "success": True,
                "message": f"Ingested {len(result.inserted_ids)} log entries",
                "count":   len(result.inserted_ids),
                "asset_id": asset_id,
            }
        return {"success": False, "error": "No valid log entries to ingest"}

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Log ingestion failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


def add_diagnostic_code(
    code: str,
    description: str,
    manufacturer: str | None = None,
    instrument_type: str | None = None,
    category: str | None = None,
    severity: str = SEVERITY_WARNING,
    probable_causes: list[str] | None = None,
    recommended_actions: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    """Add or update a diagnostic code entry."""
    try:
        from common.ai.embedding_manager import generate_embedding

        collection = get_diagnostic_codes_collection()
        if collection is None:
            return {"success": False, "error": "Collection not available"}

        doc = {
            'code':                code.strip().upper(),
            'description':         description,
            'manufacturer':        manufacturer,
            'instrument_type':     instrument_type,
            'category':            category,
            'severity':            severity,
            'probable_causes':     probable_causes or [],
            'recommended_actions': recommended_actions or [],
            'references':          references or [],
            'updated_at':          datetime.now(UTC),
        }
        embedding_text = f"{code} {description} "
        if probable_causes:
            embedding_text += " ".join(probable_causes) + " "
        if recommended_actions:
            embedding_text += " ".join(recommended_actions)
        embedding = generate_embedding(embedding_text.strip())
        if embedding:
            doc['embedding'] = embedding

        result = collection.update_one({'code': doc['code']}, {'$set': doc}, upsert=True)
        action = "updated" if result.matched_count > 0 else "added"
        logger.info(f"[DIAGNOSTICS_RAG] ✓ Diagnostic code {code} {action}")
        return {"success": True, "code": code, "action": action}

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Failed to add diagnostic code: {e}")
        return {"success": False, "error": str(e)}


def search_diagnostic_codes(
    query: str,
    manufacturer: str | None = None,
    category: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Semantic search for diagnostic codes matching a query."""
    try:
        from common.ai.embedding_manager import cosine_similarity, generate_embedding

        collection = get_diagnostic_codes_collection()
        if collection is None:
            return []

        filter_query = {}
        if manufacturer:
            filter_query['manufacturer'] = {'$regex': manufacturer, '$options': 'i'}
        if category:
            filter_query['category'] = {'$regex': category, '$options': 'i'}

        docs = list(collection.find(filter_query))
        if not docs:
            return []

        query_embedding = generate_embedding(query)
        if not query_embedding:
            return docs[:top_k]

        scored = []
        for doc in docs:
            doc_embedding = doc.get('embedding')
            if doc_embedding:
                similarity = cosine_similarity(query_embedding, doc_embedding)
            else:
                text = f"{doc.get('code', '')} {doc.get('description', '')}".lower()
                similarity = 0.5 if any(w in text for w in query.lower().split()) else 0.0
            scored.append((doc, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for doc, score in scored[:top_k]:
            doc.pop('embedding', None)
            doc.pop('_id', None)
            doc['similarity_score'] = round(score, 3)
            results.append(doc)
        return results

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Diagnostic code search failed: {e}")
        return []


def create_diagnostic_session(
    user_id: str,
    asset_id: str | None = None,
    tag_number: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a new diagnostic session for tracking analysis."""
    try:
        collection = get_diagnostic_sessions_collection()
        if collection is None:
            return {"success": False, "error": "Collection not available"}

        session_id = str(uuid.uuid4())
        doc = {
            'session_id':               session_id,
            'user_id':                  int(user_id) if str(user_id).isdigit() else user_id,
            'asset_id':                 asset_id,
            'tag_number':               tag_number,
            'description':              description,
            'status':                   'pending',
            'created_at':               datetime.now(UTC),
            'updated_at':               datetime.now(UTC),
            'findings':                 [],
            'anomalies_detected':       0,
            'diagnostic_codes_matched': [],
        }
        collection.insert_one(doc)
        logger.info(f"[DIAGNOSTICS_RAG] ✓ Created session {session_id}")
        return {"success": True, "session_id": session_id}

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Failed to create session: {e}")
        return {"success": False, "error": str(e)}


def update_diagnostic_session(
    session_id: str,
    findings: list[dict] | None = None,
    anomalies_detected: int | None = None,
    diagnostic_codes_matched: list[str] | None = None,
    status: str | None = None,
    analysis_summary: str | None = None,
) -> dict[str, Any]:
    """Update a diagnostic session with findings."""
    try:
        collection = get_diagnostic_sessions_collection()
        if collection is None:
            return {"success": False, "error": "Collection not available"}

        update_doc = {'updated_at': datetime.now(UTC)}
        if findings is not None:
            update_doc['findings'] = findings
        if anomalies_detected is not None:
            update_doc['anomalies_detected'] = anomalies_detected
        if diagnostic_codes_matched is not None:
            update_doc['diagnostic_codes_matched'] = diagnostic_codes_matched
        if status is not None:
            update_doc['status'] = status
        if analysis_summary is not None:
            update_doc['analysis_summary'] = analysis_summary

        result = collection.update_one({'session_id': session_id}, {'$set': update_doc})
        if result.matched_count == 0:
            return {"success": False, "error": "Session not found"}
        return {"success": True, "session_id": session_id}

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Failed to update session: {e}")
        return {"success": False, "error": str(e)}


def _format_logs_for_chat(logs: list[dict], total: int, time_range_hours: int) -> str:
    """Format log entries as markdown for LLM context."""
    lines = [
        "## INSTRUMENT DIAGNOSTIC LOGS",
        f"*(Showing {len(logs)} most relevant of {total} logs from last {time_range_hours} hours)*\n",
    ]
    by_tag: dict[str, list] = {}
    for log in logs:
        tag = log.get('tag_number', 'Unknown')
        by_tag.setdefault(tag, []).append(log)

    for tag, tag_logs in by_tag.items():
        lines.append(f"### Instrument: {tag}")
        lines.append("| Timestamp | Type | Value | Severity | Message |")
        lines.append("|-----------|------|-------|----------|---------|")
        for log in tag_logs[:10]:
            ts = log.get('timestamp', '')
            if isinstance(ts, datetime):
                ts = ts.strftime('%Y-%m-%d %H:%M:%S')
            log_type = log.get('log_type', '')
            if log.get('alarm_type'):
                log_type = f"{log_type} ({log['alarm_type']})"
            value = log.get('value', '')
            if value and log.get('unit'):
                value = f"{value} {log['unit']}"
            severity = log.get('severity', '')
            message  = log.get('message', '')[:50]
            lines.append(f"| {ts} | {log_type} | {value} | {severity} | {message} |")
        lines.append("")

    anomalies = [log for log in logs if log.get('is_anomaly')]
    if anomalies:
        lines.append(f"**⚠️ {len(anomalies)} anomalies detected in this data**\n")
    return "\n".join(lines)


def search_diagnostics_for_chat(
    user_query: str,
    user_id: str,
    asset_id: str | None = None,
    tag_number: str | None = None,
    time_range_hours: int = 24,
    top_k: int = 10,
) -> str | None:
    """Semantic search over instrument logs for chat context."""
    try:
        from common.ai.embedding_manager import cosine_similarity, generate_embedding

        collection = get_instrument_logs_collection()
        if collection is None:
            return None

        try:
            user_id_norm = int(user_id)
        except (ValueError, TypeError):
            user_id_norm = user_id

        filter_query = {
            "user_id":   user_id_norm,
            "timestamp": {'$gte': datetime.now(UTC) - timedelta(hours=time_range_hours)},
        }
        if asset_id:
            filter_query['asset_id'] = asset_id
        if tag_number:
            filter_query['tag_number'] = tag_number

        logs  = list(collection.find(filter_query).sort('timestamp', -1).limit(500))
        total = len(logs)
        if not logs:
            return None

        logger.info(f"[DIAGNOSTICS_RAG] Scoring {total} logs for: {user_query[:80]}")
        query_embedding = generate_embedding(user_query)

        scored = []
        for log in logs:
            if query_embedding:
                log_embedding = log.get('embedding')
                if log_embedding:
                    similarity = cosine_similarity(query_embedding, log_embedding)
                else:
                    text = _build_log_embedding_text(log).lower()
                    similarity = 0.6 if any(w in text for w in user_query.lower().split()) else 0.0
            else:
                similarity = 0.5
            scored.append((log, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        THRESHOLD = 0.55
        top = [log for log, score in scored[:top_k] if score >= THRESHOLD]
        if not top:
            top = [log for log, _ in scored[:5]]
        if not top:
            return None

        context = _format_logs_for_chat(top, total, time_range_hours)
        logger.info(f"[DIAGNOSTICS_RAG] ✓ Built context: {len(top)} logs from {total}")
        return context

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] search_diagnostics_for_chat failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def get_diagnostic_statistics(
    user_id: str,
    asset_id: str | None = None,
    time_range_hours: int = 168,
) -> dict[str, Any]:
    """Get diagnostic statistics for a user's instruments."""
    try:
        collection = get_instrument_logs_collection()
        if collection is None:
            return {"error": "Collection not available"}

        try:
            user_id_norm = int(user_id)
        except (ValueError, TypeError):
            user_id_norm = user_id

        match_filter: dict = {
            "user_id":   user_id_norm,
            "timestamp": {'$gte': datetime.now(UTC) - timedelta(hours=time_range_hours)},
        }
        if asset_id:
            match_filter['asset_id'] = asset_id

        pipeline = [
            {'$match': match_filter},
            {'$facet': {
                'total':      [{'$count': 'count'}],
                'by_type':    [{'$group': {'_id': '$log_type', 'count': {'$sum': 1}}}],
                'by_severity':[{'$group': {'_id': '$severity', 'count': {'$sum': 1}}}],
                'anomalies':  [{'$match': {'is_anomaly': True}}, {'$count': 'count'}],
                'instruments':[
                    {'$group': {'_id': '$tag_number', 'count': {'$sum': 1}, 'last_reading': {'$max': '$timestamp'}}},
                    {'$sort': {'count': -1}},
                    {'$limit': 20},
                ],
            }},
        ]

        result = list(collection.aggregate(pipeline))
        if not result:
            return {"total_logs": 0, "by_type": {}, "by_severity": {}, "anomaly_count": 0, "instruments": []}

        facets = result[0]
        return {
            "total_logs":    facets['total'][0]['count'] if facets['total'] else 0,
            "by_type":       {r['_id']: r['count'] for r in facets['by_type']},
            "by_severity":   {r['_id']: r['count'] for r in facets['by_severity']},
            "anomaly_count": facets['anomalies'][0]['count'] if facets['anomalies'] else 0,
            "instruments":   [
                {
                    "tag":         r['_id'],
                    "log_count":   r['count'],
                    "last_reading": r['last_reading'].isoformat() if r['last_reading'] else None,
                }
                for r in facets['instruments']
            ],
            "time_range_hours": time_range_hours,
        }

    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Failed to get statistics: {e}")
        return {"error": str(e)}


def delete_user_diagnostic_data(user_id: str) -> dict[str, Any]:
    """Delete all diagnostic data for a user."""
    try:
        logs_col     = get_instrument_logs_collection()
        sessions_col = get_diagnostic_sessions_collection()
        if not logs_col or not sessions_col:
            return {"success": False, "error": "Collections not available"}

        query         = build_user_id_filter(user_id)
        logs_result    = logs_col.delete_many(query)
        sessions_result = sessions_col.delete_many(query)

        logger.info(
            f"[DIAGNOSTICS_RAG] Deleted {logs_result.deleted_count} logs, "
            f"{sessions_result.deleted_count} sessions for user {user_id}"
        )
        return {
            "success":          True,
            "logs_deleted":     logs_result.deleted_count,
            "sessions_deleted": sessions_result.deleted_count,
        }
    except Exception as e:
        logger.error(f"[DIAGNOSTICS_RAG] Deletion failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# HEALTH CHECKS
# ============================================================================

def check_assets_rag_health():
    """Health check for the Assets RAG section."""
    from common.monitoring.health import AgentHealthChecker, AgentHealthStatus, DependencyStatus

    checker      = AgentHealthChecker()
    dependencies: dict = {}
    status       = "healthy"
    error_msg    = None

    try:
        dependencies["llm_flash"] = checker.check_llm_connectivity("google")
        if dependencies["llm_flash"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_assets"] = checker.check_mongodb_collection("user_assets")
        if dependencies["mongodb_assets"].status == "unavailable":
            status = "unhealthy"

        try:
            from common.infra.azure_blob import azure_blob_manager
            azure_blob_manager.blob_service_client.get_account_information()
            dependencies["azure_blob"] = DependencyStatus("azure_blob", "available")
        except Exception as e:
            dependencies["azure_blob"] = DependencyStatus("azure_blob", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"

        try:
            conn = get_mongodb_connection()
            if conn:
                dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "available")
            else:
                dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "unavailable", "Connection failed")
                status = "unhealthy"
        except Exception as e:
            dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "unavailable", str(e))
            status = "unhealthy"

    except Exception as e:
        status    = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[RAG_HEALTH] Assets RAG health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="assets_rag",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg,
    )


def check_diagnostics_rag_health():
    """Health check for the Diagnostics RAG section."""
    from common.monitoring.health import AgentHealthStatus, DependencyStatus

    dependencies: dict = {}
    status    = "healthy"
    error_msg = None

    try:
        logs_coll = get_instrument_logs_collection()
        if logs_coll is not None:
            logs_coll.find_one({}, {'_id': 1})
            dependencies["mongodb_instrument_logs"] = DependencyStatus("mongodb_instrument_logs", "available")
        else:
            dependencies["mongodb_instrument_logs"] = DependencyStatus(
                "mongodb_instrument_logs", "unavailable", "Collection not accessible"
            )
            status = "unhealthy"

        codes_coll = get_diagnostic_codes_collection()
        if codes_coll is not None:
            codes_coll.find_one({}, {'_id': 1})
            dependencies["mongodb_diagnostic_codes"] = DependencyStatus("mongodb_diagnostic_codes", "available")
        else:
            dependencies["mongodb_diagnostic_codes"] = DependencyStatus(
                "mongodb_diagnostic_codes", "unavailable", "Collection not accessible"
            )
            status = "degraded"

        try:
            from common.ai.embedding_manager import get_embedding_model
            get_embedding_model()
            dependencies["embedding_model"] = DependencyStatus("embedding_model", "available")
        except Exception as e:
            dependencies["embedding_model"] = DependencyStatus("embedding_model", "unavailable", str(e))
            status = "degraded"

    except Exception as e:
        status    = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[DIAGNOSTICS_RAG] Health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="diagnostics_rag",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg,
    )
