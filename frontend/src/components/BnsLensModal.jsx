import { useState, useEffect } from "react"
import { apiFetch } from "../lib/auth.js"

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || "http://localhost:8000"

const QUICK_SECTIONS = [
  { label: "IPC 420 (Cheating)", query: "420" },
  { label: "IPC 302 (Murder)", query: "302" },
  { label: "CrPC 154 (Zero FIR)", query: "154" },
  { label: "CrPC 437/439 (Bail)", query: "bail" },
  { label: "IPC 304A (Hit & Run)", query: "106" },
  { label: "IEA 65B (Digital Evidence)", query: "65b" },
  { label: "IPC 498A (Dowry Cruelty)", query: "498a" },
  { label: "CrPC 167 (15-Day Remand)", query: "167" },
]

export default function BnsLensModal({ open, onClose }) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState([])
  const [analyzing, setAnalyzing] = useState(false)
  const [deepAnalysis, setDeepAnalysis] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    loadQuickResults(query)
  }, [open, query])

  async function loadQuickResults(q) {
    try {
      const res = await apiFetch(`${API_BASE}/bns-lens/quick?q=${encodeURIComponent(q)}`)
      if (res.ok) {
        const data = await res.json()
        setResults(data.results || [])
      }
    } catch {
      // offline fallback
    }
  }

  async function runDeepAnalysis(sectionQuery) {
    const q = sectionQuery || query
    if (!q.trim()) return
    setAnalyzing(true)
    setError(null)
    setDeepAnalysis(null)
    try {
      const res = await apiFetch(`${API_BASE}/bns-lens/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      })
      if (!res.ok) throw new Error("Deep comparative analysis failed.")
      const data = await res.json()
      setDeepAnalysis(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  if (!open) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="bns-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="bns-header">
          <div className="bns-title-wrap">
            <span className="bns-badge">⚖️ 2024 Criminal Law Transition</span>
            <h2>BNS ↔ IPC Cross-Reference Lens</h2>
            <p className="bns-subtitle">
              Instant side-by-side transition mapper between IPC/CrPC/IEA and Bharatiya Nyaya Sanhita (BNS), BNSS &amp; BSA.
            </p>
          </div>
          <button type="button" className="btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Search Input */}
        <div className="bns-search-bar">
          <input
            type="text"
            className="bns-input"
            placeholder="Search section or keyword (e.g., 420, 302, bail, hit and run, 65b, theft)..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setDeepAnalysis(null)
            }}
            onKeyDown={(e) => e.key === "Enter" && runDeepAnalysis()}
          />
          <button
            type="button"
            className="btn-primary"
            onClick={() => runDeepAnalysis()}
            disabled={analyzing || !query.trim()}
          >
            {analyzing ? "Analyzing..." : "🔍 Deep Comparative Analysis"}
          </button>
        </div>

        {/* Quick Pills */}
        <div className="bns-pills-row">
          <span className="bns-pills-label">Popular Transitions:</span>
          {QUICK_SECTIONS.map((sec, i) => (
            <button
              key={i}
              type="button"
              className="bns-pill-btn"
              onClick={() => {
                setQuery(sec.query)
                runDeepAnalysis(sec.query)
              }}
            >
              {sec.label}
            </button>
          ))}
        </div>

        {error && <div className="bns-error-box">⚠️ {error}</div>}

        {/* Deep Analysis Card */}
        {deepAnalysis && (
          <div className="bns-deep-card">
            <div className="bns-compare-header">
              <div className="bns-compare-side old">
                <span className="compare-tag old">PRE-2024 STATUTE</span>
                <h3>{deepAnalysis.old_provision?.act} {deepAnalysis.old_provision?.section}</h3>
                <p>{deepAnalysis.old_provision?.title}</p>
              </div>
              <div className="bns-compare-arrow">➔</div>
              <div className="bns-compare-side new">
                <span className="compare-tag new">JULY 1, 2024 LAW</span>
                <h3>{deepAnalysis.new_provision?.act} {deepAnalysis.new_provision?.section}</h3>
                <p>{deepAnalysis.new_provision?.title}</p>
              </div>
            </div>

            <div className="bns-meta-row">
              <span className="bns-status-pill">{deepAnalysis.bailable_status}</span>
              <span className="bns-status-pill">{deepAnalysis.cognizable_status}</span>
              {deepAnalysis.provider && <span className="bns-status-pill provider">✦ {deepAnalysis.provider}</span>}
            </div>

            <div className="bns-detail-block">
              <h4>⚖️ Punishment &amp; Penalty Changes:</h4>
              <p>{deepAnalysis.punishment_comparison}</p>
            </div>

            {deepAnalysis.key_substantive_changes?.length > 0 && (
              <div className="bns-detail-block">
                <h4>✨ Key Substantive Changes in 2024:</h4>
                <ul>
                  {deepAnalysis.key_substantive_changes.map((ch, idx) => (
                    <li key={idx}>{ch}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="bns-detail-block">
              <h4>🚨 Procedural Impact for Advocates &amp; Police:</h4>
              <p>{deepAnalysis.procedural_impact}</p>
            </div>

            <div className="bns-transitional-box">
              <strong>📅 Transitional Application:</strong> {deepAnalysis.transitional_application}
            </div>
          </div>
        )}

        {/* Quick Results Grid */}
        {!deepAnalysis && (
          <div className="bns-results-grid">
            {results.map((r, idx) => (
              <div key={idx} className="bns-card" onClick={() => runDeepAnalysis(r.old_section)}>
                <div className="bns-card-head">
                  <span className="bns-card-sec old">{r.old_act} {r.old_section}</span>
                  <span className="bns-card-arrow">➔</span>
                  <span className="bns-card-sec new">{r.new_act} {r.new_section}</span>
                </div>
                <h4 className="bns-card-title">{r.title}</h4>
                <p className="bns-card-changes">{r.key_changes}</p>
                <div className="bns-card-footer">
                  <span className="bns-card-cat">{r.category}</span>
                  <span className="bns-card-cta">View Deep Analysis ›</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
