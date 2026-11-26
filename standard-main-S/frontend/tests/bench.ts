// Phase 4 performance benchmark harness.
//
// Run: node tests/bench.ts            (all workloads)
//      node tests/bench.ts --json     (machine-readable, for before/after diff)
//
// Deterministic and browser-free: every unit measured here is pure TypeScript.
// What it CANNOT measure is stated in the report — React reconciliation, DOM
// and SVG paint, and real drag interaction need a browser profiler, which is
// not available in this environment.
//
// Workloads are generated from a fixed LCG so a run is reproducible, and the
// real project is read from studio.db when present.

import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'

import { extractedLayout, normalizedPointToPixel } from '../src/components/canvas/extractedLayout.ts'
import { pickHandles } from '../src/features/canvas/utils/edgeHelpers.ts'
import { sanitizeWaypoints, buildRoute, routeKindFor, edgeTrust } from '../src/features/canvas/utils/waypoints.ts'
import { checkGraphIntegrity, makeEdgeId } from '../src/features/canvas/utils/graphIntegrity.ts'
import { roundedPolyline } from '../src/features/canvas/utils/pipePath.ts'

const JSON_OUT = process.argv.includes('--json')
const CW = 3000, CH = 2200
const NW = 60, NH = 40
const size = () => ({ w: NW, h: NH })

interface Row { metric: string; n: number; e: number; ms: number; note?: string }
const rows: Row[] = []

/** Median of `reps` runs — medians are far less noisy than a single sample. */
function timeIt(fn: () => void, reps = 5): number {
  const samples: number[] = []
  for (let i = 0; i < reps; i++) {
    const t = performance.now()
    fn()
    samples.push(performance.now() - t)
  }
  samples.sort((a, b) => a - b)
  return samples[Math.floor(samples.length / 2)]
}

function record(metric: string, n: number, e: number, ms: number, note?: string) {
  rows.push({ metric, n, e, ms: Math.round(ms * 100) / 100, note })
}

// ── synthetic workloads ─────────────────────────────────────────────────────

function makeGraph(n: number, edgeCount = n - 1) {
  let seed = 987654321
  const rand = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648
    return seed / 2147483648
  }
  const nodes = Array.from({ length: n }, (_, i) => ({
    id: `n${i + 1}`, label: `T-${i + 1}`, kind: 'vessel',
    x: rand(), y: rand(), page_w: 4096, page_h: 2896,
  }))
  const edges = Array.from({ length: edgeCount }, (_, i) => ({
    source: `n${(i % n) + 1}`,
    target: `n${((i * 7 + 3) % n) + 1}`,
    kind: 'process',
    waypoints: i % 3 === 0
      ? [[rand(), rand()], [rand(), rand()], [rand(), rand()]]
      : null,
    bend_x: null, bend_y: null,
  }))
  return { nodes, edges }
}

/** React-Flow-shaped nodes, as CanvasScreen builds them. */
function toRfNodes(nodes: any[], pos: Map<string, { x: number; y: number }>) {
  return nodes.map(n => ({
    id: n.id, type: 'vessel_v',
    position: pos.get(n.id) ?? { x: 0, y: 0 },
    width: NW, height: NH,
    data: {},
  }))
}

// ── B. extractedLayout (incl. C. collision resolution) ──────────────────────

for (const n of [100, 500, 1000, 2000]) {
  const { nodes, edges } = makeGraph(n)
  const ms = timeIt(() => { extractedLayout(nodes as never, size, CW, CH, edges) }, 3)
  record('extractedLayout (single drawing)', n, edges.length, ms)
}

// multi-drawing path (Phase 3 per-page cells)
for (const n of [500, 1000]) {
  const { nodes, edges } = makeGraph(n)
  nodes.forEach((nd: any, i: number) => {
    nd.drawing = `page_${(i % 4) + 1}`
    nd.page_w = i % 2 ? 2048 : 4096
    nd.page_h = i % 2 ? 4096 : 2048
  })
  const ms = timeIt(() => { extractedLayout(nodes as never, size, CW, CH, edges) }, 3)
  record('extractedLayout (4 drawings)', n, edges.length, ms)
}

