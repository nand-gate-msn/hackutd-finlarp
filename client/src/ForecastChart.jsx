import { useState } from 'react'
import { compact as money } from './format'

// A fan chart: for each layer, the median balance as a line and the 10th-90th percentile range as a band.
// It is the usual way to show a Monte Carlo cash-flow forecast: where the balance is likely to go, how
// uncertain that is, and whether the band dips under the red zero line (an overdraft).
//
// layers: [{ key: 'baseline' | 'scenario' | 'suggestion', label, band: { p10, p50, p90 } }] (cents per day)
// small:  the compact version inside the graph's card (no axes, no hover)
// start:  ISO date of day 0, used for the axis and the hover readout of the full-size chart

function niceStep(raw) {
  const pow = 10 ** Math.floor(Math.log10(raw || 1))
  const f = raw / pow
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow
}

const dayLabel = (start, i) =>
  start ? new Date(`${start}T00:00:00`).getTime() + i * 86400000 : null
const fmtDay = (ms) => new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

export default function ForecastChart({ layers, width, height, x = 0, y = 0, small = false, start = null }) {
  const [hoverIdx, setHoverIdx] = useState(null)
  const shown = layers.filter((l) => l?.band?.p50?.length)
  if (!shown.length || width <= 0 || height <= 0) return null
  const n = shown[0].band.p50.length
  const values = shown.flatMap((l) => [...l.band.p10, ...l.band.p90])
  const rawLo = Math.min(0, ...values), rawHi = Math.max(0, ...values)
  const stepDollars = niceStep((rawHi - rawLo) / 100 / 4)
  const lo = small ? rawLo : Math.floor(rawLo / 100 / stepDollars) * stepDollars * 100
  const hi = small ? rawHi : Math.ceil(rawHi / 100 / stepDollars) * stepDollars * 100
  const pad = small ? { l: 4, r: 4, t: 4, b: 4 } : { l: 64, r: 16, t: 14, b: 30 }
  const X = (i) => pad.l + (i / Math.max(1, n - 1)) * (width - pad.l - pad.r)
  const Y = (v) => pad.t + ((hi - v) / (hi - lo || 1)) * (height - pad.t - pad.b)
  const line = (arr) => arr.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')
  const band = (b) =>
    `${line(b.p90)}${b.p10.map((_, i) => n - 1 - i).map((i) => `L${X(i).toFixed(1)},${Y(b.p10[i]).toFixed(1)}`).join('')}Z`
  const ends = shown.map((l) => `${l.label} ends near ${money(l.band.p50[n - 1] / 100)}`).join('; ')

  const yTicks = []
  if (!small) for (let v = lo; v <= hi + 1; v += stepDollars * 100) yTicks.push(v)
  const xTicks = small ? [] : [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (n - 1)))

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - r.left - pad.l) / (r.width - pad.l - pad.r)
    setHoverIdx(Math.min(n - 1, Math.max(0, Math.round(frac * (n - 1)))))
  }

  return (
    <svg x={x} y={y} width={width} height={height} className={`fchart ${small ? '' : 'fchart-full'}`} role="img"
      aria-label={`Projected balance over the next ${n} days. ${ends}.`}>
      {!small && (
        <g className="faxis">
          {yTicks.map((v) => (
            <g key={v}>
              <line className="fgrid" x1={pad.l} x2={width - pad.r} y1={Y(v)} y2={Y(v)} />
              <text x={pad.l - 8} y={Y(v)} textAnchor="end" dominantBaseline="central">{money(v / 100)}</text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
              {start ? fmtDay(dayLabel(start, i)) : i === 0 ? 'Today' : `+${i + 1}d`}
            </text>
          ))}
        </g>
      )}
      {shown.map((l) => <path key={`b-${l.key}`} className={`fband f-${l.key}`} d={band(l.band)} />)}
      <line className="fzero" x1={pad.l} x2={width - pad.r} y1={Y(0)} y2={Y(0)} />
      {!small && <text className="fzero-label" x={pad.l + 4} y={Y(0) - 6}>$0 · below this is an overdraft</text>}
      {shown.map((l) => <path key={`l-${l.key}`} className={`fline f-${l.key}`} d={line(l.band.p50)} />)}

      {!small && (
        <>
          {hoverIdx != null && (
            <g className="fhover" pointerEvents="none">
              <line x1={X(hoverIdx)} x2={X(hoverIdx)} y1={pad.t} y2={height - pad.b} />
              {shown.map((l) => <circle key={l.key} className={`fdot f-${l.key}`} cx={X(hoverIdx)} cy={Y(l.band.p50[hoverIdx])} r={4} />)}
              <Readout i={hoverIdx} shown={shown} x={X(hoverIdx)} width={width} start={start} />
            </g>
          )}
          <rect className="fcatch" x={pad.l} y={pad.t} width={width - pad.l - pad.r} height={height - pad.t - pad.b}
            onPointerMove={onMove} onPointerLeave={() => setHoverIdx(null)} />
        </>
      )}
    </svg>
  )
}

function Readout({ i, shown, x, width, start }) {
  const w = 214, rowH = 17, h = 26 + rowH * shown.length
  const left = x + 14 + w > width ? x - 14 - w : x + 14
  const title = start ? fmtDay(dayLabel(start, i)) : `Day ${i + 1}`
  return (
    <g transform={`translate(${left} 16)`}>
      <rect className="ftip" width={w} height={h} rx={8} />
      <text className="ftip-title" x={10} y={17}>{title}</text>
      {shown.map((l, k) => (
        <g key={l.key} transform={`translate(10 ${32 + rowH * k})`}>
          <rect className={`fswatch f-${l.key}`} width={9} height={4} rx={2} y={-8} />
          <text className="ftip-label" x={15}>{l.label}</text>
          <text className="ftip-value" x={w - 20} textAnchor="end">{money(l.band.p50[i] / 100)}</text>
        </g>
      ))}
    </g>
  )
}
