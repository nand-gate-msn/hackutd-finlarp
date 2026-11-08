// Obsidian-style force-directed layout for the money-flow graph.
//
// Pure functions (no React, no DOM) so the layout can be checked in plain Node:
//   layoutGraph(graph, measure) -> model   run the force simulation from several starts, keep the tidiest
//   refresh(model, measure)                recompute edge geometry + label placement after nodes move
//
// Guarantees (checked by scripts/check-graph-layout.mjs against real data):
//   * no two nodes (circle + its title) overlap;
//   * every edge amount is placed in a pill that overlaps no node, no title, no other pill and no other edge;
//   * if a pill cannot be placed cleanly it is flagged `hidden` and only shown on hover, never on top of things.

import { forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force'
import { compact, titleCase } from './format.js'

export const FONT = 12
export const LABEL_GAP = 4
export const LABEL_H = 15
export const PILL_H = 19
export const PILL_PAD = 7

// ---------- sizing: bigger flows look bigger ----------
export const radiusOf = (value, max) => 8 + 19 * Math.sqrt(value / max)
export const widthOf = (amount, max) => 1.2 + 11 * Math.sqrt(amount / max) // 1.2px .. 12.2px

const truncate = (s, n = 24) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

// ---------- geometry helpers ----------
function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Distance from a node's centre to its edge along direction (ux, uy): circles use r, cards their rectangle. */
export function rimDistance(n, ux, uy) {
  if (n.shape !== 'card') return n.r
  const ax = Math.abs(ux) || 1e-9, ay = Math.abs(uy) || 1e-9
  return Math.min(n.w / 2 / ax, n.h / 2 / ay)
}

/** Where a node's title sits: the side with the fewest lines through it is chosen in refresh(). */
export function labelRect(n, side = n.side || 'below') {
  if (n.shape === 'card') return { x0: n.x, x1: n.x, y0: n.y, y1: n.y } // a card draws its title inside
  const hw = n.lw / 2
  const d = n.r * 0.72 + LABEL_GAP // a corner sits diagonally off the circle
  if (side === 'center') return { x0: n.x - hw - 4, x1: n.x + hw + 4, y0: n.y - LABEL_H / 2 - 2, y1: n.y + LABEL_H / 2 + 2 } // badge on the node itself
  if (side === 'above-right') return { x0: n.x + d, x1: n.x + d + n.lw, y0: n.y - d - LABEL_H, y1: n.y - d }
  if (side === 'above-left') return { x0: n.x - d - n.lw, x1: n.x - d, y0: n.y - d - LABEL_H, y1: n.y - d }
  if (side === 'below-right') return { x0: n.x + d, x1: n.x + d + n.lw, y0: n.y + d, y1: n.y + d + LABEL_H }
  if (side === 'below-left') return { x0: n.x - d - n.lw, x1: n.x - d, y0: n.y + d, y1: n.y + d + LABEL_H }
  if (side === 'above') return { x0: n.x - hw, x1: n.x + hw, y0: n.y - n.r - LABEL_GAP - LABEL_H, y1: n.y - n.r - LABEL_GAP }
  if (side === 'right') return { x0: n.x + n.r + LABEL_GAP, x1: n.x + n.r + LABEL_GAP + n.lw, y0: n.y - LABEL_H / 2, y1: n.y + LABEL_H / 2 }
  if (side === 'left') return { x0: n.x - n.r - LABEL_GAP - n.lw, x1: n.x - n.r - LABEL_GAP, y0: n.y - LABEL_H / 2, y1: n.y + LABEL_H / 2 }
  return { x0: n.x - hw, x1: n.x + hw, y0: n.y + n.r + LABEL_GAP, y1: n.y + n.r + LABEL_GAP + LABEL_H }
}

/** The area a node occupies: its circle plus its title. */
export function boxOf(n, pad = 0) {
  if (n.shape === 'card') return { x0: n.x - n.w / 2 - pad, x1: n.x + n.w / 2 + pad, y0: n.y - n.h / 2 - pad, y1: n.y + n.h / 2 + pad }
  const t = labelRect(n)
  return {
    x0: Math.min(n.x - n.r, t.x0) - pad,
    x1: Math.max(n.x + n.r, t.x1) + pad,
    y0: Math.min(n.y - n.r, t.y0) - pad,
    y1: Math.max(n.y + n.r, t.y1) + pad,
  }
}

const rectsOverlap = (a, b, pad = 0) =>
  a.x0 < b.x1 + pad && a.x1 > b.x0 - pad && a.y0 < b.y1 + pad && a.y1 > b.y0 - pad

function segsCross(p, q, r, s) {
  const o = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
  const d1 = o(p, q, r), d2 = o(p, q, s), d3 = o(r, s, p), d4 = o(r, s, q)
  return d1 * d2 < 0 && d3 * d4 < 0
}

export function segHitsRect(p, q, r) {
  const inside = (a) => a.x >= r.x0 && a.x <= r.x1 && a.y >= r.y0 && a.y <= r.y1
  if (inside(p) || inside(q)) return true
  const c = [{ x: r.x0, y: r.y0 }, { x: r.x1, y: r.y0 }, { x: r.x1, y: r.y1 }, { x: r.x0, y: r.y1 }]
  return [0, 1, 2, 3].some((i) => segsCross(p, q, c[i], c[(i + 1) % 4]))
}

// ---------- forces ----------
/** Push apart any two nodes whose circle+title boxes overlap (a rectangle version of forceCollide). */
function boxForce(pad) {
  let nodes = []
  const force = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        const A = boxOf(a, pad), B = boxOf(b, pad)
        const ox = Math.min(A.x1, B.x1) - Math.max(A.x0, B.x0)
        const oy = Math.min(A.y1, B.y1) - Math.max(A.y0, B.y0)
        if (ox <= 0 || oy <= 0) continue
        if (ox < oy) {
          const s = (a.x < b.x ? -1 : 1) * ox * 0.25
          a.vx += s
          b.vx -= s
        } else {
          const s = (a.y < b.y ? -1 : 1) * oy * 0.25
          a.vy += s
          b.vy -= s
        }
      }
    }
  }
  force.initialize = (n) => { nodes = n }
  return force
}

