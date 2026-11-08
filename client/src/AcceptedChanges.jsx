import { useState } from 'react'
import { post, when } from './api'
import Modal from './Modal'
import { money } from './format'

const score = (x) => Math.round(x)

/**
 * "Changes accepted": a one-line bar that shows only the most recent change; clicking it opens the full
 * history. Each change can be undone, and any point in the history can be restored ("revert to here"),
 * like rewinding a conversation: everything accepted after that point is undone.
 */
export default function AcceptedChanges({ rules, scenario, onChanged }) {
  const [open, setOpen] = useState(false)
  const latest = rules[0]
  return (
    <>
      <button
        type="button"
        className={`accepted-bar ${latest ? '' : 'empty'}`}
        onClick={() => latest && setOpen(true)}
        disabled={!latest}
        aria-haspopup="dialog"
      >
        <span className="accepted-icon" aria-hidden="true">✓</span>
        <span className="accepted-text">
          <span className="accepted-label">Changes accepted{latest ? <em>{rules.length}</em> : null}</span>
          <span className="accepted-latest">{latest ? latest.title : 'None yet. Accept a suggestion to start.'}</span>
        </span>
        {latest && <span className="accepted-chevron" aria-hidden="true">›</span>}
      </button>
      {open && rules.length > 0 && (
        <HistoryModal rules={rules} scenario={scenario} onChanged={onChanged} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

function HistoryModal({ rules, scenario, onChanged, onClose }) {
  const [confirm, setConfirm] = useState(null) // { to: ruleId | null }
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const run = async (fn, summarize, emptiesList = false) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      setMessage(summarize(r))
      setConfirm(null)
      onChanged?.()
      if (emptiesList) onClose() // nothing left to show
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  const healthLine = (r) =>
    r.health ? ` Financial health ${score(r.health.before.score)} → ${score(r.health.after.score)}.` : ''

  const undo = (rule) =>
    run(() => post(`/api/undo/${rule.id}`, { scenario }), (r) => `Undid “${rule.title}”.${healthLine(r)}`, rules.length === 1)
  const revert = (toId) =>
    run(
      () => post('/api/revert', { to_rule_id: toId, scenario }),
      (r) => `Reverted ${r.reverted.length} change${r.reverted.length === 1 ? '' : 's'}.${healthLine(r)}`,
      toId === null,
    )

  const laterThan = (i) => rules.slice(0, i) // newer than rules[i]: the ones a revert to rules[i] would undo

  return (
    <Modal title="Changes accepted" onClose={onClose} size="md">
      <p className="muted small">
        Newest first. Undo removes one change; “Revert to here” restores your finances to how they were right after
        that change and undoes everything accepted later.
      </p>
      <div className="sr-only" aria-live="polite">{message}</div>
      {message && <p className="notice ok">{message}</p>}
      {error && <p className="notice bad">{error}</p>}

      <ol className="timeline">
        {rules.map((rule, i) => {
          const later = laterThan(i)
          const asking = confirm?.to === rule.id
          return (
            <li key={rule.id} className={`tl-item ${i === 0 ? 'current' : ''}`}>
              <span className="tl-dot" aria-hidden="true" />
              <div className="tl-main">
                <div className="tl-title">
                  <b>{rule.title}</b>
                  {i === 0 && <span className="tl-tag">Latest</span>}
                </div>
                <div className="muted small">
                  {rule.from_label} → {rule.to_label}
                  {rule.amount_cents ? ` · about ${money.format(rule.amount_cents / 100)} per paycheck` : ''}
                </div>
                <div className="muted small">Accepted {when(rule.created_at)}</div>
                <div className="tl-actions">
                  <button className="btn ghost sm" disabled={busy} onClick={() => undo(rule)}>Undo</button>
                  {later.length > 0 && (
                    <button className="btn ghost sm" disabled={busy} onClick={() => setConfirm({ to: rule.id })}>
                      Revert to here
                    </button>
                  )}
                </div>
                {asking && (
                  <div className="confirm" role="alert">
                    <p>
                      This undoes {later.length} later change{later.length === 1 ? '' : 's'}
                      {': '}{later.map((l) => l.title).join(', ')}. Your finances return to how they were right after
                      this change.
                    </p>
                    <button className="btn sm" disabled={busy} onClick={() => revert(rule.id)}>
                      {busy ? 'Reverting…' : 'Revert'}
                    </button>
                    <button className="btn ghost sm" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button>
                  </div>
                )}
              </div>
            </li>
          )
        })}
        <li className="tl-item start">
          <span className="tl-dot" aria-hidden="true" />
          <div className="tl-main">
            <div className="tl-title"><b>Start</b></div>
            <div className="muted small">Your finances before any accepted change.</div>
            <div className="tl-actions">
              <button className="btn ghost sm" disabled={busy} onClick={() => setConfirm({ to: null })}>Revert to start</button>
            </div>
            {confirm?.to === null && (
              <div className="confirm" role="alert">
                <p>This undoes all {rules.length} accepted change{rules.length === 1 ? '' : 's'}.</p>
                <button className="btn sm" disabled={busy} onClick={() => revert(null)}>{busy ? 'Reverting…' : 'Revert everything'}</button>
                <button className="btn ghost sm" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button>
              </div>
            )}
          </div>
        </li>
      </ol>
    </Modal>
  )
}
