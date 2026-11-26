"""
services/manifest_service.py — manifest update workflows.

Extracted from main.py (Phase 6): cache_espx_stats(), update_manifest_after_extract(),
update_manifest_after_export() — moved verbatim. Each computes some business
state (stat counts, extraction summary, export record) and calls the
manifest repository to persist it; the repository itself still owns the
actual read/write (see repositories/manifest_repository.py, Phase 5).

`projects_dir` is an explicit parameter (these functions originally closed
over main.py's PROJECTS_DIR) — main.py keeps thin wrappers with the original
signatures so every existing call site is unchanged (see Phase 6 Step 9).

Coordinates: repositories.manifest_repository. No Flask, no SQL, no CV/LLM.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from repositories import manifest_repository as _manifest_repo


def cache_espx_stats(pid: str, espx: dict, projects_dir: Path):
    """Write instrument/equipment/node counts to manifest.stats for fast list reads."""
    studio = espx.get('studio', {})
    m = _manifest_repo.load_manifest(pid, projects_dir)
    m['stats'] = {
        'n_instruments': len(studio.get('instruments', {})),
        'n_equipment':   len(studio.get('equipment', {})),
        'n_nodes':       len(espx.get('nodes', [])),
        'plant_name':    studio.get('metadata', {}).get('plant_name', pid),
        'process_type':  studio.get('metadata', {}).get('process_type', ''),
        'revision':      studio.get('metadata', {}).get('revision', 1),
        'extraction_locked': studio.get('metadata', {}).get('extraction_locked', False),
    }
    _manifest_repo.save_manifest(pid, m, projects_dir)


def update_manifest_after_extract(pid: str, filename: str, fhash: str,
                                   n_nodes: int, n_instruments: int,
                                   n_equipment: int, n_edges: int,
                                   projects_dir: Path,
                                   drawings: list = None):
    m = _manifest_repo.load_manifest(pid, projects_dir)
    sources = m.setdefault('sources', [])
    if not any(s.get('hash') == fhash for s in sources):
        sources.append({
            'filename': filename,
            'hash': fhash,
            'uploaded': datetime.datetime.now().isoformat(timespec='seconds'),
            'drawings': drawings or [],
        })
    m['extraction'] = {
        'last_run': datetime.datetime.now().isoformat(timespec='seconds'),
        'source_hash': fhash,
        'nodes': n_nodes,
        'instruments': n_instruments,
        'equipment': n_equipment,
        'connections': n_edges,
        'status': 'complete'
    }
    m['stats'] = {
        'instruments': n_instruments,
        'equipment': n_equipment,
        'connections': n_edges
    }
    _manifest_repo.save_manifest(pid, m, projects_dir)


def update_manifest_after_export(pid: str, export_type: str, filename: str, projects_dir: Path):
    m = _manifest_repo.load_manifest(pid, projects_dir)
    m.setdefault('exports', []).append({
        'type': export_type,
        'filename': filename,
        'exported': datetime.datetime.now().isoformat(timespec='seconds')
    })
    _manifest_repo.save_manifest(pid, m, projects_dir)