/** Hard guarantee: nudge positions directly until no two boxes overlap. */
export function relax(nodes, pad = 8, iterations = 400) {
  for (let it = 0; it < iterations; it++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        const A = boxOf(a, pad), B = boxOf(b, pad)
        const ox = Math.min(A.x1, B.x1) - Math.max(A.x0, B.x0)
        const oy = Math.min(A.y1, B.y1) - Math.max(A.y0, B.y0)
        if (ox <= 0 || oy <= 0) continue
        const aFixed = a.fx != null, bFixed = b.fx != null
        if (aFixed && bFixed) continue // pinned nodes (the customer's graph while ghosts are placed) never move
        moved = true
        const horizontal = ox < oy
        const amount = (horizontal ? ox : oy) / 2 + 0.5
        const dir = horizontal ? (a.x < b.x ? -1 : 1) : a.y < b.y ? -1 : 1
        const [ma, mb] = aFixed && !bFixed ? [0, 2] : bFixed && !aFixed ? [2, 0] : [1, 1]
        if (horizontal) { a.x += dir * amount * ma; b.x -= dir * amount * mb }
        else { a.y += dir * amount * ma; b.y -= dir * amount * mb }
      }
    }
    if (!moved) return true
  }
  return false
}

export function hasOverlap(nodes, pad = 8) {
  for (let i = 0; i < nodes.length; i++)
    for (let j = i + 1; j < nodes.length; j++) if (rectsOverlap(boxOf(nodes[i], pad / 2), boxOf(nodes[j], pad / 2))) return true
  return false
}

/** Titles move when sides change and nodes move when overlaps are removed: alternate until both are stable. */
export function settle(model, measure, rounds = 8) {
  for (let i = 0; i < rounds; i++) {
    refresh(model, measure)
    relax(model.nodes)
    refresh(model, measure)
    if (!hasOverlap(model.nodes)) break
  }
  return model
}

const linkDistance = (l) => (l.raw.type === 'forecast' ? 50 : 150) + l.source.r + l.target.r

function makeSim(nodes, links) {
  return forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => d.id).distance(linkDistance).strength(0.45))
    .force('charge', forceManyBody().strength((d) => -520 - d.r * 18).distanceMax(760))
    .force('x', forceX(0).strength(0.03))
    .force('y', forceY(0).strength(0.04))
    .force('boxes', boxForce(10))
    .stop()
}

// ---------- model ----------
export function buildModel(graph, measure) {
  const throughput = (n) => Math.max(n.in_cents, n.out_cents, 1)
  const maxThroughput = Math.max(...graph.nodes.map(throughput), 1)
  const maxAmount = Math.max(...graph.edges.map((e) => e.amount_cents), 1)
  const scale = { maxThroughput, maxAmount }
  const nodes = graph.nodes.map((n) => makeNode(n, measure, scale))
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const links = graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => makeLink(e, scale))
  return { nodes, links, byId, scale }
}

