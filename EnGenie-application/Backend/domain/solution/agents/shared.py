"""
Shared utilities, constants, LLM instances, and helpers
used across all deep instrument analysis agent nodes.
"""

import ast
import json
import logging
import os
import re
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from common.ai.llm import SOLUTION_LLM_PROVIDER, get_solution_flash_llm, get_solution_pro_llm

logger = logging.getLogger(__name__)

# ============================================================================
# PROMPTS
# ============================================================================

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def _load_prompt(filename: str) -> str:
    try:
        with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {filename}")
        return ""


HOLISTIC_AGENT_PROMPT = _load_prompt("holistic_agent.md")
INFER_AGENT_PROMPT = _load_prompt("infer_agent.md")
SOLUTION_BUILD_PROMPT = _load_prompt("solution_build.md")
PID_BUILD_PROMPT = _load_prompt("pid_build.md")
GREENFIELD_PID_PROMPT = _load_prompt("greenfield_pid.md")
BROWNFIELD_PID_PROMPT = _load_prompt("brownfield_pid.md")
BROWNFIELD_UPDATE_PID_PROMPT = _load_prompt("brownfield_update_pid.md")
PID_ROUTER_PROMPT = _load_prompt("pid_router.md")

# ============================================================================
# SHARED LLM INSTANCES
# ============================================================================

llm_pro = get_solution_pro_llm(temperature=0.1)
llm_flash = get_solution_flash_llm(temperature=0.1)

# ============================================================================
# FIELD CONSTANTS
# ============================================================================

REQUIRED_INSTRUMENT_FIELDS = ["category", "specifications", "quantity", "strategy", "sample_input"]
REQUIRED_ACCESSORY_FIELDS = ["accessory_name", "category", "specifications", "quantity", "strategy", "sample_input"]

# ============================================================================
# IDENTIFICATION TRACE LOGGING
# ============================================================================

_TRACE_ENABLED = os.environ.get("ENGENIE_IDENT_TRACE", "1") != "0"


def _trace_identification(event: str, payload: dict) -> None:
    """Log a single identification trace event to standard output."""
    if not _TRACE_ENABLED:
        return
    try:
        record = {"ts": datetime.utcnow().isoformat() + "Z", "event": event, **payload}
        compact = {k: v for k, v in record.items() if k not in ("rendered_prompt", "raw_response", "instruments", "accessories")}
        logging.info(f"[IDENT_TRACE:{event}] {json.dumps(compact, default=str)[:500]}")
    except Exception as trace_exc:
        logging.warning(f"[IDENT_TRACE] Failed to write trace: {trace_exc}")


def _summarize_items(items: list, kind: str) -> list:
    """Build compact per-item summaries for trace records."""
    summaries = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if kind == "instrument":
            summaries.append({
                "category": it.get("category"),
                "quantity": it.get("quantity"),
                "sample_input": (it.get("sample_input") or "")[:200],
                "spec_keys": list((it.get("specifications") or {}).keys()),
            })
        else:
            summaries.append({
                "accessory_name": it.get("accessory_name"),
                "category": it.get("category"),
                "quantity": it.get("quantity"),
                "sample_input": (it.get("sample_input") or "")[:200],
                "spec_keys": list((it.get("specifications") or {}).keys()),
            })
    return summaries

# ============================================================================
# PARALLEL CHUNKING HELPERS
# ============================================================================

_CHUNK_THRESHOLD_CHARS = 1800
_MAX_CHUNK_CHARS = 900
_MAX_PARALLEL_CHUNK_WORKERS = 5


