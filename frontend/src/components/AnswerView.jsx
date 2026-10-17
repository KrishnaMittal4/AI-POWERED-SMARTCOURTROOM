import { useState, useMemo, useCallback } from 'react'
import { renderMarkdown } from '../lib/safeHtml.js'
import { annotateAnswer, summarize, toMarkdown, download, verdictOf, followUps, submitFeedback, VERDICT_LABEL } from '../lib/utils.js'
import DraftModal from './DraftModal.jsx'


const LEVELS = {
  high: { label: 'All citations verified', cls: 'high' },
  review: { label: 'Some citations need review', cls: 'review' },
  low: { label: 'Citation problems found', cls: 'low' },
  none: { label: 'No citations to verify', cls: 'none' },
}

function TrustBar({ verification }) {
  const sum = summarize(verification)
  if (!sum) return <div className="trust none"><strong>Verification off</strong><span>Run with citation verification turned on to check this answer.</span></div>
  const { counts: c } = sum
  const parts = []
  if (c.yes) parts.push(`${c.yes} supported`)
  if (c.partial) parts.push(`${c.partial} partly supported`)
  if (c.disputed) parts.push(`${c.disputed} disputed between models`)
  if (c.no) parts.push(`${c.no} not supported`)
  if (c.missing) parts.push(`${c.missing} not in corpus`)
  if (c.unclear + c.unchecked) parts.push(`${c.unclear + c.unchecked} unclear`)
  if (c.unverifiable) parts.push(`${c.unverifiable} unmatched`)
  const lv = LEVELS[sum.level]
  return (
    <div className={`trust ${lv.cls}`} role="status">
      <strong>{lv.label}</strong>
      <span>{parts.join(' · ') || 'Nothing in this answer cites a case.'}</span>
    </div>
  )
}

function FeedbackButtons({ entry }) {
  const [sent, setSent] = useState(null) // 'up' | 'down' | null

  async function send(rating) {
    const label = rating === 1 ? 'up' : 'down'
    if (sent === label) return // already sent this vote
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
    <span className="feedback-btns" role="group" aria-label="Rate this answer">
      <button
        className={`feedback-btn ${sent === 'up' ? 'active up' : ''}`}
        onClick={() => send(1)}
        disabled={!!sent}
        aria-label="Helpful answer"
        title="Helpful"
      >
        👍{sent === 'up' && <span className="feedback-label"> Thanks!</span>}
      </button>
      <button
        className={`feedback-btn ${sent === 'down' ? 'active down' : ''}`}
        onClick={() => send(-1)}
        disabled={!!sent}
        aria-label="Unhelpful answer"
        title="Not helpful"
      >
        👎{sent === 'down' && <span className="feedback-label"> Noted</span>}
      </button>
    </span>
  )
}

