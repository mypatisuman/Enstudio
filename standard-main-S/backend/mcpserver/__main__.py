"""
mcpserver/__main__.py — lets `python -m mcpserver` run the stdio server.

Replaces the old root-level `mcp_server.py` compatibility shim: Claude
Desktop's config now invokes this package as a module (`command: python,
args: ["-m", "mcpserver"]`, with `PYTHONPATH` set to the studio directory
via env — see tools/register_mcp.py) instead of spawning a literal script
path.
"""
import asyncio

from .server import main

if __name__ == "__main__":
    asyncio.run(main())