// ── D. pickHandles over every edge ──────────────────────────────────────────

for (const [n, e] of [[100, 500], [500, 2000], [1000, 5000]] as [number, number][]) {
  const { nodes, edges } = makeGraph(n, e)
  const { pos } = extractedLayout(nodes as never, size, CW, CH, edges)
  const rfNodes = toRfNodes(nodes, pos)
  const ms = timeIt(() => {
    const idx = new Map(rfNodes.map(n => [n.id, n]))
    for (const ed of edges) pickHandles(idx as never, ed.source, ed.target)
  }, 3)
  record('pickHandles (all edges)', n, e, ms)
}

// ── F. React Flow edge creation (the rfEdges memo body) ─────────────────────

function buildEdges(nodes: any[], edges: any[], pos: Map<string, { x: number; y: number }>) {
  const rfNodes = toRfNodes(nodes, pos)
  const ids = new Set(rfNodes.map(n => n.id))
  const byId = new Map(rfNodes.map(n => [n.id, n]))
  const seen = new Map<string, number>()
  const out: any[] = []
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue
    const srcN = byId.get(e.source)
    const tgtN = byId.get(e.target)
    const boxOf = (nd: any) => nd ? {
      x1: nd.position.x, y1: nd.position.y,
      x2: nd.position.x + (nd.width ?? 80), y2: nd.position.y + (nd.height ?? 50),
    } : null
    const sBox = boxOf(srcN), tBox = boxOf(tgtN)
    const interior = sanitizeWaypoints(e.waypoints)
    const wants = routeKindFor(e, interior, 'extracted') === 'waypoint'
    const built = (wants && sBox && tBox)
      ? buildRoute(interior.map(p => normalizedPointToPixel(p.x, p.y, CW, CH)), sBox, tBox)
      : null
    const handles = built
      ? { sourceHandle: built.sourceHandle, targetHandle: built.targetHandle }
      : pickHandles(byId as never, e.source, e.target)
    out.push({
      id: makeEdgeId(e.source, e.target, seen),
      source: e.source, target: e.target, ...handles,
      data: { pts: built?.pts, trust: edgeTrust(e) },
    })
  }
  return out
}

for (const [n, e] of [[100, 500], [500, 2000], [1000, 5000]] as [number, number][]) {
  const { nodes, edges } = makeGraph(n, e)
  const { pos } = extractedLayout(nodes as never, size, CW, CH, edges)
  const ms = timeIt(() => { buildEdges(nodes, edges, pos) }, 3)
  record('rfEdges build', n, e, ms)
}

// ── H. node drag: one node moves, edges rebuilt ─────────────────────────────

for (const [n, e] of [[100, 500], [500, 2000], [1000, 5000]] as [number, number][]) {
  const { nodes, edges } = makeGraph(n, e)
  const { pos } = extractedLayout(nodes as never, size, CW, CH, edges)
  const ms = timeIt(() => {
    const p = pos.get('n1')!
    pos.set('n1', { x: p.x + 1, y: p.y })
    buildEdges(nodes, edges, pos)          // what a drag frame currently costs
  }, 5)
  record('drag frame (1 node moved)', n, e, ms)
}

// ── J. graph integrity ──────────────────────────────────────────────────────

for (const [n, e] of [[100, 500], [500, 2000], [1000, 5000]] as [number, number][]) {
  const { nodes, edges } = makeGraph(n, e)
  const { pos } = extractedLayout(nodes as never, size, CW, CH, edges)
  const rfNodes = toRfNodes(nodes, pos)
  const rfEdges = buildEdges(nodes, edges, pos)
  const ms = timeIt(() => { checkGraphIntegrity(rfNodes, rfEdges) }, 5)
  record('checkGraphIntegrity', n, e, ms)
}

// ── waypoint sanitisation in isolation ──────────────────────────────────────

{
  const { edges } = makeGraph(1000, 5000)
  const ms = timeIt(() => { for (const e of edges) sanitizeWaypoints(e.waypoints) }, 5)
  record('sanitizeWaypoints (all edges)', 1000, 5000, ms)
}

