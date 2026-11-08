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
