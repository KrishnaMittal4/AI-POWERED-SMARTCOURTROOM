import { useEffect, useState } from 'react'
import { parseSource } from '../lib/utils.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

function titleOf(r) {
  // Prefer the parsed party names; fall back to a readable filename.
  const t = r.case_name && !/^[\d\s]+(EN)?$/i.test(r.case_name) ? r.case_name : parseSource(r.source_file).title
  return t || r.source_file
}

/**
 * "Find similar cases" for one judgment. `target` = { sourceFile, title, text? }.
 * If a passage was supplied the user can switch between matching on that
 * passage or on the whole judgment. Results are one row per case.
 */
export default function SimilarModal({ target, onClose }) {
  const [basis, setBasis] = useState('passage')
  const [current, setCurrent] = useState(target)   // lets a result be used as the next starting point
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [openIdx, setOpenIdx] = useState(null)

  useEffect(() => { setCurrent(target); setBasis(target?.text ? 'passage' : 'document') }, [target])

  useEffect(() => {
    if (!current) return
    const ctl = new AbortController()
    setLoading(true); setError(null); setData(null); setOpenIdx(null)
    const usePassage = basis === 'passage' && current.text
    fetch(`${API_BASE}/similar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: ctl.signal,
      body: JSON.stringify({
        source_file: current.sourceFile,
        text: usePassage ? current.text.slice(0, 4000) : undefined,
        limit: 8,
      }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const b = await res.json().catch(() => ({}))
          throw new Error(typeof b.detail === 'string' ? b.detail : `Request failed (${res.status})`)
        }
        return res.json()
      })
      .then(setData)
      .catch((e) => { if (e.name !== 'AbortError') setError(e instanceof TypeError ? 'Cannot reach the API.' : e.message) })
      .finally(() => { if (!ctl.signal.aborted) setLoading(false) })
    return () => ctl.abort()
  }, [current, basis])

  useEffect(() => {
    if (!target) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [target, onClose])

  if (!target) return null
  const results = data?.results || []

  return (
    <div className="modal-scrim" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="similar-title">
      <div className="modal similar-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 id="similar-title" style={{ margin: 0 }}>Similar cases</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '13px' }}>
              Like: <b>{current.title}</b>
            </p>
          </div>
          <button className="btn-quiet close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {current.text && (
          <div className="similar-basis" role="group" aria-label="Match on">
            <span className="muted">Match on</span>
            <button className={`btn-quiet small ${basis === 'passage' ? 'on' : ''}`} aria-pressed={basis === 'passage'} onClick={() => setBasis('passage')}>This passage</button>
            <button className={`btn-quiet small ${basis === 'document' ? 'on' : ''}`} aria-pressed={basis === 'document'} onClick={() => setBasis('document')}>Whole judgment</button>
          </div>
        )}

        {loading && (
          <div className="loading" role="status" aria-live="polite">
            <div className="skeleton w90" /><div className="skeleton w75" /><div className="skeleton w85" />
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        {!loading && !error && data && results.length === 0 && <p className="muted">No other judgments matched.</p>}

        {!loading && results.length > 0 && (
          <ol className="similar-list">
            {results.map((r, i) => (
              <li key={r.source_file} className="similar-item">
                <div className="src-top">
                  <span className="src-title">{titleOf(r)}</span>
                  <span className="similar-score" title={`Best-matching passage similarity ${r.score.toFixed(3)}`}>{r.score.toFixed(2)}</span>
                </div>
                <div className="src-meta">
                  {r.case_no && r.case_no !== 'Unknown' && <span>{r.case_no}</span>}
                  {r.court && r.court !== 'Unknown Court' && <span>{r.court}</span>}
                  {r.matched_chunks > 1 && <span title="Passages from this case among the top 500 matches">{r.matched_chunks} matching passages</span>}
                </div>
                <div className="similar-actions">
                  <button className="btn-quiet small" aria-expanded={openIdx === i} onClick={() => setOpenIdx(openIdx === i ? null : i)}>
                    {openIdx === i ? 'Hide passage' : 'Best-matching passage'}
                  </button>
                  <button className="btn-quiet small" onClick={() => setCurrent({ sourceFile: r.source_file, title: titleOf(r) })}>
                    Find cases like this
                  </button>
                </div>
                {openIdx === i && <blockquote className="passage">{r.text}</blockquote>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}
