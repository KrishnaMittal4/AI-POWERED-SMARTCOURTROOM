import { renderMarkdown } from '../lib/safeHtml.js'
import { useMemo } from 'react'


export default function NotFound({ entry, examples, onRephrase, onAsk }) {
  const hasStatutory = Boolean(entry.statutory_fallback && entry.answer)

  const renderedHtml = useMemo(() => {
    if (!hasStatutory) return ''
    return renderMarkdown(entry.answer || '')
  }, [hasStatutory, entry.answer])

  return (
    <article className="answer notfound">
      <h2 className="question" id="answer-heading" tabIndex={-1}>{entry.question}</h2>

      {hasStatutory ? (
        <div className="statutory-fallback-card" role="region" aria-label="Statutory Law Overview">
          <div className="statutory-badge" style={{ background: 'rgba(245, 158, 11, 0.1)', borderLeft: '4px solid #f59e0b', padding: '14px 18px', borderRadius: 'var(--r-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14.5px', fontWeight: 700, color: '#f59e0b' }}>
              <span>⚠️</span>
              <span>Not Found in Uploaded Document · General Legal Knowledge</span>
            </div>
            <span className="statutory-badge-sub" style={{ display: 'block', marginTop: '5px', fontSize: '12.5px', color: 'var(--muted)', lineHeight: 1.5 }}>
              This query is not covered in your uploaded PDF. The answer below is synthesized from general statutory knowledge — <b>not grounded in the uploaded document and citations are unverified</b>.
            </span>
          </div>

          <div
            className="statutory-md-body"
            dangerouslySetInnerHTML={{ __html: renderedHtml }}
          />

          <div className="statutory-footer">
            <span>Closest local match score: <b>{entry.top_score != null ? entry.top_score.toFixed(2) : 'very low'}</b> {entry.threshold != null ? `(threshold: ${entry.threshold.toFixed(2)})` : ''}</span>
            <span>· Check the <b>Sources</b> panel for partial matches</span>
          </div>
        </div>
      ) : (
        <div className="notfound-card" role="status">
          <h3>Not covered by these judgments</h3>
          <p>
            The closest passage scored {entry.top_score != null ? entry.top_score.toFixed(2) : 'very low'}, which is too weak to answer reliably.
          </p>
          <ul>
            <li>Rephrase using terms that appear in the judgments — a section number or party name.</li>
            <li>Check the Sources tab to see what partial matches were found.</li>
          </ul>
          <button className="btn-primary" onClick={onRephrase}>Rephrase question</button>
        </div>
      )}

      <p className="muted pad0" style={{ marginTop: '24px' }}>Questions your local corpus can answer with verified citations:</p>
      <ul className="examples compact">
        {examples.slice(0, 3).map((ex) => (
          <li key={ex}><button onClick={() => onAsk(ex)}>{ex}</button></li>
        ))}
      </ul>
    </article>
  )
}
