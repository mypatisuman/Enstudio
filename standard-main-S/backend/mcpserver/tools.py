"""
mcpserver/tools.py -- MCP tool schema registration (list_tools) and tool
dispatch/implementation (call_tool).

Extracted from mcp_server.py (Phase 12), moved verbatim -- both handlers
are inherently protocol-facing (they construct/consume `mcp.types` objects
and are registered via `@app.list_tools()`/`@app.call_tool()`), so per
Phase 12 Step 7 ("Do NOT move protocol code into handlers"), both stay
together here rather than being split into a separate handlers module.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml
from mcp import types

from .server import app, HUB, PROJECTS_DIR, SKILLS_DIR, STUDIO_DIR
from .handlers import (
    load_espx, load_manifest, project_conventions, expects_controller,
    list_projects, DB_PATH, _db_conn, _get_api_key,
    _INSTR_KINDS_SQL, _INSTR_KINDS_PY, _sync_project_internal,
)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_projects",
            description=(
                "List all EngineeringStudio projects with "
                "instrument and equipment counts."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_instruments",
            description=(
                "Get all instruments for a project. "
                "Optionally filter by drawing number or instrument type. "
                "Returns tag, type, equipment_ref, loop_id, drawing, confidence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID e.g. 'ctp'"
                    },
                    "drawing": {
                        "type": "string",
                        "description": "Optional drawing number filter e.g. '157-2-130'"
                    },
                    "instrument_type": {
                        "type": "string",
                        "description": (
                            "Optional type filter: transmitter, controller, "
                            "indicator, switch, analyzer, element"
                        )
                    }
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_equipment",
            description=(
                "Get all equipment for a project. "
                "Returns tag, kind, area, drawing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "drawing":    {"type": "string", "description": "Optional drawing filter"}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_loops",
            description=(
                "Get inferred control loops for a project. "
                "Shows measurement, controller, final element, "
                "status (complete/incomplete/no_controller), and confirmation status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id":    {"type": "string", "description": "Project ID"},
                    "status_filter": {
                        "type": "string",
                        "description": "Optional: complete, incomplete, no_controller, unconfirmed"
                    }
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_drawing_context",
            description=(
                "Get full context for a specific drawing: equipment list, "
                "instrument list, connections, loops, and process context "
                "(feeds from/to, safety devices). "
                "Use this to answer questions about a specific P&ID sheet."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "drawing":    {
                        "type": "string",
                        "description": "Drawing number e.g. '157-2-130'"
                    }
                },
                "required": ["project_id", "drawing"]
            }
        ),
        types.Tool(
            name="find_tag",
            description=(
                "Search for a specific tag or tags matching a pattern "
                "across all drawings in a project. "
                "Returns full details including equipment_ref, loop_id, drawing, type, confidence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "query":      {
                        "type": "string",
                        "description": "Tag name or partial pattern e.g. 'PIC-1504' or 'TIC' or '3004'"
                    }
                },
                "required": ["project_id", "query"]
            }
        ),
        types.Tool(
            name="check_loop_completeness",
            description=(
                "Analyse loop completeness for a project or drawing. "
                "Identifies: complete loops, loops missing final element, "
                "loops missing measurement, orphan transmitters with no controller. "
                "Returns actionable findings for engineer review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "drawing":    {"type": "string", "description": "Optional drawing filter"}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_orphaned_instruments",
            description=(
                "Find instruments with no equipment_ref — instruments that could not "
                "be associated with any equipment during extraction. "
                "These need engineer review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_connections",
            description=(
                "Get process connections (pipe runs) for a project or drawing. "
                "Returns line ID, from, to, fluid service, pipe size."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "drawing":    {"type": "string", "description": "Optional drawing filter"}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="get_project_summary",
            description=(
                "Get a complete summary of a project: drawing list, instrument count "
                "by type, equipment count by kind, loop completeness statistics, "
                "data quality metrics. Use as the starting point for any project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"}
                },
                "required": ["project_id"]
            }
        ),
        # ── Action tools ─────────────────────────────────────────────────────────
        types.Tool(
            name="sync_project",
            description=(
                "Regenerate the project .espx file from studio.db so MCP reads "
                "the latest extraction data. Call after any extraction or edit. "
                "Returns node, edge, drawing, instrument, and equipment counts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID e.g. 'uop'"}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="run_extraction",
            description=(
                "Trigger P&ID extraction on a PDF file or directory. "
                "Runs extract_cli.py, streams NDJSON progress, auto-syncs on completion. "
                "Requires an Anthropic API key configured via the app's Settings screen."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id":   {"type": "string", "description": "Project ID"},
                    "source_path":  {"type": "string",
                                     "description": "Full path to PDF or directory of PDFs"},
                    "mode":         {"type": "string",
                                     "enum": ["single", "directory"],
                                     "description": "single = one multi-page PDF, directory = one PDF per drawing"}
                },
                "required": ["project_id", "source_path"]
            }
        ),
        types.Tool(
            name="get_drawing_extraction",
            description=(
                "Return the structured extraction for ONE drawing: equipment list, "
                "instrument list, and connections. Use to review extraction quality "
                "against the original P&ID image."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "drawing":    {"type": "string",
                                   "description": "Drawing number e.g. 'S22018-110-01-A1'"}
                },
                "required": ["project_id", "drawing"]
            }
        ),
        types.Tool(
            name="review_action",
            description=(
                "Accept, reject, or edit a tag in the project. "
                "accept/reject marks the tag's review status. "
                "edit can change the tag name, kind, or area. "
                "Auto-syncs the .espx after any action."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "tag":        {"type": "string", "description": "Tag to act on e.g. 'FT-1001'"},
                    "action":     {"type": "string",
                                   "enum": ["accept", "reject", "edit"]},
                    "edit_data":  {
                        "type": "object",
                        "description": "Only for action=edit",
                        "properties": {
                            "new_tag":  {"type": "string"},
                            "new_kind": {"type": "string"},
                            "new_area": {"type": "string"}
                        }
                    }
                },
                "required": ["project_id", "tag", "action"]
            }
        ),
        types.Tool(
            name="validate_drawing",
            description=(
                "Run automated data quality checks on a drawing: "
                "orphaned instruments, unconnected equipment, duplicate tags, "
                "missing types, suspicious tags. Returns a quality score (0–100)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "drawing":    {"type": "string",
                                   "description": "Drawing number to validate"}
                },
                "required": ["project_id", "drawing"]
            }
        ),
        types.Tool(
            name="launch_app",
            description=(
                "Open the enSTUDIO Tauri desktop application. "
                "Tries the release .exe first; falls back to dev.bat. "
                "Returns immediately — the app stays open after MCP returns."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="export_drawing",
            description=(
                "Export project data. "
                "format=markdown returns the content inline (Claude can read it). "
                "format=vids or ympl writes a file and returns the path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "format":     {"type": "string",
                                   "enum": ["markdown", "vids", "ympl"],
                                   "description": "Export format"},
                    "drawing":    {"type": "string",
                                   "description": "Optional: restrict to one drawing"}
                },
                "required": ["project_id", "format"]
            }
        ),
        types.Tool(
            name="export_connectivity",
            description=(
                "Export the P&ID connectivity graph JSON (nodes, edges, lines, control "
                "loops, signal paths). schema_version 2.0.0 is the base format; 2.1.0 "
                "adds each node's system and subsystem. Writes the file and returns the "
                "path, the metadata summary and any schema violations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "schema_version": {"type": "string", "enum": ["2.0.0", "2.1.0"]}
                },
                "required": ["project_id"]
            }
        ),
        types.Tool(
            name="list_hierarchy",
            description=(
                "The project's plant hierarchy (site > plant > unit > area > system > "
                "subsystem) with node counts and how many nodes are unassigned."
            ),
            inputSchema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"]
            }
        ),
    ]


EQUIP_KINDS = {
    'vessel', 'reactor', 'heat_exchanger', 'compressor',
    'pump', 'column', 'absorber', 'separator', 'filter',
    'fired_heater', 'storage_tank', 'flash_vessel', 'meter'
}


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    def respond(data) -> list[types.TextContent]:
        if isinstance(data, str):
            return [types.TextContent(type="text", text=data)]
        return [types.TextContent(
            type="text",
            text=json.dumps(data, indent=2, default=str)
        )]

    pid = arguments.get("project_id", "")

    # ── list_projects ──────────────────────────────────────────────────────────
    if name == "list_projects":
        projects = list_projects()
        if not projects:
            return respond("No projects found in EngineeringHub.")
        return respond(projects)

    # ── get_instruments ────────────────────────────────────────────────────────
    elif name == "get_instruments":
        espx = load_espx(pid)
        instruments = espx.get('studio', {}).get('instruments', {})
        drawing_filter = arguments.get('drawing', '').strip()
        type_filter    = arguments.get('instrument_type', '').strip().lower()

        # studio.instruments[tag] doesn't always carry 'drawing'. Cross-reference
        # espx['nodes'] (which is stamped by Pass 1 + preserved through rebuild)
        # so MCP responses always answer "which sheet is this tag on?"
        label_to_drawing: dict = {}
        for n in espx.get('nodes', []) or []:
            lbl = (n.get('label') or '').strip().upper()
            dwg = n.get('drawing') or ''
            if lbl and dwg and lbl not in label_to_drawing:
                label_to_drawing[lbl] = dwg

        results = []
        for tag, data in sorted(instruments.items()):
            if not isinstance(data, dict):
                continue
            drw = data.get('drawing') or label_to_drawing.get(tag.strip().upper(), '')
            typ = (data.get('type') or '').lower()
            if drawing_filter and drawing_filter not in drw:
                continue
            if type_filter and type_filter not in typ:
                continue
            results.append({
                'tag':           tag,
                'type':          data.get('type'),
                'equipment_ref': data.get('equipment_ref'),
                'loop_id':       data.get('loop_id'),
                'drawing':       drw,
                'confidence':    data.get('confidence'),
            })
        return respond({'count': len(results), 'instruments': results})

    # ── get_equipment ──────────────────────────────────────────────────────────
    elif name == "get_equipment":
        espx = load_espx(pid)
        drawing_filter = arguments.get('drawing', '').strip()
        results = []
        for node in espx.get('nodes', []):
            if node.get('kind') not in EQUIP_KINDS:
                continue
            drw = node.get('drawing', '')
            if drawing_filter and drawing_filter not in drw:
                continue
            results.append({
                'tag':     node.get('label'),
                'kind':    node.get('kind'),
                'area':    node.get('area'),
                'drawing': drw,
            })
        return respond({
            'count':     len(results),
            'equipment': sorted(results, key=lambda x: x.get('drawing', ''))
        })

    # ── get_loops ──────────────────────────────────────────────────────────────
    elif name == "get_loops":
        espx = load_espx(pid)
        loops = espx.get('studio', {}).get('loops', {})
        status_filter = arguments.get('status_filter', '').strip().lower()

        if not loops:
            return respond(
                "No loops inferred yet. Run loop inference in EngineeringStudio first."
            )

        results = []
        for loop_id, loop in sorted(loops.items()):
            status    = loop.get('status', '')
            confirmed = loop.get('confirmed', False)
            if status_filter == 'unconfirmed' and confirmed:
                continue
            elif status_filter and status_filter != 'unconfirmed':
                if status != status_filter:
                    continue
            results.append({
                'loop_id':       loop_id,
                'variable':      loop.get('variable'),
                'measurement':   loop.get('measurement'),
                'controller':    loop.get('controller'),
                'final_element': loop.get('final_element'),
                'alarms':        loop.get('alarms', []),
                'status':        status,
                'confirmed':     confirmed,
                'drawing':       loop.get('drawing'),
            })

        return respond({
            'total':            len(loops),
            'complete':         sum(1 for l in loops.values() if l.get('status') == 'complete'),
            'incomplete':       sum(1 for l in loops.values() if l.get('status') == 'incomplete'),
            'no_controller':    sum(1 for l in loops.values() if l.get('status') == 'no_controller'),
            'confirmed':        sum(1 for l in loops.values() if l.get('confirmed')),
            'filtered_results': len(results),
            'loops':            results,
        })

    # ── get_drawing_context ────────────────────────────────────────────────────
    elif name == "get_drawing_context":
        drawing = arguments.get('drawing', '').strip()
        espx    = load_espx(pid)
        studio  = espx.get('studio', {})
        nodes   = espx.get('nodes', [])
        edges   = espx.get('edges', [])
        instruments = studio.get('instruments', {})
        loops       = studio.get('loops', {})
        connections = studio.get('connections', [])

        equip = [
            {'tag': n.get('label'), 'kind': n.get('kind'), 'area': n.get('area')}
            for n in nodes
            if n.get('drawing') == drawing and n.get('kind') in EQUIP_KINDS
        ]
        instr = [
            {'tag': tag, 'type': d.get('type'),
             'equipment_ref': d.get('equipment_ref'),
             'loop_id': d.get('loop_id'),
             'confidence': d.get('confidence')}
            for tag, d in instruments.items()
            if isinstance(d, dict) and d.get('drawing') == drawing
        ]
        off_page = [
            n.get('label') for n in nodes
            if n.get('drawing') == drawing and n.get('kind') == 'off_page_connector'
        ]
        drw_loops = [
            {'loop_id': lid, 'status': l.get('status'),
             'measurement': l.get('measurement'),
             'controller':  l.get('controller'),
             'final_element': l.get('final_element')}
            for lid, l in loops.items()
            if l.get('drawing') == drawing
        ]
        safety_tags = [
            tag for tag, d in instruments.items()
            if isinstance(d, dict)
            and d.get('drawing') == drawing
            and any(tag.startswith(p) for p in
                    ['PSV', 'ESD', 'PAHH', 'TSHH', 'LSHH', 'PSHH', 'FSL', 'FSLL'])
        ]
        return respond({
            'drawing':             drawing,
            'project':             pid,
            'equipment':           equip,
            'instruments':         {'count': len(instr), 'list': instr},
            'loops':               drw_loops,
            'off_page_connectors': off_page,
            'safety_devices':      safety_tags,
            'connections':         [c for c in connections if c.get('drawing') == drawing],
        })

    # ── find_tag ───────────────────────────────────────────────────────────────
    elif name == "find_tag":
        query       = arguments.get('query', '').strip().upper()
        espx        = load_espx(pid)
        instruments = espx.get('studio', {}).get('instruments', {})
        nodes       = espx.get('nodes', [])

        results = []
        for tag, data in instruments.items():
            if query in tag.upper():
                results.append({
                    'tag':           tag,
                    'source':        'instrument',
                    'type':          data.get('type') if isinstance(data, dict) else None,
                    'equipment_ref': data.get('equipment_ref') if isinstance(data, dict) else None,
                    'loop_id':       data.get('loop_id') if isinstance(data, dict) else None,
                    'drawing':       data.get('drawing') if isinstance(data, dict) else None,
                    'confidence':    data.get('confidence') if isinstance(data, dict) else None,
                })
        for node in nodes:
            label = node.get('label', '')
            if query in label.upper() and not any(r['tag'] == label for r in results):
                results.append({
                    'tag':     label,
                    'source':  'node',
                    'kind':    node.get('kind'),
                    'drawing': node.get('drawing'),
                    'area':    node.get('area'),
                })
        return respond({'query': query, 'count': len(results), 'results': results})

    # ── check_loop_completeness ────────────────────────────────────────────────
    elif name == "check_loop_completeness":
        drawing_filter = arguments.get('drawing', '').strip()
        espx  = load_espx(pid)
        loops = espx.get('studio', {}).get('loops', {})

        if not loops:
            return respond("No loops inferred. Run loop inference first.")

        # Conventions tell us which prefixes (HT, JE, JT, RT, ...) are
        # measurement-only and should not be flagged as orphan transmitters.
        conv = project_conventions(pid)

        findings = {
            'complete':              [],
            'missing_valve':         [],
            'missing_measurement':   [],
            'controller_only':       [],
            'orphan_transmitters':   [],
        }
        excluded_measurement_only = 0
        for lid, loop in sorted(loops.items()):
            drw    = loop.get('drawing', '')
            status = loop.get('status')
            if drawing_filter and drawing_filter not in drw:
                continue
            if status == 'complete':
                findings['complete'].append({
                    'loop': lid, 'drawing': drw,
                    'measurement':   loop.get('measurement'),
                    'final_element': loop.get('final_element'),
                })
            elif status == 'incomplete':
                if loop.get('measurement') and not loop.get('final_element'):
                    findings['missing_valve'].append({
                        'loop': lid, 'drawing': drw,
                        'controller':  loop.get('controller'),
                        'measurement': loop.get('measurement'),
                    })
                elif loop.get('final_element') and not loop.get('measurement'):
                    findings['missing_measurement'].append({
                        'loop': lid, 'drawing': drw,
                        'controller':    loop.get('controller'),
                        'final_element': loop.get('final_element'),
                    })
            elif status == 'controller_only':
                findings['controller_only'].append({
                    'loop': lid, 'drawing': drw,
                    'controller': loop.get('controller'),
                })
            elif status == 'no_controller':
                meas_tag = loop.get('measurement') or ''
                if not expects_controller(meas_tag, conv):
                    excluded_measurement_only += 1
                    continue
                findings['orphan_transmitters'].append({
                    'tag':      meas_tag,
                    'drawing':  drw,
                    'has_valve': bool(loop.get('final_element')),
                })

        return respond({
            'scope':                      drawing_filter or 'full plant',
            'complete_count':             len(findings['complete']),
            'missing_valve_count':        len(findings['missing_valve']),
            'missing_measurement_count':  len(findings['missing_measurement']),
            'controller_only_count':      len(findings['controller_only']),
            'orphan_transmitter_count':   len(findings['orphan_transmitters']),
            'measurement_only_excluded':  excluded_measurement_only,
            'findings':                   findings,
        })

    # ── get_orphaned_instruments ───────────────────────────────────────────────
    elif name == "get_orphaned_instruments":
        espx        = load_espx(pid)
        instruments = espx.get('studio', {}).get('instruments', {})
        orphans = [
            {'tag': tag, 'type': d.get('type'),
             'drawing': d.get('drawing'), 'confidence': d.get('confidence')}
            for tag, d in instruments.items()
            if isinstance(d, dict) and not d.get('equipment_ref')
        ]
        return respond({
            'count':                  len(orphans),
            'orphaned_instruments':   sorted(orphans, key=lambda x: x.get('drawing', '')),
        })

    # ── get_connections ────────────────────────────────────────────────────────
    elif name == "get_connections":
        drawing_filter = arguments.get('drawing', '').strip()
        espx  = load_espx(pid)
        nodes = espx.get('nodes', [])
        edges = espx.get('edges', [])
        node_map = {n['id']: n for n in nodes}

        results = []
        for edge in edges:
            if edge.get('kind') in ('signal', 'inter_drawing'):
                continue
            from_node = node_map.get(edge.get('from', ''), {})
            to_node   = node_map.get(edge.get('to',   ''), {})
            if drawing_filter and drawing_filter not in from_node.get('drawing', ''):
                continue
            results.append({
                'line_id': edge.get('label', ''),
                'from':    from_node.get('label', edge.get('from', '')),
                'to':      to_node.get('label',   edge.get('to',   '')),
                'kind':    edge.get('kind', 'stream'),
            })
        return respond({'count': len(results), 'connections': results[:200]})

    # ── get_project_summary ────────────────────────────────────────────────────
    elif name == "get_project_summary":
        espx         = load_espx(pid)
        manifest     = load_manifest(pid)
        studio       = espx.get('studio', {})
        nodes        = espx.get('nodes', [])
        instruments  = studio.get('instruments', {})
        equipment_db = studio.get('equipment', {})
        loops        = studio.get('loops', {})

        drawings = sorted(set(
            n.get('drawing', '') for n in nodes if n.get('drawing')
        ))

        type_counts: dict = {}
        for d in instruments.values():
            if isinstance(d, dict):
                t = d.get('type', 'unknown')
                type_counts[t] = type_counts.get(t, 0) + 1

        def conf(d): return d.get('confidence') or 0
        high   = sum(1 for d in instruments.values() if isinstance(d, dict) and conf(d) >= 0.75)
        medium = sum(1 for d in instruments.values() if isinstance(d, dict) and 0.5 <= conf(d) < 0.75)
        low    = sum(1 for d in instruments.values() if isinstance(d, dict) and conf(d) < 0.5)

        loop_stats = {
            'total':         len(loops),
            'complete':      sum(1 for l in loops.values() if l.get('status') == 'complete'),
            'incomplete':    sum(1 for l in loops.values() if l.get('status') == 'incomplete'),
            'no_controller': sum(1 for l in loops.values() if l.get('status') == 'no_controller'),
            'confirmed':     sum(1 for l in loops.values() if l.get('confirmed')),
        }
        orphaned = sum(1 for d in instruments.values()
                       if isinstance(d, dict) and not d.get('equipment_ref'))

        return respond({
            'project_id':   pid,
            'plant_name':   manifest.get('name', pid),
            'process_type': studio.get('metadata', {}).get('process_type'),
            'drawings':     drawings,
            'drawing_count': len(drawings),
            'instruments': {
                'total':    len(instruments),
                'by_type':  type_counts,
                'orphaned': orphaned,
                'confidence': {
                    'high_75plus':   high,
                    'medium_50_75':  medium,
                    'low_below_50':  low,
                },
            },
            'equipment': {'total': len(equipment_db)},
            'loops': loop_stats,
            'data_quality': {
                'orphaned_instruments':    orphaned,
                'unconfirmed_loops':       loop_stats['total'] - loop_stats['confirmed'],
                'low_confidence_instruments': low,
            },
        })

    # ── sync_project ──────────────────────────────────────────────────────────
    elif name == "sync_project":
        try:
            result = _sync_project_internal(pid)
            return respond(result)
        except Exception as e:
            return respond({'error': str(e)})

    # ── run_extraction ────────────────────────────────────────────────────────
    elif name == "run_extraction":
        source_path = arguments.get('source_path', '').strip()
        mode        = arguments.get('mode', 'single')
        src = Path(source_path)
        if not src.exists():
            return respond({'error': f'source_path not found: {source_path}'})

        key = _get_api_key()
        if not key:
            return respond({'error': 'Anthropic API key not configured — set it in the app\'s Settings screen'})

        cmd = [sys.executable, str(STUDIO_DIR / 'extract_cli.py'),
               str(HUB), pid, source_path]

        env = {**os.environ, 'ANTHROPIC_API_KEY': key,
               'ENGINEERING_HUB': str(HUB)}

        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=str(STUDIO_DIR),
                capture_output=True, text=True, env=env, timeout=3600
            )
        except subprocess.TimeoutExpired:
            return respond({'error': 'Extraction timed out after 1 hour'})
        except Exception as e:
            return respond({'error': f'Subprocess failed: {e}'})

        # Parse NDJSON output — find the final "done" line
        done_data: dict = {}
        pages_ok, pages_err = 0, 0
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('stage') == 'done':
                    done_data = obj
                elif obj.get('stage') == 'page':
                    if obj.get('status') == 'complete':
                        pages_ok += 1
                    elif obj.get('status') == 'error':
                        pages_err += 1
            except json.JSONDecodeError:
                pass

        if proc.returncode != 0 and not done_data:
            stderr_tail = proc.stderr[-800:] if proc.stderr else ''
            return respond({
                'error':     f'extract_cli.py exited {proc.returncode}',
                'stderr':    stderr_tail,
            })

        # Auto-sync the .espx so subsequent read-tools see fresh data
        try:
            sync_result = _sync_project_internal(pid)
        except Exception as e:
            sync_result = {'error': str(e)}

        return respond({
            'nodes':      done_data.get('total_nodes', sync_result.get('nodes', 0)),
            'edges':      done_data.get('total_edges', sync_result.get('edges', 0)),
            'drawings':   sync_result.get('drawings', 0),
            'rejected':   done_data.get('total_rejected', 0),
            'pages_ok':   pages_ok,
            'pages_err':  pages_err,
            'elapsed':    done_data.get('elapsed', round(time.time() - t0, 1)),
            'cached':     done_data.get('cached', False),
            'sync':       sync_result,
        })

    # ── get_drawing_extraction ────────────────────────────────────────────────
    elif name == "get_drawing_extraction":
        drawing = arguments.get('drawing', '').strip()
        if not drawing:
            return respond({'error': 'drawing parameter is required'})
        try:
            conn = _db_conn()
            try:
                equip_rows = conn.execute(
                    f"""SELECT label AS tag, kind, kind_detail AS name, area
                        FROM nodes
                        WHERE pid=?
                          AND COALESCE(json_extract(extra_json,'$.drawing'),'') = ?
                          AND kind NOT IN ({_INSTR_KINDS_SQL})
                          AND label NOT LIKE 'off_page%'
                        ORDER BY label""",
                    (pid, drawing)
                ).fetchall()

                instr_rows = conn.execute(
                    f"""SELECT label AS tag, kind AS type,
                               json_extract(extra_json,'$.equipment_ref') AS equipment_ref
                        FROM nodes
                        WHERE pid=?
                          AND COALESCE(json_extract(extra_json,'$.drawing'),'') = ?
                          AND kind IN ({_INSTR_KINDS_SQL})
                        ORDER BY label""",
                    (pid, drawing)
                ).fetchall()

                conn_rows = conn.execute(
                    """SELECT n1.label AS from_tag, n2.label AS to_tag, e.kind
                       FROM edges e
                       JOIN nodes n1 ON n1.id=e.from_id AND n1.pid=e.pid
                       JOIN nodes n2 ON n2.id=e.to_id   AND n2.pid=e.pid
                       WHERE e.pid=?
                         AND COALESCE(json_extract(n1.extra_json,'$.drawing'),'') = ?
                       LIMIT 500""",
                    (pid, drawing)
                ).fetchall()
            finally:
                conn.close()

            equipment    = [dict(r) for r in equip_rows]
            instruments  = [dict(r) for r in instr_rows]
            connections  = [{'from': r['from_tag'], 'to': r['to_tag'],
                              'type': r['kind']} for r in conn_rows]
            return respond({
                'drawing':     drawing,
                'equipment':   equipment,
                'instruments': instruments,
                'connections': connections,
                'stats': {
                    'equipment_count':   len(equipment),
                    'instrument_count':  len(instruments),
                    'connection_count':  len(connections),
                }
            })
        except Exception as e:
            return respond({'error': str(e)})

    # ── review_action ─────────────────────────────────────────────────────────
    elif name == "review_action":
        tag       = arguments.get('tag', '').strip()
        action    = arguments.get('action', '').strip()
        edit_data = arguments.get('edit_data') or {}
        if not tag or not action:
            return respond({'error': 'tag and action are required'})
        try:
            conn = _db_conn()
            try:
                if action in ('accept', 'reject'):
                    status = 'accepted' if action == 'accept' else 'rejected'
                    conn.execute(
                        """UPDATE nodes
                           SET extra_json = json_set(COALESCE(extra_json,'{}'),
                                                     '$.review_status', ?)
                           WHERE pid=? AND label=?""",
                        (status, pid, tag)
                    )
                    # Also write to the review table if it exists
                    conn.execute(
                        "INSERT OR REPLACE INTO review (pid, key, state) VALUES (?,?,?)",
                        (pid, tag, status)
                    )
                elif action == 'edit':
                    new_tag  = edit_data.get('new_tag',  tag)
                    new_kind = edit_data.get('new_kind', '')
                    new_area = edit_data.get('new_area', '')
                    sql_parts, params = [], []
                    if new_tag != tag:
                        sql_parts.append('label=?'); params.append(new_tag)
                    if new_kind:
                        sql_parts.append('kind=?'); params.append(new_kind)
                    if new_area:
                        sql_parts.append('area=?'); params.append(new_area)
                    if sql_parts:
                        params += [pid, tag]
                        conn.execute(
                            f"UPDATE nodes SET {', '.join(sql_parts)} WHERE pid=? AND label=?",
                            params
                        )
                else:
                    return respond({'error': f'Unknown action: {action}'})
                conn.commit()
            finally:
                conn.close()

            sync_result = _sync_project_internal(pid)
            return respond({'action': action, 'tag': tag, 'success': True,
                            'sync': sync_result})
        except Exception as e:
            return respond({'error': str(e)})

    # ── validate_drawing ──────────────────────────────────────────────────────
    elif name == "validate_drawing":
        drawing = arguments.get('drawing', '').strip()
        if not drawing:
            return respond({'error': 'drawing parameter is required'})
        try:
            conn = _db_conn()
            try:
                all_rows = conn.execute(
                    """SELECT id, label, kind,
                              COALESCE(json_extract(extra_json,'$.equipment_ref'),'') AS eq_ref,
                              COALESCE(json_extract(extra_json,'$.confidence'), 1.0) AS conf
                       FROM nodes
                       WHERE pid=?
                         AND COALESCE(json_extract(extra_json,'$.drawing'),'') = ?""",
                    (pid, drawing)
                ).fetchall()

                node_ids = {r['id'] for r in all_rows}
                equip_ids: dict = {}   # id → label
                instr_tags: list = []
                all_labels: list = []
                for r in all_rows:
                    lbl  = r['label'] or ''
                    kind = (r['kind'] or '').lower()
                    all_labels.append(lbl)
                    if kind in _INSTR_KINDS_PY:
                        instr_tags.append({'tag': lbl, 'eq_ref': r['eq_ref'],
                                           'conf': r['conf']})
                    elif lbl and not lbl.lower().startswith('off_page'):
                        equip_ids[r['id']] = lbl

                # Edges touching this drawing
                connected_equip: set = set()
                if equip_ids:
                    id_ph = ','.join('?' * len(equip_ids))
                    edge_rows = conn.execute(
                        f"""SELECT from_id, to_id FROM edges
                            WHERE pid=?
                              AND (from_id IN ({id_ph}) OR to_id IN ({id_ph}))""",
                        [pid] + list(equip_ids) * 2
                    ).fetchall()
                    for er in edge_rows:
                        connected_equip.add(er['from_id'])
                        connected_equip.add(er['to_id'])
            finally:
                conn.close()

            # ── checks ──────────────────────────────────────────────────────
            orphaned  = [i['tag'] for i in instr_tags if not i['eq_ref']]
            no_conn   = [lbl for eid, lbl in equip_ids.items()
                         if eid not in connected_equip]
            from collections import Counter
            dup_tags  = [lbl for lbl, cnt in Counter(all_labels).items() if cnt > 1]
            missing   = [r['label'] for r in all_rows if not r['kind']]
            suspicious = [
                r['label'] for r in all_rows
                if r['label'] and r['label'].isdigit() and len(r['label']) > 3
            ]

            # Score: start at 100, deduct per issue category
            deductions = (min(len(orphaned), 20) +
                          min(len(no_conn) * 2, 20) +
                          len(dup_tags) * 5 +
                          len(missing) +
                          len(suspicious) * 2)
            score = max(0, 100 - deductions)

            return respond({
                'drawing': drawing,
                'checks': {
                    'orphaned_instruments':      orphaned,
                    'equipment_no_connections':  no_conn,
                    'duplicate_tags':            dup_tags,
                    'missing_types':             missing,
                    'suspicious_tags':           suspicious,
                },
                'score': score,
                'total_nodes': len(all_rows),
            })
        except Exception as e:
            return respond({'error': str(e)})

    # ── launch_app ────────────────────────────────────────────────────────────
    elif name == "launch_app":
        exe = Path(r'C:\Users\expadmin\Projects\standard\frontend'
                   r'\src-tauri\target\release\enstudio.exe')
        bat = Path(r'C:\Users\expadmin\Projects\standard\frontend\dev.bat')
        try:
            if exe.exists():
                subprocess.Popen(
                    [str(exe)],
                    creationflags=subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
                return respond({'launched': 'exe', 'path': str(exe)})
            elif bat.exists():
                subprocess.Popen(
                    ['cmd', '/c', str(bat)],
                    creationflags=subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
                return respond({'launched': 'dev', 'path': str(bat)})
            else:
                return respond({'error': 'Neither enstudio.exe nor dev.bat found'})
        except Exception as e:
            return respond({'error': str(e)})

    # ── export_drawing ────────────────────────────────────────────────────────
    elif name == "export_drawing":
        fmt     = arguments.get('format', 'markdown').lower()
        drawing = arguments.get('drawing', '').strip()
        espx    = load_espx(pid)
        export_dir = PROJECTS_DIR / pid / 'exports'
        export_dir.mkdir(parents=True, exist_ok=True)

        if fmt == 'markdown':
            try:
                from adapters.md_export import to_markdown
                manifest = load_manifest(pid)
                result   = to_markdown(espx, manifest=manifest)
                if drawing:
                    content = result.get(drawing) or result.get('_index', '')
                    return respond({'drawing': drawing, 'content': content,
                                    'format': 'markdown'})
                # Return index + first drawing inline
                combined = '\n\n---\n\n'.join(
                    v for k, v in result.items() if isinstance(v, str)
                )
                return respond({'format': 'markdown', 'content': combined[:20000]})
            except Exception as e:
                return respond({'error': f'Markdown export failed: {e}'})

        elif fmt == 'vids':
            nodes = espx.get('nodes', [])
            studio = espx.get('studio', {})
            instr  = studio.get('instruments', {})
            equip  = studio.get('equipment', {})
            vids = {
                'project': pid,
                'equipment': [
                    {'tag': tag, **({k: v for k, v in d.items()} if isinstance(d, dict) else {})}
                    for tag, d in equip.items()
                    if not drawing or (isinstance(d, dict) and drawing in d.get('drawing', ''))
                ],
                'instruments': [
                    {'tag': tag, **({k: v for k, v in d.items()} if isinstance(d, dict) else {})}
                    for tag, d in instr.items()
                    if not drawing or (isinstance(d, dict) and drawing in d.get('drawing', ''))
                ],
                'connections': studio.get('connections', []),
            }
            fname = f'{pid}_vids{"_" + drawing.replace("/","-") if drawing else ""}.yaml'
            fpath = export_dir / fname
            fpath.write_text(yaml.dump(vids, default_flow_style=False, allow_unicode=True),
                             encoding='utf-8')
            return respond({'format': 'vids', 'path': str(fpath),
                            'equipment': len(vids['equipment']),
                            'instruments': len(vids['instruments'])})

        elif fmt == 'ympl':
            nodes = espx.get('nodes', [])
            edges = espx.get('edges', [])
            ympl = {
                'schema_version': 'ympl-1.0',
                'id':    pid,
                'title': load_manifest(pid).get('name', pid),
                'nodes': [
                    {'id': n['id'], 'label': n.get('label'), 'kind': n.get('kind'),
                     'drawing': n.get('drawing')}
                    for n in nodes
                    if not drawing or n.get('drawing') == drawing
                ],
                'edges': [
                    {'from': e['from'], 'to': e['to'], 'kind': e.get('kind', 'stream')}
                    for e in edges
                ],
                'meta': {'source': 'mcp_export'}
            }
            fname = f'{pid}.ympl'
            fpath = export_dir / fname
            fpath.write_text(yaml.dump(ympl, default_flow_style=False, allow_unicode=True),
                             encoding='utf-8')
            return respond({'format': 'ympl', 'path': str(fpath),
                            'nodes': len(ympl['nodes']),
                            'edges': len(ympl['edges'])})

        else:
            return respond({'error': f'Unknown format: {fmt}'})

    # ── export_connectivity / list_hierarchy ──────────────────────────────────
    # Both read the hub database directly, so point adapters.db at it first.
    elif name in ("export_connectivity", "list_hierarchy"):
        from adapters import db as _hub_db
        _hub_db.reset_for_path(HUB / 'studio.db')
        _hub_db.init_db()
        if name == "list_hierarchy":
            from services.hierarchy import tree
            return respond(tree(pid))
        from adapters.connectivity_export import validate, write_export
        schema = arguments.get("schema_version") or "2.0.0"
        path = write_export(pid, PROJECTS_DIR / pid / "exports", schema)
        document = json.loads(path.read_text(encoding="utf-8"))
        return respond({"path": str(path), "metadata": document["metadata"],
                        "validation_errors": validate(document)})

    else:
        return respond(f"Unknown tool: {name}")
