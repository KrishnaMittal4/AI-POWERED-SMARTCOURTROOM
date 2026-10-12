import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import AnswerView from './components/AnswerView.jsx'
import Evidence from './components/Evidence.jsx'
import NotFound from './components/NotFound.jsx'
import Shortcuts from './components/Shortcuts.jsx'
import MootCourtModal from './components/MootCourtModal.jsx'
import ParticleBackground from './components/ParticleBackground.jsx'
import GavelLoader from './components/GavelLoader.jsx'
import TiltCard from './components/TiltCard.jsx'
import CitizenAdviceView from './components/CitizenAdviceView.jsx'
import DraftModal from './components/DraftModal.jsx'
import VoiceInput from './components/VoiceInput.jsx'
import { loadHistory, saveHistory, summarize, streamQuery } from './lib/utils.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const EXAMPLES = [
  'What must a complainant prove to succeed under Section 138 of the Negotiable Instruments Act?',
  'Can the accused be acquitted when the cheque was issued by a firm?',
  'When is a legal notice of dishonour considered valid?',
  'Which court has territorial jurisdiction over a cheque bounce complaint?',
]

const CITIZEN_EXAMPLES = [
  'My landlord is refusing to refund my ₹50,000 security deposit even after 2 months of vacating',
  'I was scammed on UPI for ₹15,000 by an online seller who took payment and blocked my number',
  'My employer fired me without notice and is withholding my final month salary and experience letter',
  'Ordered a mobile phone online which arrived damaged and the e-commerce company refuses a return',
]

