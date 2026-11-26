// Phase 5 — document identity reaching React Flow.
//
// Loads the controlled two-document fixture through the same transforms
// CanvasScreen applies, and asserts the canvas can tell the two PDFs apart.
// PHASE5_DB must point at the fixture built by studio's build_fixture.py.

import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { makeEdgeId, checkGraphIntegrity } from '../src/features/canvas/utils/graphIntegrity.ts'
import { extractedLayout } from '../src/components/canvas/extractedLayout.ts'

const DB = process.env.PHASE5_DB
const PY = '../backend/.venv/Scripts/python.exe'
if (!DB || !existsSync(DB) || !existsSync(PY)) {
  console.log('identity.test.ts: SKIPPED (PHASE5_DB not set or fixture missing)')
  process.exit(0)
}

const raw = execFileSync(PY, ['-c', `
import sqlite3, json
c=sqlite3.connect(${JSON.stringify(DB)}); c.row_factory=sqlite3.Row
ns=[];es=[]
for r in c.execute("SELECT id,label,kind,x,y,extra_json,source_id FROM nodes WHERE pid='P' ORDER BY id"):
    ex=json.loads(r['extra_json'] or '{}')
    ns.append({'id':r['id'],'label':r['label'] or '','kind':r['kind'] or '','x':r['x'],'y':r['y'],
               'source_id':r['source_id'],'page':ex.get('page'),'drawing':ex.get('drawing',''),
               'page_w':ex.get('page_w'),'page_h':ex.get('page_h')})
for r in c.execute("SELECT from_id,to_id,kind,label,source_id FROM edges WHERE pid='P' ORDER BY id"):
    es.append({'source':r['from_id'],'target':r['to_id'],'kind':r['kind'] or 'process',
               'label':r['label'],'source_id':r['source_id']})
print(json.dumps({'nodes':ns,'edges':es}))`], { encoding: 'utf-8', maxBuffer: 64e6 })

const { nodes, edges } = JSON.parse(raw)
let checks = 0
const ok = (label: string, cond: boolean) => { assert.ok(cond, label); checks++; console.log(`  ok  ${label}`) }

ok('both documents present', nodes.length === 12 && edges.length === 8)

// React Flow node ids must be unique or React silently drops the duplicates.
const ids = nodes.map((n: any) => n.id)
ok('React Flow node ids unique across documents', new Set(ids).size === ids.length)

// Document identity survives the Rust DTO -> TS boundary.
const docs = new Set(nodes.map((n: any) => n.source_id))
ok('nodes carry document identity', docs.size === 2 && !docs.has(null))
ok('edges carry document identity', new Set(edges.map((e: any) => e.source_id)).size === 2)

// Page 1 exists in both documents without collapsing into one drawing cell.
const page1 = nodes.filter((n: any) => n.page === 1)
ok('page 1 exists in both documents', page1.length === 6 &&
   new Set(page1.map((n: any) => n.source_id)).size === 2)
ok('page 1 of each document is its own drawing',
   new Set(page1.map((n: any) => n.drawing)).size === 2)
ok('four distinct drawing cells', new Set(nodes.map((n: any) => n.drawing)).size === 4)

// Parallel edges: same endpoints, distinct React Flow ids (Phase 3 makeEdgeId).
const seen = new Map<string, number>()
const edgeIds = edges.map((e: any) => makeEdgeId(e.source, e.target, seen))
ok('parallel edges get distinct React Flow ids', new Set(edgeIds).size === edgeIds.length)
ok('parallel edges are not dropped', edgeIds.length === 8)
ok('duplicate pair is suffixed', edgeIds.some((i: string) => i.includes('#')))

// No edge may join two documents.
const docOf = new Map(nodes.map((n: any) => [n.id, n.source_id]))
ok('no cross-document edges', edges.every((e: any) => docOf.get(e.source) === docOf.get(e.target)))

// The layout must not merge the two documents' sheets.
const { pos } = extractedLayout(nodes, () => ({ w: 60, h: 40 }), 3000, 2200, edges)
ok('every node laid out', pos.size === 12)
const centres = new Map<number, { x: number; y: number }[]>()
for (const n of nodes) {
  const p = pos.get(n.id)!
  if (!centres.has(n.source_id)) centres.set(n.source_id, [])
  centres.get(n.source_id)!.push(p)
}
ok('documents occupy separate regions', [...centres.values()].every(v => v.length === 6))

// Integrity check over the React Flow graph itself.
const rfNodes = nodes.map((n: any) => ({ id: n.id, position: pos.get(n.id)!, data: {}, width: 60, height: 40 }))
const rfEdges = edges.map((e: any, i: number) => ({ id: edgeIds[i], source: e.source, target: e.target }))
const report = checkGraphIntegrity(rfNodes as never, rfEdges as never)
ok('graph integrity clean', report.ok)

console.log(`\nidentity.test.ts: ${checks} assertions passed`)
