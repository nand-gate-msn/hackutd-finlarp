export const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const compact = (n) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: Math.abs(n) >= 10000 ? 'compact' : 'standard',
    maximumFractionDigits: Math.abs(n) >= 10000 ? 1 : 0,
  }).format(n)
export const fmtDate = (d) => (d ? new Date(d + 'T00:00:00').toLocaleDateString() : '—')
export const titleCase = (s) => (s ? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '—')

// Shared by the copilot sidebar and the graph's problem panel
export const pct = (x) => (x > 0 && x < 0.005 ? '<1%' : `${Math.round(x * 100)}%`)
export const pts = (n) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(Math.round(n * 10) / 10)}`
export const score = (x) => Math.round(x)
// a suggestion counts as accepted while a saved rule matches it (same accounts, same percent)
export const ruleKey = (r) => `${r.from_alias}|${r.to_alias}|${Number(r.percent)}`
