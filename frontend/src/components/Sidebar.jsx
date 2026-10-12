import { useMemo, useState } from 'react'
import { timeAgo, tabKeys } from '../lib/utils.js'

export default function Sidebar({ history, activeId, onOpen, onNew, onToggleSave, onDelete, onClear, open, onClose }) {
  const [tab, setTab] = useState('recent')
  const [filter, setFilter] = useState('')

  const items = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return history
      .filter((h) => (tab === 'saved' ? h.saved : true))
      .filter((h) => !f || h.question.toLowerCase().includes(f))
  }, [history, tab, filter])

  return (
    <aside id="sidebar" className={`sidebar ${open ? 'open' : ''}`} aria-label="Research history">
      <button className="new-btn" onClick={() => { onNew(); onClose() }}>
        <span>＋</span>
        <span>New Research</span>
      </button>

      <div className="tabs" role="tablist" aria-label="History" onKeyDown={(e) => tabKeys(e, ['recent', 'saved'], tab, setTab, 'hs')}>
        <button role="tab" id="hs-tab-recent" aria-controls="hs-panel" aria-selected={tab === 'recent'} tabIndex={tab === 'recent' ? 0 : -1} onClick={() => setTab('recent')}>Recent</button>
        <button role="tab" id="hs-tab-saved" aria-controls="hs-panel" aria-selected={tab === 'saved'} tabIndex={tab === 'saved' ? 0 : -1} onClick={() => setTab('saved')}>
          Saved{history.some((h) => h.saved) ? ` (${history.filter((h) => h.saved).length})` : ''}
        </button>
      </div>

      <input
        className="side-search"
        type="search"
        placeholder="Search your questions"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        aria-label="Search your questions"
      />

      <ul
        className="history-list" id="hs-panel" role="tabpanel" aria-labelledby={`hs-tab-${tab}`}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
          const btns = [...e.currentTarget.querySelectorAll('.history-item')]
          const i = btns.indexOf(document.activeElement)
          if (i === -1) return
          e.preventDefault()
          btns[Math.min(btns.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus()
        }}
      >
        {items.length === 0 && (
          <li className="empty-note">
            {tab === 'saved' ? 'Star an answer to keep it here.' : history.length ? 'No question matches.' : 'Your questions will appear here.'}
          </li>
        )}
        {items.map((h) => (
          <li key={h.id} className={h.id === activeId ? 'active' : ''}>
            <button className="history-item" aria-current={h.id === activeId ? 'true' : undefined} onClick={() => { onOpen(h.id); onClose() }}>
              <span className="history-q">{h.question}</span>
              <span className="history-meta">{timeAgo(h.ts)}</span>
            </button>
            <button className={`icon-btn star ${h.saved ? 'on' : ''}`} onClick={() => onToggleSave(h.id)} aria-label={h.saved ? 'Remove from saved' : 'Save this answer'} title={h.saved ? 'Remove from saved' : 'Save'}>
              {h.saved ? '★' : '☆'}
            </button>
            <button className="icon-btn" onClick={() => onDelete(h.id)} aria-label="Delete from history" title="Delete">×</button>
          </li>
        ))}
      </ul>

      {history.length > 0 && (
        <button className="btn-quiet clear-btn" onClick={() => { if (window.confirm('Delete all saved history from this browser?')) onClear() }}>
          Clear history
        </button>
      )}
    </aside>
  )
}
