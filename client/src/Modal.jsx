import { useEffect, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { usePresenceState } from './presenceState'

// Open dialogs, oldest first: only the top-most one answers to Esc and Tab.
const stack = []

// A dialog that covers either the whole page (`within="page"`) or just the component it sits in
// (`within="container"`, e.g. the graph). Esc and the backdrop close it, focus moves in and returns on close,
// and Tab stays inside while it is open.
export default function Modal({ title, onClose, within = 'page', size = 'md', children, actions = null }) {
  const active = usePresenceState()
  const dialog = useRef(null)
  const opener = useRef(null)
  const token = useRef({})

  useLayoutEffect(() => {
    opener.current = document.activeElement
    const rect = opener.current?.getBoundingClientRect()
    const bounds = dialog.current?.getBoundingClientRect()
    if (rect && bounds) dialog.current.style.transformOrigin = `${rect.left + rect.width / 2 - bounds.left}px ${rect.top + rect.height / 2 - bounds.top}px`
    const me = token.current
    stack.push(me)
    return () => {
      stack.splice(stack.indexOf(me), 1)
      opener.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    if (active) dialog.current?.querySelector('[data-autofocus]')?.focus()
    const onKey = (e) => {
      if (!active || stack[stack.length - 1] !== token.current) return // a dialog on top of this one is in charge
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      } else if (e.key === 'Tab' && dialog.current) {
        const items = [...dialog.current.querySelectorAll('button, [href], input, [tabindex]:not([tabindex="-1"])')].filter(
          (el) => !el.disabled,
        )
        if (!items.length) return
        const first = items[0], last = items[items.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, active])

  const view = (
    <div className={`modal modal-${within}`} data-state={active ? 'open' : 'closed'} inert={!active} onPointerDown={(e) => e.stopPropagation()}>
      <div className="modal-backdrop" onClick={onClose} />
      <div className={`modal-dialog modal-${size}`} role="dialog" aria-modal="true" aria-label={title} ref={dialog}>
        <header className="modal-head">
          <h3>{title}</h3>
          <div className="modal-actions">
            {actions}
            <button className="modal-close" onClick={onClose} aria-label={`Close ${title}`} data-autofocus>×</button>
          </div>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
  // a page-wide dialog is drawn at the top of the document, so no sticky/positioned ancestor can trap it
  return within === 'page' ? createPortal(view, document.body) : view
}