export default function AnswerView({ entry, onJump, onToggleSave, onRetryWider, loadingWider, onAsk, streaming, onOpenMootCourt }) {
  const [copied, setCopied] = useState('')
  const [draftOpen, setDraftOpen] = useState(false)
  const [sourceFeedback, setSourceFeedback] = useState(false)

  async function markTopSourceCorrect() {
    const src = entry.sources?.[0]
    if (!src || sourceFeedback) return
    setSourceFeedback(true)
    await submitFeedback({
      question: entry.question, answer: entry.answer || '', rating: 1,
      sources: entry.sources || [], correct_source: src.source_file || src.case_name,
      event_type: 'correct_source', top_score: entry.top_score, weak_match: entry.weak_match, not_found: entry.not_found,
    })
  }
  const isStreaming = streaming && !entry.answer
  const answerText = entry.answer || entry._streamingText || ''
  const best = entry.sources?.length ? Math.max(...entry.sources.map((s) => s.score)) : 0
  const weak = entry.weak_match ?? (entry.sources?.length > 0 && best < 0.55)
  const nexts = !streaming ? followUps(entry) : []

  // Pre-annotate text with clickable HTML buttons for citations before markdown parsing
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
          const label = seg.kind === 'unverifiable' ? 'Not in local corpus' : (VERDICT_LABEL[verdict] || 'Verified')
          return `<button type="button" class="cite ${vClass}" data-index="${seg.index}" data-kind="${seg.kind}" title="${label}: Click to inspect source passage">${seg.text}</button>`
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
      setTimeout(() => setCopied(''), 1600)
    } catch {
      setCopied('failed')
    }
  }

  return (
    <article className="answer">
      <header className="answer-head">
        <h2 className="question" id="answer-heading" tabIndex={-1}>{entry.question}</h2>
        {entry.rewritten_query && entry.rewritten_query !== entry.question && (
          <div className="rewritten-query">
            <span className="rewritten-label">🔍 Searched as:</span> {entry.rewritten_query}
          </div>
        )}
        <div className="actions" role="toolbar" aria-label="Answer actions">
          <FeedbackButtons entry={entry} />
          <button className="btn-quiet draft-btn" onClick={() => setDraftOpen(true)}>📝 Draft Document</button>
          <button className="btn-quiet moot-btn" onClick={() => onOpenMootCourt && onOpenMootCourt(entry.question)} title="Simulate courtroom trial on this issue">⚖️ Moot Court</button>
          <button className="btn-quiet" onClick={() => copy('text')}>{copied === 'text' ? 'Copied' : 'Copy answer'}</button>
          <button className="btn-quiet" onClick={() => copy('md')}>{copied === 'md' ? 'Copied' : 'Copy with sources'}</button>
          <button className="btn-quiet" onClick={() => download('research-note.md', toMarkdown(entry))}>Download .md</button>
          <button className="btn-quiet" onClick={() => window.print()}>Print</button>
          <button className={`btn-quiet star-btn ${entry.saved ? 'on' : ''}`} onClick={() => onToggleSave(entry.id)} aria-pressed={!!entry.saved}>
            {entry.saved ? '★ Saved' : '☆ Save'}
          </button>
        </div>
      </header>

      {entry.sources?.length > 0 && !entry.not_found && (
        <div className="source-doc-badge" style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 14px',
          borderRadius: 'var(--r-sm)',
          background: 'rgba(16, 185, 129, 0.08)',
          border: '1px solid rgba(16, 185, 129, 0.25)',
          color: 'var(--yes)',
          fontSize: '12.5px',
          fontWeight: 600,
          marginBottom: '14px',
        }}>
          <span>✅</span>
          <span>Verified against document: <b>{entry.sources[0]?.source_file || entry.sources[0]?.case_name}</b> · Grounded in uploaded text</span>
          <button type="button" className={`source-correct-btn ${sourceFeedback ? 'active' : ''}`} onClick={markTopSourceCorrect} disabled={sourceFeedback} title="Teach retrieval that this was the correct supporting source">
            {sourceFeedback ? '✓ Source learned' : '✓ Correct source'}
          </button>
        </div>
      )}

      {!streaming && <TrustBar verification={entry.verification} />}
      {streaming && entry._verifying && (
        <div className="trust none"><strong>Checking citations…</strong><span>Each cited case is checked against the source passages once the answer is complete.</span></div>
      )}

      {weak && !streaming && (
        <div className="notice" role="alert">
          <strong>Weak match.</strong> The best passage scored {(entry.top_score ?? best).toFixed(2)}, which is low. The corpus may not cover this question, so check the sources before relying on the answer.
          <button className="btn-quiet" onClick={onRetryWider} disabled={loadingWider}>{loadingWider ? 'Searching…' : 'Retry with more passages'}</button>
        </div>
      )}

      <div className={`answer-body trust-${summarize(entry.verification)?.level || 'none'}`}>
        <div
          className="answer-content markdown-body"
          onClick={handleContentClick}
          dangerouslySetInnerHTML={{ __html: renderedHtml }}
        />
      </div>
      {!streaming && nexts.length > 0 && (
        <nav className="followups" aria-label="Suggested follow-up questions">
          <h3>Ask next</h3>
          <ul>
            {nexts.map((q) => (
              <li key={q}><button onClick={() => onAsk(q)}>{q}</button></li>
            ))}
          </ul>
        </nav>
      )}
      <p className="disclaimer">Research aid, not legal advice. Confirm every point against the original judgment.</p>

      <DraftModal isOpen={draftOpen} onClose={() => setDraftOpen(false)} entry={entry} />
    </article>
  )
}
