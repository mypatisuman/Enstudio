"""
services/convention_service.py — company-convention & layout-rule coordination.

Extracted from main.py (Phase 6): _get_conventions(), _load_layout_rules(),
_apply_convention_overrides() — moved verbatim. These coordinate the
manifest repository, the adapters.company.CompanyConventions adapter, and
the SkillRegistry adapter to produce merged layout rules; none of them own
persistence or define pure business rules themselves.

`hub`, `projects_dir`, and `skill_registry` are explicit parameters (these
functions originally closed over main.py's HUB/PROJECTS_DIR globals and its
module-level `skill_registry` instance) — main.py keeps thin wrappers with
the original signatures (see Phase 6 Step 9).

Coordinates: repositories.manifest_repository, adapters.company,
adapters.skill_registry (via the passed-in instance). No Flask, no SQL.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from repositories import manifest_repository as _manifest_repo


def _get_conventions(pid: str, hub: Path, projects_dir: Path):
    """Return a loaded+parsed CompanyConventions for the project, or None."""
    m = _manifest_repo.load_manifest(pid, projects_dir)
    company = m.get('company')
    if not company:
        return None
    from adapters.company import CompanyConventions
    conv = CompanyConventions(company, hub)
    if conv.exists():
        conv.load()
        conv.parse()
        return conv
    return None


def _load_layout_rules(skill_registry, company: str | None = None) -> dict:
    """Delegates to SkillRegistry — registry.yaml is the source of truth."""
    return skill_registry.get_layout_rules(company)


def _apply_convention_overrides(rules: dict, pid: str, hub: Path, projects_dir: Path) -> dict:
    """Merge company-specific rendering preferences on top of skill-file defaults."""
    rules = copy.deepcopy(rules)
    conv = _get_conventions(pid, hub, projects_dir)
    if not conv:
        return rules
    raw = conv._raw  # already loaded + parsed by _get_conventions
    # Section 8: valve placement overrides
    if re.search(r'PCV[:\s][^\n]*spoke', raw, re.IGNORECASE):
        rules.setdefault('control_valve', {})['pcv_placement'] = 'spoke_below'
    if re.search(r'FCV[:\s][^\n]*inline', raw, re.IGNORECASE):
        rules.setdefault('control_valve', {})['fcv_placement'] = 'inline_on_pipe'
    return rules