function useLocal(key, initial) {
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(key); return s === null ? initial : JSON.parse(s) } catch { return initial }
  })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* ignore */ } }, [key, v])
  return [v, setV]
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingWider, setLoadingWider] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState(loadHistory)
  const [activeId, setActiveId] = useState(null)
  const [focus, setFocus] = useState(null)
  const [health, setHealth] = useState({ state: 'checking' })
  const [menu, setMenu] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [shortcuts, setShortcuts] = useState(false)
  const [announce, setAnnounce] = useState('')
  const focusAnswer = useRef(false)
  const [theme, setTheme] = useLocal('smart-courtroom:theme', 'dark')
  const [topK, setTopK] = useLocal('smart-courtroom:topk', 3)
  const [verify, setVerify] = useLocal('smart-courtroom:verify', true)
  const [useStreaming, setUseStreaming] = useLocal('smart-courtroom:streaming', true)
  const [customExamples, setCustomExamples] = useLocal('smart-courtroom:custom-examples', null)
  const [appMode, setAppMode] = useLocal('smart-courtroom:appMode', 'research')
  const [citizenResult, setCitizenResult] = useState(null)
  const [citizenLoading, setCitizenLoading] = useState(false)
  const [citizenDraftOpen, setCitizenDraftOpen] = useState(false)
  const [draftPrefill, setDraftPrefill] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState(null)
  const [mootOpen, setMootOpen] = useState(false)
  const [mootQuery, setMootQuery] = useState('')
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const streamControllerRef = useRef(null)

  // Streaming state
  const [streamingId, setStreamingId] = useState(null)
  const [streamingText, setStreamingText] = useState('')
  const [streamingSources, setStreamingSources] = useState(null)
  const [streamingVerifying, setStreamingVerifying] = useState(false)

  const entry = useMemo(() => history.find((h) => h.id === activeId) || null, [history, activeId])

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { saveHistory(history) }, [history])

  // move focus to the answer heading after a new answer arrives
  useEffect(() => {
    if (!loading && !loadingWider && entry && focusAnswer.current) {
      focusAnswer.current = false
      document.getElementById('answer-heading')?.focus()
    }
  }, [loading, loadingWider, entry])

  // server status
  useEffect(() => {
    let alive = true
    const ping = () =>
      fetch(`${API_BASE}/health`)
        .then((r) => r.json())
        .then((d) => alive && setHealth({ state: 'ok', chunks: d.chunks_indexed }))
        .catch(() => alive && setHealth({ state: 'down' }))
    ping()
    const t = setInterval(ping, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  // elapsed timer while waiting
  useEffect(() => {
    if (!loading && !loadingWider) return
    setElapsed(0)
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [loading, loadingWider])

  // keyboard shortcuts (off while typing in a field)
  const kbRef = useRef({})
  kbRef.current = { history, activeId, menu, settingsOpen, shortcuts }
  useEffect(() => {
    const onKey = (e) => {
      const st = kbRef.current
      const tag = document.activeElement?.tagName
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || document.activeElement?.isContentEditable
      if (e.key === 'Escape') {
        if (st.shortcuts) return // the dialog handles its own Escape
        if (st.menu) setMenu(false)
        else if (st.settingsOpen) setSettingsOpen(false)
        else if (typing) document.activeElement.blur()
        return
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || st.shortcuts) return
      if (e.key === '/') { e.preventDefault(); inputRef.current?.focus() }
      else if (e.key === '?') { e.preventDefault(); setShortcuts(true) }
      else if (e.key === 'n') { e.preventDefault(); newResearch() }
      else if (e.key === 'j' || e.key === 'k') {
        const list = st.history
        if (!list.length) return
        const i = list.findIndex((h) => h.id === st.activeId)
        const next = e.key === 'j' ? Math.min(list.length - 1, i + 1) : Math.max(0, i === -1 ? 0 : i - 1)
        const target = list[next]
        setActiveId(target.id); setQuestion(target.question); setError(null); setFocus(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Non-streaming query (legacy) ---
  const runClassic = useCallback(async (q, k, wider = false) => {
    wider ? setLoadingWider(true) : setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, top_k: k, verify }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`)
      }
      const data = await res.json()
      const item = { id: String(Date.now()), ts: Date.now(), question: q, topK: k, saved: false, ...data }
      setHistory((h) => [item, ...h.filter((x) => !(wider && x.id === activeId))])
      setActiveId(item.id)
      setFocus(null)
      focusAnswer.current = true
      if (data.not_found) setAnnounce('Not covered by the judgments. No answer was written.')
      else {
        const sum = summarize(data.verification)
        setAnnounce(`Answer ready.${sum ? ` ${sum.total} citation${sum.total === 1 ? '' : 's'} checked.` : ''}${data.weak_match ? ' Weak match.' : ''}`)
      }
    } catch (err) {
      setAnnounce('The request failed.')
      setError(
        err instanceof TypeError
          ? `Cannot reach the API at ${API_BASE}. Check that the backend is running.`
          : err.message,
      )
    } finally {
      wider ? setLoadingWider(false) : setLoading(false)
    }
  }, [verify, activeId])

  // --- Streaming query (SSE) ---
  const runStream = useCallback((q, k) => {
    setLoading(true)
    setError(null)

    const itemId = String(Date.now())
    setStreamingId(itemId)
    setStreamingText('')
    setStreamingSources(null)
    setStreamingVerifying(false)

    // Create a placeholder entry immediately
    const placeholder = { id: itemId, ts: Date.now(), question: q, topK: k, saved: false, answer: '', sources: [], verification: null, not_found: false, _verifying: verify }
    setHistory((h) => [placeholder, ...h])
    setActiveId(itemId)
    setFocus(null)

    let accumulatedText = ''

    const controller = streamQuery({
      question: q,
      top_k: k,
      verify,
      onSources: (data) => {
        setStreamingSources(data.sources)
        // Update the history entry with sources
        setHistory((h) => h.map((x) =>
          x.id === itemId ? {
            ...x,
            sources: data.sources,
            top_score: data.top_score,
            weak_match: data.weak_match,
            not_found: data.not_found ?? false,
            threshold: data.threshold,
            rewritten_query: data.rewritten_query,
          } : x
        ))
      },
      onToken: (token) => {
        accumulatedText += token
        setStreamingText(accumulatedText)
        // Update the answer in the history entry in real time
        setHistory((h) => h.map((x) =>
          x.id === itemId ? { ...x, answer: accumulatedText, _streamingText: accumulatedText } : x
        ))
      },
      onVerification: (data) => {
        setStreamingVerifying(false)
        setHistory((h) => h.map((x) =>
          x.id === itemId ? { ...x, verification: data.verification, _verifying: false } : x
        ))
      },
      onDone: (data) => {
        setLoading(false)
        setStreamingId(null)
        setStreamingText('')
        setStreamingSources(null)
        // Final update with the complete answer
        setHistory((h) => h.map((x) =>
          x.id === itemId ? { ...x, answer: data.answer, not_found: data.not_found ?? x.not_found, statutory_fallback: data.statutory_fallback ?? false, _streamingText: undefined, _verifying: false } : x
        ))
        focusAnswer.current = true
        setAnnounce('Answer ready.')
      },
      onError: (errorMsg) => {
        setLoading(false)
        setStreamingId(null)
        setStreamingText('')
        setAnnounce('The request failed.')
        setError(errorMsg)
        setHistory((h) => h.map((x) => (x.id === itemId ? { ...x, _verifying: false } : x)))
      },
    })

    streamControllerRef.current = controller


  }, [verify])

  const run = useCallback((q, k, wider = false) => {
    if (useStreaming && !wider) {
      runStream(q, k)
    } else {
      runClassic(q, k, wider)
    }
  }, [useStreaming, runStream, runClassic])

  async function runCitizenAdvice(incidentText) {
    setCitizenLoading(true)
    setError(null)
    setCitizenResult(null)
    setActiveId(null)
    try {
      const res = await fetch(`${API_BASE}/citizen-advice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incident: incidentText }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(typeof d.detail === 'string' ? d.detail : `Request failed (${res.status})`)
      }
      const data = await res.json()
      setCitizenResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setCitizenLoading(false)
    }
  }

  function submit(e) {
    e?.preventDefault()
    const q = question.trim()
    if (q.length < 3 || loading || citizenLoading) return
    if (appMode === 'citizen') {
      runCitizenAdvice(q)
    } else {
      run(q, topK)
    }
  }

  function newResearch() {
    // Cancel any in-progress stream
    if (streamControllerRef.current) {
      streamControllerRef.current.abort()
      streamControllerRef.current = null
    }
    setActiveId(null); setError(null); setQuestion(''); setFocus(null); setCitizenResult(null)
    setStreamingId(null); setStreamingText(''); setStreamingSources(null)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  function openItem(id) {
    const h = history.find((x) => x.id === id)
    setActiveId(id); setQuestion(h?.question || ''); setError(null); setFocus(null)
  }

  const toggleSave = (id) => setHistory((h) => h.map((x) => (x.id === id ? { ...x, saved: !x.saved } : x)))
  const remove = (id) => { setHistory((h) => h.filter((x) => x.id !== id)); if (id === activeId) setActiveId(null) }
  const jump = (kind, index) => setFocus({ kind, index, n: Date.now() })

  const isStreaming = streamingId && streamingId === activeId

  const handleFileUpload = async (e) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    setUploadStatus({ type: 'info', msg: `Uploading and indexing ${files.length} PDF(s)...` })

    const formData = new FormData()
    for (let i = 0; i < files.length; i++) {
      formData.append('files', files[i])
    }

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Upload failed (${res.status})`)

      const skippedNote = data.skipped?.length ? ` Skipped: ${data.skipped.join('; ')}.` : ''
      setUploadStatus({
        type: data.new_chunks_count ? 'success' : 'info',
        msg: (data.new_chunks_count
          ? `Indexed ${data.uploaded_files?.length || 0} PDF(s) into ${data.new_chunks_count} new chunks. Total passages: ${data.total_chunks}.`
          : 'Nothing was indexed.') + skippedNote,
      })
      if (data.suggested_questions && data.suggested_questions.length > 0) {
        setCustomExamples({
          filename: data.source_filename || (data.uploaded_files && data.uploaded_files[0]) || 'Uploaded Document',
          questions: data.suggested_questions,
        })
      }
      setHealth((prev) => ({ ...prev, chunks: data.total_chunks }))
    } catch (err) {
      setUploadStatus({ type: 'error', msg: err.message })
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="shell">
      <ParticleBackground theme={theme} />
      <a className="skip" href="#main-content">Skip to results</a>
      <div className="sr-only" role="status" aria-live="polite">{announce}</div>
      <header className="topbar">
        <button className="icon-btn menu-btn" onClick={() => setMenu((m) => !m)} aria-label="Toggle history" aria-expanded={menu} aria-controls="sidebar">☰</button>
        <div className="brand">
          <div className="brand-icon" aria-hidden="true">⚖</div>
          <div className="brand-text">
            <span className="brand-name">LexAI</span>
            <span className="brand-sub">Legal Intelligence · Verified Citations</span>
          </div>
        </div>
        <div className="top-right">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            multiple
            accept=".pdf"
            style={{ display: 'none' }}
          />
          <button
            className="btn-quiet"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            title="Upload judgment PDFs to index"
          >
            <span>📁</span>
            <span>{uploading ? 'Indexing…' : 'Upload PDFs'}</span>
          </button>
          <button
            className="moot-nav-btn"
            onClick={() => { setMootQuery(question || ''); setMootOpen(true) }}
            title="Open the Virtual Moot Court Arena"
          >
            <span>⚖️</span>
            <span>Moot Court</span>
          </button>
          <span className={`status ${health.state}`} title={health.state === 'ok' ? `${health.chunks} passages indexed` : health.state === 'down' ? 'API not reachable' : 'Checking API'}>
            <i aria-hidden="true" />
            {health.state === 'ok' ? `${health.chunks} passages` : health.state === 'down' ? 'API offline' : 'Connecting'}
          </span>
          <button className="btn-quiet" onClick={() => setShortcuts(true)} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">?</button>
          <button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>{theme === 'dark' ? '☀️' : '🌙'}</button>
        </div>
      </header>

      {uploadStatus && (
        <div className={`upload-bar ${uploadStatus.type}`}>
          <span>{uploadStatus.msg}</span>
          <button
            onClick={() => setUploadStatus(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '16px', lineHeight: 1 }}
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}


      <div className="layout">
        <Sidebar
          history={history} activeId={activeId} open={menu}
          onOpen={openItem} onNew={newResearch} onToggleSave={toggleSave}
          onDelete={remove} onClear={() => { setHistory([]); setActiveId(null) }} onClose={() => setMenu(false)}
        />
        {menu && <div className="scrim" onClick={() => setMenu(false)} />}

        <main className="main" id="main-content" tabIndex={-1}>
          {/* Show the compact ask bar only when viewing results */}
          {(entry || loading || error) && (
          <form className="ask" onSubmit={submit} role="search">
            <div className="ask-row">
              <input
                ref={inputRef}
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a legal question  ( press / to focus )"
                aria-label="Legal question"
              />
              <VoiceInput
                onTranscript={(text, isFinal) => {
                  setQuestion((prev) => (isFinal ? (prev ? `${prev} ${text}` : text) : text))
                }}
                disabled={loading || citizenLoading}
              />
              <button className="btn-primary" type="submit" disabled={loading || question.trim().length < 3}>{loading ? 'Researching…' : 'Ask'}</button>
              <button type="button" className="btn-quiet" onClick={() => setSettingsOpen((s) => !s)} aria-expanded={settingsOpen}>Options</button>
            </div>
            {settingsOpen && (
              <div className="options">
                <label>
                  Passages to retrieve: <b>{topK}</b>
                  <input type="range" min="1" max="10" value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
                </label>
                <label className="check">
                  <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />
                  Verify citations (slower, uses both checking models)
                </label>
                <label className="check">
                  <input type="checkbox" checked={useStreaming} onChange={(e) => setUseStreaming(e.target.checked)} />
                  Stream answer (shows tokens as they arrive)
                </label>
              </div>
            )}
          </form>
          )}

          {error && (
            <div className="error" role="alert">
              <div>{error}</div>
              <button className="btn-quiet" onClick={() => run(question.trim(), topK)}>Try again</button>
            </div>
          )}

          {(loading || citizenLoading) && !isStreaming && (
            <GavelLoader elapsed={elapsed} verify={verify && !citizenLoading} />
          )}

          {!loading && !citizenLoading && !entry && !citizenResult && !error && (
            <div className="home-hero">
              {/* Mode Switcher Toggle */}
              <div className="mode-switcher-bar" role="tablist" aria-label="Platform Mode">
                <button
                  type="button"
                  className={`mode-switcher-btn ${appMode === 'research' ? 'active' : ''}`}
                  onClick={() => { setAppMode('research'); setCitizenResult(null); setError(null) }}
                >
                  <span>⚖️</span>
                  <span>Advocate Research</span>
                </button>
                <button
                  type="button"
                  className={`mode-switcher-btn ${appMode === 'citizen' ? 'active' : ''}`}
                  onClick={() => { setAppMode('citizen'); setError(null) }}
                >
                  <span>🛡️</span>
                  <span>Citizen Advisor ("Is There a Law for This?")</span>
                </button>
              </div>

              <div className="hero-eyebrow">
                {appMode === 'citizen' ? '🛡️ Everyday Citizen Legal Advisor · No Jargon' : '⚖ Indian Legal Intelligence System'}
              </div>
              <h1 className="hero-title">
                {appMode === 'citizen' ? (
                  <>Describe what happened to you.<br />We'll tell you the law.</>
                ) : (
                  <>What do you want to find<br />in the judgments?</>
                )}
              </h1>
              <p className="hero-subtitle">
                {appMode === 'citizen'
                  ? 'Tell us your issue in plain English or Hinglish. We identify the applicable Indian laws, your legal rights, and give you an exact 3-step action roadmap.'
                  : 'Every answer is sourced exclusively from your uploaded judgments corpus — with each cited case checked, verified, and colour-coded for accuracy.'}
              </p>

              {appMode === 'citizen' ? (
                <div className="feature-pills" style={{ justifyContent: 'center', marginBottom: '32px' }}>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Applicable Acts & Sections</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Civil vs Criminal Remedy</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />3-Step Action Roadmap</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />1-Click Notice Drafting</TiltCard>
                </div>
              ) : (
                <div className="feature-pills" style={{ justifyContent: 'center', marginBottom: '32px' }}>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Citation Verification</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Moot Court Simulation</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Legal Draft Generator</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Precedent Analysis</TiltCard>
                </div>
              )}

              {/* Big Hero Chat Input */}
              <form className="hero-chat-form" onSubmit={submit}>
                <div className="hero-chat-box">
                  <textarea
                    ref={inputRef}
                    className="hero-chat-textarea"
                    rows={3}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(e) } }}
                    placeholder={
                      appMode === 'citizen'
                        ? 'Describe what happened in simple words — e.g. My landlord refuses to refund my security deposit of ₹50,000 even after 2 months of vacating the flat...'
                        : 'Ask a legal question — e.g. What must a complainant prove to succeed under Section 138 NI Act?'
                    }
                    aria-label="Legal question"
                    id="hero-question-input"
                  />
                  <div className="hero-chat-footer">
                    <span className="hero-chat-hint">Press Enter to ask · Shift+Enter for new line</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <VoiceInput
                        onTranscript={(text, isFinal) => {
                          setQuestion((prev) => isFinal ? (prev ? `${prev} ${text}` : text) : text)
                        }}
                        disabled={loading || citizenLoading}
                      />
                      <button
                        className="hero-ask-btn"
                        type="submit"
                        disabled={loading || citizenLoading || question.trim().length < 3}
                        id="hero-ask-btn"
                      >
                        {citizenLoading ? 'Analyzing Law…' : loading ? 'Researching…' : appMode === 'citizen' ? '🛡️ Check My Legal Rights' : '⚖ Ask LexAI'}
                      </button>
                    </div>
                  </div>
                </div>
              </form>

              {/* Example suggestions */}
              <div className="hero-examples">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <div className="hero-examples-label" style={{ margin: 0 }}>
                    {appMode === 'citizen' ? (
                      'Try these everyday citizen scenarios:'
                    ) : customExamples?.filename ? (
                      <span>
                        📄 Questions from <b style={{ color: 'var(--gold)' }}>{customExamples.filename}</b>:
                      </span>
                    ) : (
                      'Try these questions:'
                    )}
                  </div>
                  {appMode === 'research' && customExamples && (
                    <button
                      type="button"
                      className="btn-quiet small"
                      onClick={() => setCustomExamples(null)}
                      style={{ fontSize: '11px', padding: '2px 8px' }}
                      title="Reset to default legal questions"
                    >
                      ↺ Reset to default
                    </button>
                  )}
                </div>
                <div className="hero-example-chips">
                  {(appMode === 'citizen'
                    ? CITIZEN_EXAMPLES
                    : customExamples?.questions?.length
                    ? customExamples.questions
                    : EXAMPLES
                  ).map((ex) => (
                    <TiltCard
                      key={ex}
                      as="button"
                      className="hero-example-chip"
                      onClick={() => {
                        setQuestion(ex)
                        if (appMode === 'citizen') {
                          runCitizenAdvice(ex)
                        } else {
                          run(ex, topK)
                        }
                      }}
                      type="button"
                      maxTilt={4}
                    >
                      {ex}
                    </TiltCard>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Citizen Advice Results */}
          {citizenResult && !citizenLoading && (
            <CitizenAdviceView
              advice={citizenResult}
              onOpenDraft={(draft) => {
                setDraftPrefill({
                  draftType: draft?.type || 'legal_notice_recovery',
                  facts: draft?.prefilled_facts || citizenResult.incident,
                })
                setCitizenDraftOpen(true)
              }}
              onReset={() => {
                setCitizenResult(null)
                setQuestion('')
              }}
            />
          )}

          {((!loading && entry) || isStreaming) && entry && (
            <div className="result-grid">
              {entry.not_found && !isStreaming ? (
                <NotFound entry={entry} examples={customExamples?.questions?.length ? customExamples.questions : EXAMPLES} onRephrase={() => inputRef.current?.focus()} onAsk={(q) => { setQuestion(q); run(q, topK) }} />
              ) : (
                <AnswerView
                  entry={entry} onJump={jump} onToggleSave={toggleSave}
                  loadingWider={loadingWider}
                  onAsk={(q) => { setQuestion(q); run(q, topK) }}
                  onRetryWider={() => run(entry.question, Math.min(10, (entry.topK || topK) + 4), true)}
                  streaming={isStreaming}
                  onOpenMootCourt={(q) => { setMootQuery(q || ''); setMootOpen(true) }}
                />
              )}
              <Evidence key={entry.id} entry={entry} focus={focus} />
            </div>
          )}
        </main>
      </div>
      {shortcuts && <Shortcuts onClose={() => setShortcuts(false)} />}
      <MootCourtModal
        isOpen={mootOpen}
        onClose={() => setMootOpen(false)}
        initialQuery={mootQuery}
      />
      <DraftModal
        isOpen={citizenDraftOpen}
        onClose={() => { setCitizenDraftOpen(false); setDraftPrefill(null) }}
        prefill={draftPrefill}
      />
    </div>
  )
}
