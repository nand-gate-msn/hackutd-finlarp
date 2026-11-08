import { useRef, useState } from 'react'
import Modal from './Modal'
import Presence from './Presence'
import { post } from './api'
import { pct, pts, score } from './format'

export function Proposal({ p, scenario, base, picked, onPick, onAccepted }) {
  const [reviewing, setReviewing] = useState(false)
  const inFlight = useRef(false)
  const [state, setState] = useState({ phase: 'idle' }) // idle | busy | error
  const accept = async () => {
    if (inFlight.current || state.phase === 'saved') return
    inFlight.current = true
    setState({ phase: 'busy' })
    try {
      const r = await post('/api/accept', { from_alias: p.from_alias, to_alias: p.to_alias, percent: p.percent, scenario })
      setState({ phase: 'saved' })
      setReviewing(false)
      onAccepted(r, p)
    } catch (err) {
      setState({ phase: 'error', message: err.message })
    } finally {
      inFlight.current = false
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
        <span className="pick-hint">{picked ? 'Preview shown on the graph · not saved' : 'Preview on the graph'}</span>
      </button>
      <div className="proposal-actions">
        <button type="button" className="btn sm" onClick={() => setReviewing(true)} disabled={state.phase === 'busy' || state.phase === 'saved'}>
          {state.phase === 'saved' ? 'Saved' : 'Review change'}
        </button>
      </div>
      <Presence show={reviewing} className="modal-host">
        {reviewing && <Modal title="Review savings change" onClose={() => { if (state.phase !== 'busy') setReviewing(false) }}>
          <p>Save <b>{p.percent}% of each paycheck</b> by moving money from <b>{p.from_label}</b> to <b>{p.to_label}</b> in your forecast.</p>
          <p className="muted">This saves a rule for future forecasts. It does not move money at your bank. Nothing is saved if you cancel.</p>
          {state.phase === 'error' && <p className="notice bad" role="alert">{state.message}</p>}
          <div className="review-actions">
            <button type="button" className="btn ghost" disabled={state.phase === 'busy'} onClick={() => setReviewing(false)}>Cancel</button>
            <button type="button" className="btn" disabled={state.phase === 'busy'} onClick={accept}>{state.phase === 'busy' ? 'Saving…' : 'Confirm & save change'}</button>
          </div>
        </Modal>}
      </Presence>
    </li>
  )
}

