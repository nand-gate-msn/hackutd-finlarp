import { useEffect, useState } from 'react'
import { PresenceState } from './presenceState'

// Retain the last live content through exit. Reopening keeps the live transition value.
export default function Presence({ show, children, as: Tag = 'div', className = '', style, ...props }) {
  const [state, setState] = useState({ show, content: children, retained: show, entered: false })
  if (show !== state.show || (show && children !== state.content)) {
    setState({ ...state, show, content: show ? children : state.content, retained: show || state.retained })
  }
  useEffect(() => {
    let a, b, timer
    if (show) {
      a = requestAnimationFrame(() => { b = requestAnimationFrame(() => setState(s => ({ ...s, entered: true }))) })
    } else {
      const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 100 : 320
      timer = setTimeout(() => setState(s => ({ ...s, retained: false, entered: false })), duration)
    }
    return () => { cancelAnimationFrame(a); cancelAnimationFrame(b); clearTimeout(timer) }
  }, [show])
  if (!show && !state.retained) return null
  const active = Boolean(show && state.entered)
  return (
    <PresenceState value={active}>
      <Tag {...props} className={`presence ${className}`} style={style} data-state={active ? 'open' : 'closed'} inert={!show}>
        {show ? children : state.content}
      </Tag>
    </PresenceState>
  )
}
