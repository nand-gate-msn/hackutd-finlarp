import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

// Open dialogs, oldest first: only the top-most one answers to Esc and Tab.
const stack = []

// A dialog that covers either the whole page (`within="page"`) or just the component it sits in
// (`within="container"`, e.g. the graph). Esc and the backdrop close it, focus moves in and returns on close,
// and Tab stays inside while it is open.
export default function Modal({ title, onClose, within = 'page', size = 'md', children, actions = null }) {
  const dialog = useRef(null)
  const opener = useRef(null)
  const token = useRef({})

  useEffect(() => {
    opener.current = document.activeElement
    const me = token.current
    stack.push(me)
    dialog.current?.querySelector('[data-autofocus]')?.focus()
    return () => {
      stack.splice(stack.indexOf(me), 1)
      opener.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (stack[stack.length - 1] !== token.current) return // a dialog on top of this one is in charge
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
  }, [onClose])

  const view = (
    <div className={`modal modal-${within}`} onPointerDown={(e) => e.stopPropagation()}>
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
