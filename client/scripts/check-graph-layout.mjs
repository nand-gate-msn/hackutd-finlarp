// Verifies the graph layout on real data:  node scripts/check-graph-layout.mjs graph30.json graph90.json ...
// Each file is the JSON from GET /api/graph?days=N. Exits non-zero if anything overlaps.
import { readFileSync } from 'node:fs'
import { approxMeasure, boxOf, labelRect, layoutGraph, segHitsRect } from '../src/graphLayout.js'

const rects = (a, b, pad = 0) => a.x0 < b.x1 + pad && a.x1 > b.x0 - pad && a.y0 < b.y1 + pad && a.y1 > b.y0 - pad
let failures = 0

for (const file of process.argv.slice(2)) {
  const graph = JSON.parse(readFileSync(file, 'utf8'))
  const started = performance.now()
  const m = layoutGraph(graph, approxMeasure)
  const ms = Math.round(performance.now() - started)
  const problems = []

  const boxes = m.nodes.map((n) => boxOf(n))
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++)
      if (rects(boxes[i], boxes[j])) problems.push(`nodes overlap: ${m.nodes[i].title} / ${m.nodes[j].title}`)

  const shown = m.links.filter((l) => !l.hidden)
  for (const l of shown) {
    const name = `${l.s.title}->${l.t.title} (${l.text})`
    boxes.forEach((b, i) => rects(l.label, b) && problems.push(`label ${name} overlaps node ${m.nodes[i].title}`))
    shown.forEach((o) => o !== l && rects(l.label, o.label) && problems.push(`label ${name} overlaps label ${o.text}`))
    m.links.forEach((o) => o !== l && segHitsRect(o.p1, o.p2, l.label) && problems.push(`label ${name} sits on edge ${o.s.title}->${o.t.title}`))
  }

  const hubs = m.nodes.filter((n) => n.side === 'center')
  for (const n of hubs) if (m.links.filter((l) => l.s === n || l.t === n).length < 6) problems.push(`a leaf node hides its dot behind a badge: ${n.title}`)
  const throughTitles = []
  for (const l of m.links)
    for (const n of m.nodes) if (!(n.side === 'center' && (n === l.s || n === l.t)) && segHitsRect(l.p1, l.p2, labelRect(n))) throughTitles.push(`${l.s.title}->${l.t.title} through "${n.title}"`)

  const widths = m.links.map((l) => [l.raw.amount_cents, l.width]).sort((a, b) => a[0] - b[0])
  const monotone = widths.every((w, i) => i === 0 || w[1] >= widths[i - 1][1])
  if (!monotone) problems.push('edge width is not increasing with weight')

  console.log(
    `${file}: ${m.nodes.length} nodes, ${m.links.length} edges | labels shown ${shown.length}/${m.links.length} | ` +
      `width ${Math.min(...m.links.map((l) => l.width)).toFixed(1)}-${Math.max(...m.links.map((l) => l.width)).toFixed(1)}px | ` +
      `lines through titles ${throughTitles.length} | score ${m.score} | ${ms}ms | ${problems.length ? 'PROBLEMS' : 'OK'}`,
  )
  problems.forEach((p) => console.log('   -', p))
  throughTitles.forEach((t) => console.log('   ~ line crosses a title:', t))
  failures += problems.length
}
process.exit(failures ? 1 : 0)
