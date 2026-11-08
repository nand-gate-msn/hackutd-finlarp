import { useEffect, useState } from 'react'
import { money } from './format'

// Score (0-100) -> tone. Matches the thresholds in overallFinHealth._status.
const tone = (s) => (s == null ? 'na' : s >= 80 ? 'good' : s >= 60 ? 'ok' : s >= 40 ? 'warn' : 'bad')

const PILLAR_HINT = {
  Spend: 'Savings rate, volatility, recurring extras',
  Save: 'Months of expenses in cash',
  Borrow: 'Housing and debt vs. income',
  Plan: 'Overdraft risk, income stability',
}

function Gauge({ score, status }) {
  const r = 52
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, score ?? 0)) / 100
  return (
    <div className={`gauge t-${tone(score)}`}>
      <svg viewBox="0 0 130 130" role="img" aria-label={`Financial health ${score ?? 'unknown'} out of 100`}>
        <circle cx="65" cy="65" r={r} className="g-track" />
        <circle
          cx="65" cy="65" r={r} className="g-fill"
          strokeDasharray={`${c * pct} ${c}`} transform="rotate(-90 65 65)"
        />
      </svg>
      <div className="gauge-text">
        <b>{score == null ? '—' : Math.round(score)}</b>
        <span>{status}</span>
      </div>
    </div>
  )
}

export default function Metrics({ refresh = 0 }) {
  const [m, setM] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/metrics', { signal: controller.signal })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(body.detail ?? `Request failed (${res.status})`)
        setM(body)
      })
      .catch((err) => err.name !== 'AbortError' && setError(err.message))
    return () => controller.abort()
  }, [refresh])

  if (error) return <p className="state error">Couldn’t load metrics: {error}</p>
  if (!m) return <p className="state">Loading metrics…</p>

  const flow = m.flow_90d
  const net = flow.income - flow.spend
  const indicators = Object.entries(m.indicators).filter(([, i]) => i.score != null)
  const missing = Object.values(m.indicators).filter((i) => i.score == null)

  return (
    <section className="panel metrics-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">The bigger picture</span>
          <h2>Financial health</h2>
          <p className="muted">Your overall score and the four pillars behind it.</p>
        </div>
        <details className="score-method"><summary>How the score works</summary><p>A weighted score computed from your transactions, using fixed formulas rather than AI. Each pillar contributes the weight shown below. Explore the indicators for the underlying measurements.</p></details>
      </div>

      <div className="health">
        <div className="health-overall">
          <span className="eyebrow">Overall score</span>
          <Gauge score={m.overallFinHealth} status={m.status} />
          <span className="small muted">Out of 100</span>
        </div>
        <div className="pillars">
          {Object.entries(m.pillars).map(([name, p]) => (
            <div className="pillar" key={name}>
              <div className="pillar-top"><h3>{name}</h3><span className={`pill t-${tone(p.score)}`}>{p.score ?? '—'}<small> / 100</small></span></div>
              <div className="bar-track"><div className={`bar-fill f-${tone(p.score)}`} style={{ transform: `scaleX(${(p.score ?? 0) / 100})` }} /></div>
              <div className="pillar-description"><span>{PILLAR_HINT[name]}</span><span>{Math.round(p.weight * 100)}% weight</span></div>
            </div>
          ))}
        </div>
      </div>

      <div className="flow-summary">
        <h3>Cash flow <span className="muted small">Last 90&nbsp;days</span></h3>
        <dl>
          <div><dt>Income</dt><dd>{money.format(flow.income / 100)}</dd></div>
          <div><dt>Spent</dt><dd>{money.format(flow.spend / 100)}</dd></div>
          <div><dt>Saved</dt><dd>{money.format(flow.saved / 100)}</dd></div>
          <div className="flow-summary-net"><dt>Net cash flow</dt><dd className={net >= 0 ? 'good' : 'bad'}>{money.format(net / 100)}</dd></div>
          <div><dt>Cash on hand</dt><dd>{money.format(m.cash_cents / 100)}</dd></div>
        </dl>
      </div>

      <details className="metric-details">
        <summary><span>Explore {indicators.length} health indicators</span><span className="small muted">Savings, debt & resilience</span></summary>
        <div className="indicators">
          {indicators.map(([key, i]) => (
            <div className={`indicator t-${tone(i.score)}`} key={key} title={i.note}>
              <span className="indicator-label">{i.label}</span><b>{i.display}</b>
              <div className="bar-track"><div className={`bar-fill f-${tone(i.score)}`} style={{ transform: `scaleX(${i.score / 100})` }} /></div>
              <p className="small muted">{i.note}</p>
            </div>
          ))}
        </div>
        {missing.length > 0 && <p className="muted small">Not scored yet (no data): {missing.map(i => i.label.toLowerCase()).join(', ')}.</p>}
      </details>
    </section>
  )
}
