import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createSpring } from './motion'

const mobileQuery = () => window.matchMedia('(max-width: 1000px)')
const subscribe = callback => {
  const query = mobileQuery()
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}
const getMobile = () => mobileQuery().matches
const SNAP_LABELS = ['Closed', 'Half height', 'Expanded']

export default function CopilotPanel({ children, width = 400, onWidthChange }) {
  const mobile = useSyncExternalStore(subscribe, getMobile)
  const [snap, setSnap] = useState(0)
  const panel = useRef(null), launcher = useRef(null), motion = useRef(null)
  const resizing = useRef(null)
  const maxWidth = () => Math.max(320, Math.min(640, window.innerWidth - 600))
  const resizeTo = next => onWidthChange?.(Math.round(Math.max(320, Math.min(maxWidth(), next))))
  const height = useRef(0), currentSnap = useRef(0), drag = useRef(null)
  const snapY = point => point === 0 ? height.current + 24 : point === 1 ? height.current * .45 : 0

  useLayoutEffect(() => {
    const el = panel.current
    height.current = el.getBoundingClientRect().height
    motion.current = createSpring({ y: height.current + 24 }, value => el.style.setProperty('--sheet-y', `${value.y}px`))
    motion.current.set({ y: height.current + 24 })
    const ro = new ResizeObserver(([entry]) => {
      height.current = entry.borderBoxSize?.[0]?.blockSize ?? el.getBoundingClientRect().height
      if (!drag.current) motion.current.to({ y: snapY(currentSnap.current) })
    })
    ro.observe(el)
    return () => { ro.disconnect(); motion.current.destroy() }
  }, [])

  useEffect(() => {
    if (!mobile || snap === 0) return
    const main = document.querySelector('main'), wasInert = main.inert, overflow = document.body.style.overflow
    main.inert = true
    document.body.style.overflow = 'hidden'
    return () => { main.inert = wasInert; document.body.style.overflow = overflow }
  }, [mobile, snap])

  const settle = (point, velocity = 0) => {
    currentSnap.current = point
    setSnap(point)
    // A deliberate press uses critical damping; only a flick can carry momentum.
    motion.current.to({ y: snapY(point) }, { y: velocity }, { damping: Math.abs(velocity) > 80 ? .8 : 1 })
    if (point === 0) requestAnimationFrame(() => launcher.current?.focus({ preventScroll: true }))
  }
  const open = () => {
    settle(1)
    requestAnimationFrame(() => panel.current.querySelector('input')?.focus({ preventScroll: true }))
  }
  const onPointerDown = e => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    motion.current.stop()
    drag.current = { id: e.pointerId, start: e.clientY, y: motion.current.value.y, samples: [{ y: e.clientY, t: e.timeStamp }] }
  }
  const onPointerMove = e => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    const raw = d.y + e.clientY - d.start
    const bounded = Math.max(0, Math.min(height.current + 24, raw)), delta = raw - bounded
    motion.current.set({ y: bounded + delta * .35 / (1 + Math.abs(delta) / Math.max(1, height.current)) })
    d.samples.push({ y: e.clientY, t: e.timeStamp })
    d.samples = d.samples.filter(s => e.timeStamp - s.t <= 100)
  }
  const onPointerUp = e => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (e.type !== 'pointerup') { settle(currentSnap.current); return }
    const first = d.samples[0], last = d.samples[d.samples.length - 1]
    const velocity = last.t > first.t && e.timeStamp - last.t < 100 ? Math.max(-2400, Math.min(2400, (last.y - first.y) * 1000 / (last.t - first.t))) : 0
    const projected = motion.current.value.y + velocity * .18
    const point = [0, 1, 2].reduce((best, p) => Math.abs(snapY(p) - projected) < Math.abs(snapY(best) - projected) ? p : best, currentSnap.current)
    settle(point, velocity)
  }
  const onKeyDown = e => {
    if (!mobile || snap === 0 || !panel.current.contains(e.target)) return
    if (e.key === 'Escape') { e.stopPropagation(); settle(0) }
    if (e.key === 'Tab') {
      const items = [...panel.current.querySelectorAll('button, input, [tabindex="0"]')].filter(el => !el.disabled)
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }
  return (
    <>
      <button ref={launcher} className="btn copilot-launcher" onClick={open} aria-haspopup="dialog" aria-expanded={snap > 0} hidden={mobile && snap > 0}>Ask the copilot</button>
      <div className="sheet-dimmer" data-open={mobile && snap > 0} onClick={() => settle(0)} aria-hidden="true" />
      <aside ref={panel} className="sidebar mobile-sheet" data-snap={snap} role={mobile ? 'dialog' : undefined} aria-modal={mobile && snap > 0 ? true : undefined} aria-label="Copilot" aria-hidden={mobile && snap === 0 ? true : undefined} inert={mobile && snap === 0} onKeyDown={onKeyDown}>
        <div className="sidebar-resizer" role="separator" aria-label="Resize copilot" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={maxWidth()} aria-valuenow={Math.min(width, maxWidth())} tabIndex={mobile ? -1 : 0}
          title="Drag to resize. Use left and right arrow keys when focused."
          onPointerDown={e => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); resizing.current = { x: e.clientX, width: panel.current.getBoundingClientRect().width + 16 } }}
          onPointerMove={e => { if (resizing.current) resizeTo(resizing.current.width + resizing.current.x - e.clientX) }}
          onPointerUp={() => { resizing.current = null }} onPointerCancel={() => { resizing.current = null }} onLostPointerCapture={() => { resizing.current = null }}
          onDoubleClick={() => resizeTo(400)}
          onKeyDown={e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) { e.preventDefault(); resizeTo(e.key === 'Home' ? 320 : e.key === 'End' ? maxWidth() : Math.min(width, maxWidth()) + (e.key === 'ArrowLeft' ? 24 : -24)) } }} />
        <div className="sheet-controls">
          <button className="sheet-grip" role="slider" aria-label="Copilot sheet height" aria-valuemin={0} aria-valuemax={2} aria-valuenow={snap} aria-valuetext={SNAP_LABELS[snap]} aria-orientation="vertical" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onLostPointerCapture={onPointerUp}
            onKeyDown={e => {
              if (['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) {
                e.preventDefault()
                settle(e.key === 'Home' ? 0 : e.key === 'End' ? 2 : Math.max(0, Math.min(2, snap + (e.key === 'ArrowUp' ? 1 : -1))))
              }
            }}><span aria-hidden="true" /></button>
          <button className="sheet-close" onClick={() => settle(0)}>Close</button>
        </div>
        {children}
      </aside>
    </>
  )
}
