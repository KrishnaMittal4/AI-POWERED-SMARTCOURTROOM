import { useEffect, useRef } from 'react'

const KEYS = [
  ['/', 'Focus the question box'],
  ['n', 'Start a new research'],
  ['j / k', 'Open the next / previous question in history'],
  ['← → Home End', 'Move between tabs'],
  ['↑ ↓', 'Move through the history list'],
  ['Esc', 'Close this window, the menu, or the options'],
  ['?', 'Show this list'],
]

export default function Shortcuts({ onClose }) {
  const ref = useRef(null)
  const closeRef = useRef(null)

  useEffect(() => {
    const prev = document.activeElement
    closeRef.current?.focus()
    return () => prev?.focus?.()
  }, [])

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
    if (e.key !== 'Tab') return
    const f = ref.current.querySelectorAll('button, [href], input')
    if (!f.length) return
    const first = f[0], last = f[f.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }

  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="sc-title" ref={ref} onKeyDown={onKeyDown}>
        <h2 id="sc-title">Keyboard shortcuts</h2>
        <dl className="sc-list">
          {KEYS.map(([k, d]) => (
            <div key={k}><dt><kbd>{k}</kbd></dt><dd>{d}</dd></div>
          ))}
        </dl>
        <p className="muted">Shortcuts are off while you are typing in a box.</p>
        <button className="btn-primary" ref={closeRef} onClick={onClose}>Close</button>
      </div>
    </div>
  )
}
