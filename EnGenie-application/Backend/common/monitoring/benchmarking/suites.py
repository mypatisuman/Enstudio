"""
Test-suite loading.

Suites are plain JSON files in ``suites/`` (one per agent type). Each has:
    {
      "suite_name": str, "agent_type": "chat"|"search"|"solution",
      "version": str, "description": str,
      "test_cases": [ {"test_id", "name", "input", "expected_behavior", ...}, ... ]
    }

No database involved — the files on disk are the single source of truth.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUITES_DIR = Path(__file__).parent / "suites"

# Short suite key -> filename.
SUITE_FILES = {
    "search": "search_suite.json",
    "solution": "solution_suite.json",
    "chat": "chat_suite.json",
}


def available_suites() -> list[str]:
    """Suite keys that have a JSON file present on disk."""
    return [key for key, fname in SUITE_FILES.items() if (SUITES_DIR / fname).exists()]


def load_suite(suite_key: str) -> dict[str, Any]:
    """Load and lightly validate one suite by key (e.g. ``"search"``)."""
    fname = SUITE_FILES.get(suite_key)
    if not fname:
        raise ValueError(f"Unknown suite '{suite_key}'. Available: {', '.join(SUITE_FILES)}")

    path = SUITES_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"Suite file missing: {path}")

    with open(path, encoding="utf-8") as f:
        suite = json.load(f)

    if not suite.get("test_cases"):
        raise ValueError(f"Suite '{suite_key}' has no test_cases")
    suite.setdefault("agent_type", suite_key)
    return suite
