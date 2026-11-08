import { useEffect, useState } from 'react'
import './App.css'
import Advisor from './Advisor'
import GraphView from './GraphView'
import Metrics from './Metrics'
import { fmtDate, money, titleCase } from './format'

function Stat({ label, value, tone }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${tone ?? ''}`}>{money.format(value)}</span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="section">
      <h4>{title}</h4>
      {children}
    </div>
  )
}

function AccountCard({ account }) {
  const { purchases, bills, deposits, spending_by_category: cats } = account
  const maxCat = Math.max(...Object.values(cats), 1)

  return (
    <article className="card">
      <header className="card-head">
        <div>
          <h3>{account.alias}</h3>
          <span className="badge">{titleCase(account.type)}</span>
        </div>
        <span className="balance">{money.format(account.balance)}</span>
      </header>

      <div className="mini-stats">
        <span>{deposits.count}&nbsp;deposits · {money.format(deposits.total)}</span>
        <span>{purchases.count}&nbsp;purchases · {money.format(purchases.total)}</span>
        <span>{bills.count}&nbsp;bills · {money.format(bills.total)}</span>
      </div>

      {Object.keys(cats).length > 0 && (
        <Section title="Spending by category">
          {Object.entries(cats).map(([name, total]) => (
            <div className="bar-row" key={name}>
              <span className="bar-name" title={name}>{name}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(total / maxCat) * 100}%` }} />
              </div>
              <span className="bar-amt">{money.format(total)}</span>
            </div>
          ))}
        </Section>
      )}

      {bills.items.length > 0 && (
        <Section title="Bills">
          <table>
            <tbody>
              {bills.items.map((b, i) => (
                <tr key={i}>
                  <td>{b.payee}</td>
                  <td className="muted">{titleCase(b.status)}</td>
                  <td className="muted">{fmtDate(b.due)}</td>
                  <td className="num">{money.format(b.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {purchases.recent.length > 0 && (
        <Section title="Recent purchases">
          <table>
            <tbody>
              {purchases.recent.map((p, i) => (
                <tr key={i}>
                  <td>{p.description}</td>
                  <td className="muted">{fmtDate(p.date)}</td>
                  <td className="num">{money.format(p.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </article>
  )
}

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [healthTick, setHealthTick] = useState(0) // bumps when a decision changes the score
  const [projection, setProjection] = useState(null) // what the copilot's answer adds to the graph
  const [rules, setRules] = useState([]) // accepted changes, newest first

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/overview', { signal: controller.signal })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(body.detail ?? `Request failed (${res.status})`)
        setData(body)
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setError(err.message)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  // The accepted changes live on the server (they survive a reload); refetch whenever a decision changes them.
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/rules', { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : []))
      .then((list) => setRules(list.filter((r) => r.status === 'active')))
      .catch(() => {})
    return () => controller.abort()
  }, [healthTick])

  return (
    <div className="shell">
    <main className="app">
      <header className="page-head">
        <h1>Cash Flow Copilot</h1>
        <p>
          {data
            ? `Last ${data.period.days}\u00a0days (to ${fmtDate(data.period.end)}) · source: ${data.source}. `
            : ''}
          Account IDs and numbers stay on the server; the AI only sees anonymous summaries.
        </p>
      </header>

      {loading && <p className="state">Loading accounts…</p>}
      {error && <p className="state error">Couldn’t load data: {error}</p>}

      {data && (
        <>
          <section className="stats">
            <Stat label="Total balance" value={data.totals.balance} />
            <Stat label="Deposits" value={data.totals.deposits} tone="good" />
            <Stat label="Purchases" value={data.totals.purchases} tone="bad" />
            <Stat label="Bills" value={data.totals.bills} tone="bad" />
          </section>

          <GraphView
            projection={projection}
            refresh={healthTick}
            onChoice={(choice) => setProjection((p) => (p ? { ...p, choice } : p))}
            onDecision={() => setHealthTick((t) => t + 1)}
          />
          <Metrics refresh={healthTick} />

          <h2 className="section-title">Accounts</h2>
          {data.accounts.length === 0 ? (
            <p className="state">This customer has no accounts yet.</p>
          ) : (
            <section className="grid">
              {data.accounts.map((a) => (
                <AccountCard key={a.alias} account={a} />
              ))}
            </section>
          )}
        </>
      )}
    </main>
    <aside className="sidebar">
      <Advisor rules={rules} choice={projection?.choice ?? null} onDecision={() => setHealthTick((t) => t + 1)} onProject={setProjection} />
    </aside>
    </div>
  )
}