// ── path construction ───────────────────────────────────────────────────────

{
  const pts = Array.from({ length: 5 }, (_, i) => ({ x: i * 50, y: (i % 2) * 50 }))
  const ms = timeIt(() => { for (let i = 0; i < 5000; i++) roundedPolyline(pts) }, 5)
  record('roundedPolyline x5000', 0, 5000, ms)
}

// ── A / G. real project: DB -> layout -> canvas prep ────────────────────────

const DB = '../EngineeringHub/EngineeringHub/studio.db'
const PY = '../backend/.venv/Scripts/python.exe'
if (existsSync(DB) && existsSync(PY)) {
  for (const pid of ['p-id-3', 'p-id-2']) {
    const script = `
import sqlite3, json, time
c=sqlite3.connect(${JSON.stringify(DB)}); c.row_factory=sqlite3.Row
t0=time.perf_counter()
nodes=[];edges=[]
for r in c.execute("SELECT id,label,kind,x,y,extra_json FROM nodes WHERE pid=?",(${JSON.stringify(pid)},)):
    ex=json.loads(r['extra_json'] or '{}')
    nodes.append({'id':r['id'],'label':r['label'] or '','kind':r['kind'] or '','x':r['x'],'y':r['y'],
                  'drawing':ex.get('drawing',''),'page_w':ex.get('page_w'),'page_h':ex.get('page_h')})
for r in c.execute("SELECT from_id,to_id,kind,extra_json FROM edges WHERE pid=?",(${JSON.stringify(pid)},)):
    ex=json.loads(r['extra_json'] or '{}')
    edges.append({'source':r['from_id'],'target':r['to_id'],'kind':r['kind'] or 'process',
                  'waypoints':ex.get('waypoints'),'bend_x':ex.get('bend_x'),'bend_y':ex.get('bend_y'),
                  'provenance':ex.get('provenance'),'audited':ex.get('audited')})
print(json.dumps({'nodes':nodes,'edges':edges,'db_ms':(time.perf_counter()-t0)*1000}))`
    const t0 = performance.now()
    const raw = execFileSync(PY, ['-c', script], { encoding: 'utf-8', maxBuffer: 64e6 })
    const readMs = performance.now() - t0
    const { nodes, edges, db_ms } = JSON.parse(raw)
    record(`${pid}: DB read (python side)`, nodes.length, edges.length, db_ms)
    record(`${pid}: read + IPC + JSON.parse`, nodes.length, edges.length, readMs)

    const layoutMs = timeIt(() => { extractedLayout(nodes, size, CW, CH, edges) }, 5)
    record(`${pid}: extractedLayout`, nodes.length, edges.length, layoutMs)

    const { pos } = extractedLayout(nodes, size, CW, CH, edges)
    const edgesMs = timeIt(() => { buildEdges(nodes, edges, pos) }, 5)
    record(`${pid}: rfEdges build`, nodes.length, edges.length, edgesMs)

    const rfNodes = toRfNodes(nodes, pos)
    const rfEdges = buildEdges(nodes, edges, pos)
    const intMs = timeIt(() => { checkGraphIntegrity(rfNodes, rfEdges) }, 5)
    record(`${pid}: checkGraphIntegrity`, nodes.length, edges.length, intMs)
  }
} else {
  record('real project', 0, 0, 0, 'SKIPPED — no studio.db on this machine')
}

// ── output ──────────────────────────────────────────────────────────────────

if (JSON_OUT) {
  console.log(JSON.stringify(rows, null, 2))
} else {
  const w = Math.max(...rows.map(r => r.metric.length))
  console.log(`${'metric'.padEnd(w)}  ${'nodes'.padStart(6)}  ${'edges'.padStart(6)}  ${'ms'.padStart(9)}`)
  console.log('-'.repeat(w + 28))
  for (const r of rows) {
    console.log(`${r.metric.padEnd(w)}  ${String(r.n).padStart(6)}  ${String(r.e).padStart(6)}  ${r.ms.toFixed(2).padStart(9)}${r.note ? '  ' + r.note : ''}`)
  }
}
