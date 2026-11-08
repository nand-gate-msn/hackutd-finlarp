import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'
import { compact, money, titleCase } from './format'

const SIZE = {
  account: { w: 210, h: 84 },
  income: { w: 180, h: 64 },
  obligation: { w: 200, h: 58 },
  category: { w: 170, h: 54 },
}
const TYPE_LABEL = { income: 'Income', account: 'Account', obligation: 'Bill', category: 'Spending' }
const EDGE_COLOR = { funds: 'var(--good)', pays: 'var(--edge-pay)', transfers: 'var(--accent)' }
const WINDOWS = [30, 90, 180, 365]

function FlowNode({ data }) {
  const { node, dim, selected } = data
  return (
    <div className={`gnode gnode-${node.type} ${dim ? 'dim' : ''} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} className="ghandle" />
      <span className="gnode-kind">{TYPE_LABEL[node.type]}</span>
      <span className="gnode-title" title={node.label}>{titleCase(node.label)}</span>
      {node.type === 'account' && <span className="gnode-sub">{node.alias}</span>}
      <span className="gnode-amt">
        {node.type === 'income' ? `+${compact(node.out_cents / 100)}` : `${compact(node.in_cents / 100)}`}
        {node.type === 'account' && <em> in · {compact(node.out_cents / 100)} out</em>}
      </span>
      <Handle type="source" position={Position.Right} className="ghandle" />
    </div>
  )
}
const nodeTypes = { flow: FlowNode }

function layout(graph, selectedId) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 26, ranksep: 150, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  graph.nodes.forEach((n) => g.setNode(n.id, { width: SIZE[n.type].w, height: SIZE[n.type].h }))
  graph.edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const connected = new Set()
  if (selectedId) {
    connected.add(selectedId)
    graph.edges.forEach((e) => {
      if (e.source === selectedId || e.target === selectedId) {
        connected.add(e.source)
        connected.add(e.target)
      }
    })
  }
  const max = Math.max(...graph.edges.map((e) => e.amount_cents), 1)

  const nodes = graph.nodes.map((n) => {
    const p = g.node(n.id)
    return {
      id: n.id,
      type: 'flow',
      position: { x: p.x - SIZE[n.type].w / 2, y: p.y - SIZE[n.type].h / 2 },
      data: { node: n, dim: selectedId && !connected.has(n.id), selected: n.id === selectedId },
    }
  })
  const edges = graph.edges.map((e) => {
    const id = `${e.source}>${e.target}:${e.type}`
    const active = !selectedId || e.source === selectedId || e.target === selectedId
    return {
      id,
      source: e.source,
      target: e.target,
      type: 'default',
      label: compact(e.amount_cents / 100),
      animated: e.type === 'transfers',
      style: {
        stroke: EDGE_COLOR[e.type],
        strokeWidth: 1.5 + 7 * Math.sqrt(e.amount_cents / max),
        opacity: active ? 0.85 : 0.1,
        strokeDasharray: e.tag !== 'observed' ? '6 4' : undefined,
      },
      labelStyle: { fill: 'var(--text)', fontWeight: 600, fontSize: 12 },
      labelBgStyle: { fill: 'var(--card)', fillOpacity: 0.95 },
      labelBgPadding: [6, 3],
      labelBgBorderRadius: 6,
      data: { raw: e },
    }
  })
  return { nodes, edges }
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

function Canvas({ graph }) {
  const [selected, setSelected] = useState(null)
  const { fitView } = useReactFlow()
  const { nodes, edges } = useMemo(() => layout(graph, selected), [graph, selected])
  const dark = useMemo(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches, [])

  useEffect(() => {
    const t = setTimeout(() => fitView({ padding: 0.12, duration: 300 }), 50)
    return () => clearTimeout(t)
  }, [graph, fitView])

  return (
    <div className="gcanvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode={dark ? 'dark' : 'light'}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.2}
        maxZoom={2.5}
        nodesConnectable={false}
        nodesDraggable
        elementsSelectable
        onNodeClick={(_, n) => setSelected((cur) => (cur === n.id ? null : n.id))}
        onPaneClick={() => setSelected(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="gminimap" nodeColor={(n) => `var(--n-${n.data.node.type})`} />
      </ReactFlow>
      {selected && <Details graph={graph} id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

export default function GraphView() {
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
  }, [days])

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Where your money goes</h2>
          <p className="muted">
            Income flows into accounts, then out to bills, spending categories and savings. Line thickness
            shows the amount. Scroll to zoom, drag to pan, click a node to trace its flows.
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
      </div>
      {error && <p className="state error">Couldn't load graph: {error}</p>}
      {graph && graph.nodes.length === 0 && <p className="state">No activity in this window.</p>}
      {graph && graph.nodes.length > 0 && (
        <ReactFlowProvider>
          <Canvas key={graph.period.end + graph.period.days} graph={graph} />
        </ReactFlowProvider>
      )}
      {!graph && !error && <p className="state">Loading graph…</p>}
    </section>
  )
}
