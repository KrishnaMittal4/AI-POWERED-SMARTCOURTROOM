import { useState, useRef } from "react"
import { apiFetch } from "../lib/auth.js"

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || "http://localhost:8000"

export default function ScanNoticeModal({ open, onClose, onOpenDraft }) {
  const [file, setFile] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  if (!open) return null

  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    if (f) {
      setFile(f)
      setError(null)
      setResult(null)
    }
  }

  const handleUploadAndAnalyze = async () => {
    if (!file) return
    setAnalyzing(true)
    setError(null)
    setResult(null)

    const formData = new FormData()
    formData.append("file", file)

    try {
      const res = await apiFetch(`${API_BASE}/analyze-document`, {
        method: "POST",
        body: formData,
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || "Document analysis failed.")
      }
      const data = await res.json()
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="scan-header">
          <div className="scan-title-wrap">
            <span className="scan-badge">📄 Document &amp; Notice Analyzer</span>
            <h2>Scan Legal Notice or Contract</h2>
            <p className="scan-subtitle">
              Upload an eviction notice, demand letter, employment contract, or challan. Our legal engine red-flags unfair clauses and prepares a counter-notice.
            </p>
          </div>
          <button type="button" className="btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Upload Dropzone */}
        {!result && (
          <div
            className={`scan-dropzone ${file ? "has-file" : ""}`}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".pdf,.txt,.doc,.docx"
              style={{ display: "none" }}
            />
            <div className="dropzone-icon">📥</div>
            {file ? (
              <div className="dropzone-file-info">
                <strong>{file.name}</strong>
                <span>({(file.size / 1024).toFixed(1)} KB) — Click to choose a different file</span>
              </div>
            ) : (
              <div className="dropzone-prompt">
                <strong>Click or drag &amp; drop your Legal Notice / Contract (PDF or Text)</strong>
                <span>Supports up to 15MB • Eviction letters, Section 138 notices, recovery demands, contracts</span>
              </div>
            )}
          </div>
        )}

        {file && !result && (
          <div className="scan-action-row">
            <button
              type="button"
              className="btn-primary large"
              onClick={handleUploadAndAnalyze}
              disabled={analyzing}
            >
              {analyzing ? "⚡ Scanning & Analyzing Legal Clauses..." : "🔍 Analyze Notice & Red-Flags"}
            </button>
          </div>
        )}

        {error && <div className="scan-error-box">⚠️ {error}</div>}

        {/* Analysis Result Display */}
        {result && (
          <div className="scan-result-container">
            {/* Top metadata strip */}
            <div className="scan-meta-strip">
              <span className="doc-type-tag">{result.document_type || "Legal Notice"}</span>
              {result.response_deadline && (
                <span className="deadline-tag">⏳ Deadline: {result.response_deadline}</span>
              )}
              {result.issuing_party && (
                <span className="party-tag">From: {result.issuing_party}</span>
              )}
            </div>

            <h3 className="doc-title">{result.document_title}</h3>
            <p className="allegation-text">
              <strong>Stated Demand / Claim:</strong> {result.stated_allegation_or_demand}
            </p>

            {/* Red Flags Section */}
            {result.red_flags?.length > 0 && (
              <div className="scan-flags-section">
                <h4>🚨 Legal Flaws &amp; Red-Flags Identified ({result.red_flags.length})</h4>
                <div className="flags-list">
                  {result.red_flags.map((f, i) => (
                    <div key={i} className={`flag-card severity-${(f.severity || "high").toLowerCase()}`}>
                      <div className="flag-top">
                        <span className="flag-claim">“{f.clause_or_claim}”</span>
                        <span className="flag-severity">{f.severity || "High"} Severity</span>
                      </div>
                      <p className="flag-flaw">{f.legal_flaw}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Counter Strategy */}
            {result.recommended_counter_strategy && (
              <div className="scan-strategy-card">
                <h4>🛡️ Recommended Counter Strategy</h4>
                <p>{result.recommended_counter_strategy}</p>
              </div>
            )}

            {/* Applicable Statutes */}
            {result.applicable_statutes?.length > 0 && (
              <div className="scan-statutes-box">
                <strong>Applicable Indian Provisions:</strong>{" "}
                {result.applicable_statutes.map((s, idx) => (
                  <span key={idx} className="statute-pill">{s.section} ({s.act})</span>
                ))}
              </div>
            )}

            {/* Bottom Actions */}
            <div className="scan-result-actions">
              {result.counter_notice_draft && (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    onClose()
                    onOpenDraft && onOpenDraft({
                      type: result.counter_notice_draft.type || "legal_notice_recovery",
                      label: "Draft Counter-Reply Notice",
                      prefilled_facts: result.counter_notice_draft.prefilled_facts,
                    })
                  }}
                >
                  📝 Draft 1-Click Counter Reply Notice ›
                </button>
              )}
              <button
                type="button"
                className="btn-quiet"
                onClick={() => {
                  setResult(null)
                  setFile(null)
                }}
              >
                🔄 Scan Another Notice
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
