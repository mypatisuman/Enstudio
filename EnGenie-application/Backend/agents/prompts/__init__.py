"""Central prompt loader for the agentic application.

Prompt .md files are CO-LOCATED with their workflow (the reference
`domain/<name>/prompts/` convention):

    agents/extraction/prompts/*.md
    agents/describe/prompts/*.md
    agents/orchestrator/prompts/*.md

This module is the single loader/filler implementation — deliberately
NOT duplicated per workflow. Each workflow exposes its prompts as named
constants in its own prompts/catalog.py (`X_V1 = load_prompt("x")`).

Placeholders use single-brace {name} syntax. Because the files also
contain literal JSON braces, they are filled with fill_prompt() — which
replaces only known keys — never with str.format().
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_AGENTS_DIR = Path(__file__).parent.parent
_PROMPT_DIRS = [
    _AGENTS_DIR / "extraction" / "prompts",
    _AGENTS_DIR / "describe" / "prompts",
    _AGENTS_DIR / "orchestrator" / "prompts",
]
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Read a prompt file (without .md extension) from the co-located
    per-workflow prompt directories."""
    for d in _PROMPT_DIRS:
        path = d / f"{name}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"prompt '{name}.md' not found in any of: "
        + ", ".join(str(d) for d in _PROMPT_DIRS))


def fill_prompt(template: str, mapping: dict) -> str:
    """Replace {key} placeholders present in `mapping`; leave every other
    brace (JSON examples, schema literals) untouched. Dict/list values are
    JSON-encoded."""
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in mapping:
            return m.group(0)
        v = mapping[key]
        return (json.dumps(v, ensure_ascii=False)
                if isinstance(v, (dict, list)) else str(v))
    return _PLACEHOLDER_RE.sub(_sub, template)
