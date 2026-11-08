import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import ForecastChart from './ForecastChart'
import Modal from './Modal'
import { applyGhosts, approxMeasure, FONT, LABEL_GAP, LABEL_H, layoutGraph, PILL_H, refresh, settle, wake } from './graphLayout.js'
import { compact, money, titleCase } from './format'

const TYPE_LABEL = {
  income: 'Income', account: 'Account', obligation: 'Bill', category: 'Spending',
  scenario: 'Projected', rule: 'Savings rule', forecast: 'Forecast',
}
const CARD = { w: 260, h: 182 }
const LAYER_LABEL = { baseline: 'No change', scenario: 'With the what-if', suggestion: 'With the suggestion*' }
const WINDOWS = [30, 90, 180, 365]

// Text widths come from the browser so the layout reserves exactly the room the labels need.
const ctx = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d')
function measure(text, size) {
  if (!ctx) return approxMeasure(text, size)
  ctx.font = `600 ${size}px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif`
  return ctx.measureText(text).width
}

// Where the title text goes for the side chosen by the layout (matches graphLayout.labelRect).
function titlePos(n) {
  const gap = n.r + LABEL_GAP
  const d = n.r * 0.72 + LABEL_GAP
  if (n.side === 'center') return { x: 0, y: 0 }
  if (n.side === 'above-right') return { x: d, y: -d }
  if (n.side === 'above-left') return { x: -d, y: -d }
  if (n.side === 'below-right') return { x: d, y: d }
  if (n.side === 'below-left') return { x: -d, y: d }
  if (n.side === 'above') return { x: 0, y: -gap }
  if (n.side === 'right') return { x: gap, y: 0 }
  if (n.side === 'left') return { x: -gap, y: 0 }
  return { x: 0, y: gap }
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/**
 * The projection from the copilot -> extra graph nodes/edges in the same shape as /api/graph.
 * Amounts arrive per month and are scaled to the graph's time window so they compare with the real lines.
 */
function ghostGraph(projection, graph, days) {
  if (!projection?.scenario) return null
  const scale = (monthly) => Math.round((monthly * days) / 30)
  const nodes = [], edges = []
  for (const pv of [projection.scenario, projection.choice].filter(Boolean)) {
    pv.nodes.forEach((n) => nodes.push({ id: n.id, type: n.type, label: n.label, in_cents: scale(n.monthly_cents), out_cents: scale(n.monthly_cents) }))
    pv.edges.forEach((e) => edges.push({ source: e.source, target: e.target, type: e.type, tag: e.tag, amount_cents: scale(e.monthly_cents), count: 0 }))
  }
  const checking = graph.nodes.find((n) => n.type === 'account' && n.account_type === 'Checking')
  if (checking) {
    nodes.push({ id: 'ghost:forecast', type: 'forecast', label: 'Projected balance', shape: 'card', ...CARD, in_cents: 0, out_cents: 0 })
    edges.push({ source: checking.id, target: 'ghost:forecast', type: 'forecast', tag: 'simulated', amount_cents: 0, count: 0 })
  }
  return { nodes, edges }
}

function layersOf(projection) {
  if (!projection?.scenario) return []
  const s = projection.scenario.series
  const out = [{ key: 'baseline', label: LAYER_LABEL.baseline, band: s.baseline }]
  if (projection.scenario.nodes.length) out.push({ key: 'scenario', label: LAYER_LABEL.scenario, band: s.scenario })
  if (projection.choice) out.push({ key: 'suggestion', label: LAYER_LABEL.suggestion, band: projection.choice.series.scenario })
  return out
}

/** The shared forecast card drawn as a node: fan chart + where each line ends. */
function ForecastCard({ n, layers, onExpand }) {
  const days = layers[0]?.band.p50.length ?? 0
  const top = -n.h / 2
  return (
    <>
      <rect className="gcard" x={-n.w / 2} y={top} width={n.w} height={n.h} rx={12} />
      <text className="gcard-title" x={-n.w / 2 + 12} y={top + 18}>Checking balance · next {days} days</text>
      <g
        className="gcard-expand"
        role="button"
        tabIndex={0}
        aria-label="Open the forecast full size"
        transform={`translate(${n.w / 2 - 30} ${top + 6})`}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={onExpand}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onExpand())}
      >
        <title>Open full size</title>
        <rect width={22} height={22} rx={6} />
        <path d="M6.5 9.5V6.5h3M15.5 9.5V6.5h-3M6.5 12.5v3h3M15.5 12.5v3h-3" />
      </g>
      <ForecastChart layers={layers} x={-n.w / 2 + 8} y={top + 26} width={n.w - 16} height={n.h - 26 - 32 - 14 * layers.length} small />
      {layers.some((l) => l.key === 'suggestion') && (
        <text className="gcard-note" x={-n.w / 2 + 12} y={n.h / 2 - 8}>*lower in checking: the difference is in savings</text>
      )}
      {layers.map((l, i) => (
        <g key={l.key} transform={`translate(${-n.w / 2 + 12} ${n.h / 2 - 24 - 14 * (layers.length - 1 - i)})`}>
          <rect className={`gcard-swatch f-${l.key}`} x={0} y={-7} width={10} height={4} rx={2} />
          <text className="gcard-legend" x={16} y={-3}>{l.label}</text>
          <text className="gcard-value" x={n.w - 24} y={-3} textAnchor="end">{compact(l.band.p50[l.band.p50.length - 1] / 100)}</text>
        </g>
      ))}
    </>
  )
}

