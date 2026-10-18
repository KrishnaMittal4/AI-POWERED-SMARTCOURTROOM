import { useState, useMemo, useCallback } from 'react'
import { renderMarkdown } from '../lib/safeHtml.js'
import { annotateAnswer, summarize, toMarkdown, download, verdictOf, followUps, submitFeedback, VERDICT_LABEL } from '../lib/utils.js'
import DraftModal from './DraftModal.jsx'

const LEVELS = {
  high: { label: 'All citations verified', cls: 'high', icon: '✓', sub: 'Every legal claim matches the cited judgment record' },
  review: { label: 'Citations require review', cls: 'review', icon: '⚠', sub: 'Some cited holdings differ or need manual checking' },
  low: { label: 'Citation discrepancies found', cls: 'low', icon: '✕', sub: 'Corpus cross-check found unsupported or missing citations' },
  none: { label: 'Unverified advisory response', cls: 'none', icon: '○', sub: 'No case citations or citation verification was off' },
}

function TrustBar({ verification }) {
  const sum = summarize(verification)
  if (!sum) {
    return (
      <div className="trust-card none" role="status">
        <div className="trust-card-top">
          <div className="trust-card-badge">
            <span className="trust-symbol">○</span>
            <span className="trust-label">Verification disabled</span>
          </div>
          <span className="trust-desc">Run with citation verification enabled to cross-check claims against judgment texts.</span>
        </div>
      </div>
    )
  }
  const { counts: c } = sum
  const parts = []
  if (c.yes) parts.push({ label: `${c.yes} Supported`, cls: 'yes' })
  if (c.partial) parts.push({ label: `${c.partial} Partly Supported`, cls: 'partial' })
  if (c.disputed) parts.push({ label: `${c.disputed} Disputed`, cls: 'disputed' })
  if (c.no) parts.push({ label: `${c.no} Not Supported`, cls: 'no' })
  if (c.missing) parts.push({ label: `${c.missing} Not in Corpus`, cls: 'missing' })
  if (c.unclear + c.unchecked) parts.push({ label: `${c.unclear + c.unchecked} Unclear`, cls: 'unclear' })
  if (c.unverifiable) parts.push({ label: `${c.unverifiable} Unmatched`, cls: 'unmatched' })
  
  const lv = LEVELS[sum.level] || LEVELS.none

  return (
    <div className={`trust-card ${lv.cls}`} role="status">
      <div className="trust-card-top">
        <div className="trust-card-badge">
          <span className="trust-symbol">{lv.icon}</span>
          <span className="trust-label">{lv.label}</span>
        </div>
        <span className="trust-desc">{lv.sub}</span>
      </div>
      {parts.length > 0 && (
        <div className="trust-chips">
          {parts.map((p, idx) => (
            <span key={idx} className={`trust-chip ${p.cls}`}>
              <i className="chip-dot" />
              {p.label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function FeedbackButtons({ entry }) {
  const [sent, setSent] = useState(null) // 'up' | 'down' | null

  async function send(rating) {
    const label = rating === 1 ? 'up' : 'down'
    if (sent === label) return
    setSent(label)
    await submitFeedback({
      question: entry.question,
      answer: entry.answer,
      rating,
      top_score: entry.top_score,
      weak_match: entry.weak_match,
      not_found: entry.not_found,
      sources: entry.sources || [],
    })
  }

  return (
    <div className="feedback-btns" role="group" aria-label="Rate this legal answer">
      <button
        type="button"
        className={`feedback-btn ${sent === 'up' ? 'active up' : ''}`}
        onClick={() => send(1)}
        disabled={!!sent}
        aria-label="Helpful answer"
        title="Helpful legal research"
      >
        <span className="thumb-icon">👍</span>
        <span className="thumb-text">{sent === 'up' ? 'Helpful' : 'Helpful'}</span>
      </button>
      <button
        type="button"
        className={`feedback-btn ${sent === 'down' ? 'active down' : ''}`}
        onClick={() => send(-1)}
        disabled={!!sent}
        aria-label="Unhelpful answer"
        title="Needs improvement"
      >
        <span className="thumb-icon">👎</span>
        <span className="thumb-text">{sent === 'down' ? 'Noted' : 'Needs work'}</span>
      </button>
    </div>
  )
}

export default function AnswerView({
  entry,
  onJump,
  onToggleSave,
  onRetryWider,
  loadingWider,
  onAsk,
  streaming,
  onOpenMootCourt,
}) {
  const [copied, setCopied] = useState('')
  const [draftOpen, setDraftOpen] = useState(false)
  const [sourceFeedback, setSourceFeedback] = useState(false)
  const [fontSize, setFontSize] = useState('normal') // 'normal' | 'large'

  async function markTopSourceCorrect() {
    const src = entry.sources?.[0]
    if (!src || sourceFeedback) return
    setSourceFeedback(true)
    await submitFeedback({
      question: entry.question,
      answer: entry.answer || '',
      rating: 1,
      sources: entry.sources || [],
      correct_source: src.source_file || src.case_name,
      event_type: 'correct_source',
      top_score: entry.top_score,
      weak_match: entry.weak_match,
      not_found: entry.not_found,
    })
  }

  const isStreaming = streaming && !entry.answer
  const answerText = entry.answer || entry._streamingText || ''
  const best = entry.sources?.length ? Math.max(...entry.sources.map((s) => s.score)) : 0
  const weak = entry.weak_match ?? (entry.sources?.length > 0 && best < 0.55)
  const nexts = !streaming ? followUps(entry) : []

  // Extract section headings for outline navigation
  const sections = useMemo(() => {
    if (!answerText) return []
    const lines = answerText.split('\n')
    const list = []
    for (const line of lines) {
      const m = line.match(/^##\s+(.+)$/)
      if (m) {
        const title = m[1].replace(/[#*`_]/g, '').trim()
        if (title.length > 2 && title.length < 50) list.push(title)
      }
    }
    return list
  }, [answerText])

  // Pre-annotate text with clickable legal citation badges before markdown parsing
  const renderedHtml = useMemo(() => {
    let text = answerText
    if (!text) return ''

    if (!streaming && entry.verification && (entry.verification.citations?.length || entry.verification.unverifiable_citations?.length)) {
      const segs = annotateAnswer(text, entry.verification)
      text = segs
        .map((seg) => {
          if (!seg.kind) return seg.text
          const verdict = seg.kind === 'unverifiable' ? 'unmatched' : verdictOf(entry.verification.citations[seg.index])
          const vClass = seg.kind === 'unverifiable' ? 'unmatched' : 'v-' + verdict
          const label = seg.kind === 'unverifiable' ? 'Not in corpus' : (VERDICT_LABEL[verdict] || 'Verified')
          return `<button type="button" class="cite ${vClass}" data-index="${seg.index}" data-kind="${seg.kind}" title="${label}: Click to inspect source excerpt in evidence panel"><span class="cite-icon">⚖</span><span class="cite-text">${seg.text}</span><span class="cite-verdict">${label}</span></button>`
        })
        .join('')
    }

    if (streaming) {
      text += ' <span class="cursor-blink" aria-hidden="true">▊</span>'
    }

    return renderMarkdown(text)
  }, [answerText, entry.verification, streaming])

  const handleContentClick = useCallback((e) => {
    const btn = e.target.closest('.cite')
    if (btn) {
      e.preventDefault()
      const { kind, index } = btn.dataset
      if (kind && index != null) {
        onJump(kind, Number(index))
      }
    }
  }, [onJump])

  async function copy(kind) {
    const text = kind === 'md' ? toMarkdown(entry) : answerText
    try {
      await navigator.clipboard.writeText(text)
      setCopied(kind)
      setTimeout(() => setCopied(''), 1800)
    } catch {
      setCopied('failed')
    }
  }

  const wordCount = useMemo(() => {
    return answerText ? answerText.trim().split(/\s+/).length : 0
  }, [answerText])

  const readMinutes = Math.max(1, Math.ceil(wordCount / 180))

  return (
    <article className="answer-brief-card" id="answer-container">
      {/* 1. TOP METADATA & STATUS HEADER */}
      <header className="brief-header">
        <div className="brief-eyebrow-row">
          <div className="brief-badge">
            <span className="brief-badge-icon">⚖️</span>
            <span className="brief-badge-text">LEXAI GROUNDED RESEARCH BRIEF</span>
          </div>
          <div className="brief-meta-chips">
            <span className="meta-chip">
              <span className="meta-chip-icon">⏱️</span> {readMinutes} min read
            </span>
            {entry.sources?.length > 0 && (
              <span className="meta-chip source-count">
                <span className="meta-chip-icon">🏛️</span> {entry.sources.length} {entry.sources.length === 1 ? 'Authority' : 'Authorities'} Grounded
              </span>
            )}
            <span className={`status-pill ${entry.statutory_fallback ? 'fallback' : 'grounded'}`}>
              {entry.statutory_fallback ? 'Statutory Precedent' : 'Corpus Grounded'}
            </span>
          </div>
        </div>

        {/* Question Title Box */}
        <div className="brief-question-box">
          <div className="brief-q-mark">Q</div>
          <div className="brief-q-content">
            <h2 className="brief-question-title" id="answer-heading" tabIndex={-1}>
              {entry.question}
            </h2>
            {entry.rewritten_query && entry.rewritten_query !== entry.question && (
              <div className="brief-query-expansion">
                <span className="expansion-label">🔍 Legal Query Expansion (HyDE):</span>
                <span className="expansion-text">{entry.rewritten_query}</span>
              </div>
            )}
          </div>
        </div>

        {/* Document Provenance (if specific file grounded) */}
        {entry.sources?.length > 0 && !entry.not_found && (
          <div className="source-provenance-bar">
            <div className="provenance-info">
              <span className="provenance-icon">📄</span>
              <span className="provenance-text">
                Primary Grounding: <b>{entry.sources[0]?.source_file || entry.sources[0]?.case_name}</b>
              </span>
              <span className="grounded-check-tag">✓ Grounded in Judgment</span>
            </div>
            <button
              type="button"
              className={`source-correct-btn ${sourceFeedback ? 'active' : ''}`}
              onClick={markTopSourceCorrect}
              disabled={sourceFeedback}
              title="Teach retrieval engine that this was the exact supporting source"
            >
              {sourceFeedback ? '✓ Learned for Retrieval' : '✓ Confirm Source'}
            </button>
          </div>
        )}

        {/* Modern Action Bar */}
        <div className="brief-actions-bar" role="toolbar" aria-label="Answer actions">
          <div className="action-group primary-actions">
            <button
              type="button"
              className="brief-btn btn-draft"
              onClick={() => setDraftOpen(true)}
              title="Generate a legal notice, petition or draft from this analysis"
            >
              <span className="btn-icon">📝</span>
              <span>Draft Document</span>
            </button>
            <button
              type="button"
              className="brief-btn btn-moot"
              onClick={() => onOpenMootCourt && onOpenMootCourt(entry.question)}
              title="Simulate courtroom trial with advocates and bench"
            >
              <span className="btn-icon">🏛️</span>
              <span>Moot Court</span>
            </button>
          </div>

          <div className="action-group utility-actions">
            <FeedbackButtons entry={entry} />

            <div className="button-separator" />

            <button
              type="button"
              className={`brief-btn btn-util ${copied === 'text' ? 'copied' : ''}`}
              onClick={() => copy('text')}
              title="Copy answer text"
            >
              <span>{copied === 'text' ? '✓ Copied' : '📋 Copy'}</span>
            </button>

            <button
              type="button"
              className={`brief-btn btn-util ${copied === 'md' ? 'copied' : ''}`}
              onClick={() => copy('md')}
              title="Copy markdown with sources and citations"
            >
              <span>{copied === 'md' ? '✓ Copied' : '📑 Copy + Sources'}</span>
            </button>

            <button
              type="button"
              className="brief-btn btn-util"
              onClick={() => download('lexai-research-brief.md', toMarkdown(entry))}
              title="Export research note as Markdown"
            >
              <span>📥 Export .md</span>
            </button>

            <button
              type="button"
              className="brief-btn btn-util"
              onClick={() => window.print()}
              title="Print legal research brief"
            >
              <span>🖨️ Print</span>
            </button>

            <button
              type="button"
              className={`brief-btn btn-save ${entry.saved ? 'saved' : ''}`}
              onClick={() => onToggleSave(entry.id)}
              aria-pressed={!!entry.saved}
              title={entry.saved ? 'Remove bookmark' : 'Bookmark this research'}
            >
              <span>{entry.saved ? '★ Saved' : '☆ Save'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* 2. CITATION VERIFICATION TRUST BAR */}
      {!streaming && <TrustBar verification={entry.verification} />}
      {streaming && entry._verifying && (
        <div className="trust-card review" role="status">
          <div className="trust-card-top">
            <div className="trust-card-badge">
              <span className="trust-symbol">⏳</span>
              <span className="trust-label">Verifying citations in real-time…</span>
            </div>
            <span className="trust-desc">Cross-checking every case proposition against retrieved judgment passages.</span>
          </div>
        </div>
      )}

      {/* Weak Match Warning */}
      {weak && !streaming && (
        <div className="notice-card" role="alert">
          <div className="notice-icon">⚠</div>
          <div className="notice-content">
            <strong>Borderline Corpus Match.</strong> The top retrieved passage scored {(entry.top_score ?? best).toFixed(2)}, which is below our high confidence threshold. Please verify claims against primary sources.
          </div>
          <button type="button" className="notice-btn" onClick={onRetryWider} disabled={loadingWider}>
            {loadingWider ? 'Searching wider pool…' : '↻ Retry with more passages'}
          </button>
        </div>
      )}

      {/* 3. SECTION OUTLINE JUMP CHIPS (if structured sections exist) */}
      {sections.length >= 2 && !streaming && (
        <nav className="brief-section-nav" aria-label="Quick section navigation">
          <span className="section-nav-label">STRUCTURED OUTLINE:</span>
          <div className="section-nav-chips">
            {sections.map((sec, idx) => (
              <span key={idx} className="section-chip">
                {sec}
              </span>
            ))}
          </div>
        </nav>
      )}

      {/* 4. THE ANSWER BODY */}
      <div className={`brief-body-wrapper font-${fontSize} trust-${summarize(entry.verification)?.level || 'none'}`}>
        <div className="brief-body-topstrip">
          <div className="topstrip-title">
            <span className="strip-dot" />
            <span>LEGAL OPINION & SUBSTANTIVE FINDINGS</span>
          </div>
          <div className="topstrip-tools">
            <span className="fontsize-label">Text Size:</span>
            <button
              type="button"
              className={`fontsize-btn ${fontSize === 'normal' ? 'active' : ''}`}
              onClick={() => setFontSize('normal')}
              title="Standard font size"
            >
              A
            </button>
            <button
              type="button"
              className={`fontsize-btn ${fontSize === 'large' ? 'active' : ''}`}
              onClick={() => setFontSize('large')}
              title="Comfortable reading font size"
            >
              A+
            </button>
          </div>
        </div>

        <div
          className="answer-content markdown-body"
          onClick={handleContentClick}
          dangerouslySetInnerHTML={{ __html: renderedHtml }}
        />
      </div>

      {/* 5. SUGGESTED NEXT INQUIRIES */}
      {!streaming && nexts.length > 0 && (
        <nav className="brief-followups" aria-label="Suggested follow-up legal queries">
          <div className="followups-title">
            <span>💡</span>
            <h3>STRATEGIC FOLLOW-UP QUESTIONS</h3>
          </div>
          <div className="followups-grid">
            {nexts.map((q) => (
              <button
                key={q}
                className="followup-card"
                onClick={() => onAsk(q)}
                type="button"
              >
                <span className="followup-arrow">↳</span>
                <span className="followup-text">{q}</span>
              </button>
            ))}
          </div>
        </nav>
      )}

      {/* 6. LEGAL DISCLAIMER */}
      <footer className="brief-footer">
        <span className="footer-scale">⚖</span>
        <p className="disclaimer-text">
          <b>LexAI Legal Intelligence System</b> · Prepared as an automated research aid based on indexed precedents and statutory authorities. Does not constitute formal legal counsel. Verify all citations against certified Law Reports or original High Court / Supreme Court orders before filing.
        </p>
      </footer>

      <DraftModal isOpen={draftOpen} onClose={() => setDraftOpen(false)} entry={entry} />
    </article>
  )
}
