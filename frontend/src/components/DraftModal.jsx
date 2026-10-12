import { useState, useEffect } from 'react'
import { renderMarkdown } from '../lib/safeHtml.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const DRAFT_TYPES = [
  { id: 'legal_notice_recovery', title: 'Legal Notice for Recovery of Dues', desc: 'Breach of contract & recovery demand under Contract Act' },
  { id: 'consumer_complaint', title: 'Consumer Court Formal Complaint', desc: 'Defective goods, unfair trade practice, or deficiency of service' },
  { id: 'police_complaint', title: 'Formal Police / Cyber Cell Complaint', desc: 'Complaint for cheating, cyber fraud, or criminal intimidation' },
  { id: 'ni_act_138', title: 'Section 138 NI Act Demand Notice', desc: 'Statutory Demand Notice for Cheque Dishonour' },
  { id: 'bail_application', title: 'Anticipatory / Regular Bail Petition', desc: 'Pre-arrest or regular bail under Sec 438/439 CrPC & BNSS' },
  { id: 'writ_petition_synopsis', title: 'Writ Petition Synopsis & Grounds', desc: 'Constitutional challenge under Article 226/32' },
]

export default function DraftModal({ isOpen, onClose, entry, prefill }) {
  const [draftType, setDraftType] = useState('legal_notice_recovery')
  const [petitioner, setPetitioner] = useState('')
  const [respondent, setRespondent] = useState('')
  const [facts, setFacts] = useState('')
  const [citations, setCitations] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  // Auto-populate facts and citations from prefill or current research entry
  useEffect(() => {
    if (prefill) {
      if (prefill.draftType) setDraftType(prefill.draftType)
      if (prefill.facts) setFacts(prefill.facts)
      if (prefill.petitioner) setPetitioner(prefill.petitioner)
      if (prefill.respondent) setRespondent(prefill.respondent)
      if (prefill.citations) setCitations(prefill.citations)
    } else if (entry) {
      setFacts(entry.question ? `Issue: ${entry.question}\n\nClient instructions: The dispute arises out of non-compliance with statutory provisions and transaction obligations between parties.` : '')
      const cites = (entry.verification?.citations || [])
        .map((c) => c.case_name)
        .concat((entry.sources || []).map((s) => s.case_name))
        .filter(Boolean)
      const uniqueCites = Array.from(new Set(cites)).slice(0, 4)
      setCitations(uniqueCites.join('\n'))
    }
  }, [entry, prefill])

  if (!isOpen) return null

  async function handleGenerate(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const citeList = citations.split('\n').map((s) => s.trim()).filter(Boolean)
      const res = await fetch(`${API_BASE}/draft/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          draft_type: draftType,
          facts,
          citations: citeList,
          petitioner: petitioner.trim() || undefined,
          respondent: respondent.trim() || undefined,
        }),
      })

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}: ${res.statusText}`)
      }

      const data = await res.json()
      if (data.status === 'error') {
        throw new Error(data.error || 'Failed to generate draft')
      }
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleCopy() {
    if (!result?.draft_text) return
    try {
      await navigator.clipboard.writeText(result.draft_text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  function handleDownload() {
    if (!result?.draft_text) return
    const blob = new Blob([result.draft_text], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${draftType}_court_draft.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="modal-scrim" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="draft-modal-title">
      <div className="modal draft-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 id="draft-modal-title" style={{ margin: 0 }}>📝 Court-Ready Legal Draft Generator</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '13px' }}>
              Convert research into formal legal notices, bail applications, or writ synopses.
            </p>
          </div>
          <button className="btn-quiet close-btn" onClick={onClose} aria-label="Close modal">✕</button>
        </div>

        {!result ? (
          <form className="draft-form" onSubmit={handleGenerate}>
            <div className="form-group">
              <label htmlFor="draft-type-select"><b>Select Document Type:</b></label>
              <select
                id="draft-type-select"
                className="select-input"
                value={draftType}
                onChange={(e) => setDraftType(e.target.value)}
              >
                {DRAFT_TYPES.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title} — ({t.desc})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-row">
              <div className="form-group flex-1">
                <label htmlFor="petitioner-input">Complainant / Petitioner Name:</label>
                <input
                  id="petitioner-input"
                  type="text"
                  placeholder="e.g. M/s ABC Enterprises / John Doe"
                  value={petitioner}
                  onChange={(e) => setPetitioner(e.target.value)}
                />
              </div>
              <div className="form-group flex-1">
                <label htmlFor="respondent-input">Opposite Party / Accused Name:</label>
                <input
                  id="respondent-input"
                  type="text"
                  placeholder="e.g. XYZ Corp / Jane Smith"
                  value={respondent}
                  onChange={(e) => setRespondent(e.target.value)}
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="facts-input"><b>Factual Background & Instructions:</b></label>
              <textarea
                id="facts-input"
                rows={4}
                value={facts}
                onChange={(e) => setFacts(e.target.value)}
                placeholder="Enter cheque numbers, dates, amounts, transaction details, or arrest apprehension..."
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="citations-input"><b>Precedents & Statutory Sections to Incorporate:</b></label>
              <textarea
                id="citations-input"
                rows={3}
                value={citations}
                onChange={(e) => setCitations(e.target.value)}
                placeholder="One citation per line (e.g. Pawankumar v. Ashish Enterprises)"
              />
            </div>

            {error && <div className="error" style={{ margin: '12px 0' }}>{error}</div>}

            <div className="modal-actions">
              <button type="button" className="btn-quiet" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={loading || !facts.trim()}>
                {loading ? 'Drafting Court Pleadings…' : '✨ Generate Court Draft'}
              </button>
            </div>
          </form>
        ) : (
          <div className="draft-result-view">
            <div className="draft-result-header">
              <span className="badge-pill">⚖️ {result.title}</span>
              <div className="draft-actions">
                <button className="btn-quiet" onClick={() => setResult(null)}>✏️ Edit Inputs</button>
                <button className="btn-quiet" onClick={handleCopy}>{copied ? 'Copied!' : '📋 Copy Draft'}</button>
                <button className="btn-primary" onClick={handleDownload}>💾 Download .md</button>
                <button className="btn-quiet" onClick={() => window.print()}>🖨️ Print</button>
              </div>
            </div>

            <div
              className="draft-body markdown-body answer-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(result.draft_text || '') }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