function makeNode(n, measure, scale) {
  if (n.shape === 'card') {
    return { id: n.id, data: n, title: n.label, shape: 'card', w: n.w, h: n.h, r: Math.max(n.w, n.h) / 2, lw: 0, x: 0, y: 0, ghost: !!n.ghost }
  }
  // projected nodes and rules already have sentence-case labels ("Save 5% of each paycheck")
  const written = n.ghost || n.type === 'rule' || n.type === 'scenario'
  const title = truncate(written ? n.label : titleCase(n.label), written ? 28 : 24)
  const value = Math.min(Math.max(n.in_cents, n.out_cents, 1), scale.maxThroughput)
  return { id: n.id, data: n, title, r: radiusOf(value, scale.maxThroughput), lw: measure(title, FONT) + 6, x: 0, y: 0, ghost: !!n.ghost }
}

function makeLink(e, scale) {
  const amount = Math.min(e.amount_cents, scale.maxAmount * 1.5) // a huge projection must not dwarf the real graph
  return {
    source: e.source,
    target: e.target,
    raw: e,
    ghost: !!e.ghost,
    width: e.type === 'forecast' ? 1.2 : widthOf(amount, scale.maxAmount),
    text: e.type === 'forecast' ? null : compact(e.amount_cents / 100), // the card's connector carries no amount
  }
}

/** Edge endpoints (on the circles' rims), arrow geometry and the pill placement for every link. */
export function refresh(model, measure) {
  for (const l of model.links) {
    const s = typeof l.source === 'object' ? l.source : model.byId.get(l.source)
    const t = typeof l.target === 'object' ? l.target : model.byId.get(l.target)
    l.s = s
    l.t = t
    const dx = t.x - s.x, dy = t.y - s.y
    const len = Math.hypot(dx, dy) || 1
    const ux = dx / len, uy = dy / len
    l.ux = ux
    l.uy = uy
    const rs = rimDistance(s, ux, uy), rt = rimDistance(t, ux, uy)
    l.p1 = { x: s.x + ux * (rs + 2), y: s.y + uy * (rs + 2) }
    l.p2 = { x: t.x - ux * (rt + 3), y: t.y - uy * (rt + 3) }
    l.arrow = l.text ? Math.max(8, l.width * 1.3) : 0
    l.arrowHalf = Math.max(4.5, l.width * 0.75)
    l.len = Math.max(0, len - rs - rt - 5)
  }
  chooseSides(model)
  placeLabels(model, measure)
  model.bounds = boundsOf(model)
  return model
}

const HUB_DEGREE = 6
const SIDES = ['below', 'above', 'right', 'left', 'below-right', 'below-left', 'above-right', 'above-left', 'center']

/** Put each title where the fewest lines run through it (and it hits no other node). Sticky, to avoid flicker. */
function chooseSides(model) {
  for (const n of model.nodes) {
    if (n.shape === 'card') continue
    let best = n.side || 'below', bestCost = Infinity
    const order = n.side ? [n.side, ...SIDES.filter((x) => x !== n.side)] : SIDES
    const degree = model.links.reduce((c, l) => c + (l.s === n || l.t === n ? 1 : 0), 0)
    for (const side of order) {
      if (side === 'center' && degree < HUB_DEGREE) continue // a badge is only for hubs: leaves must keep their dot visible
      const r = labelRect(n, side)
      const padded = { x0: r.x0 - 1, x1: r.x1 + 1, y0: r.y0 - 1, y1: r.y1 + 1 }
      // a badge on the node hides the line stubs underneath it, so it only costs a little: the last resort for hubs
      let cost = side === 'center' ? 0.4 : model.links.reduce((c, l) => c + (segHitsRect(l.p1, l.p2, padded) ? 1 : 0), 0)
      for (const o of model.nodes) {
        if (o === n) continue
        if (rectsOverlap(r, boxOf(o, 2))) cost += 10
      }
      if (cost < bestCost - 0.5) { best = side; bestCost = cost }
      if (bestCost === 0) break
    }
    n.side = best
  }
}

