import { useEffect, useRef, useState } from 'react'
import { parseSource, verdictOf, passagesFor, tabKeys, VERDICT_LABEL } from '../lib/utils.js'
import Passage from './Passage.jsx'
import RatioObiterModal from './RatioObiterModal.jsx'
import SimilarModal from './SimilarModal.jsx'

const VERDICT = {
  yes: { label: 'Supported', cls: 'yes' },
  partial: { label: 'Partly supported', cls: 'partial' },
  no: { label: 'Not supported', cls: 'no' },
  disputed: { label: 'Models disagree', cls: 'disputed' },
  unclear: { label: 'Unclear', cls: 'unclear' },
  unchecked: { label: 'Not checked', cls: 'unclear' },
  missing: { label: 'Not in corpus', cls: 'no' },
}

function splitDisputed(reason = '') {
  const [a = '', b = ''] = reason.split(' | ')
  const strip = (t) => t.replace(/^[^:]*said '[^']*':\s*/, '').trim()
  return [strip(a), strip(b)]
}

function Pill({ verdict }) {
  const v = VERDICT[verdict] || VERDICT.unclear
  return <span className={`pill ${v.cls}`}><span className="sr-only">Verification: </span>{v.label}</span>
}

function CitationItem({ citation, open, onToggle, refCb, sources, query, answer, onDissectRatio }) {
  const passages = passagesFor(citation, sources).filter((p) => p.text)
  const s = citation.passage_support
  const verdict = verdictOf(citation)
  const secondaryChecked = Boolean(s?.gemini_checked)
  const secondaryName = s?.secondary_provider === 'groq_fallback' ? 'Groq fallback' : 'Gemini'
  const independent = s?.independent_provider === true
  const prec = citation.precedent_status
  const attr = citation.attribution
  const strength = citation.evidence_strength
  const supported = verdict === 'yes' || verdict === 'partial'
  return (
    <li className={`cit-item v-${verdict} ${open ? 'open' : ''}`} ref={refCb}>
      <button className="cit-head" onClick={onToggle} aria-expanded={open}>
        <span className="cit-name">{citation.case_name}</span>
        <div className="citation-badges">
          <span className={`citation-primary-badge ${supported ? 'verified' : verdict}`}>
            {verdict === 'yes' ? '✓ Citation supported' : verdict === 'partial' ? '◐ Partly supported' : verdict === 'no' ? '✕ Not supported' : verdict === 'disputed' ? '⚠ Models disagree' : '○ Verification unclear'}
          </span>
          {independent && secondaryChecked && <span className="citation-crosscheck-badge">✓ Independent AI cross-check</span>}
        </div>
      </button>
      {open && (
        <div className="cit-body">
          <div className="citation-compact-summary">
            <div>
              <strong>{verdict === 'yes' ? 'Source-backed citation' : VERDICT[verdict]?.label || 'Citation review'}</strong>
              <p>{s?.reason || 'LEXAI compared the claim with the retrieved judgment passage.'}</p>
            </div>
          </div>

          {strength && (
            <div className={`evidence-strength ${strength.level || 'low'}`}>
              <strong>Evidence strength: {(strength.level || 'low').toUpperCase()} · {strength.score ?? 0}/100</strong>
              <p>{strength.reasons?.slice(0, 3).join(' · ') || 'Evidence signals are limited.'}</p>
              {strength.warnings?.length > 0 && <small>Review: {strength.warnings.join(' · ')}</small>}
            </div>
          )}

          {attr?.checked && (
            <div className={`attribution-status ${attr.status || 'uncertain'}`}>
              <strong>{attr.status === 'supported' ? '✓ Attribution supported' : attr.status === 'mismatch' ? '⚠ Attribution mismatch' : '○ Attribution uncertain'}</strong>
              <p>{attr.reason}</p>
              {attr.passage_roles?.length > 0 && <small>Passage role: {attr.passage_roles.join(', ').replaceAll('_', ' ')}</small>}
            </div>
          )}

          <dl className="citation-source-meta">
            <dt>In corpus</dt>
            <dd>
              {citation.existence.exists_in_corpus ? '✓ Yes' : 'No'}
              {citation.existence.matched_files?.length > 0 && (() => {
                const names = [...new Set(citation.existence.matched_files.map((f) => parseSource(f).title.replace(/^(\d{4})\s+\1\s+/, '$1 ')))]
                return <span className="files"> · Source: {names.join('; ')}</span>
              })()}
            </dd>
          </dl>

          {passages.length > 0 && (
            <details className="source-disclosure">
              <summary>View supporting source</summary>
              <div className="cit-passages">
                <div className="source-disclosure-head"><span>Source evidence used for grounding and verification</span><button type="button" className="btn-quiet small ratio-btn" onClick={() => onDissectRatio(citation.case_name, passages[0].text)}>⚖️ Ratio vs. Obiter</button></div>
                {passages.map((p, i) => <Passage key={i} text={p.text} query={query} answer={answer} />)}
              </div>
            </details>
          )}

          <details className="verification-details">
            <summary>Verification details</summary>
            <div className="provider-checks">
              <div><span>Corpus passage</span><strong>{passages.length ? '✓ Retrieved' : '○ Not retrieved'}</strong></div>
              <div><span>Groq primary</span><strong>{s?.checked ? `✓ ${VERDICT[s?.groq_verdict || s?.verdict]?.label || s?.groq_verdict || s?.verdict || verdict}` : '○ Not checked'}</strong></div>
              {secondaryChecked && <div><span>{secondaryName}</span><strong>✓ {VERDICT[s?.gemini_verdict || s?.verdict]?.label || s?.gemini_verdict || s?.verdict || verdict}</strong></div>}
              <div><span>Independent provider</span><strong>{independent ? '✓ Yes' : '○ No'}</strong></div>
              <div><span>Attribution</span><strong>{attr?.status === 'supported' ? '✓ Supported' : attr?.status === 'mismatch' ? '⚠ Mismatch' : attr?.checked ? '○ Uncertain' : '○ Not checked'}</strong></div>
            </div>
            {prec && (
              <div className="precedent-history-note">
                <strong>Precedent history</strong>
                <p>{prec.status === 'verified' ? prec.summary : 'Not checked against a comprehensive authoritative citator. This does not affect whether the retrieved passage supports the claim.'}</p>
                {prec.overruled_by && <span className="overruled-alert">Overruled in: {prec.overruled_by}</span>}
              </div>
            )}
            {s?.agreement === false && secondaryChecked && (
              <div className="duel">
                <div><h4>Groq</h4><p className="duel-verdict">{s.groq_verdict || 'unclear'}</p><p>{splitDisputed(s.reason)[0]}</p></div>
                <div><h4>{secondaryName}</h4><p className="duel-verdict">{s.gemini_verdict || 'unclear'}</p><p>{splitDisputed(s.reason)[1]}</p></div>
              </div>
            )}
            {(s?.fallback_reason || s?.gemini_skip_reason) && (
              <>
                <p>{s?.fallback_reason ? `Gemini did not complete the independent cross-check after ${s.gemini_attempts || 0} attempt(s), so LEXAI used the Groq resilience fallback.` : 'The secondary verifier was unavailable. Primary corpus verification remains valid.'}</p>
                <details className="technical-verification-error"><summary>Technical details</summary><pre>{s.fallback_reason || s.gemini_skip_reason}</pre></details>
              </>
            )}
          </details>
        </div>
      )}
    </li>
  )
}