function Details({ graph, id, onClose }) {
  const node = graph.nodes.find((n) => n.id === id)
  if (!node) return null
  const label = (nid) => titleCase(graph.nodes.find((n) => n.id === nid)?.label)
  const incoming = graph.edges.filter((e) => e.target === id)
  const outgoing = graph.edges.filter((e) => e.source === id)
  const row = (e, other) => (
    <li key={`${e.source}${e.target}${e.type}`}>
      <span>{label(other)}</span>
      <span className="muted">{e.count}×</span>
      <b>{money.format(e.amount_cents / 100)}</b>
    </li>
  )
  return (
    <aside className="gdetail">
      <button className="gclose" onClick={onClose} aria-label="Close details">×</button>
      <span className="gnode-kind">{TYPE_LABEL[node.type]}</span>
      <h4>{titleCase(node.label)}</h4>
      {node.type === 'obligation' && node.bill_cents != null && (
        <p className="muted">
          {money.format(node.bill_cents / 100)} due on day {node.due_day} each month
        </p>
      )}
      {incoming.length > 0 && (
        <>
          <h5>Money in · {money.format(node.in_cents / 100)}</h5>
          <ul>{incoming.map((e) => row(e, e.source))}</ul>
        </>
      )}
      {outgoing.length > 0 && (
        <>
          <h5>Money out · {money.format(node.out_cents / 100)}</h5>
          <ul>{outgoing.map((e) => row(e, e.target))}</ul>
        </>
      )}
    </aside>
  )
}

