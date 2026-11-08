import { useState } from 'react'
import { post } from './api'
import { pct, pts, score } from './format'

export function Proposal({ p, scenario, base, picked, onPick, onAccepted }) {
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
            Overdraft chance with this change: {pct(p.forecast.scenario.share_below_zero)}{base != null && ` (now ${pct(base)})`}
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

