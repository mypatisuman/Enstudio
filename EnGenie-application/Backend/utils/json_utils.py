"""
utils/json_utils.py — generic, framework-independent JSON parsing helpers.

Extracted from main.py (Phase 3), which had `repair_truncated_json()` and
`extract_json()` embedded among Flask route handlers. The generic parsing
mechanics now live here as `repair_truncated_json()` (moved verbatim) and
`extract_json_object()` (the search/parse engine behind main.py's
`extract_json()`, factored out so it returns `None` on total failure instead
of main.py's business-specific empty-schema dict). main.py's `extract_json()`
is now a thin wrapper: call `extract_json_object()`, and only main.py knows
what an "empty P&ID extraction result" looks like, so it supplies that
fallback itself. No parsing behavior, regex, print statements, or exception
handling changed — see the Phase 3 report for the byte-for-byte comparison.

No Flask/DB/LLM/CV imports — stdlib only.
"""
from __future__ import annotations

import json
from typing import Optional


def repair_truncated_json(raw: str) -> str:
    """
    Repair truncated JSON by finding the last complete object boundary
    and closing all open structures from there.
    Handles the case where truncation occurs mid-string-literal.
    """
    raw = raw.rstrip()

    # Find the last complete closing brace — end of last complete node/object
    last_close = raw.rfind('}')
    if last_close == -1:
        return raw

    # Work only up to the last complete object
    truncated = raw[:last_close + 1]

    # Walk through and track open structures (string-aware)
    stack = []
    opens = {'{': '}', '[': ']'}
    in_string = False
    escape_next = False

    for c in truncated:
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c in opens:
            stack.append(opens[c])
        elif c in ('}', ']'):
            if stack and stack[-1] == c:
                stack.pop()

    closing = ''.join(reversed(stack))
    return truncated + closing


def extract_json_object(raw: str) -> Optional[dict]:
    """Robustly extract a JSON object from LLM response text. Handles
    markdown fences and truncation.

    Returns the parsed dict, or None if every strategy fails. Callers that
    need a non-empty fallback (e.g. a domain-specific empty-schema dict)
    supply it themselves — this function has no opinion on what "nothing
    found" should look like.
    """
    raw = raw.strip()

    def try_parse(s: str) -> Optional[dict]:
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        # Try repairing truncated JSON
        try:
            repaired = repair_truncated_json(s)
            result = json.loads(repaired)
            if isinstance(result, dict):
                print(f'Parsed repaired (truncated) JSON — partial results')
                return result
        except (json.JSONDecodeError, Exception):
            pass
        return None

    # 1. Direct parse
    result = try_parse(raw)
    if result is not None:
        return result

    # 2. Extract from markdown fences
    if '```' in raw:
        start = raw.find('```')
        newline = raw.find('\n', start)
        if newline != -1:
            close = raw.find('\n```', newline + 1)
            content = raw[newline + 1: close if close != -1 else len(raw)].strip()
            result = try_parse(content)
            if result is not None:
                return result

    # 3. Depth-counted brace search with string awareness
    start_idx = raw.find('{')
    if start_idx != -1:
        depth = 0
        in_string = False
        escape_next = False
        last_close = -1
        for i in range(start_idx, len(raw)):
            c = raw[i]
            if escape_next:
                escape_next = False
                continue
            if c == '\\' and in_string:
                escape_next = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    last_close = i
                    break

        candidate = raw[start_idx: last_close + 1 if last_close != -1 else len(raw)]
        result = try_parse(candidate)
        if result is not None:
            return result

    return None
