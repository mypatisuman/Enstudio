"""
register_mcp.py — Write / verify the Claude Desktop MCP server registration.

Run:  python tools/register_mcp.py
"""
import json
import os
import shutil
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

STUDIO_DIR  = Path(__file__).resolve().parent.parent
MCP_PACKAGE = STUDIO_DIR / 'mcpserver'
CONFIG_DIR  = Path(os.environ['APPDATA']) / 'Claude'
CONFIG_FILE = CONFIG_DIR / 'claude_desktop_config.json'

# Candidate ENGINEERING_HUB locations — first with a studio.db wins
HUB_CANDIDATES = [
    Path(os.environ.get('ENGINEERING_HUB', '')),
    Path(r'C:\Users\expadmin\Projects\standard\EngineeringHub\EngineeringHub'),
    Path(r'C:\Users\expadmin\Projects\standard\EngineeringHub'),
    Path(r'C:\standard\EngineeringHub'),
]

# Prefer the Windows py.exe launcher; fall back to current interpreter
PY_CANDIDATES = [
    Path(r'C:\Users\expadmin\AppData\Local\Programs\Python\Launcher\py.exe'),
    Path(sys.executable),
]

# ── Detect paths ──────────────────────────────────────────────────────────────

def find_hub() -> Path:
    for p in HUB_CANDIDATES:
        if p and p.exists() and (p / 'studio.db').exists():
            return p
    # Return the known-correct path even if DB not present yet
    return Path(r'C:\Users\expadmin\Projects\standard\EngineeringHub\EngineeringHub')

def find_python() -> str:
    for p in PY_CANDIDATES:
        if p.exists():
            return str(p)
    return sys.executable

hub    = find_hub()
python = find_python()

DESIRED_ENTRY = {
    "command": python,
    "args":    ["-m", "mcpserver"],
    "env": {
        "ENGINEERING_HUB": str(hub),
        "PYTHONPATH":      str(STUDIO_DIR),
    }
}

# ── Read existing config ───────────────────────────────────────────────────────

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

if CONFIG_FILE.exists():
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        config = {}
else:
    config = {}

config.setdefault('mcpServers', {})

# ── Check whether an update is needed ─────────────────────────────────────────

existing     = config['mcpServers'].get('engineering-studio', {})
existing_env = existing.get('env') or {}
needs_update = (
    existing.get('command') != DESIRED_ENTRY['command']
    or existing.get('args')  != DESIRED_ENTRY['args']
    or existing_env.get('ENGINEERING_HUB') != DESIRED_ENTRY['env']['ENGINEERING_HUB']
    or existing_env.get('PYTHONPATH')      != DESIRED_ENTRY['env']['PYTHONPATH']
)

# ── Apply update ──────────────────────────────────────────────────────────────

if needs_update:
    if CONFIG_FILE.exists():
        backup = CONFIG_FILE.with_suffix('.json.bak')
        shutil.copy2(CONFIG_FILE, backup)
        print(f'Backed up existing config -> {backup}')
    config['mcpServers']['engineering-studio'] = DESIRED_ENTRY
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    action = 'UPDATED'
else:
    action = 'OK (already correct — no changes needed)'

# ── Report ────────────────────────────────────────────────────────────────────

print()
print(f'Config file :    {CONFIG_FILE}')
print(f'MCP package :    {MCP_PACKAGE}   exists={MCP_PACKAGE.exists()}')
print(f'Python      :    {python}')
print(f'HUB         :    {hub}')
print(f'  studio.db :    exists={(hub / "studio.db").exists()}')
print(f'Status      :    {action}')
print()

# Count tools in mcpserver/tools.py source
try:
    src        = (MCP_PACKAGE / 'tools.py').read_text(encoding='utf-8')
    tool_names = [
        line.split('"')[1]
        for line in src.splitlines()
        if line.strip().startswith('name="') and line.strip().endswith('",')
    ]
    new_tools = {
        'sync_project', 'run_extraction', 'get_drawing_extraction',
        'review_action', 'validate_drawing', 'launch_app', 'export_drawing',
    }
    print(f'Tools in mcpserver/tools.py: {len(tool_names)}')
    for i, t in enumerate(tool_names, 1):
        tag = ' <-- NEW' if t in new_tools else ''
        print(f'  {i:2}. {t}{tag}')
except Exception as e:
    print(f'  (could not parse tool list: {e})')

log_path = Path(os.environ['APPDATA']) / 'Claude' / 'logs' / 'mcp-server-engineering-studio.log'
print()
print('=' * 62)
print('  HOW TO RESTART THE MCP SERVER')
print('=' * 62)
print()
print('Claude Desktop keeps the MCP subprocess alive and does NOT')
print('hot-reload.  You must do a full restart:')
print()
print('  1. Quit Claude Desktop')
print('       Right-click the tray icon -> Quit')
print('       or: Task Manager -> End "Claude.exe"')
print()
print('  2. Relaunch Claude Desktop from the Start menu.')
print()
print('  3. Check the MCP log to confirm the new server loaded:')
print(f'       {log_path}')
print('     You should see a line like:')
print('       [mcp_server] loaded server.py sha=... pid=...')
print()
print('  4. In a new conversation ask:')
print('       "What MCP tools do you have?"')
print('     You should see all 17 tools, including the 7 new ones.')
print()
