# PlantSketch Desktop — Claude Code Guide

Tauri 2 desktop app (React + Vite frontend, Rust backend).
Reads from `studio.db` at the EngineeringHub path. No Flask dependency
for core operations — exports and canvas run directly from the DB.

---

## Stack

| Layer       | Tech                          |
|-------------|-------------------------------|
| Shell       | Tauri 2.11 (Rust)             |
| Frontend    | React 19 + Vite 8 + TypeScript |
| Graph       | @xyflow/react 12 + @dagrejs/dagre |
| DB          | rusqlite (reads studio.db)    |
| Build env   | VS2022 BuildTools 14.44.35207 |

---

## Run (dev)

```
cd C:\Users\expadmin\Projects\standard\frontend
dev.bat          ← sets VS2022 env then runs cargo tauri dev
```

`dev.bat` calls `vcvarsall.bat x64` from VS2022 BuildTools before
`cargo tauri dev`. Do not use the VS18 toolchain — it is missing
`msvcrt.lib` and will fail to link.

---

## Project layout

```
src/                              React frontend
  App.tsx                         Root — Screen router, Project type
  components/
    Sidebar.tsx                   Project list + nav (invokes list_projects)
    Topbar.tsx                    Project name + screen label
    screens/
      ReviewScreen.tsx            Instrument review — accept/reject, inline edit
      IngestScreen.tsx            PDF upload + CLI extraction with streaming log
      CanvasScreen.tsx            React Flow graph — dagre layout, ISA node shapes
      ExportScreen.tsx            VIDS/YMPL/Markdown (native Rust) + SVG (Flask)
      GapsScreen.tsx              Data quality — orphans, low-conf, missing drawings
src-tauri/
  src/lib.rs                      All Tauri commands (read below)
  Cargo.toml                      ureq features = ["json"] required
  capabilities/default.json       dialog:default permission
```

---

## Tauri commands (lib.rs)

### Read commands
| Command | Table(s) | Notes |
|---|---|---|
| `list_projects` | projects + instruments + equipment + sources | sidebar |
| `get_instruments` | instruments LEFT JOIN review | Review screen |
| `get_equipment` | equipment | Review screen |
| `get_graph` | nodes + edges (primary) merged with connections (secondary) | Canvas |
| `get_sources` | sources | Ingest screen |
| `get_gaps` | instruments, equipment | Gaps screen |
| `get_export_status` | filesystem exports/ dir | Export screen |

### Write commands
| Command | Action |
|---|---|
| `update_review_status` | INSERT OR REPLACE INTO review (pid, key, state) |
| `bulk_update_review` | same, in transaction |
| `update_instrument` | UPDATE instruments — equipment_ref, area, or json_set description |
| `add_connection` | INSERT OR IGNORE INTO connections |
| `delete_instrument` | transaction: DELETE instruments + review |

### Export commands (no Flask needed)
| Command | Output |
|---|---|
| `export_vids` | `{pid}_vids.yaml` — connections → equipment → instruments → metadata |
| `export_ympl` | `{pid}.ympl` — edges → id → meta → nodes → schema_version → title |
| `export_markdown` | `{pid}_report.md` — tables + data quality |

### Extraction commands
| Command | Action |
|---|---|
| `run_extraction(project_id, source_id)` | async: spawns `python extract_cli.py` |
| `cancel_extraction()` | kills spawned process |
| `set_api_key(key)` | stores ANTHROPIC_API_KEY in session memory |
| `get_api_key_status()` | checks if key is set |

`run_extraction` emits `extraction-progress` events (NDJSON per line from extract_cli.py).
IngestScreen listens via `listen('extraction-progress', ...)` from `@tauri-apps/api/event`.

---

## Canvas screen architecture

`CanvasScreen.tsx` uses dagre for hierarchical LR layout:

1. `get_graph` returns nodes (from `nodes` table) + edges (merged `edges` + `connections`)
2. Soft tags (alarm/switch variants AL-, AH-, PAL-, etc.) are collapsed into their parent
   instrument via `buildSoftGroups()` — parent shows "+N alarms" badge
3. Association edges built from `equipment_ref` (instruments near their equipment)
4. Dagre layout: equipment 200×70, instruments 70–82×36–46, valves 44×44 diamond
5. Orphan nodes (no edges, no equipment_ref) shown in strip below canvas
6. Off-page connectors rendered as pentagon chevrons

Node type colours:
- Equipment: blue (`#3b82f6`), HX: green, reactor: red, compressor: indigo, column: purple
- Instruments: by ISA function letter — F=cyan, P=purple, T=red, L=green, A=amber, S=orange
- Valves (CV/HV/XV…): slate gray, diamond shape

---

## DB location

Resolved by `find_db()` in lib.rs — checks `ENGINEERING_HUB` env var, then two
hardcoded candidates:
```
C:\Users\expadmin\Projects\standard\EngineeringHub\EngineeringHub\studio.db
C:\Users\expadmin\Projects\standard\EngineeringHub\studio.db
```

Exports written to `{hub}/projects/{pid}/exports/`.
PDFs read from `{hub}/projects/{pid}/source_docs/`.
`extract_cli.py` located at `{repo_root}/backend/extract_cli.py`
(two levels up from the hub directory).

---

## New extraction pipeline (May 2026)

The studio now uses per-page extraction instead of multi-page batch:

```
PDF → page_splitter.py (pymupdf) → page_N.png
     → extract_page.py (Sonnet, PASS1_SINGLE_PAGE) → validated nodes + edges
     → import_extraction.py → studio.db
```

Results on CTP: 364 nodes (was 857 with ghosts), 289 edges (was 162), ratio 0.79.

`extract_cli.py` is the CLI entry point that `run_extraction` spawns.
It reads the same DB and hub path as the desktop app.

---

## Known issues / gotchas

- `ureq` must have `features = ["json"]` in Cargo.toml for `into_json()` to compile
- `edgesUpdatable` prop was removed in @xyflow/react v12; use `edgesFocusable={false}`
- VS18 BuildTools (14.50.35717) is incomplete — use VS2022 (14.44.35207) for builds
- Windows asyncio policy deprecated in Python 3.13 — only set on Python < 3.12
