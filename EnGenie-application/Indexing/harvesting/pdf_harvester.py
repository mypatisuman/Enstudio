"""
PDF spec-value extraction for Indexing pipeline.

  extract_pdf(stream)               -> list[str]  (per-page text chunks + table lines)
  extract_with_llm(chunks)          -> list[dict] (vendor/models/specs JSON)
  _validate_extracted_data(data, text_sample) -> bool  (LLM accuracy gate)
  aggregate(results)                -> dict        (merged, deduped across PDFs)
  split_types(results)              -> list[dict]  (split "a/b" product types)

  enrich_l3_with_pdf_values(node_id, spec_doc_url, parameters, db_write_fn)
      -> dict  (field -> extracted value)  -- main integration point for pipeline

Requires: Indexing/harvesting/resilience.py
"""

import os
import io
import re
import json
import logging
from typing import Any, Dict, List, Optional

from .resilience import (RetryConfig, retry_with_backoff,
                         get_next_google_api_key, _clean_llm_content)

log = logging.getLogger(__name__)

# ── PDF text extraction ───────────────────────────────────────────────────────

def extract_pdf(stream) -> List[str]:
    """
    Parse a PDF file-like object into per-page text chunks.
    Each chunk includes raw page text plus colon-separated spec lines extracted
    from block-layout parsing (table rows like "Accuracy: ±0.1%").
    """
    import fitz  # PyMuPDF
    stream.seek(0)
    doc = fitz.open(stream=stream, filetype="pdf")
    chunks = []
    for i, page in enumerate(doc, 1):
        txt = page.get_text("text") or ""
        tbl_lines = [
            l.strip()
            for b in (page.get_text("blocks") or [])
            for l in b[4].splitlines()
            if ":" in l
        ]
        formatted_lines = []
        for l in (f"--- Page {i} ---\n{txt}\n" + "\n".join(tbl_lines)).splitlines():
            m = re.match(r"^([\w \-/\(\)]+):\s*(.+)$", l.strip())
            if m:
                formatted_lines.append(f"Spec: {m.group(1).strip()} = {m.group(2).strip()}")
            else:
                formatted_lines.append(l)
        chunks.append("\n".join(formatted_lines))
    doc.close()
    return chunks


# ── LLM spec extraction ───────────────────────────────────────────────────────

_EXTRACT_PROMPT = """IDENTITY & OBJECTIVE
You are an Industrial Specification Extraction Expert. Extract EVERY technical specification from the product documentation with standardized field names.

CRITICAL EXTRACTION RULES:

1. PRODUCT DETECTION:
   - Extract base product category (e.g., "pressure transmitter", "flow meter", "control valve")
   - Remove technology modifiers: "differential pressure transmitter" → "pressure transmitter"

2. COMPREHENSIVE SPECIFICATION EXTRACTION:
   Extract ALL technical specifications found in the document. Use standardized `snake_case` field names.

   **MEASUREMENT & PERFORMANCE:**
   measurement_range, accuracy, repeatability, response_time, measurement_principle,
   turndown_ratio, rangeability, stability, linearity, hysteresis,
   resolution, sensitivity, drift, zero_offset, span_adjustment,
   calibration_range, reference_accuracy, total_error_band

   **ELECTRICAL:**
   power_supply, output_signal, communication_protocol, power_consumption,
   loop_resistance, voltage_rating, current_consumption, supply_voltage,
   electrical_connection, cable_entry, terminal_type, grounding_requirement,
   explosion_proof_rating, intrinsic_safety_rating

   **ENVIRONMENTAL:**
   operating_temperature, ambient_temperature, process_temperature, storage_temperature,
   operating_pressure, process_pressure, design_pressure, proof_pressure, burst_pressure,
   ingress_protection, humidity, vibration_resistance, shock_resistance,
   corrosion_resistance, weather_resistance, altitude_range

   **MATERIALS:**
   wetted_material, housing_material, process_connection, gasket_material,
   diaphragm_material, body_material, flange_material, seal_material,
   electrode_material, liner_material, coating_type, surface_finish

   **CERTIFICATIONS & STANDARDS:**
   hazardous_area_rating, sil_rating, certifications, approvals,
   atex_rating, iecex_rating, nec_classification, fm_approval,
   ce_marking, ul_listing, csa_approval, marine_approval, applicable_standards

   **MECHANICAL:**
   mounting_type, display_type, enclosure_type, installation_orientation,
   process_connection_size, flange_rating, flange_size, pipe_size,
   weight, dimensions, installation_length, insertion_depth,
   face_to_face_dimension, mounting_bracket_type

   **FLOW SPECIFIC:** flow_rate, flow_range, velocity_range, pipe_diameter,
   cv_value, flow_coefficient, pressure_drop, flow_direction

   **LEVEL SPECIFIC:** level_range, probe_length, dead_band, blanking_distance

   **VALVE SPECIFIC:** valve_size, seat_leakage_class, shutoff_rating, cv_characteristic,
   actuator_type, fail_action, stroke_time, control_action

   Extract ANY other specs not listed above with descriptive snake_case names.

   CRITICAL RULES:
   - Extract EVERY technical specification found (do NOT limit to predefined list)
   - Use standardized snake_case field names (lowercase with underscores)
   - Extract ONLY factual technical data with units
   - Preserve exact values: "0-100 bar" not "pressure range up to 100 bar"
   - NO sentences or prose in values: "316L SS" not "manufactured from 316L stainless steel"
   - Include units in values: "85°C" not just "85"

3. VENDOR & MODEL EXTRACTION:
   - vendor: Extract manufacturer name (e.g., Emerson, Rosemount, ABB, Yokogawa)
   - model_series: Extract model family (e.g., 3051, EJA110, STD800)
   - sub_model name: Extract specific variant (e.g., 3051CD, EJA110A)

4. DUPLICATE HANDLING:
   - If multiple PDFs contain same submodel, MERGE specifications
   - Keep unique specifications only; if conflicting values exist use the most specific

5. EXCLUDE:
   - Marketing descriptions, generic feature lists, installation instructions,
     general product overviews, warranty terms, ordering information

OUTPUT FORMAT — return ONLY valid JSON (no markdown):
[
  {{
    "product_type": "<core_category>",
    "vendor": "<vendor_name>",
    "models": [
      {{
        "model_series": "<model_family>",
        "sub_models": [
          {{
            "name": "<sub_model_variant>",
            "specifications": {{
              "measurement_range": "0-100 bar",
              "accuracy": "±0.1%",
              "<any_other_spec>": "<exact_value_with_units>"
            }}
          }}
        ]
      }}
    ]
  }}
]

EXTRACTION GOAL: Extract 20-100+ specifications per product variant depending on document detail.

Text:
{text}"""


