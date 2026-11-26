"""
Shared helpers for cleaning up and parsing JSON-shaped LLM output.

Previously reimplemented identically in domain/search/services/search_modification.py,
domain/search/agents/update_agent.py, and domain/search/agents/search_agent.py.
"""
from __future__ import annotations

import ast
import json
from typing import Any


def escape_newlines_in_json(s: str) -> str:
    """Escapes literal newlines, carriage returns, and tabs inside JSON string values."""
    result = []
    in_string = False
    escaped = False
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
            result.append(char)
        elif char == "\\" and in_string:
            escaped = not escaped
            result.append(char)
        else:
            if escaped:
                escaped = False
            if in_string and char in ("\n", "\r", "\t"):
                if char == "\n":
                    result.append("\\n")
                elif char == "\r":
                    result.append("\\r")
                elif char == "\t":
                    result.append("\\t")
            else:
                result.append(char)
    return "".join(result)


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Strip code-fence wrappers, escape stray newlines, and parse an LLM's
    JSON-shaped response. Falls back to ast.literal_eval for near-JSON output
    (single quotes, trailing commas) that json.loads rejects."""
    cleaned = raw.strip()
    for fence in ("```json", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = escape_newlines_in_json(cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return ast.literal_eval(cleaned)
