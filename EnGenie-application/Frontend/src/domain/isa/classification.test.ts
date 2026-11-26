// Run: node src/domain/isa/classification.test.ts   (Node >= 23.6 strips types natively)
import assert from 'node:assert/strict'
import { fitTag } from './classification.ts'

const AVG_GLYPH_EM = 0.58   // must match classification.ts

// Width the label will actually occupy once fitTag's props are applied.
const renderedWidth = (s: string, p: ReturnType<typeof fitTag>) =>
  p.textLength ?? s.length * p.fontSize * AVG_GLYPH_EM

// 1. Text that already fits is returned untouched — short ISA tags must render
//    exactly as they did before fitTag existed.
assert.deepEqual(fitTag('P-101', 152, 13), { fontSize: 13 })
assert.deepEqual(fitTag('', 52, 12), { fontSize: 12 })

// 2. The bug from the screenshot: a long name in a 160-wide vessel viewBox.
//    It must come back smaller, not clipped.
const vessel = fitTag('AVAILABLE AQUEOUS SAMPLE', 152, 13)
assert.ok(vessel.fontSize < 13, 'long label should shrink')
assert.ok(renderedWidth('AVAILABLE AQUEOUS SAMPLE', vessel) <= 152)

// 3. Past the legibility floor the font stops shrinking and the native SVG
//    squeeze takes over, so the text still cannot overflow.
const narrow = fitTag('AVAILABLE AQUEOUS SAMPLE', 52, 12)
assert.equal(narrow.fontSize, 7, 'should clamp at MIN_FONT_PX')
assert.equal(narrow.textLength, 52)
assert.equal(narrow.lengthAdjust, 'spacingAndGlyphs')

// 4. The invariant that actually matters: nothing ever exceeds its box.
for (const width of [52, 72, 74, 112, 152]) {
  for (const len of [1, 5, 12, 24, 60, 200]) {
    const s = 'X'.repeat(len)
    const p = fitTag(s, width, 13)
    assert.ok(
      renderedWidth(s, p) <= width,
      `overflow: len=${len} maxWidth=${width} -> ${JSON.stringify(p)}`,
    )
    assert.ok(p.fontSize >= 7, `unreadable font: ${JSON.stringify(p)}`)
  }
}

console.log('fitTag: all assertions passed')
