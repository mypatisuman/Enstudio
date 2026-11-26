// Run: node src/components/canvas/extractedLayout.test.ts   (Node >= 23.6)
import assert from 'node:assert/strict'
import { packVendorPackages, type ExtractedNode } from './extractedLayout.ts'

// The p-id-5 shape from the drawing: AT XXXX inside GCV-XXXX inside VENDOR PACKAGE.
const nodes: ExtractedNode[] = [
  { id: 'n40', label: 'VENDOR PACKAGE', kind: 'vendor_package', x: 0, y: 0 },
  { id: 'n39', label: 'GCV-XXXX', kind: 'package', x: 0, y: 0, equipment_ref: 'n40' },
  { id: 'n27', label: 'AT XXXX', kind: 'instrument', x: 0, y: 0, equipment_ref: 'n39' },
]
const DEFAULT = { vendor_package: { w: 800, h: 600 }, package: { w: 800, h: 600 }, instrument: { w: 52, h: 52 } }
const getSize = (n: ExtractedNode) => DEFAULT[n.kind as keyof typeof DEFAULT] ?? { w: 60, h: 60 }

const pos = new Map(nodes.map(n => [n.id, { x: 0, y: 0 }]))
const sizes = packVendorPackages(nodes, pos, getSize)

const box = (id: string) => {
  const p = pos.get(id)!, s = sizes.get(id) ?? getSize(nodes.find(n => n.id === id)!)
  return { x1: p.x, y1: p.y, x2: p.x + s.w, y2: p.y + s.h }
}
const contains = (outer: string, inner: string) => {
  const o = box(outer), i = box(inner)
  return i.x1 >= o.x1 && i.y1 >= o.y1 && i.x2 <= o.x2 && i.y2 <= o.y2
}

// Both boxes must have been resized to wrap their contents.
assert.ok(sizes.has('n39'), 'inner package should get a packed size')
assert.ok(sizes.has('n40'), 'outer package should get a packed size')

// The whole point: real containment at BOTH levels. Before the depth-ordering
// fix the outer box was sized against the inner package's DEFAULT size, so the
// inner one spilled outside it.
assert.ok(contains('n39', 'n27'), `AT should sit inside GCV: ${JSON.stringify({ gcv: box('n39'), at: box('n27') })}`)
assert.ok(contains('n40', 'n39'), `GCV should sit inside VENDOR PACKAGE: ${JSON.stringify({ vp: box('n40'), gcv: box('n39') })}`)

// The outer box must be strictly larger than the inner one it wraps.
assert.ok(sizes.get('n40')!.w > sizes.get('n39')!.w, 'outer must be wider than inner')

// A ref cycle must not hang the layout.
const cyclic: ExtractedNode[] = [
  { id: 'a', label: 'A', kind: 'package', x: 0, y: 0, equipment_ref: 'b' },
  { id: 'b', label: 'B', kind: 'package', x: 0, y: 0, equipment_ref: 'a' },
]
const cpos = new Map(cyclic.map(n => [n.id, { x: 0, y: 0 }]))
packVendorPackages(cyclic, cpos, getSize)

console.log('packVendorPackages: nesting assertions passed')
