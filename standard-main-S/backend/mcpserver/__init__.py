"""
mcpserver/__init__.py — public API surface for the MCP server package.

Phase 12: mcp_server.py (~1345 lines) was decomposed into this package:

    server.py     sys.path bootstrap, hub resolution, mcp SDK Server
                   instance (`app`), startup banner, stdio run loop (`main`)
    handlers.py   protocol-independent business-logic helpers (espx/manifest
                   loading, conventions lookup, sqlite access, DB->espx sync)
    tools.py       MCP tool schema registration (list_tools) and tool
                   dispatch/implementation (call_tool)

Note on naming: this package is `mcpserver/`, not `mcp/` as the phase's
generic template suggests, because mcp_server.py imports directly from the
real `mcp` PyPI SDK (`from mcp.server import Server`, `from mcp import
types`) — a local `studio/mcp/` package would have shadowed that SDK on
sys.path and broken every SDK import. Likewise, the object this codebase
calls the "mcp server" instance is genuinely named `app` (a low-level
`mcp.server.Server`, not a `FastMCP` instance conventionally named `mcp`) —
preserved under its real name rather than renamed to match the template.

Importing `.tools` is required (not just for its names) because
`@app.list_tools()`/`@app.call_tool()` register their handlers with `app`
as a decorator side effect at module-body execution time — the same
registration-on-import behavior the original single-file script had.

The root-level `studio/mcp_server.py` shim (introduced in Phase 12 so
Claude Desktop's `python3 mcp_server.py` spawn-by-literal-path kept
working) has since been removed: Claude Desktop now runs this package
directly as a module (`command: python, args: ["-m", "mcpserver"]`, with
`PYTHONPATH` set to the studio directory via env) — see
`__main__.py` and `tools/register_mcp.py`.
"""
from __future__ import annotations

from .server import app, main, HUB, PROJECTS_DIR, SKILLS_DIR, STUDIO_DIR
from . import tools as _tools  # noqa: F401  (import triggers tool registration)

__all__ = ['app', 'main', 'HUB', 'PROJECTS_DIR', 'SKILLS_DIR', 'STUDIO_DIR']