function placeLabels(model, measure) {
  const boxes = model.nodes.map((n) => boxOf(n, 3))
  const placed = []
  const order = [...model.links].sort((a, b) => b.raw.amount_cents - a.raw.amount_cents) // heaviest first
  const OFFSETS = [0, 12, -12, 24, -24]
  const TS = [0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65, 0.3, 0.7, 0.25, 0.75, 0.2, 0.8, 0.15, 0.85, 0.1, 0.9]

  for (const l of order) {
    if (!l.text) { l.label = null; l.hidden = true; continue } // e.g. the forecast card's connector
    const w = measure(l.text, FONT) + PILL_PAD * 2
    const dx = l.p2.x - l.p1.x, dy = l.p2.y - l.p1.y
    const nx = -l.uy, ny = l.ux
    let chosen = null
    search: for (const off of OFFSETS) {
      for (const t of TS) {
        const cx = l.p1.x + dx * t + nx * off, cy = l.p1.y + dy * t + ny * off
        const rect = { x0: cx - w / 2, x1: cx + w / 2, y0: cy - PILL_H / 2, y1: cy + PILL_H / 2, cx, cy, w }
        if (boxes.some((b) => rectsOverlap(rect, b))) continue
        if (placed.some((p) => rectsOverlap(rect, p, 3))) continue
        const padded = { x0: rect.x0 - 1, x1: rect.x1 + 1, y0: rect.y0 - 1, y1: rect.y1 + 1 }
        if (model.links.some((o) => o !== l && segHitsRect(o.p1, o.p2, padded))) continue
        chosen = rect
        break search
      }
    }
    if (chosen) {
      l.label = chosen
      l.hidden = false
      placed.push(chosen)
    } else {
      // no clean spot: keep the text available on hover instead of drawing it on top of something
      const cx = (l.p1.x + l.p2.x) / 2, cy = (l.p1.y + l.p2.y) / 2
      l.label = { x0: cx - w / 2, x1: cx + w / 2, y0: cy - PILL_H / 2, y1: cy + PILL_H / 2, cx, cy, w }
      l.hidden = true
    }
  }
}

function boundsOf(model) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  const add = (r) => { x0 = Math.min(x0, r.x0); y0 = Math.min(y0, r.y0); x1 = Math.max(x1, r.x1); y1 = Math.max(y1, r.y1) }
  model.nodes.forEach((n) => add(boxOf(n)))
  model.links.forEach((l) => l.label && !l.hidden && add(l.label))
  return { x0, y0, x1, y1 }
}

/** Lower is tidier: hidden labels, edges running through unrelated nodes, and crossings. */
export function score(model) {
  let s = 0
  const boxes = new Map(model.nodes.map((n) => [n.id, boxOf(n, 2)]))
  for (const l of model.links) {
    if (l.hidden) s += 6
    for (const n of model.nodes) {
      const own = n === l.s || n === l.t
      if (own && n.side === 'center') continue // the badge covers the line stubs under it
      const area = own ? labelRect(n) : boxes.get(n.id) // an edge may touch its own circle, not its own title
      if (segHitsRect(l.p1, l.p2, own ? { x0: area.x0 - 1, x1: area.x1 + 1, y0: area.y0 - 1, y1: area.y1 + 1 } : area)) s += 4
    }
  }
  for (let i = 0; i < model.links.length; i++) {
    for (let j = i + 1; j < model.links.length; j++) {
      const a = model.links[i], b = model.links[j]
      if (a.s === b.s || a.s === b.t || a.t === b.s || a.t === b.t) continue
      if (segsCross(a.p1, a.p2, b.p1, b.p2)) s += 1
    }
  }
  return s
}

function runOnce(graph, measure, seed, ticks) {
  const model = buildModel(graph, measure)
  const rand = mulberry32(seed * 7919 + 13)
  const radius = 120 + model.nodes.length * 7
  model.nodes.forEach((n, i) => {
    const angle = (i / model.nodes.length) * Math.PI * 2 + rand() * 0.8
    const r = radius * (0.55 + rand() * 0.6)
    n.x = Math.cos(angle) * r
    n.y = Math.sin(angle) * r
    n.vx = 0
    n.vy = 0
  })
  const sim = makeSim(model.nodes, model.links)
  for (let i = 0; i < ticks; i++) sim.tick()
  settle(model, measure)
  model.sim = sim
  model.score = score(model)
  return model
}

/** Try several starting positions and keep the tidiest result (the force layout is chaotic). */
export function layoutGraph(graph, measure, { seeds = 14, ticks = 340 } = {}) {
  let best = null
  for (let seed = 0; seed < seeds; seed++) {
    const m = runOnce(graph, measure, seed, ticks)
    if (!best || m.score < best.score) best = m
    if (best.score === 0) break
  }
  return best
}