@retry_with_backoff(RetryConfig(max_retries=8, base_delay=10.0))
def extract_with_llm(chunks: List[str]) -> List[Dict[str, Any]]:
    """Send combined PDF chunks to LLM and parse extracted spec JSON."""
    import sys
    import os
    from langchain_core.messages import HumanMessage

    _HERE = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.abspath(os.path.join(_HERE, "..", "..", "Backend"))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from common.ai.llm.manager import get_flash_llm

    llm = get_flash_llm(temperature=0.1)
    prompt = _EXTRACT_PROMPT.format(text="\n".join(chunks))
    content = _clean_llm_content(llm.invoke([HumanMessage(content=prompt)]).content)
    data = json.loads(content)
    return data if isinstance(data, list) else [data]


# ── LLM validation gate ───────────────────────────────────────────────────────

@retry_with_backoff(RetryConfig(max_retries=6, base_delay=5.0))
def _validate_extracted_data(extracted_data: Dict[str, Any],
                              original_text_sample: str) -> bool:
    """
    LLM accuracy gate: verify that vendor/product_type/model names in the
    extracted data actually appear in the source PDF text.
    """
    import sys
    from langchain_core.messages import HumanMessage

    vendor = extracted_data.get("vendor", "")
    product_type = extracted_data.get("product_type", "")
    models = extracted_data.get("models", [])

    if not vendor or not product_type or not models:
        log.warning("[PDF] Validation failed: missing vendor/product_type/models")
        return False

    model_names = [m.get("model_series", "") for m in models[:3] if m.get("model_series")]
    if not model_names:
        log.warning("[PDF] Validation failed: no valid model names")
        return False

    prompt = f"""You are a data quality expert. Verify if the extracted product data is accurate.

Original PDF text (sample):
{original_text_sample[:1000]}

Extracted data:
- Vendor: {vendor}
- Product Type: {product_type}
- Models: {', '.join(model_names[:5])}

Does the extracted data accurately match the PDF content?
Reply EXACTLY 'YES' if accurate (vendor name correct, product type correct, model names found in text).
Reply 'NO' if inaccurate or if data seems wrong."""

    _HERE = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.abspath(os.path.join(_HERE, "..", "..", "Backend"))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from common.ai.llm.manager import get_flash_llm

    llm = get_flash_llm(temperature=0.1)
    result = _clean_llm_content(
        llm.invoke([HumanMessage(content=prompt)]).content).strip().upper()
    is_valid = "YES" in result
    if is_valid:
        log.info("[PDF] Validated: %s %s (%d models)", vendor, product_type, len(models))
    else:
        log.warning("[PDF] Validation FAILED for %s %s: %s", vendor, product_type, result)
    return is_valid


# ── Aggregation / deduplication ───────────────────────────────────────────────

