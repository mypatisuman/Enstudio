/**
 * gen-symbols.mjs — render the Canvas's own ISA symbols to a static SVG sprite.
 *
 * The SVG exporter used to hand-draw 18 symbol kinds in Python while the
 * Canvas rendered 188 React components, so anything outside those 18 exported
 * as a plain box and the two sets drifted apart whenever a component changed.
 * This renders the REAL components (ICON_BY_TYPE, the Handle-free icons the
 * Canvas itself uses) once into <symbol> defs that the exporter references
 * with <use>. One symbol set, no port to maintain.
 *
 * Run:  node scripts/gen-symbols.mjs
 * Out:  ../backend/symbols/canvas_symbols.svg   (+ .json index)
 *
 * Re-run whenever a symbol component changes.
 */
import { createServer } from 'vite'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.resolve(HERE, '../../backend/symbols')

// Drawn at this box, then scaled by the exporter into each node's real size.
const BOX = 100

async function main() {
  const server = await createServer({
    configFile: path.resolve(HERE, '../vite.config.ts'),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'error',
  })

  let ICON_BY_TYPE, getNodeSize
  try {
    ;({ ICON_BY_TYPE } = await server.ssrLoadModule('/src/components/canvas/ISANodes.tsx'))
    ;({ getNodeSize } = await server.ssrLoadModule('/src/domain/isa/classification.ts'))
  } finally {
    // keep the server alive until after the render below
  }

  const types = Object.keys(ICON_BY_TYPE).sort()
  const symbols = []
  const index = {}
  const failed = []

  for (const type of types) {
    const Icon = ICON_BY_TYPE[type]
    let markup
    try {
      markup = renderToStaticMarkup(
        React.createElement(Icon, { width: BOX, height: BOX, strokeWidth: 1.5 }),
      )
    } catch (e) {
      failed.push(`${type}: ${e.message}`)
      continue
    }
    // The component renders a full <svg …>…</svg>; lift its children into a
    // <symbol> and carry the viewBox so <use> scales correctly.
    const open = markup.match(/^<svg\b([^>]*)>/)
    if (!open) { failed.push(`${type}: did not render an <svg> root`); continue }
    const viewBox = (open[1].match(/viewBox="([^"]+)"/) || [])[1] || `0 0 ${BOX} ${BOX}`
    const inner = markup.replace(/^<svg\b[^>]*>/, '').replace(/<\/svg>\s*$/, '')
    if (!inner.trim()) { failed.push(`${type}: rendered empty`); continue }

    symbols.push(
      `  <symbol id="sym-${type}" viewBox="${viewBox}" overflow="visible">\n` +
      `    ${inner.trim()}\n  </symbol>`,
    )
    const { w, h } = getNodeSize(type)
    index[type] = { viewBox, w, h }
  }

  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.writeFileSync(
    path.join(OUT_DIR, 'canvas_symbols.svg'),
    '<svg xmlns="http://www.w3.org/2000/svg">\n<defs>\n' +
    symbols.join('\n') + '\n</defs>\n</svg>\n',
    'utf-8',
  )
  fs.writeFileSync(
    path.join(OUT_DIR, 'canvas_symbols.json'), JSON.stringify(index, null, 2), 'utf-8',
  )

  console.log(`rendered ${symbols.length}/${types.length} symbols -> ${OUT_DIR}`)
  if (failed.length) {
    console.log(`skipped ${failed.length}:`)
    for (const f of failed.slice(0, 12)) console.log('   ' + f)
  }
  await server.close()
}

main().catch(e => { console.error(e); process.exit(1) })