/**
 * Replace the projected ("ghost") nodes and links: { nodes, edges } in the same shape as /api/graph.
 * Existing nodes are pinned while the ghosts find free space, so toggling a choice never reshuffles the graph.
 * Returns the model (mutated) with a fresh, stopped `model.sim` that includes the ghosts (for dragging).
 */
export function applyGhosts(model, ghosts, measure) {
  model.sim?.stop()
  model.nodes = model.nodes.filter((n) => !n.ghost)
  model.links = model.links.filter((l) => !l.ghost)
  model.byId = new Map(model.nodes.map((n) => [n.id, n]))

  const real = [...model.nodes]
  const add = ghosts?.nodes ?? []
  const want = new Set(add.map((n) => n.id))
  const edges = (ghosts?.edges ?? []).filter(
    (e) => (model.byId.has(e.source) || want.has(e.source)) && (model.byId.has(e.target) || want.has(e.target)),
  )
  const linked = new Set(edges.flatMap((e) => [e.source, e.target]))
  const fresh = add.filter((n) => linked.has(n.id)).map((n) => makeNode({ ...n, ghost: true }, measure, model.scale))
  fresh.forEach((n) => model.byId.set(n.id, n))
  model.nodes.push(...fresh)
  model.links.push(...edges.map((e) => makeLink({ ...e, ghost: true }, model.scale)))

  if (fresh.length) {
    const pinned = real.map((n) => [n, n.fx, n.fy])
    real.forEach((n) => { n.fx = n.x; n.fy = n.y })
    refresh(model, measure) // real edge geometry, so ghost placement can avoid crossing it
    placeNearAnchors(model, fresh)
    settle(model, measure)
    pinned.forEach(([n, fx, fy]) => { n.fx = fx ?? null; n.fy = fy ?? null })
  }
  model.sim = makeSim(model.nodes, model.links)
  refresh(model, measure)
  return model
}

/**
 * Put each ghost in the best free spot around the real node it hangs off: no overlap with any node, then the
 * fewest crossings with existing lines, then as close to its anchor as possible. Deterministic, no simulation.
 */
function placeNearAnchors(model, fresh) {
  const placed = model.nodes.filter((n) => !fresh.includes(n))
  const segments = model.links.filter((l) => l.p1 && l.p2).map((l) => [l.p1, l.p2])
  for (const g of fresh) {
    const link = model.links.find((l) => {
      const other = idOf(l.source) === g.id ? idOf(l.target) : idOf(l.target) === g.id ? idOf(l.source) : null
      return other && placed.some((n) => n.id === other)
    })
    const anchorId = link && (idOf(link.source) === g.id ? idOf(link.target) : idOf(link.source))
    const anchor = placed.find((n) => n.id === anchorId) ?? placed[0]
    let best = null
    for (let i = 0; i < 32; i++) {
      const angle = (i / 32) * Math.PI * 2
      for (const step of [0, 1, 2, 3, 4, 5]) {
        const reach = anchor.r + g.r + 90 + step * 55
        g.x = anchor.x + Math.cos(angle) * reach
        g.y = anchor.y + Math.sin(angle) * reach
        const box = boxOf(g, 14)
        const hits = placed.filter((o) => rectsOverlap(box, boxOf(o))).length
        const own = [{ x: anchor.x, y: anchor.y }, { x: g.x, y: g.y }]
        const crossings = segments.filter(([a, b]) => segsCross(own[0], own[1], a, b)).length
        const through = placed.filter((o) => o !== anchor && segHitsRect(own[0], own[1], boxOf(o, 2))).length
        const lineHits = segments.filter(([a, b]) => segHitsRect(a, b, box)).length
        const cost = hits * 10000 + through * 400 + lineHits * 300 + crossings * 60 + reach
        if (!best || cost < best.cost) best = { cost, x: g.x, y: g.y }
      }
    }
    g.x = best.x
    g.y = best.y
    g.vx = 0
    g.vy = 0
    placed.push(g)
    segments.push([{ x: anchor.x, y: anchor.y }, { x: g.x, y: g.y }])
  }
}

const idOf = (end) => (typeof end === 'object' ? end.id : end)

/** Re-heat the simulation for dragging; call model.sim.on('tick', ...) in the UI. */
export function wake(model, alphaTarget = 0.25) {
  model.sim.alphaTarget(alphaTarget).restart()
}

export const approxMeasure = (text, size) => text.length * size * 0.58
