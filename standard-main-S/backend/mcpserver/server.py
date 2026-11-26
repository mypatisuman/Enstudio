"""
mcpserver/server.py -- MCP server initialization: sys.path bootstrap, hub
resolution, SDK imports, startup banner, the Server instance, and the
stdio-server run loop.

Extracted from mcp_server.py (Phase 12), moved verbatim.
"""
from __future__ import annotations

import json
import subprocess
import sys
import os
import time
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent.parent

# Make sibling adapter modules importable when this file is run as a stdio
# server from Claude Desktop (cwd is not necessarily the studio dir). Moved
# ahead of the HUB resolution below (previously came after) so the new
# `utils.paths` import is guaranteed to resolve regardless of invocation
# method -- pure reordering of an import-path setup step relative to a new
# import statement, no observable behavior changes.
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from utils.paths import resolve_hub, resolve_projects_dir

_default_hub = STUDIO_DIR.parent / 'EngineeringHub' / 'EngineeringHub'
HUB = resolve_hub(default=_default_hub)
PROJECTS_DIR = resolve_projects_dir(HUB)
SKILLS_DIR = STUDIO_DIR / 'skills'

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from adapters.company import CompanyConventions

# -- Startup banner ------------------------------------------------------------
# Claude Desktop keeps the stdio subprocess alive across conversations, so the
# only way to know which mcp_server.py is loaded is to log identity at import
# time. stderr is safe -- stdio MCP reserves stdout for JSON-RPC traffic, and
# stderr is captured into %APPDATA%\Claude\logs\mcp-server-engineering-studio.log.
import hashlib as _hashlib
import datetime as _dt
# Identity banner reports THIS package's server.py (the file actually
# executing this code) -- same intent as the original single-file banner,
# now naturally pointing at the module doing the SDK wiring/startup rather
# than the root-level compatibility shim.
_src = Path(__file__).resolve()
try:
    _sha = _hashlib.sha256(_src.read_bytes()).hexdigest()[:12]
    _mtime = _dt.datetime.fromtimestamp(_src.stat().st_mtime).isoformat(timespec='seconds')
    print(f'[mcp_server] loaded {_src.name} sha={_sha} mtime={_mtime} pid={os.getpid()}',
          file=sys.stderr, flush=True)
except OSError as _e:
    print(f'[mcp_server] banner failed: {_e}', file=sys.stderr, flush=True)

app = Server("engineering-studio")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )
