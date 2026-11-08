// Simulates dragging nodes around and checks that nothing overlaps once the graph settles.
//   node scripts/check-graph-drag.mjs graph90.json
import { readFileSync } from 'node:fs'
import { approxMeasure, boxOf, hasOverlap, layoutGraph, refresh, settle } from '../src/graphLayout.js'

const graph = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const m = layoutGraph(graph, approxMeasure)
const rects = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0
const shownOverlaps = () => {
  const boxes = m.nodes.map((n) => boxOf(n))
  const shown = m.links.filter((l) => !l.hidden)
  let bad = 0
  for (const l of shown) {
    bad += boxes.filter((b) => rects(l.label, b)).length
    bad += shown.filter((o) => o !== l && rects(l.label, o.label)).length
  }
  return bad
}

let failures = 0
const rand = (() => { let a = 7; return () => ((a = (a * 1664525 + 1013904223) >>> 0) / 4294967296) })()
for (let drag = 0; drag < 25; drag++) {
  const node = m.nodes[Math.floor(rand() * m.nodes.length)]
  const tx = node.x + (rand() - 0.5) * 500, ty = node.y + (rand() - 0.5) * 500
  for (let step = 1; step <= 40; step++) { // pointer moves toward the target; neighbours follow
    node.fx = node.x + (tx - node.x) * 0.2
    node.fy = node.y + (ty - node.y) * 0.2
    m.sim.alpha(0.3).tick()
    refresh(m, approxMeasure)
  }
  node.fx = node.fy = null // release, then let the simulation cool and settle like the UI does
  for (let t = 0; t < 120; t++) m.sim.alpha(Math.max(m.sim.alpha(), 0.02)).tick()
  settle(m, approxMeasure)
  const overlap = hasOverlap(m.nodes), labels = shownOverlaps()
  if (overlap || labels) { failures++; console.log(`drag ${drag} (${node.title}): node overlap ${overlap}, label overlaps ${labels}`) }
}
console.log(failures ? `${failures}/25 drags left overlaps` : 'OK: 25 random drags, nothing overlapped after settling')
process.exit(failures ? 1 : 0)
