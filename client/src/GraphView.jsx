import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import ForecastChart from './ForecastChart'
import Modal from './Modal'
import { applyGhosts, approxMeasure, FONT, LABEL_GAP, LABEL_H, layoutGraph, PILL_H, refresh, settle, wake } from './graphLayout.js'
import { compact, money, titleCase } from './format'
import { post } from './api'
import { pct } from './format'
import { Proposal } from './Suggestions'

const TYPE_LABEL = {
  income: 'Income', account: 'Account', obligation: 'Bill', category: 'Spending',
  scenario: 'Projected', rule: 'Savings rule', forecast: 'Forecast',
}
const LAYER_LABEL = { baseline: 'No change', scenario: 'With the what-if', suggestion: 'With the suggestion' }
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

/** One flagged problem: why it is red, and on request, savings moves that ease it (the AI sees only an anonymous summary). */
function Problem({ f, input, choice, onChoice, onDecision }) {
  const [state, setState] = useState({ phase: 'idle', proposals: [], note: null }) // idle | busy | done | error
  const [notice, setNotice] = useState(null)

  const suggest = async () => {
    setState({ phase: 'busy', proposals: [], note: null })
    try {
      const r = await post('/api/fix', { finding_id: f.id, scenario: input })
      const note = r.ai_unavailable
        ? 'The AI could not be reached, so there are no suggestions right now. Try again in a moment.'
        : r.proposals.length === 0
          ? 'No safe savings move would help with this one. The problem needs a change outside the app, such as how or when the bill is paid.'
          : null
      setState({ phase: 'done', proposals: r.proposals, note })
    } catch (err) {
      setState({ phase: 'error', proposals: [], note: err.message })
    }
  }
  const accepted = (resp, p) => {
    onChoice(null)
    setNotice(`Accepted “Save ${p.percent}% of each paycheck”. Overdraft chance ${pct(resp.forecast.before.scenario.share_below_zero)} → ${pct(resp.forecast.after.scenario.share_below_zero)}.`)
    setState((s) => ({ ...s, proposals: s.proposals.filter((x) => x !== p) }))
    onDecision?.()
  }

  return (
    <section className={`problem sev-${f.severity}`} aria-label={f.title}>
      <div className="problem-head">
        <span className="problem-sev">{f.severity === 'risk' ? 'High risk' : 'Watch'}</span>
        <b>{f.title}</b>
      </div>
      <p className="problem-why">{f.reason}</p>
      {state.phase === 'idle' && (
        <button className="btn sm" onClick={suggest}>Suggest fixes</button>
      )}
      {state.phase === 'busy' && <p className="muted small" role="status">Looking for savings moves that would help…</p>}
      {state.note && <p className={`small ${state.phase === 'error' ? 'error-text' : 'muted'}`}>{state.note}</p>}
      {state.phase !== 'idle' && state.phase !== 'busy' && (
        <button className="btn ghost sm" onClick={suggest}>{state.phase === 'error' ? 'Try again' : 'Suggest again'}</button>
      )}
      {notice && <p className="small saved" role="status">{notice}</p>}
      {state.proposals.length > 0 && (
        <ul className="proposals fixes">
          {state.proposals.map((p) => (
            <Proposal
              key={`${p.from_alias}-${p.to_alias}-${p.percent}`}
              p={p}
              scenario={input}
              base={null}
              picked={choice === p.preview}
              onPick={() => onChoice(choice === p.preview ? null : p.preview)}
              onAccepted={accepted}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function Details({ graph, id, onClose, flags = [], input, choice, onChoice, onDecision }) {
  const node = graph.nodes.find((n) => n.id === id)
  const ghost = !node
  if (!node && !flags.length) return null
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
      <span className="gnode-kind">{ghost ? 'Projected' : TYPE_LABEL[node.type]}</span>
      <h4>{ghost ? 'This decision' : titleCase(node.label)}</h4>
      {flags.map((f) => (
        <Problem key={f.id} f={f} input={input} choice={choice} onChoice={onChoice} onDecision={onDecision} />
      ))}
      {node?.type === 'obligation' && node.bill_cents != null && (
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
          {layers.some((l) => l.key === 'suggestion') && ' The suggestion line sits lower in checking because that money moves to savings.'}
        </p>
        <div className="fmodal-chart" ref={body}>
          <ForecastChart layers={visible} width={box.w} height={box.h} start={start} />
        </div>
        <div className="fmodal-legend" role="group" aria-label="Show or hide a line">
          {layers.map((l) => (
            <button key={l.key} className={`flegend ${hidden.has(l.key) ? 'off' : ''}`} aria-pressed={!hidden.has(l.key)} onClick={() => toggle(l.key)}>
              <i className={`fswatch-dot f-${l.key}`} />
              <span>{l.label}</span>
              <b>{compact(l.band.p50[l.band.p50.length - 1] / 100)}</b>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  )
}

function Canvas({ graph, projection, days, onChoice, onDecision }) {
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
  const problemsOpen = useRef(false) // is the problems panel on screen? (read when framing the graph)

  // The layout is computed once per dataset; dragging mutates it in place and we just redraw.
  const model = useMemo(() => layoutGraph(graph, measure), [graph])

  // Projected nodes from the copilot: placed into free space around the graph; existing nodes stay put.
  const ghosts = useMemo(() => ghostGraph(projection, graph, days), [projection, graph, days])
  const layers = useMemo(() => layersOf(projection), [projection])
  const open = forecastOpen && layers.length > 0 // a new question with no forecast closes the modal

  // Problem spots found by the math: node id -> findings. Only nodes that are on screen are painted.
  const flagged = useMemo(() => {
    const map = new Map()
    for (const f of projection?.findings ?? []) {
      for (const id of f.node_ids) map.set(id, [...(map.get(id) ?? []), f])
    }
    return map
  }, [projection])
  const flagList = (projection?.findings ?? []).filter((f) => f.node_ids.some((id) => model.byId.has(id)))
  const [flagsOpen, setFlagsOpen] = useState(true)
  useEffect(() => {
    problemsOpen.current = flagsOpen && flagList.length > 0 // read when the graph is framed
  })
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
    // keep the graph out from under the "Needs attention" panel that sits on the left while it is open
    const inset = problemsOpen.current ? 330 : 0
    const k = clamp(Math.min((size.w - 56 - inset) / bw, (size.h - 56) / bh), 0.25, 1.6)
    setView({ k, x: inset + (size.w - inset) / 2 - k * (b.x0 + bw / 2), y: size.h / 2 - k * (b.y0 + bh / 2) })
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
            const bad = (l.s.ghost && flagged.has(l.s.id)) || (l.t.ghost && flagged.has(l.t.id))
            const cls = `gedge ${l.raw.type} ${l.raw.tag !== 'observed' ? 'projected' : ''} ${bad ? 'flagged' : ''} ${focus ? (touches(l) ? 'hot' : 'dim') : ''}`
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
              className={`gn gn-${n.data.type} ${n.ghost || n.data.tag === 'proposed' ? 'ghost' : ''} ${flagged.has(n.id) ? `flagged sev-${flagged.get(n.id)[0].severity}` : ''} ${near && !near.has(n.id) ? 'dim' : ''} ${n.id === selected ? 'selected' : ''}`}
              transform={`translate(${n.x} ${n.y})`}
              onPointerDown={(e) => onPointerDown(e, n)}
              onPointerEnter={() => setHover(n.id)}
              onPointerLeave={() => setHover(null)}
            >
              <title>{`${titleCase(n.data.label)} · ${TYPE_LABEL[n.data.type]}${flagged.has(n.id) ? ` · ${flagged.get(n.id).map((f) => f.title).join('; ')}` : ''}`}</title>
              <circle r={n.r} />
              {flagged.has(n.id) && (
                <g className="gflag" transform={`translate(${n.r * 0.75} ${-n.r * 0.75})`}>
                  <circle r={9} /><text y={0.5}>!</text>
                </g>
              )}
              {n.side === 'center' && (
                <rect className="gbadge" x={-n.lw / 2 - 4} y={-LABEL_H / 2 - 2} width={n.lw + 8} height={LABEL_H + 4} rx={(LABEL_H + 4) / 2} />
              )}
              <text className={`gtitle side-${n.side}`} {...titlePos(n)} fontSize={FONT}>{n.title}</text>
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
      {flagList.length > 0 && (
        <aside className="gflags" aria-label="Problems found">
          <button className="gflags-head" aria-expanded={flagsOpen} onClick={() => setFlagsOpen((v) => !v)}>
            <span className="gflags-dot" aria-hidden="true">!</span>
            Needs attention <em>{flagList.length}</em>
            <span className="gflags-chev" aria-hidden="true">{flagsOpen ? '▾' : '▸'}</span>
          </button>
          {flagsOpen && (
            <ul>
              {flagList.map((f) => (
                <li key={f.id}>
                  <button className={`gflag-item sev-${f.severity}`} onClick={() => setSelected(f.node_ids.find((id) => model.byId.has(id)))}>
                    <b>{f.title}</b>
                    <span>{f.reason}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}
      {selected && (
        <Details
          graph={graph}
          id={selected}
          onClose={() => setSelected(null)}
          flags={flagged.get(selected) ?? []}
          input={projection?.input ?? null}
          choice={projection?.choice ?? null}
          onChoice={onChoice}
          onDecision={onDecision}
        />
      )}
    </div>
  )
}

export default function GraphView({ projection = null, refresh: refreshKey = 0, onChoice, onDecision }) {
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
        <Canvas key={graph.period.end + graph.period.days} graph={graph} projection={projection} days={days} onChoice={onChoice} onDecision={onDecision} />
      )}
      {!graph && !error && <p className="state">Loading graph…</p>}
    </section>
  )
}