def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge spec extractions from multiple PDFs into a single deduplicated result.
    For duplicate spec keys, keeps the longer (more detailed) value.
    """
    def _norm_key(k: str) -> str:
        return k.lower().strip().replace(" ", "_").replace("-", "_")

    def _meaningful(specs: dict) -> bool:
        return bool(specs and any(v and str(v).strip() for v in specs.values()))

    models: Dict[str, dict] = {}
    vendor, ptype = "", ""

    for item in results:
        if isinstance(item, list):
            continue
        vendor = vendor or item.get("vendor", "").strip()
        ptype = ptype or item.get("product_type", "").strip()

        for m in item.get("models", []):
            series = (m.get("model_series") or "").strip()
            if not series:
                continue
            key = series.lower().replace(" ", "_")
            if key not in models:
                models[key] = {"model_series": series, "sub_models": []}

            for sm in m.get("sub_models", []):
                name = (sm.get("name") or "").strip()
                raw_specs = sm.get("specifications") or {}

                # Normalize + skip empty/NA values
                specs: Dict[str, str] = {}
                for k, v in raw_specs.items():
                    if not v:
                        continue
                    nk = _norm_key(k)
                    nv = str(v).strip()
                    if not nv or nv.lower() in ("n/a", "na", "none", "not applicable"):
                        continue
                    if nk in specs:
                        if len(nv) > len(str(specs[nk])):
                            specs[nk] = nv
                    else:
                        specs[nk] = nv

                if not name and not _meaningful(specs):
                    continue

                existing = next(
                    (s for s in models[key]["sub_models"] if s.get("name") == name), None)
                if existing:
                    ex_specs = existing.setdefault("specifications", {})
                    for sk, sv in specs.items():
                        nsk = _norm_key(sk)
                        match_key = next(
                            (k for k in ex_specs if _norm_key(k) == nsk), None)
                        if match_key:
                            if len(str(sv)) > len(str(ex_specs[match_key])):
                                del ex_specs[match_key]
                                ex_specs[sk] = sv
                        else:
                            ex_specs[sk] = sv
                else:
                    models[key]["sub_models"].append({
                        "name": name,
                        "specifications": specs or {"_raw_text": "No specs"},
                    })

    # Drop model families with no usable sub-models
    filtered = []
    for m in models.values():
        good_subs = [s for s in m["sub_models"]
                     if s.get("name") or _meaningful(s.get("specifications", {}))]
        if good_subs:
            m["sub_models"] = good_subs
            filtered.append(m)

    log.info("[PDF] Aggregated %d model families for %s %s", len(filtered), vendor, ptype)
    return {"product_type": ptype, "vendor": vendor, "models": filtered}


def split_types(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split combined 'a/b' or 'a,b' product_type strings into separate records."""
    out = []
    for item in results:
        pt = item.get("product_type", "").strip()
        v = item.get("vendor", "")
        m = item.get("models", [])
        types_ = ([t.strip() for t in re.split(r"[/,]", pt) if t.strip()]
                  if ("/" in pt or "," in pt) else [pt])
        out.extend({"product_type": t, "vendor": v, "models": m} for t in types_)
    return out


# ── Pipeline integration helper ───────────────────────────────────────────────

def enrich_l3_with_pdf_values(
    node_id: str,
    spec_doc_url: str,
    parameters: Dict[str, Dict[str, Any]],
    blob_download_fn,           # callable(spec_doc_url) -> bytes
) -> Dict[str, Any]:
    """
    Download the L3 spec_doc_url PDF, extract spec values, and return
    a flat {field_name: value} dict for the fields already in parameters.

    blob_download_fn: e.g. lambda url: azure_blob_manager.download_document_from_url(url)
                           or the _pdf_text helper from build_catalog_hierarchy.

    Returns {} on any failure (caller decides whether to skip or raise).
    """
    try:
        pdf_bytes = blob_download_fn(spec_doc_url)
    except Exception as e:
        log.warning("[PDF] Could not download %s for %s: %s", spec_doc_url, node_id, e)
        return {}

    try:
        chunks = extract_pdf(io.BytesIO(pdf_bytes))
    except Exception as e:
        log.warning("[PDF] extract_pdf failed for %s: %s", node_id, e)
        return {}

    if not any(len(c.strip()) >= 50 for c in chunks):
        log.warning("[PDF] No usable content in PDF for %s", node_id)
        return {}

    try:
        raw_results = extract_with_llm(chunks)
    except Exception as e:
        log.warning("[PDF] extract_with_llm failed for %s: %s", node_id, e)
        return {}

    aggregated = aggregate(raw_results)
    text_sample = "\n".join(chunks[:3])
    if not _validate_extracted_data(aggregated, text_sample):
        log.warning("[PDF] Validation failed for %s — skipping value fill", node_id)
        return {}

    # Flatten all sub-model specs into a single best-value map
    all_fields: set = set()
    for tier in ("mandatoryRequirements", "optionalRequirements", "latestRequirements"):
        all_fields |= set(parameters.get(tier, {}).keys())

    spec_votes: Dict[str, Dict[str, int]] = {}
    for m in aggregated.get("models", []):
        for sm in m.get("sub_models", []):
            for k, v in (sm.get("specifications") or {}).items():
                nk = re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_")
                if nk in all_fields:
                    spec_votes.setdefault(nk, {})
                    spec_votes[nk][str(v)[:120]] = spec_votes[nk].get(str(v)[:120], 0) + 1

    values = {f: max(votes, key=votes.get)
              for f, votes in spec_votes.items() if votes}
    log.info("[PDF] Filled %d/%d fields for %s", len(values), len(all_fields), node_id)
    return values
