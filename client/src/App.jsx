import { useEffect, useState } from 'react'
import './App.css'
import Advisor from './Advisor'
import CopilotPanel from './CopilotPanel'
import GraphView from './GraphView'
import Metrics from './Metrics'
import { fmtDate, money, titleCase } from './format'

function Stat({ label, value, tone, hint, primary = false }) {
  return (
    <div className={`stat ${primary ? 'stat-primary' : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{money.format(value)}</span>
      <span className={`stat-hint ${tone ?? ''}`}>{hint}</span>
    </div>
  )
}

function Section({ title, children, className = '' }) {
  return (
    <div className={`section ${className}`}>
      <h4>{title}</h4>
      {children}
    </div>
  )
}

function AccountCard({ account, totalBalance, days }) {
  const { purchases, bills, deposits, spending_by_category: cats, transfers } = account
  const categories = Object.entries(cats).sort((a, b) => b[1] - a[1])
  const maxCat = Math.max(...categories.map(([, value]) => value), 1)
  const share = totalBalance > 0 ? account.balance / totalBalance : 0
  const hasSpending = categories.length > 0 || bills.items.length > 0 || purchases.recent.length > 0
  const orderedBills = [...bills.items].sort((a, b) => (a.due ?? '9999').localeCompare(b.due ?? '9999') || a.payee.localeCompare(b.payee))

  return (
    <article className={`card account-card ${hasSpending ? '' : 'account-card-quiet'}`}>
      <header className="card-head">
        <div className="account-title">
          <span className="account-alias">{account.alias}</span>
          <h3>{titleCase(account.type)} account</h3>
        </div>
        <div className="account-balance">
          <span className="small muted">Account balance</span>
          <span className="balance">{money.format(account.balance)}</span>
        </div>
      </header>
      <div className="account-layout">
        <div className="account-overview">
          <div className="account-share">
            <div><span>Share of total cash</span><b>{Math.round(share * 100)}%</b></div>
            <div className="bar-track"><div className="bar-fill" style={{ transform: `scaleX(${Math.max(0, Math.min(1, share))})` }} /></div>
          </div>
          <dl className="account-summary">
            <div><dt>Deposits <span>{deposits.count} received</span></dt><dd>{money.format(deposits.total)}</dd></div>
            {purchases.count > 0 && <div><dt>Purchases <span>{purchases.count} transactions</span></dt><dd>{money.format(purchases.total)}</dd></div>}
            {bills.count > 0 && <div><dt>Bill payments <span>{bills.count} paid</span></dt><dd>{money.format(bills.total)}</dd></div>}
            <div><dt>Transfers in</dt><dd>{money.format(transfers?.in ?? 0)}</dd></div>
            <div><dt>Transfers out</dt><dd>{money.format(transfers?.out ?? 0)}</dd></div>
          </dl>
          <p className="small muted">Activity over the last {days}&nbsp;days.</p>
        </div>
        <div className="account-content">
          {categories.length > 0 && (
            <Section title="Spending by category">
              {categories.map(([name, total]) => (
                <div className="bar-row" key={name}>
                  <span className="bar-name" title={name}>{titleCase(name)}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ transform: `scaleX(${total / maxCat})` }} /></div>
                  <span className="bar-amt">{money.format(total)}</span>
                </div>
              ))}
            </Section>
          )}
          {purchases.recent.length > 0 && (
            <Section title="Recent purchases">
              <div className="account-table-wrap"><table>
                <thead><tr><th>Merchant</th><th>Date</th><th className="num">Amount</th></tr></thead>
                <tbody>{[...purchases.recent].sort((a, b) => b.date.localeCompare(a.date)).map((item, i) => (
                  <tr key={i}><td>{item.description}</td><td className="muted">{fmtDate(item.date)}</td><td className="num">{money.format(item.amount)}</td></tr>
                ))}</tbody>
              </table></div>
            </Section>
          )}
          {orderedBills.length > 0 && (
            <Section title="Upcoming bills" className="account-section-wide">
              <div className="account-table-wrap"><table>
                <thead><tr><th>Payee</th><th>Next due</th><th>Status</th><th className="num">Amount</th></tr></thead>
                <tbody>{orderedBills.map((bill, i) => (
                  <tr key={i}><td>{bill.payee}</td><td className="muted">{fmtDate(bill.due)}</td><td><span className="badge">{titleCase(bill.status)}</span></td><td className="num">{money.format(bill.amount)}</td></tr>
                ))}</tbody>
              </table></div>
            </Section>
          )}
          {!hasSpending && (
            <div className="account-quiet-state">
              <span className="badge badge-accent">{titleCase(account.type)}</span>
              <h4>Your balance at a glance</h4>
              <p>Deposits and transfers are summarized alongside this account. No purchases or bill payments were recorded in this period.</p>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

export default function App() {
  const [copilotWidth, setCopilotWidth] = useState(400)
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
    <div className="shell" style={{ '--copilot-width': `${copilotWidth}px` }}>
    <div className="ambient" aria-hidden="true" />
    <main className="app">
      <header className="page-head">
        <div className="brand-lockup">
          <span className="eyebrow">Your financial overview</span>
          <h1>Fin<span>LARP</span></h1>
          <p>A clearer view of your money. More confidence in your next move.</p>
        </div>
        <div className="snapshot-meta">
          {data && <><span className="badge badge-accent">{data.period.days}-day snapshot</span><span className="small muted">Through {fmtDate(data.period.end)}</span></>}
          <details className="snapshot-details"><summary>Data & privacy</summary><p>Account IDs and numbers stay on the server; the AI only sees anonymous summaries.{data?.source && ` Data source: ${data.source}.`}</p></details>
        </div>
      </header>

      {loading && <p className="state">Loading accounts…</p>}
      {error && <p className="state error">Couldn’t load data: {error}</p>}

      {data && (
        <>
          <section className="stats">
            <Stat primary label="Total balance" value={data.totals.balance} hint={`Across ${data.accounts.length} accounts`} />
            <Stat label="Deposits" value={data.totals.deposits} tone="good" hint="Money coming in" />
            <Stat label="Purchases" value={data.totals.purchases} hint="Everyday spending" />
            <Stat label="Bills" value={data.totals.bills} hint="Paid during this period" />
          </section>

          <GraphView
            projection={projection}
            refresh={healthTick}
            onChoice={(choice) => setProjection((p) => (p ? { ...p, choice } : p))}
            onDecision={() => setHealthTick((t) => t + 1)}
          />
          <Metrics refresh={healthTick} />

          <div className="accounts-heading"><div><span className="eyebrow">Your accounts</span><h2 className="section-title">Balances & activity</h2></div><span className="small muted">{data.accounts.length} accounts · last {data.period.days}&nbsp;days</span></div>
          {data.accounts.length === 0 ? (
            <p className="state">This customer has no accounts yet.</p>
          ) : (
            <section className="accounts-list">
              {data.accounts.map((a) => (
                <AccountCard key={a.alias} account={a} totalBalance={data.totals.balance} days={data.period.days} />
              ))}
            </section>
          )}
        </>
      )}
    </main>
    <CopilotPanel width={copilotWidth} onWidthChange={setCopilotWidth}>
      <Advisor rules={rules} choice={projection?.choice ?? null} onDecision={() => setHealthTick((t) => t + 1)} onProject={setProjection} />
    </CopilotPanel>
    </div>
  )
}
