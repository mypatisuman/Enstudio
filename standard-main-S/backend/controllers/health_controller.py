"""
controllers/health_controller.py — basic app/health endpoints (home page, static JS, hub info)

Extracted from main.py (Phase 8): request parsing, validation, service/repo
calls, and jsonify()/response construction for these routes -- moved
verbatim into per-function controller bodies. Flask route decorators,
function signatures, and endpoint names all remain in main.py unchanged;
each route body is now a one-line delegate to the matching function here.

Main.py-level names used by these bodies (module-level singletons like
PROJECTS_DIR/HUB/cache_store/llm/skill_registry, and the thin repository/
service wrapper functions established in Phases 2-7) are pulled in via a
function-local `import main as _m` -- mirroring the pre-existing lazy-import
pattern already used elsewhere in this codebase (api/detect.py, extract_cli.py)
to reach main.py without a module-level circular import (main.py imports
this controller module at startup).
"""
from __future__ import annotations

from flask_compat import jsonify, render_template, send_from_directory


def _active_provider_key_set() -> bool:
    """Whether the currently-selected LLM provider has its API key saved
    (via Settings, in the `settings` table) — no env var fallback."""
    from adapters.config import load_config
    cfg = load_config()
    provider = cfg.get('llm_provider', 'anthropic')
    key_field = {
        'anthropic': 'anthropic_api_key',
        'gemini':    'gemini_api_key',
        'openai':    'openai_api_key',
    }.get(provider)
    if key_field is None:
        return True  # e.g. ollama — no key needed
    return bool(cfg.get(key_field))


def index():
    return render_template('index.html')


def serve_ympl_js():
    """Serve ympl.js to the browser (templates/index.html loads it).

    This used to send from REPO_ROOT, but ympl.js has never been there — it
    lives in the ympl-sdk directory — so the route always 404'd and the studio
    UI lost its client-side codec without any error. Serving from the SAME
    constant the Node bridge uses keeps the two from drifting apart again.
    """
    import main as _m
    return send_from_directory(str(_m.YMPL_SDK_DIR), 'ympl.js')


def hub_info():
    import main as _m
    HUB = _m.HUB
    PROJECTS_DIR = _m.PROJECTS_DIR
    STUDIO_DIR = _m.STUDIO_DIR
    YMPL_JS = _m.YMPL_JS
    """Return hub status — skills loaded, projects count, defaults."""
    skills_available = []
    skills_dir = STUDIO_DIR / 'skills' / 'core'
    if skills_dir.exists():
        for d in skills_dir.iterdir():
            if d.is_dir():
                skill_md = d / 'SKILL.md'
                if skill_md.exists():
                    content = skill_md.read_text()
                    active = 'PLACEHOLDER' not in content[:100]
                    skills_available.append({'name': d.name, 'active': active})
    return jsonify({
        'hub': str(HUB),
        'projects_dir': str(PROJECTS_DIR),
        'ympl_js': str(YMPL_JS),
        'ympl_js_exists': YMPL_JS.exists(),
        'skills': skills_available,
        'api_key_set': _active_provider_key_set()
    })
