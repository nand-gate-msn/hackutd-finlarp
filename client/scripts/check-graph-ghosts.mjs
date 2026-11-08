// Projected nodes on real data: node scripts/check-graph-ghosts.mjs graph90.json ...
// Applies a what-if node, then a what-if + suggestion (rule node), plus the forecast card, and checks:
// no overlaps, every amount pill placed, and the customer's existing nodes do not move.
import { readFileSync } from 'node:fs'
import { applyGhosts, approxMeasure, boxOf, layoutGraph, segHitsRect } from '../src/graphLayout.js'

const rects = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0
let failures = 0

function ghostsFor(graph, withRule) {
  const checking = graph.nodes.find((n) => n.type === 'account' && n.account_type === 'Checking').id
  const savings = graph.nodes.find((n) => n.type === 'account' && n.account_type === 'Savings')?.id
  const nodes = [
    { id: 'ghost:scenario', type: 'scenario', label: 'Car loan (projected)', in_cents: 144000, out_cents: 144000 },
    { id: 'ghost:forecast', type: 'forecast', label: 'Projected balance', shape: 'card', w: 260, h: 182, in_cents: 0, out_cents: 0 },
  ]
  const edges = [
    { source: checking, target: 'ghost:scenario', type: 'pays', tag: 'simulated', amount_cents: 144000 },
    { source: checking, target: 'ghost:forecast', type: 'forecast', tag: 'simulated', amount_cents: 0 },
  ]
  if (withRule) {
    nodes.push({ id: 'ghost:rule', type: 'rule', label: 'Save 5% of each paycheck', in_cents: 55000, out_cents: 55000 })
    edges.push({ source: checking, target: 'ghost:rule', type: 'transfers', tag: 'proposed', amount_cents: 55000 })
    if (savings) edges.push({ source: 'ghost:rule', target: savings, type: 'transfers', tag: 'proposed', amount_cents: 55000 })
  }
  return { nodes, edges }
}

function check(m, label) {
  const problems = []
  const boxes = m.nodes.map((n) => boxOf(n))
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) if (rects(boxes[i], boxes[j])) problems.push(`overlap ${m.nodes[i].id} / ${m.nodes[j].id}`)
  const withText = m.links.filter((l) => l.text)
  const shown = withText.filter((l) => !l.hidden)
  for (const l of shown) {
    boxes.forEach((b, i) => rects(l.label, b) && problems.push(`pill ${l.text} on node ${m.nodes[i].id}`))
    shown.forEach((o) => o !== l && rects(l.label, o.label) && problems.push(`pill ${l.text} on pill ${o.text}`))
    m.links.forEach((o) => o !== l && segHitsRect(o.p1, o.p2, l.label) && problems.push(`pill ${l.text} on a line`))
  }
  console.log(`  ${label}: ${m.nodes.length} nodes | pills ${shown.length}/${withText.length} | ${problems.length ? 'PROBLEMS' : 'OK'}`)
  problems.forEach((p) => console.log('     -', p))
  failures += problems.length + (withText.length - shown.length)
}

for (const file of process.argv.slice(2)) {
  const graph = JSON.parse(readFileSync(file, 'utf8'))
  const m = layoutGraph(graph, approxMeasure)
  const before = new Map(m.nodes.map((n) => [n.id, [n.x, n.y]]))
  console.log(file.split('/').pop())
  applyGhosts(m, ghostsFor(graph, false), approxMeasure)
  check(m, 'what-if + forecast card')
  applyGhosts(m, ghostsFor(graph, true), approxMeasure)
  check(m, 'what-if + suggestion + card')
  applyGhosts(m, null, approxMeasure)
  check(m, 'cleared')
  const moved = [...before].filter(([id, [x, y]]) => { const n = m.byId.get(id); return Math.hypot(n.x - x, n.y - y) > 0.5 })
  console.log(`  existing nodes moved: ${moved.length}`)
  failures += moved.length
}
process.exit(failures ? 1 : 0)
