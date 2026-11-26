"""
repositories/manifest_repository.py — project.json manifest persistence.

Extracted from main.py (Phase 5): manifest_path(), load_manifest(),
save_manifest(), moved verbatim. Preserves the exact JSON format, default
manifest shape, and filesystem layout (<projects_dir>/<pid>/project.json).

`projects_dir` is an explicit parameter rather than a module-level global:
these functions originally closed over main.py's PROJECTS_DIR. main.py keeps
thin wrappers with the original single/two-argument signatures (see Step 7)
so every existing call site (`load_manifest(pid)`, `save_manifest(pid, m)`)
continues to work unchanged.

Depends only on stdlib. No Flask, no DB, no CV/LLM imports.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path


def manifest_path(pid: str, projects_dir: Path) -> Path:
    return projects_dir / pid / 'project.json'


def load_manifest(pid: str, projects_dir: Path) -> dict:
    p = manifest_path(pid, projects_dir)
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return {
        'id': pid,
        'created': datetime.date.today().isoformat(),
        'sources': [],
        'extraction': {},
        'exports': [],
        'stats': {},
        'units': []
    }


def save_manifest(pid: str, manifest: dict, projects_dir: Path):
    manifest_path(pid, projects_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