/** The forecast at the size of the graph: fan chart, hover readout, and per-line toggles. */
function ForecastModal({ layers, start, onClose }) {
  const body = useRef(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [hidden, setHidden] = useState(() => new Set())
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(body.current)
    return () => ro.disconnect()
  }, [])
  const days = layers[0]?.band.p50.length ?? 0
  const visible = layers.filter((l) => !hidden.has(l.key))
  const toggle = (key) =>
    setHidden((h) => {
      const next = new Set(h)
      if (next.has(key)) next.delete(key)
      else if (layers.length - next.size > 1) next.add(key) // always keep one line on screen
      return next
    })
  return (
    <Modal
      title={`Projected balance · next ${days} days`}
      onClose={onClose}
      within="container"
      size="fill"
      actions={
        <button className="gforecast inline on" aria-pressed="true" onClick={onClose} title="Back to the graph">
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M2 15l4.5-5 3.5 3 6-7.5M12.5 5.5H16V9" /></svg>
          Back to graph
        </button>
      }
    >
      <div className="fmodal">
        <p className="muted small">
          Each line is the median outcome across 5,000 simulated futures; the shaded band is the likely range
          (10th to 90th percentile). Below the red $0 line is an overdraft. Hover to read any day.
        </p>
        <div className="fmodal-chart" ref={body}>
          <ForecastChart layers={visible} width={box.w} height={box.h} start={start} />
        </div>
        <div className="fmodal-legend" role="group" aria-label="Show or hide a line">
          {layers.map((l) => (
            <button key={l.key} className={`flegend ${hidden.has(l.key) ? 'off' : ''}`} aria-pressed={!hidden.has(l.key)} onClick={() => toggle(l.key)}>
              <i className={`fswatch-dot f-${l.key}`} />
              <span>{l.label.replace('*', '')}</span>
              <b>{compact(l.band.p50[l.band.p50.length - 1] / 100)}</b>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  )
}

function Canvas({ graph, projection, days }) {
  const wrap = useRef(null)
  const svg = useRef(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [selected, setSelected] = useState(null)
  const [hover, setHover] = useState(null)
  const [hoverEdge, setHoverEdge] = useState(null)
  const [panning, setPanning] = useState(false)
  const [, redraw] = useReducer((n) => n + 1, 0)
  const [simVersion, setSimVersion] = useState(0)
  const [forecastOpen, setForecastOpen] = useState(false)
  const drag = useRef(null)
  const fitted = useRef(false)

  // The layout is computed once per dataset; dragging mutates it in place and we just redraw.
  const model = useMemo(() => layoutGraph(graph, measure), [graph])

  // Projected nodes from the copilot: placed into free space around the graph; existing nodes stay put.
  const ghosts = useMemo(() => ghostGraph(projection, graph, days), [projection, graph, days])
  const layers = useMemo(() => layersOf(projection), [projection])
  const open = forecastOpen && layers.length > 0 // a new question with no forecast closes the modal
  const fitFor = useRef(null)
  useEffect(() => {
    applyGhosts(model, ghosts, measure)
    setSimVersion((v) => v + 1)
  }, [model, ghosts])

  // Keep the picture live while the simulation runs (dragging a node makes its neighbours follow).
  useEffect(() => {
    const sim = model.sim
    const step = () => { refresh(model, measure); redraw() }
    sim.on('tick.ui', step)
    sim.on('end.ui', () => { settle(model, measure); redraw() })
    return () => { sim.on('tick.ui', null); sim.on('end.ui', null); sim.stop() }
  }, [model, simVersion])

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  const fit = useCallback(() => {
    if (!size.w) return
    const b = model.bounds
    const bw = b.x1 - b.x0, bh = b.y1 - b.y0
    const k = clamp(Math.min((size.w - 56) / bw, (size.h - 56) / bh), 0.25, 1.6)
    setView({ k, x: size.w / 2 - k * (b.x0 + bw / 2), y: size.h / 2 - k * (b.y0 + bh / 2) })
  }, [model, size.w, size.h])

  useEffect(() => {
    if (size.w && !fitted.current) { fitted.current = true; fit() }
  }, [size.w, fit])

  // A new question brings new projected nodes: re-frame once so the forecast card is in view.
  useEffect(() => {
    const key = projection?.scenario ? JSON.stringify(projection.scenario.nodes) + projection.scenario.series.start : null
    if (key && key !== fitFor.current && simVersion) { fitFor.current = key; fit() }
  }, [projection, simVersion, fit])

  // Wheel zoom around the cursor (needs a non-passive listener to stop the page scrolling).
  useEffect(() => {
    const el = svg.current
    const onWheel = (e) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const px = e.clientX - r.left, py = e.clientY - r.top
      setView((v) => {
        const k = clamp(v.k * Math.exp(-e.deltaY * 0.0015), 0.25, 3)
        return { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const toGraph = (e) => {
    const r = svg.current.getBoundingClientRect()
    return { x: (e.clientX - r.left - view.x) / view.k, y: (e.clientY - r.top - view.y) / view.k }
  }

  const onPointerDown = (e, node) => {
    svg.current.setPointerCapture(e.pointerId)
    drag.current = { node, sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false }
    if (!node) setPanning(true)
    e.stopPropagation()
  }
  const onPointerMove = (e) => {
    const d = drag.current
    if (!d) return
    if (Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > 3) d.moved = true
    if (!d.moved) return
    if (d.node) {
      const g = toGraph(e)
      d.node.fx = g.x
      d.node.fy = g.y
      wake(model)
    } else {
      setView((v) => ({ ...v, x: d.vx + e.clientX - d.sx, y: d.vy + e.clientY - d.sy }))
    }
  }
  const onPointerUp = () => {
    const d = drag.current
    drag.current = null
    setPanning(false)
    if (!d) return
    if (d.node) {
      d.node.fx = null
      d.node.fy = null
      model.sim.alphaTarget(0)
      if (!d.moved) setSelected((cur) => (cur === d.node.id ? null : d.node.id))
    } else if (!d.moved) setSelected(null)
  }

  const zoomBy = (f) =>
    setView((v) => {
      const k = clamp(v.k * f, 0.25, 3)
      const cx = size.w / 2, cy = size.h / 2
      return { k, x: cx - ((cx - v.x) / v.k) * k, y: cy - ((cy - v.y) / v.k) * k }
    })

  // Hovering (or selecting) a node lights up its connections and dims the rest, as in Obsidian.
  const focus = hover ?? selected
  const near = useMemo(() => {
    if (!focus) return null
    const set = new Set([focus])
    model.links.forEach((l) => {
      if (l.s.id === focus) set.add(l.t.id)
      if (l.t.id === focus) set.add(l.s.id)
    })
    return set
  }, [focus, model])
  const touches = (l) => focus && (l.s.id === focus || l.t.id === focus)

  return (
    <div className="gcanvas" ref={wrap}>
      <svg
        ref={svg}
        className={`gsvg ${panning ? 'panning' : ''}`}
        role="img"
        aria-label="Graph of how money flows between income, accounts, bills and spending"
        onPointerDown={(e) => onPointerDown(e, null)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {model.links.map((l) => {
            const key = `${l.raw.source}>${l.raw.target}:${l.raw.type}`
            const arrow = l.arrow > 0 && l.len > l.arrow * 1.6
            const tip = l.p2
            const bx = tip.x - l.ux * l.arrow, by = tip.y - l.uy * l.arrow
            const end = arrow ? { x: tip.x - l.ux * l.arrow * 0.85, y: tip.y - l.uy * l.arrow * 0.85 } : tip
            const cls = `gedge ${l.raw.type} ${l.raw.tag !== 'observed' ? 'projected' : ''} ${focus ? (touches(l) ? 'hot' : 'dim') : ''}`
            return (
              <g key={key} className={cls}>
                <line className="gl" x1={l.p1.x} y1={l.p1.y} x2={end.x} y2={end.y} strokeWidth={l.width} />
                {arrow && (
                  <polygon
                    points={`${tip.x},${tip.y} ${bx - l.uy * l.arrowHalf},${by + l.ux * l.arrowHalf} ${bx + l.uy * l.arrowHalf},${by - l.ux * l.arrowHalf}`}
                  />
                )}
                <line
                  className="ghit"
                  x1={l.p1.x} y1={l.p1.y} x2={l.p2.x} y2={l.p2.y}
                  strokeWidth={Math.max(14, l.width + 8)}
                  onPointerEnter={() => setHoverEdge(key)}
                  onPointerLeave={() => setHoverEdge(null)}
                />
              </g>
            )
          })}

          {model.links.map((l) => {
            const key = `${l.raw.source}>${l.raw.target}:${l.raw.type}`
            const reveal = hoverEdge === key || touches(l)
            if (!l.text || !l.label) return null // e.g. the forecast card's connector
            if (l.hidden && !reveal) return null // no clean spot: shown only on hover, never on top of something
            const dim = focus && !touches(l)
            return (
              <g
                key={`p-${key}`}
                className={`gpill ${dim ? 'dim' : ''} ${l.hidden ? 'floating' : ''}`}
                transform={`translate(${l.label.cx} ${l.label.cy})`}
                onPointerEnter={() => setHoverEdge(key)}
                onPointerLeave={() => setHoverEdge(null)}
              >
                <rect x={-l.label.w / 2} y={-PILL_H / 2} width={l.label.w} height={PILL_H} rx={PILL_H / 2} />
                <text>{l.text}</text>
              </g>
            )
          })}

          {model.nodes.map((n) => (
            <g
              key={n.id}
              className={`gn gn-${n.data.type} ${n.ghost || n.data.tag === 'proposed' ? 'ghost' : ''} ${near && !near.has(n.id) ? 'dim' : ''} ${n.id === selected ? 'selected' : ''}`}
              transform={`translate(${n.x} ${n.y})`}
              onPointerDown={(e) => onPointerDown(e, n)}
              onPointerEnter={() => setHover(n.id)}
              onPointerLeave={() => setHover(null)}
            >
              <title>{`${n.shape === 'card' ? n.data.label : titleCase(n.data.label)} · ${TYPE_LABEL[n.data.type]}`}</title>
              {n.shape === 'card' ? <ForecastCard n={n} layers={layers} onExpand={() => setForecastOpen(true)} /> : <circle r={n.r} />}
              {n.side === 'center' && (
                <rect className="gbadge" x={-n.lw / 2 - 4} y={-LABEL_H / 2 - 2} width={n.lw + 8} height={LABEL_H + 4} rx={(LABEL_H + 4) / 2} />
              )}
              {n.shape !== 'card' && (
                <text className={`gtitle side-${n.side}`} {...titlePos(n)} fontSize={FONT}>{n.title}</text>
              )}
            </g>
          ))}
        </g>
      </svg>

      {layers.length > 0 && (
        <button
          className={`gforecast ${open ? 'on' : ''}`}
          aria-pressed={open}
          onClick={() => setForecastOpen((v) => !v)}
          title="Show the balance forecast full size"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M2 15l4.5-5 3.5 3 6-7.5M12.5 5.5H16V9" /></svg>
          Forecast
        </button>
      )}
      {open && <ForecastModal layers={layers} start={projection?.scenario?.series?.start} onClose={() => setForecastOpen(false)} />}
      <div className="gctl" role="group" aria-label="Graph view controls">
        <button onClick={() => zoomBy(1.25)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomBy(0.8)} aria-label="Zoom out">−</button>
        <button onClick={fit} aria-label="Fit to screen">⤢</button>
      </div>
      <p className="ghint">Drag a node to pull its neighbours · scroll to zoom · drag the background to pan · hover to trace</p>
      {selected && <Details graph={graph} id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

export default function GraphView({ projection = null, refresh: refreshKey = 0 }) {
  const [days, setDays] = useState(90)
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    fetch(`/api/graph?days=${days}`, { signal: controller.signal })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(body.detail ?? `Request failed (${res.status})`)
        setGraph(body)
      })
      .catch((err) => err.name !== 'AbortError' && setError(err.message))
    return () => controller.abort()
  }, [days, refreshKey])

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Where your money goes</h2>
          <p className="muted">
            Income flows into accounts, then out to bills, spending categories and savings. Thicker lines
            carry more money, and each line shows its amount. Click a node to trace its flows. Dashed nodes
            are projections: what a decision or a suggestion would add.
          </p>
        </div>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((d) => (
            <button key={d} className={d === days ? 'on' : ''} onClick={() => setDays(d)}>
              {d}d
            </button>
          ))}
        </div>
      </div>
      <div className="legend">
        <span><i className="sw n-income" />Income</span>
        <span><i className="sw n-account" />Account</span>
        <span><i className="sw n-obligation" />Bill</span>
        <span><i className="sw n-category" />Spending</span>
        <span><i className="ln pay" />Payment</span>
        <span><i className="ln fund" />Deposit</span>
        <span><i className="ln xfer" />Transfer</span>
        <span><i className="sw ghost" />Projected</span>
      </div>
      {error && <p className="state error">Couldn't load graph: {error}</p>}
      {graph && graph.nodes.length === 0 && <p className="state">No activity in this window.</p>}
      {graph && graph.nodes.length > 0 && (
        <Canvas key={graph.period.end + graph.period.days} graph={graph} projection={projection} days={days} />
      )}
      {!graph && !error && <p className="state">Loading graph…</p>}
    </section>
  )
}
