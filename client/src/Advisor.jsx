import { useRef, useState } from 'react'

// The four agents, in order, with what the customer sees while each one works.
const STEPS = [
  { id: 'planner', label: 'Understanding your question' },
  { id: 'explainer', label: 'Writing the explanation' },
  { id: 'action', label: 'Looking for improvements' },
  { id: 'critic', label: 'Double-checking everything' },
]
const IDEAS = ['Can I afford a car?', 'What if my rent goes up?', 'What if I lose some income?', 'I want a new subscription']

const pct = (x) => (x > 0 && x < 0.005 ? '<1%' : `${Math.round(x * 100)}%`)
const TONE = { ok: 'good', watch: 'ok', risk: 'bad' }
const FLAG = { overdraft: 'Overdraft', payment_too_big: 'Payment vs. income', low_buffer: 'Cash cushion' }

// Reads a Server-Sent Events stream from fetch (EventSource can't POST) and calls onEvent(name, data).
async function readEvents(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop()
    for (const block of blocks) {
      const name = /^event: (.+)$/m.exec(block)?.[1]
      const data = /^data: (.+)$/m.exec(block)?.[1]
      if (name && data) onEvent(name, JSON.parse(data))
    }
  }
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : `Request failed (${res.status})`)
  return json
}

function Progress({ steps }) {
  return (
    <ol className="steps">
      {STEPS.map((s) => (
        <li key={s.id} className={`step ${steps[s.id] ?? 'waiting'}`}>
          <span className="dot" aria-hidden="true" />
          {s.label}
          {steps[s.id] === 'canned' && <em> · used a standard answer</em>}
        </li>
      ))}
    </ol>
  )
}

function Chance({ label, value }) {
  return (
    <div className="chance">
      <span className="stat-label">{label}</span>
      <b>{pct(value)}</b>
    </div>
  )
}

function Proposal({ p, scenario, base }) {
  const [state, setState] = useState({ phase: 'idle' }) // idle | busy | saved | error
  const act = async (fn) => {
    setState((s) => ({ ...s, phase: 'busy' }))
    try {
      setState(await fn())
    } catch (err) {
      setState({ phase: 'error', message: err.message })
    }
  }
  const accept = () =>
    act(async () => {
      const r = await post('/api/accept', { from_alias: p.from_alias, to_alias: p.to_alias, percent: p.percent, scenario })
      return { phase: 'saved', ruleId: r.rule_id, before: r.forecast.before, after: r.forecast.after }
    })
  const undo = () =>
    act(async () => {
      await post(`/api/undo/${state.ruleId}`, { scenario })
      return { phase: 'idle' }
    })

  return (
    <li className="proposal">
      <div>
        <b>Move {p.percent}% of each paycheck</b>
        <span className="muted"> from {p.from_label} to {p.to_label}</span>
        <p>{p.reason}</p>
        {p.forecast && (
          <span className="muted">
            Chance of going below zero with this change: {pct(p.forecast.scenario.share_below_zero)} (now {pct(base)})
          </span>
        )}
        {state.phase === 'saved' && (
          <p className="saved">
            Saved. Forecast re-run: overdraft chance {pct(state.before.scenario.share_below_zero)} →{' '}
            {pct(state.after.scenario.share_below_zero)}.
          </p>
        )}
        {state.phase === 'error' && <p className="error-text">{state.message}</p>}
      </div>
      {state.phase === 'saved' ? (
        <button className="btn ghost" onClick={undo}>Undo</button>
      ) : (
        <button className="btn" onClick={accept} disabled={state.phase === 'busy'}>
          {state.phase === 'busy' ? 'Saving…' : 'Accept'}
        </button>
      )}
    </li>
  )
}

function Result({ r }) {
  const { forecast: f } = r
  const withWhatIf = r.scenario.kind !== 'none'
  return (
    <div className="advice">
      <p className="explanation">{r.explanation.text}</p>

      <div className="chances">
        <Chance label={`Chance of going below zero · next ${f.horizon_days} days`} value={f.baseline.share_below_zero} />
        {withWhatIf && <Chance label="…with this change" value={f.scenario.share_below_zero} />}
      </div>

      <div className="flags">
        {r.risk.flags.map((fl) => (
          <span key={fl.flag} className={`flag ${TONE[fl.status]}`}>
            {FLAG[fl.flag]}: {fl.status}
          </span>
        ))}
      </div>

      {r.proposals.length > 0 ? (
        <>
          <h4>Suggested changes</h4>
          <ul className="proposals">
            {r.proposals.map((p) => (
              <Proposal
                key={`${p.from_alias}-${p.to_alias}-${p.percent}`}
                p={p}
                scenario={r.scenario}
                base={f.scenario.share_below_zero}
              />
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">No safe changes to suggest right now.</p>
      )}
      {r.retries > 0 && <p className="muted small">Reviewed and revised {r.retries}× before showing you this.</p>}
    </div>
  )
}

export default function Advisor() {
  const [text, setText] = useState('')
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const abort = useRef(null)

  const ask = async (question) => {
    const request = question.trim()
    if (!request || running) return
    abort.current?.abort()
    abort.current = new AbortController()
    setRunning(true)
    setResult(null)
    setError(null)
    setSteps({ planner: 'running' })
    try {
      const res = await fetch('/api/advise', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request }),
        signal: abort.current.signal,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`)
      }
      await readEvents(res, (name, data) => {
        if (name === 'progress') {
          setSteps((s) => {
            const next = { ...s, [data.agent]: data.fallback ? 'canned' : 'done' }
            const after = STEPS[STEPS.findIndex((x) => x.id === data.agent) + 1]
            if (after) next[after.id] = 'running'
            // the Critic sent work back: Action and the Critic run again
            if (data.agent === 'critic' && /sent back/.test(data.message)) {
              next.action = 'running'
              next.critic = 'waiting'
            }
            return next
          })
        } else if (name === 'result') setResult(data)
        else if (name === 'error') setError(data.message)
      })
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="advisor card">
      <h2 className="section-title">Ask the copilot</h2>
      <p className="muted">
        Describe a decision or worry. The AI sees only anonymous summaries; your names and numbers stay here.
      </p>
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault()
          ask(text)
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Can I afford a car with a 60-month loan?"
          maxLength={500}
          aria-label="Your question"
        />
        <button className="btn" disabled={running || !text.trim()}>
          {running ? 'Working…' : 'Ask'}
        </button>
      </form>
      <div className="ideas">
        {IDEAS.map((q) => (
          <button key={q} className="chip" disabled={running} onClick={() => { setText(q); ask(q) }}>
            {q}
          </button>
        ))}
      </div>

      {(running || Object.keys(steps).length > 0) && !result && !error && <Progress steps={steps} />}
      {error && <p className="state error">{error}</p>}
      {result && <Result r={result} />}
    </section>
  )
}
