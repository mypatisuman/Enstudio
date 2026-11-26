"""
utils/paths.py — shared, behavior-preserving helpers for resolving the
EngineeringHub location, the studio.db path, and a few trivially-derived
project/company paths.

Phase 1's audit found six independent implementations of "resolve the
EngineeringHub directory" scattered across main.py, mcp_server.py,
export_svg_cli.py, export_dxf_cli.py, and tools/migrate_to_sqlite.py — each
with a *slightly* different default, existence-check, and directory-creation
behavior. These helpers factor out only the literally-identical mechanics
(env-var lookup with a fallback, and the existence-based multi-candidate
search used by the two export CLIs) while leaving every caller's own
default value, resolved-vs-unresolved path choice, and mkdir/exists timing
exactly where it was — so no observable behavior changes at any call site.
See the Phase 2 report for the call-site-by-call-site behavior comparison
that this file is built from.

Deliberately NOT touched/consolidated here (see Phase 2 report "Risks"):
  - tools/register_mcp.py's find_hub() — a one-time interactive registration
    tool with hardcoded per-developer-machine candidate paths; a genuinely
    different shape (multi-machine search, not env-var-with-one-default)
    used nowhere in the running app's hot path.
  - extract_cli.py — has no independent env-var-based HUB resolution; it
    either receives `hub` as an explicit function parameter (and forwards it
    into ENGINEERING_HUB for main.py to resolve normally) or as a required,
    existence-validated CLI positional argument. Nothing to extract.
  - main.py's ~15 internal `PROJECTS_DIR / pid / ...` call sites — all
    identical to each other (no behavioral divergence risk), repeated within
    one file rather than duplicated *across* entry points. Left for a later
    service-extraction phase (see Phase 1 roadmap) to avoid inflating this
    phase's diff beyond its stated scope.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


def resolve_hub(
    default: Path,
    env_var: str = 'ENGINEERING_HUB',
    treat_empty_as_unset: bool = False,
) -> Path:
    """Read `env_var`; if unset, fall back to `default`.

    `treat_empty_as_unset=False` (the default) matches the plain
    `Path(os.getenv(env_var, default))` / `Path(os.environ.get(env_var,
    str(default)))` pattern used identically by main.py, mcp_server.py, and
    tools/migrate_to_sqlite.py: only an *absent* env var falls back to
    `default` — an env var explicitly set to `''` resolves to `Path('')`,
    same as calling `os.environ.get` directly.

    `treat_empty_as_unset=True` matches adapters/db.py's original
    `hub = os.environ.get('ENGINEERING_HUB'); if hub: ...` truthy check,
    where an empty-string value ALSO falls back to `default`. These two
    behaviors genuinely differed across call sites before this extraction
    (db.py guarded against empty string, the others didn't) — preserved
    here via the parameter rather than silently unified.

    Does NOT call .resolve() and does NOT check existence — callers that
    need resolved/absolute paths or existence checks keep doing that
    themselves before/after calling this, exactly as before.
    """
    if treat_empty_as_unset:
        value = os.environ.get(env_var)
        return Path(value) if value else default
    return Path(os.environ.get(env_var, str(default)))


def resolve_projects_dir(hub: Path) -> Path:
    """`<hub>/projects` — identical in every caller that derives it.
    Does NOT create the directory; callers decide whether/when to mkdir.
    """
    return hub / 'projects'


def resolve_database_path(
    candidates: Sequence[Path],
    env_var: str = 'ENGINEERING_HUB',
    env_subpath: str = 'studio.db',
) -> Path:
    """Existence-based search matching export_svg_cli.py / export_dxf_cli.py's
    find_db() (verified byte-identical in both before this extraction):

        1. If `env_var` is set AND `<env_var value>/env_subpath` exists,
           return it.
        2. Otherwise return the first path in `candidates` that exists.
        3. Otherwise raise FileNotFoundError with the exact message both
           call sites already used.

    Unlike resolve_hub(), this checks existence and can raise — that IS the
    existing behavior of both call sites, not a change.
    """
    hub = os.environ.get(env_var, '')
    if hub:
        candidate = Path(hub) / env_subpath
        if candidate.exists():
            return candidate
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError('studio.db not found. Set ENGINEERING_HUB env var.')


def resolve_project_path(projects_dir: Path, pid: str) -> Path:
    """`<projects_dir>/<pid>` — exposed for future call sites (e.g. a later
    project-repository service extraction); not force-adopted at every
    existing `PROJECTS_DIR / pid` site in this phase, see module docstring.
    """
    return projects_dir / pid


def resolve_company_path(hub: Path, company_name: str | None = None) -> Path:
    """`<hub>/companies` (no name given) or `<hub>/companies/<name>/
    conventions.md` (name given) — matches adapters/company.py's
    CompanyConventions path construction and main.py's companies_dir
    listing path. Exposed for future use; not force-adopted this phase.
    """
    companies_dir = hub / 'companies'
    if company_name is None:
        return companies_dir
    return companies_dir / company_name / 'conventions.md'
