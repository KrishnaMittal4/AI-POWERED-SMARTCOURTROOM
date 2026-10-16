import { apiFetch } from '../lib/auth.js'
import { useState, useEffect } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function RatioObiterModal({ isOpen, onClose, caseName, passageText }) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [copiedQuote, setCopiedQuote] = useState(false)

  useEffect(() => {
    if (isOpen && passageText) {
      setLoading(true)
      setError(null)
      setData(null)

      apiFetch(`${API_BASE}/analyze/ratio-obiter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_name: caseName || 'Judgment Analysis',
          passage: passageText,
        }),
      })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
          return res.json()
        })
        .then((resData) => setData(resData))
        .catch((err) => setError(err.message))
        .finally(() => setLoading(false))
    }
  }, [isOpen, caseName, passageText])

  if (!isOpen) return null

  function copyQuote(text) {
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopiedQuote(true)
    setTimeout(() => setCopiedQuote(false), 2000)
  }

  return (
    <div className="modal-scrim" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="ratio-modal-title">
      <div className="modal ratio-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 id="ratio-modal-title" style={{ margin: 0 }}>⚖️ Ratio Decidendi vs. Obiter Dicta</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '13px' }}>
              Case: <b>{caseName || 'Selected Passage'}</b>
            </p>
          </div>
          <button className="btn-quiet close-btn" onClick={onClose} aria-label="Close modal">✕</button>
        </div>

        {loading && (
          <div className="loading" style={{ margin: '30px auto', textAlign: 'center' }}>
            <div className="skeleton w90" /><div className="skeleton w75" /><div className="skeleton w85" />
            <p className="muted">Analyzing jurisprudential ratio and separating passing remarks…</p>
          </div>
        )}

        {error && (
          <div className="error" style={{ margin: '16px 0' }}>
            Error analyzing passage: {error}
          </div>
        )}

        {!loading && data && (
          <div className="ratio-content">
            {/* Disposition */}
            {data.disposition && (
              <div className="disposition-banner">
                <span className="disp-label">🏛️ Judicial Decree / Disposition:</span>
                <span className="disp-text">{data.disposition}</span>
              </div>
            )}

            {/* Ratio Decidendi Box */}
            <div className="juris-section ratio-box">
              <div className="juris-title">
                <span className="juris-tag ratio">⚖️ Ratio Decidendi</span>
                <span className="juris-desc">Binding legal principle / core holding of the court</span>
              </div>
              <ul className="juris-list">
                {(data.ratio_decidendi || []).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>

            {/* Obiter Dicta Box */}
            <div className="juris-section obiter-box">
              <div className="juris-title">
                <span className="juris-tag obiter">💬 Obiter Dicta</span>
                <span className="juris-desc">Non-binding judicial observations & passing remarks</span>
              </div>
              <ul className="juris-list">
                {(data.obiter_dicta || []).map((o, i) => (
                  <li key={i}>{o}</li>
                ))}
              </ul>
            </div>

            {/* Key Quote for Court Pleading */}
            {data.key_quote && (
              <div className="key-quote-box">
                <div className="quote-header">
                  <span>📜 Authoritative Sentence for Court Pleadings:</span>
                  <button className="btn-quiet small-btn" onClick={() => copyQuote(data.key_quote)}>
                    {copiedQuote ? 'Copied!' : '📋 Copy Quote'}
                  </button>
                </div>
                <blockquote>"{data.key_quote}"</blockquote>
              </div>
            )}
          </div>
        )}

        <div className="modal-actions" style={{ marginTop: '20px' }}>
          <button className="btn-quiet" onClick={onClose}>Close Analysis</button>
        </div>
      </div>
    </div>
  )
}