def _split_requirements_into_chunks(text: str) -> list:
    """Split requirements text into paragraph-level chunks for parallel processing."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(paragraphs) <= 1:
        return [text]

    chunks: list = []
    current_parts: list = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > _MAX_CHUNK_CHARS and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_len = len(para)
        else:
            current_parts.append(para)
            current_len += len(para)
    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return chunks if len(chunks) > 1 else [text]


def escape_newlines_in_json(s: str) -> str:
    """Escapes literal newlines, carriage returns, and tabs inside JSON string values."""
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


def _repair_lenient_json(text: str) -> str:
    """String-aware cleanup of the classic LLM-JSON defects that kill both
    json.loads AND the ast fallback (JSON true/false are not Python literals):
    // line comments, /* */ block comments, trailing commas before } or ], and
    unescaped double-quotes INSIDE string values (engineering inch marks:
    '1/2" NPT', '4" Digital' — observed live from LLMs as 'Unterminated
    string'). A quote inside a string counts as the real terminator only when
    the next non-whitespace character is , } ] or : — otherwise it is content
    and gets escaped. Valid JSON passes through byte-identical."""
    out = []
    i, n = 0, len(text)
    in_string = False
    escape_next = False
    while i < n:
        ch = text[i]
        if in_string:
            if escape_next:
                out.append(ch)
                escape_next = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                escape_next = True
                i += 1
                continue
            if ch == '"':
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in ",}]:":
                    in_string = False
                    out.append(ch)
                else:
                    out.append('\\"')  # inner quote (e.g. inch mark) — escape it
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # drop trailing comma; closer emitted on a later pass
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _log_parse_failure_window(cleaned: str, err: Exception) -> None:
    """On total parse failure, log the raw text around the error position so
    the actual model defect is visible in the logs instead of just an offset."""
    pos = getattr(err, "pos", None)
    if isinstance(pos, int):
        start, end = max(0, pos - 150), min(len(cleaned), pos + 150)
        logging.error("[JSON_PARSE] Unrecoverable defect near char %d: ...%r...", pos, cleaned[start:end])


def _parse_extraction_json(raw: str) -> dict:
    """Parse JSON from a requirements extraction LLM response with multiple fallback strategies."""
    cleaned = raw.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    cleaned = escape_newlines_in_json(cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            return json.loads(_repair_lenient_json(cleaned))
        except json.JSONDecodeError:
            pass
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            for candidate in (match.group(1), _repair_lenient_json(match.group(1))):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
            try:
                result = ast.literal_eval(match.group(1))
                if isinstance(result, dict):
                    return result
            except Exception:
                pass

        # Last resort: truncated JSON recovery
        logging.warning("[DEEP_AGENT] JSON truncated — attempting partial recovery")
        brace_depth = 0
        last_safe_pos = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(cleaned):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 1:
                    last_safe_pos = i
        if last_safe_pos > 0:
            for tail_candidate in (cleaned[:last_safe_pos + 1] + "\n}",
                                   _repair_lenient_json(cleaned[:last_safe_pos + 1] + "\n}")):
                try:
                    return json.loads(tail_candidate)
                except json.JSONDecodeError:
                    pass
        try:
            json.loads(cleaned)
        except json.JSONDecodeError as final_err:
            _log_parse_failure_window(cleaned, final_err)
        raise


# ============================================================================
# MERGE HELPERS (for parallel chunk results)
# ============================================================================

_NUMERIC_RANGE_PATTERN = re.compile(r"^[\d.,]+\s*")


def _merge_spec_value(existing_val: str, new_val: str, key: str) -> str:
    """Merge two specification values intelligently."""
    ev = str(existing_val).strip()
    nv = str(new_val).strip()
    if ev.lower() == nv.lower():
        return existing_val

    if key.endswith("_min") or key.endswith("_max"):
        try:
            e_match = _NUMERIC_RANGE_PATTERN.match(ev)
            n_match = _NUMERIC_RANGE_PATTERN.match(nv)
            if e_match and n_match:
                e_num = float(e_match.group().replace(",", "").strip())
                n_num = float(n_match.group().replace(",", "").strip())
                if key.endswith("_min"):
                    return ev if e_num <= n_num else nv
                else:
                    return ev if e_num >= n_num else nv
        except (ValueError, AttributeError):
            pass

    parts = [p.strip() for p in ev.split(" / ")]
    for p in [p.strip() for p in nv.split(" / ")]:
        if p.lower() not in {x.lower() for x in parts}:
            parts.append(p)
    return " / ".join(parts)


def _merge_extraction_results(results: list) -> dict:
    """Merge multiple parallel extraction results into one unified BOM."""
    merged_instruments: dict = {}
    merged_accessories: dict = {}
    project_name = ""
    sub_systems: list = []
    summaries: list = []
    _arr_fields = ("specified_vendors", "specified_model_families", "user_specified_standards")

    for result in results:
        if not result:
            continue
        if not project_name and result.get("project_name"):
            project_name = result["project_name"]
        if result.get("summary"):
            summaries.append(result["summary"])
        for ss in result.get("sub_systems", []):
            if ss not in sub_systems:
                sub_systems.append(ss)

        for inst in result.get("instruments", []):
            cat_key = (inst.get("category") or "").strip().lower().replace("_", " ")
            if not cat_key:
                continue
            if cat_key in merged_instruments:
                existing = merged_instruments[cat_key]
                existing["quantity"] = (existing.get("quantity") or 1) + (inst.get("quantity") or 1)
                existing_specs = existing.setdefault("specifications", {})
                for k, v in inst.get("specifications", {}).items():
                    if k in existing_specs:
                        existing_specs[k] = _merge_spec_value(existing_specs[k], v, k)
                    else:
                        existing_specs[k] = v
                for field in _arr_fields:
                    existing_arr = existing.get(field) or []
                    new_arr = inst.get(field) or []
                    seen: set = set(existing_arr)
                    for item in new_arr:
                        if item not in seen:
                            existing_arr.append(item)
                            seen.add(item)
                    existing[field] = existing_arr
            else:
                merged_instruments[cat_key] = dict(inst)

        for acc in result.get("accessories", []):
            cat_key = (acc.get("category") or "").strip().lower().replace("_", " ")
            parent_key = (acc.get("parent_instrument_category") or "").strip().lower().replace("_", " ")
            dedup_key = f"{cat_key}___{parent_key}"
            if not cat_key:
                continue
            if dedup_key in merged_accessories:
                existing = merged_accessories[dedup_key]
                existing["quantity"] = (existing.get("quantity") or 1) + (acc.get("quantity") or 1)
                existing_specs = existing.setdefault("specifications", {})
                for k, v in acc.get("specifications", {}).items():
                    if k in existing_specs:
                        existing_specs[k] = _merge_spec_value(existing_specs[k], v, k)
                    else:
                        existing_specs[k] = v
            else:
                merged_accessories[dedup_key] = dict(acc)

    return {
        "project_name": project_name,
        "sub_systems": sub_systems,
        "instruments": list(merged_instruments.values()),
        "accessories": list(merged_accessories.values()),
        "summary": "; ".join(summaries) if summaries else "Requirements extracted.",
    }


def _parse_llm_json(raw: str) -> dict:
    """Parse JSON from an LLM inference response with fallback strategies."""
    cleaned = raw.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    cleaned = escape_newlines_in_json(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            return json.loads(_repair_lenient_json(cleaned))
        except json.JSONDecodeError:
            pass
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            for candidate in (match.group(1), _repair_lenient_json(match.group(1))):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
            result = ast.literal_eval(match.group(1))
            if not isinstance(result, dict):
                raise ValueError("Parsed item is not dict")
            return result
        _log_parse_failure_window(cleaned, json.JSONDecodeError("unparseable", cleaned, 0))
        raise
