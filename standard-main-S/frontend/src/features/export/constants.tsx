import type { ReactNode } from 'react'
import { EXPORT_SUFFIXES } from '../../domain/export/filenames'

export interface CardDef {
  key:     string
  icon:    ReactNode
  title:   string
  desc:    string
  preview: string
  matchFn: (files: string[]) => string | undefined
}

export const CARDS: CardDef[] = [
  {
    key:     'vids',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>,
    title:   'VIDS YAML',
    desc:    'enVIEW operator configuration — instruments, alarms, ranges, screen assignments.',
    preview: 'instruments:\n  FT-101:\n    area: FEED GAS\n    type: transmitter\nequipment:\n  E-101:\n    type: heat_exchanger',
    // VIDS is written only to the path chosen in the Save dialog — never into
    // the hub's exports/ dir that getExportStatus lists. Matching against that
    // listing reported a file this export doesn't produce (an old copy left by
    // the removed export_vids command) as if it were the last export.
    matchFn: () => undefined,
  },
  {
    key:     'ympl',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"></path><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 7.76a6 6 0 0 0 0 8.49"></path></svg>,
    title:   'YMPL',
    desc:    'enableSim topology model — nodes, edges, Perry defaults. Feed directly into enable build.',
    preview: 'schema_version: ympl-1.0\nnodes:\n- id: n1\n  label: E-201\n  kind: heat_exchanger\n  x: 2.5\n  y: 0.5',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.ympl)),
  },
  {
    key:     'connectivity',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="12" r="2"></circle><circle cx="19" cy="5" r="2"></circle><circle cx="19" cy="19" r="2"></circle><path d="M7 11l10-5M7 13l10 5"></path></svg>,
    title:   'Connectivity graph JSON',
    desc:    'Schema 2.0.0 graph — nodes, pipe runs, flow direction, control loops and signal paths, including every retrofit.',
    preview: '{\n  "metadata": { "schema_version": "2.0.0", "diagram_type": "PID" },\n  "nodes": { "PT-1111": { "type": "instrument", "point": [265, 410] } },\n  "control_loops": { "P1111": { "loop_type": "Pressure" } }\n}',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.connectivity)),
  },
  {
    key:     'connectivity_hierarchy',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="2" width="6" height="5" rx="1"></rect><rect x="2" y="17" width="6" height="5" rx="1"></rect><rect x="16" y="17" width="6" height="5" rx="1"></rect><path d="M12 7v5M5 17v-3h14v3"></path></svg>,
    title:   'Connectivity JSON + systems',
    desc:    'Schema 2.1.0 — the same graph with each node\'s system, subsystem, origin and specification status.',
    preview: '{\n  "nodes": { "PT-1111": { "system": "Hydrocarbon Ingress", "subsystem": "Feed Supply Header", "origin": "authored" } }\n}',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.connectivity_hierarchy)),
  },
  {
    key:     'markdown',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>,
    title:   'Markdown report',
    desc:    'Human-readable project report — instrument table, equipment table, data quality summary.',
    preview: '# Project: ctp\n## Instruments (N)\n| Tag | Type | Drawing | Equip Ref | Confidence |\n|---|---|---|---|---|',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.markdown)),
  },
  {
    key:     'mermaid',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="8.5" y="14" width="7" height="7" rx="1"></rect><path d="M6.5 10v2a2 2 0 0 0 2 2h2M17.5 10v2a2 2 0 0 0-2 2h-2"></path></svg>,
    title:   'Mermaid Diagram',
    desc:    'Flowchart of the extracted P&ID — nodes and edges as a mermaid.js flowchart, for docs/wikis/GitHub.',
    preview: 'flowchart LR\n\nclassDef vessel fill:#E8F4FD,stroke:#2E6DA4\n\n  n_n1(("FT-101")):::transmitter\n  n_n2["E-101"]:::heatExchanger\n\n  n_n1 --> n_n2',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.mermaid)),
  },
  {
    key:     'svg',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>,
    title:   'SVG',
    desc:    'ISA-5.1 vector drawing — real paths and text, so it opens and edits in Inkscape, Illustrator or CAD.',
    preview: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1441 1476">\n  <g id="layer-piping">\n    <path d="M 420,300 L 512,300" marker-end="url(#arrow_stream)"/>\n  <g id="layer-instruments">\n    <circle cx="560" cy="410" r="22"/>',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.svg)),
  },
  {
    key:     'dxf',
    icon:    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M9 15l3 3 3-3M12 18v-6"></path></svg>,
    title:   'DXF (AutoCAD)',
    desc:    'AutoCAD R2010 DXF — ISA-5.1 blocks and layers, for import into AutoCAD/Inkscape/etc.',
    preview: '0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nBLOCKS\n...',
    matchFn: files => files.find(f => f.endsWith(EXPORT_SUFFIXES.dxf)),
  },
]
