import { useEffect, useLayoutEffect, useRef } from 'react'
import { createSpring } from './motion'

export default function SegmentedControl({ values, value, onChange, label }) {
  const tray = useRef(null)
  const thumb = useRef(null)
  const spring = useRef(null)
  useLayoutEffect(() => {
    const selected = tray.current.querySelector('[aria-pressed="true"]')
    const initial = { x: selected.offsetLeft, width: selected.offsetWidth }
    spring.current = createSpring(initial, v => {
      thumb.current.style.transform = `translateX(${v.x}px)`
      thumb.current.style.width = `${v.width}px`
    })
    spring.current.set(initial)
    const measure = () => {
      const button = tray.current.querySelector('[aria-pressed="true"]')
      spring.current.to({ x: button.offsetLeft, width: button.offsetWidth })
    }
    const observer = new ResizeObserver(measure)
    observer.observe(tray.current)
    return () => { observer.disconnect(); spring.current.destroy() }
  }, [])
  useEffect(() => {
    const button = tray.current.querySelector('[aria-pressed="true"]')
    spring.current.to({ x: button.offsetLeft, width: button.offsetWidth })
  }, [value])
  return (
    <div className="seg" ref={tray} role="group" aria-label={label}>
      <span className="seg-thumb" ref={thumb} aria-hidden="true" />
      {values.map(v => <button key={v} aria-pressed={v === value} className={v === value ? 'on' : ''} onClick={() => onChange(v)}>{v}d</button>)}
    </div>
  )
}