function SourceItem({ source, max, query, answer, onDissectRatio, onFindSimilar }) {
  const info = parseSource(source.source_file)
  const [copied, setCopied] = useState(false)
  const [showText, setShowText] = useState(false)
  const pct = Math.max(4, Math.round((source.score / (max || 1)) * 100))
  async function copy() {
    try {
      await navigator.clipboard.writeText(`${info.title}${info.date ? ', decided ' + info.date : ''}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch { /* clipboard unavailable */ }
  }
  return (
    <li className="src-item">
      <div className="src-top">
        <span className="src-title">{info.title || source.case_name}</span>
        <button className="btn-quiet small" onClick={copy}>{copied ? 'Copied' : 'Copy cite'}</button>
      </div>
      <div className="src-meta">{info.year && <span className="year">{info.year}</span>}<span>Judgment source</span></div>
      <details className="rag-inspector-row"><summary>RAG Inspector</summary><div className="score-row" title={`Retrieval score ${source.score.toFixed(3)}`}><div className="bar"><div style={{ width: pct + '%' }} /></div><span>{source.score.toFixed(2)}</span></div><small title={source.source_file}>{source.source_file}</small></details>
      {source.text && (
        <div style={{ marginTop: '8px', display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn-quiet small passage-toggle" aria-expanded={showText} onClick={() => setShowText((v) => !v)}>
            {showText ? 'Hide source' : 'View supporting source'}
          </button>
          <button
            type="button"
            className="btn-quiet small ratio-btn"
            onClick={() => onDissectRatio(info.title || source.case_name, source.text)}
          >
            ⚖️ Dissect Ratio vs. Obiter
          </button>
        </div>
      )}
      <div style={{ marginTop: '8px' }}>
        <button
          type="button"
          className="btn-quiet small"
          onClick={() => onFindSimilar({ sourceFile: source.source_file, title: info.title || source.case_name, text: source.text })}
        >
          Find similar cases
        </button>
      </div>
      {source.text && showText && <Passage text={source.text} query={query} answer={answer} />}
    </li>
  )
}

export default function Evidence({ entry, focus }) {
  const [tab, setTab] = useState(entry.not_found ? 'sources' : 'citations')
  const [openSet, setOpenSet] = useState(() => new Set())
  const [ratioTarget, setRatioTarget] = useState(null)
  const [similarTarget, setSimilarTarget] = useState(null)
  const refs = useRef({})
  const cits = entry.verification?.citations || []
  const unmatched = entry.verification?.unverifiable_citations || []
  const max = entry.sources.length ? Math.max(...entry.sources.map((s) => s.score)) : 1

  useEffect(() => {
    if (!focus) return
    setTab('citations')
    const key = focus.kind === 'unverifiable' ? 'u' + focus.index : 'c' + focus.index
    setOpenSet((prev) => new Set(prev).add(key))
    setTimeout(() => refs.current[key]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 40)
  }, [focus])

  function toggle(key) {
    setOpenSet((prev) => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }

  function handleDissectRatio(caseName, passageText) {
    setRatioTarget({ caseName, passageText })
  }

  return (
    <section className="evidence" aria-label="Evidence">
      <div className="tabs" role="tablist" aria-label="Evidence" onKeyDown={(e) => tabKeys(e, ['citations', 'sources'], tab, setTab, 'ev')}>
        <button role="tab" id="ev-tab-citations" aria-controls="ev-panel-citations" aria-selected={tab === 'citations'} tabIndex={tab === 'citations' ? 0 : -1} onClick={() => setTab('citations')}>
          Citations{cits.length + unmatched.length ? ` (${cits.length + unmatched.length})` : ''}
        </button>
        <button role="tab" id="ev-tab-sources" aria-controls="ev-panel-sources" aria-selected={tab === 'sources'} tabIndex={tab === 'sources' ? 0 : -1} onClick={() => setTab('sources')}>
          Sources ({entry.sources.length})
        </button>
      </div>

      {tab === 'citations' && (
        <div role="tabpanel" id="ev-panel-citations" aria-labelledby="ev-tab-citations">
          {!entry.verification && (
            <p className="muted pad">
              {entry._verifying
                ? 'Checking citations… results appear here once the answer is complete.'
                : 'Verification was turned off for this question.'}
            </p>
          )}
          {entry.verification && cits.length + unmatched.length === 0 && (
            <p className="muted pad">The answer does not name any case, so there is nothing to verify.</p>
          )}
          <ul className="cit-list">
            {unmatched.map((u, i) => (
              <li key={'u' + i} className={`cit-item v-no ${openSet.has('u' + i) ? 'open' : ''}`} ref={(el) => (refs.current['u' + i] = el)}>
                <button className="cit-head" onClick={() => toggle('u' + i)} aria-expanded={openSet.has('u' + i)}>
                  <span className="cit-name">{u}</span>
                  <span className="pill no">Not in corpus</span>
                </button>
                {openSet.has('u' + i) && (
                  <div className="cit-body"><p className="reason">This looks like a citation, but no judgment in the corpus matches it. It may be invented, or the case may simply not be indexed.</p></div>
                )}
              </li>
            ))}
            {cits.map((c, i) => (
              <CitationItem
                key={i}
                citation={c}
                open={openSet.has('c' + i)}
                onToggle={() => toggle('c' + i)}
                refCb={(el) => (refs.current['c' + i] = el)}
                sources={entry.sources}
                query={entry.question}
                answer={entry.answer}
                onDissectRatio={handleDissectRatio}
              />
            ))}
          </ul>
        </div>
      )}

      {tab === 'sources' && (
        <div role="tabpanel" id="ev-panel-sources" aria-labelledby="ev-tab-sources">
          {entry.not_found && <p className="muted pad">Closest passages. They scored too low to answer from.</p>}
          <ul className="src-list">
            {entry.sources.map((s, i) => (
              <SourceItem
                key={i}
                source={s}
                max={max}
                query={entry.question}
                answer={entry.not_found ? '' : entry.answer}
                onDissectRatio={handleDissectRatio}
                onFindSimilar={setSimilarTarget}
              />
            ))}
            {entry.sources.length === 0 && <li className="muted pad">No passages were retrieved.</li>}
          </ul>
        </div>
      )}

      <SimilarModal target={similarTarget} onClose={() => setSimilarTarget(null)} />
      <RatioObiterModal
        isOpen={Boolean(ratioTarget)}
        onClose={() => setRatioTarget(null)}
        caseName={ratioTarget?.caseName}
        passageText={ratioTarget?.passageText}
      />
    </section>
  )
}
