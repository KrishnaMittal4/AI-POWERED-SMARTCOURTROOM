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
  const both = s?.gemini_checked
  const prec = citation.precedent_status
  return (
    <li className={`cit-item v-${verdict} ${open ? 'open' : ''}`} ref={refCb}>
      <button className="cit-head" onClick={onToggle} aria-expanded={open}>
        <span className="cit-name">{citation.case_name}</span>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
          <Pill verdict={verdict} />
          {prec && (
            <span className={`pill precedent-pill ${prec.status}`} title={prec.summary}>
              {prec.badge}
            </span>
          )}
        </div>
      </button>
      {open && (
        <div className="cit-body">
          {prec && (
            <div className={`precedent-box ${prec.status}`}>
              <div className="prec-badge-row">
                <strong>{prec.badge}</strong>
                {prec.overruled_by && <span className="overruled-alert">Overruled in: {prec.overruled_by}</span>}
              </div>
              <p className="prec-summary">{prec.summary}</p>
            </div>
          )}

          <dl>
            <dt>In corpus</dt>
            <dd>
              {citation.existence.exists_in_corpus ? 'Yes' : 'No'}
              {citation.existence.matched_files?.length > 0 && (
                <span className="files">{citation.existence.matched_files.map((f) => parseSource(f).title).join('; ')}</span>
              )}
            </dd>
          </dl>
          {s?.checked && (
            both && s.agreement === false ? (
              <div className="duel">
                <div>
                  <h4>Groq</h4>
                  <p className="duel-verdict">{s.groq_verdict || 'unclear'}</p>
                  <p>{splitDisputed(s.reason)[0]}</p>
                </div>
                <div>
                  <h4>Gemini</h4>
                  <p className="duel-verdict">{s.gemini_verdict || 'unclear'}</p>
                  <p>{splitDisputed(s.reason)[1]}</p>
                </div>
              </div>
            ) : (
              <p className="reason">{s.reason}</p>
            )
          )}
          {passages.length > 0 && (
            <div className="cit-passages">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '8px 0 4px' }}>
                <h4 style={{ margin: 0 }}>Retrieved passage{passages.length > 1 ? 's' : ''} from this case</h4>
                <button
                  type="button"
                  className="btn-quiet small ratio-btn"
                  onClick={() => onDissectRatio(citation.case_name, passages[0].text)}
                >
                  ⚖️ Dissect Ratio vs. Obiter
                </button>
              </div>
              {passages.map((p, i) => <Passage key={i} text={p.text} query={query} answer={answer} />)}
            </div>
          )}
          {both && s.agreement && <p className="agree">Groq and Gemini reached the same verdict independently.</p>}
          {s?.gemini_checked === false && s?.gemini_skip_reason && <p className="muted">Second check skipped: {s.gemini_skip_reason}</p>}
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
      <div className="src-meta">
        {info.year && <span className="year">{info.year}</span>}
        <span className="file" title={source.source_file}>{source.source_file}</span>
      </div>
      <div className="score-row" title={`Similarity score ${source.score.toFixed(3)}`}>
        <div className="bar"><div style={{ width: pct + '%' }} /></div>
        <span>{source.score.toFixed(2)}</span>
      </div>
      {source.text && (
        <div style={{ marginTop: '8px', display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn-quiet small passage-toggle" aria-expanded={showText} onClick={() => setShowText((v) => !v)}>
            {showText ? 'Hide passage' : 'Show passage'}
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
