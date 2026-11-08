import { useRef, useState } from 'react'
import { post } from './api'
import AcceptedChanges from './AcceptedChanges'

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
const HEALTH_TONE = { Healthy: 'good', Okay: 'ok', 'Needs attention': 'warn', 'At risk': 'bad' }
const pts = (n) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(Math.round(n * 10) / 10)}`
const score = (x) => Math.round(x)
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

function Health({ h }) {
  const { before, after, change, drivers, what_if: whatIf } = h
  return (
    <div className="health-card">
      <div className="health-score">
        <span className="stat-label">Overall financial health</span>
        <div className="health-numbers">
          <b className={`tone-${HEALTH_TONE[before.status]}`}>{score(before.score)}</b>
          {whatIf && (
            <>
              <span className="arrow" aria-hidden="true">→</span>
              <b className={`tone-${HEALTH_TONE[after.status]}`}>{score(after.score)}</b>
              <span className={`delta ${change < 0 ? 'down' : change > 0 ? 'up' : ''}`}>{pts(score(after.score) - score(before.score))}</span>
            </>
          )}
        </div>
        <span className="muted small">
          {whatIf ? `${before.status} today · ${after.status} with this decision` : `${before.status} today`}
        </span>
      </div>
      {whatIf && drivers.length > 0 && (
        <ul className="drivers">
          {drivers.map((d) => (
            <li key={d.label}>
              <span className={d.effect === 'worse' ? 'down' : 'up'}>{d.effect === 'worse' ? '▼' : '▲'}</span>{' '}
              {d.label} {d.effect === 'worse' ? 'lowers' : 'raises'} it by about {Math.max(1, Math.round(d.points))}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const ruleKey = (r) => `${r.from_alias}|${r.to_alias}|${Number(r.percent)}`

function Proposal({ p, scenario, base, picked, onPick, onAccepted }) {
  const [state, setState] = useState({ phase: 'idle' }) // idle | busy | error
  const accept = async () => {
    setState({ phase: 'busy' })
    try {
      const r = await post('/api/accept', { from_alias: p.from_alias, to_alias: p.to_alias, percent: p.percent, scenario })
      onAccepted(r, p)
    } catch (err) {
      setState({ phase: 'error', message: err.message })
    }
  }
  return (
    <li className={`proposal ${picked ? 'picked' : ''}`}>
      {/* The card itself is the button: selecting it previews the change on the graph. */}
      <button type="button" className="pick" aria-pressed={picked} onClick={onPick}>
        <span className="pick-head">
          <b>Move {p.percent}% of each paycheck</b>
          <span className="muted"> from {p.from_label} to {p.to_label}</span>
        </span>
        <span className="pick-reason">{p.reason}</span>
        {p.forecast && (
          <span className="muted small">
            Overdraft chance with this change: {pct(p.forecast.scenario.share_below_zero)} (now {pct(base)})
            {p.health && ` · health ${score(p.health.score)} (${pts(Math.round(p.health.change_vs_scenario * 10) / 10)})`}
          </span>
        )}
        <span className="pick-hint">{picked ? '● Shown on the graph' : 'Show on the graph'}</span>
      </button>
      <div className="proposal-actions">
        <button className="btn sm" onClick={accept} disabled={state.phase === 'busy'}>
          {state.phase === 'busy' ? 'Saving…' : 'Accept'}
        </button>
      </div>
      {state.phase === 'error' && <p className="error-text">{state.message}</p>}
    </li>
  )
}

function Result({ r, rules, onProject, onAccepted }) {
  const { forecast: f } = r
  const [picked, setPicked] = useState(null)
  const [showOthers, setShowOthers] = useState(false)
  const withWhatIf = r.scenario.kind !== 'none'

  // A suggestion counts as accepted while a saved rule matches it. Undo it in "Changes accepted" and it
  // comes straight back here, so the customer can always go back to the other options.
  const taken = new Set(rules.map(ruleKey))
  const indexed = r.proposals.map((p, i) => ({ p, i, accepted: taken.has(ruleKey(p)) }))
  const open = indexed.filter((x) => !x.accepted)
  const anyAccepted = open.length < indexed.length
  const listShown = !anyAccepted || showOthers

  // Selecting a suggestion (or clearing it) redraws the projected part of the money-flow graph.
  const pick = (i) => {
    const next = picked === i ? null : i
    setPicked(next)
    onProject?.({ scenario: r.preview, choice: next == null ? null : r.proposals[next].preview })
  }
  const accepted = (resp, p) => {
    setPicked(null)
    setShowOthers(false)
    onProject?.({ scenario: r.preview, choice: null })
    onAccepted(resp, p)
  }

  return (
    <div className="advice">
      <Health h={r.health} />
      <p className="explanation">{r.explanation.text}</p>

      <div className="chances">
        <Chance label={`Overdraft chance · next ${f.horizon_days} days`} value={f.baseline.share_below_zero} />
        {withWhatIf && <Chance label="…with this change" value={f.scenario.share_below_zero} />}
      </div>

      <div className="flags">
        {r.risk.flags.map((fl) => (
          <span key={fl.flag} className={`flag ${TONE[fl.status]}`}>
            {FLAG[fl.flag]}: {fl.status}
          </span>
        ))}
      </div>

      {r.proposals.length === 0 ? (
        <p className="muted">No safe changes to suggest right now.</p>
      ) : (
        <section className="suggestions" aria-label="Suggested changes">
          <h4>Suggested changes</h4>
          {anyAccepted && (
            <p className="muted small">
              {indexed.length - open.length} of {indexed.length} accepted. It is listed under “Changes accepted”.
            </p>
          )}
          {anyAccepted && open.length > 0 && (
            <button
              type="button"
              className="see-others"
              aria-expanded={showOthers}
              onClick={() => setShowOthers((v) => !v)}
            >
              {showOthers ? 'Hide other suggested options' : `See other suggested options (${open.length})`}
            </button>
          )}
          {!anyAccepted && <p className="muted small">Select one to preview it on the graph.</p>}
          {listShown && open.length > 0 && (
            <ul className="proposals">
              {open.map(({ p, i }) => (
                <Proposal
                  key={ruleKey(p)}
                  p={p}
                  scenario={r.scenario}
                  base={f.scenario.share_below_zero}
                  picked={picked === i}
                  onPick={() => pick(i)}
                  onAccepted={accepted}
                />
              ))}
            </ul>
          )}
          {anyAccepted && open.length === 0 && <p className="muted small">That was the last suggestion.</p>}
        </section>
      )}
      {r.retries > 0 && <p className="muted small">Reviewed and revised {r.retries}× before showing you this.</p>}
    </div>
  )
}

export default function Advisor({ rules = [], onDecision, onProject }) {
  const [text, setText] = useState('')
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const abort = useRef(null)

  const ask = async (question) => {
    const request = question.trim()
    if (!request || running) return
    abort.current?.abort()
    abort.current = new AbortController()
    setRunning(true)
    setResult(null)
    setNotice(null)
    onProject?.(null) // clear the previous question's projections
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
        } else if (name === 'result') {
          setResult({ ...data, received: Date.now() })
          onProject?.({ scenario: data.preview, choice: null }) // the what-if appears on the graph right away
        } else if (name === 'error') setError(data.message)
      })
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setRunning(false)
    }
  }

  const accepted = (resp, p) => {
    setNotice({
      title: `Save ${p.percent}% of each paycheck`,
      ruleId: resp.rule_id,
      overdraft: [resp.forecast.before.scenario.share_below_zero, resp.forecast.after.scenario.share_below_zero],
      health: [resp.health.before.score, resp.health.after.score],
    })
    onDecision?.() // refresh the saved changes, the graph and the health gauge
  }
  const undoNotice = async () => {
    try {
      await post(`/api/undo/${notice.ruleId}`, { scenario: result?.scenario ?? null })
      setNotice(null)
      onDecision?.()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="copilot" aria-label="Copilot">
      <header className="copilot-head">
        <h2>Copilot</h2>
        <p className="muted small">
          Ask about a decision or worry. The AI sees only anonymous summaries; your names and numbers stay here.
        </p>
      </header>

      <div className="copilot-scroll">
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
            placeholder="e.g. Can I afford a car?"
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
        {notice && (
          <div className="notice ok" role="status">
            <div>
              <b>Accepted:</b> {notice.title}. Overdraft chance {pct(notice.overdraft[0])} → {pct(notice.overdraft[1])}
              {' · '}health {score(notice.health[0])} → {score(notice.health[1])}
            </div>
            <div className="notice-actions">
              <button className="btn ghost sm" onClick={undoNotice}>Undo</button>
              <button className="btn ghost sm" onClick={() => setNotice(null)} aria-label="Dismiss">Dismiss</button>
            </div>
          </div>
        )}
        {result && (
          <Result key={result.received} r={result} rules={rules} onProject={onProject} onAccepted={accepted} />
        )}
      </div>

      <footer className="copilot-foot">
        <AcceptedChanges rules={rules} scenario={result?.scenario ?? null} onChanged={onDecision} />
      </footer>
    </section>
  )
}
