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
import CaseWorkspace from './components/CaseWorkspace.jsx'
import CasesDashboard from './components/CasesDashboard.jsx'
import RagLab from './components/RagLab.jsx'
import { loadHistory, saveHistory, summarize, streamQuery } from './lib/utils.js'
import { apiFetch } from './lib/auth.js'

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8000'

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

export default function App({ user, onLogout }) {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingWider, setLoadingWider] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null)
  const [cases, setCases] = useState([])
  const [activeCaseId, setActiveCaseId] = useState(() => localStorage.getItem(`smart-courtroom:active-case:${user.id}`) || '')
  const [history, setHistory] = useState(() => loadHistory(`${user.id}:global`))
  const [activeId, setActiveId] = useState(null)
  const [focus, setFocus] = useState(null)
  const [health, setHealth] = useState({ state: 'checking' })
  const [healthOpen, setHealthOpen] = useState(false)
  const [menu, setMenu] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [shortcuts, setShortcuts] = useState(false)
  const [announce, setAnnounce] = useState('')
  const focusAnswer = useRef(false)
  const [theme, setTheme] = useLocal('smart-courtroom:theme', 'dark')
  const [accent, setAccent] = useLocal('smart-courtroom:accent', 'indigo')
  const [topK, setTopK] = useLocal('smart-courtroom:topk', 3)
  const [verify, setVerify] = useLocal('smart-courtroom:verify', true)
  const [useStreaming, setUseStreaming] = useLocal('smart-courtroom:streaming', true)
  const [ragInspector, setRagInspector] = useLocal('smart-courtroom:rag-inspector', false)
  const [ragLabOpen, setRagLabOpen] = useState(false)
  const openRagLab = (e) => {
    e?.preventDefault?.()
    e?.stopPropagation?.()
    setRagLabOpen(true)
  }
  const [researchSource, setResearchSource] = useLocal('smart-courtroom:research-source', 'judgments')
  const [customExamples, setCustomExamples] = useLocal('smart-courtroom:custom-examples', null)
  const [appMode, setAppMode] = useLocal('smart-courtroom:appMode', 'research')
  const [citizenResult, setCitizenResult] = useState(null)
  const [citizenLoading, setCitizenLoading] = useState(false)
  const [citizenDraftOpen, setCitizenDraftOpen] = useState(false)
  const [draftPrefill, setDraftPrefill] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFiles, setUploadFiles] = useState([])
  const [existingJudgments, setExistingJudgments] = useState(new Set())
  const [replaceExisting, setReplaceExisting] = useState(false)
  const [mootOpen, setMootOpen] = useState(false)
  const [casesOpen, setCasesOpen] = useState(false)
  const [mootQuery, setMootQuery] = useState('')
  const [quickPdfUploading, setQuickPdfUploading] = useState(false)
  const [initialCaseTab, setInitialCaseTab] = useState('overview')
  const [initialCaseMode, setInitialCaseMode] = useState(null)
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const quickPdfInputRef = useRef(null)
  const streamControllerRef = useRef(null)

  // Streaming state
  const [streamingId, setStreamingId] = useState(null)
  const [streamingText, setStreamingText] = useState('')
  const [streamingSources, setStreamingSources] = useState(null)
  const [streamingVerifying, setStreamingVerifying] = useState(false)

  const activeCase = useMemo(() => cases.find((c) => c.id === activeCaseId) || null, [cases, activeCaseId])
  const globalCorpusAvailable = health.capabilities?.global_judgment_corpus === true
  const developerToolsAvailable = health.capabilities?.developer_tools === true
  const historyScope = `${user.id}:${activeCaseId || 'global'}`
  const entry = useMemo(() => history.find((h) => h.id === activeId) || null, [history, activeId])

  useEffect(() => {
    const action = sessionStorage.getItem('lexai:post-auth-action')
    if (!action) return
    sessionStorage.removeItem('lexai:post-auth-action')
    if (action === 'upload') { setAnnounce('Signed in. Choose a judgment or case PDF to research.'); setTimeout(() => quickPdfInputRef.current?.click(), 120) }
    if (action === 'cases') { setCasesOpen(true); setAnnounce('Signed in. Open your private case workspace.') }
    if (action === 'moot') setMootOpen(true)
    if (action === 'draft') setCitizenDraftOpen(true)
    if (action === 'ask') setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { document.documentElement.dataset.accent = accent }, [accent])
  useEffect(() => { saveHistory(history, historyScope) }, [history, historyScope])
  useEffect(() => {
    apiFetch(`${API_BASE}/cases`).then(r => r.json()).then(d => setCases(d.cases || [])).catch(() => {})
  }, [])
  useEffect(() => {
    localStorage.setItem(`smart-courtroom:active-case:${user.id}`, activeCaseId)
    setHistory(loadHistory(historyScope)); setActiveId(null); setQuestion(''); setCitizenResult(null); setError(null)
  }, [activeCaseId])

  async function refreshCases() {
    const r = await apiFetch(`${API_BASE}/cases`); if (r.ok) setCases((await r.json()).cases || [])
  }
  async function makeCase() {
    const title = window.prompt('Case title (for example: State vs Sharma)')?.trim(); if (!title) return
    const description = window.prompt('Short case description (optional)') || ''
    const r = await apiFetch(`${API_BASE}/cases`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title,description}) })
    const d = await r.json(); if (!r.ok) { setError(d.detail || 'Could not create case.'); return }
    await refreshCases(); setActiveCaseId(d.case.id)
  }
  async function removeActiveCase() {
    if (!activeCase || !window.confirm(`Delete case workspace “${activeCase.title}” and its private documents?`)) return
    const r = await apiFetch(`${API_BASE}/cases/${activeCase.id}`, {method:'DELETE'}); if (!r.ok) return
    setActiveCaseId(''); await refreshCases()
  }
  async function deleteCaseById(caseId) {
    const r = await apiFetch(`${API_BASE}/cases/${caseId}`, {method:'DELETE'})
    if (!r.ok) { const d=await r.json().catch(()=>({})); throw new Error(d.detail || 'Could not delete case.') }
    if (activeCaseId===caseId) setActiveCaseId('')
    await refreshCases()
    setUploadStatus({type:'success',msg:'Case and its private workspace data were permanently deleted.'})
  }

  async function handleQuickPdfUpload(e) {
    const file = e.target?.files?.[0]
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a valid PDF case document.')
      return
    }
    setQuickPdfUploading(true)
    setError(null)
    setAnnounce('Uploading and indexing case PDF…')
    try {
      const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/[_-]+/g, ' ').trim()
      const title = cleanName ? `Matter: ${cleanName.slice(0, 40)}` : 'Private Legal Matter'

      // 1. Create new case workspace for this document
      const rCase = await apiFetch(`${API_BASE}/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          description: `Imported from ${file.name} · Ready for citation verification & questions`
        })
      })
      const dCase = await rCase.json().catch(() => ({}))
      if (!rCase.ok) throw new Error(dCase.detail || 'Could not create workspace for this PDF.')

      const newCaseId = dCase.case.id

      // 2. Upload and index document
      const formData = new FormData()
      formData.append('files', file)
      const rDoc = await apiFetch(`${API_BASE}/cases/${newCaseId}/documents`, {
        method: 'POST',
        body: formData
      })
      const dDoc = await rDoc.json().catch(() => ({}))
      if (!rDoc.ok) throw new Error(dDoc.detail || 'Failed to upload and index document.')

      // 3. Refresh and open directly into "Ask LEXAI" — case-only mode (no global corpus search)
      await refreshCases()
      setInitialCaseTab('ask')
      setInitialCaseMode('case')
      setActiveCaseId(newCaseId)
      setCasesOpen(false)
      setUploadStatus({
        type: 'success',
        msg: `"${file.name}" uploaded and indexed! Ask any question below to verify citations.`
      })
      setAnnounce('Case PDF uploaded and indexed.')
    } catch (err) {
      setError(err.message || 'Could not upload PDF.')
      setAnnounce('Upload failed.')
    } finally {
      setQuickPdfUploading(false)
      if (e.target) e.target.value = ''
    }
  }

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
      apiFetch(`${API_BASE}/health`)
        .then((r) => r.json())
        .then((d) => { if (!alive) return; setHealth({ state: 'ok', chunks: d.chunks_indexed, providers: d.providers, capabilities: d.capabilities || {}, environment: d.environment }); if (d.capabilities?.global_judgment_corpus === false) setResearchSource('general') })
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

  // --- Query execution: PDF data if uploaded/active, else General Legal AI ---
  const runClassic = useCallback(async (q, k, wider = false) => {
    wider ? setLoadingWider(true) : setLoading(true)
    setError(null)
    try {
      // 1. If user has an active case / uploaded PDF, query the case PDF with verified citations
      if (activeCaseId) {
        const res = await apiFetch(`${API_BASE}/cases/${activeCaseId}/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q, mode: 'case', top_k: k, verify }),
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
        setAnnounce('Case PDF analysis ready.')
        return
      }

      // 2. Otherwise (no PDF uploaded), answer using General Legal AI
      const res = await apiFetch(`${API_BASE}/query/general`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, top_k: k, verify: false }),
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
      setAnnounce('General legal analysis ready.')
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
  }, [verify, activeId, activeCaseId])

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
    // Only stream when: streaming is ON, not a wider search, global corpus is available, AND there is no active case PDF.
    // With no global corpus (Render free mode) or an active case PDF, always use runClassic which routes correctly.
    const canStream = useStreaming && !wider && globalCorpusAvailable && !activeCaseId && researchSource !== 'general'
    if (canStream) {
      runStream(q, k)
    } else {
      runClassic(q, k, wider)
    }
  }, [useStreaming, runStream, runClassic, researchSource, globalCorpusAvailable, activeCaseId])

  async function runCitizenAdvice(incidentText) {
    setCitizenLoading(true)
    setError(null)
    setCitizenResult(null)
    setActiveId(null)
    try {
      const res = await apiFetch(`${API_BASE}/citizen-advice`, {
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
    // New Research always opens a clean Advocate Research session.
    setAppMode('research')
    setCasesOpen(false)
    // Cancel any in-progress stream
    if (streamControllerRef.current) {
      streamControllerRef.current.abort()
      streamControllerRef.current = null
    }
    setActiveId(null); setError(null); setQuestion(''); setFocus(null); setCitizenResult(null); setResearchSource('judgments')
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

  async function openJudgmentUpload() {
    if (!globalCorpusAvailable) return
    setUploadStatus(null)
    setReplaceExisting(false)
    setUploadFiles([])
    try {
      const r = await apiFetch(`${API_BASE}/documents`)
      const docs = r.ok ? await r.json() : []
      setExistingJudgments(new Set((docs || []).map(d => d.filename)))
    } catch { setExistingJudgments(new Set()) }
    setUploadOpen(true)
  }

  function stageJudgments(fileList) {
    const chosen = [...(fileList || [])]
    const seen = new Set()
    setUploadFiles(chosen.map(file => {
      let status = 'ready', note = 'Ready to index'
      if (!file.name.toLowerCase().endsWith('.pdf') || file.type && file.type !== 'application/pdf') { status='invalid'; note='PDF files only' }
      else if (seen.has(file.name)) { status='invalid'; note='Duplicate selection' }
      else if (existingJudgments.has(file.name)) { status='exists'; note='Already in Knowledge Base' }
      seen.add(file.name)
      return { file, status, note }
    }))
  }

  async function uploadStagedJudgments() {
    const candidates = uploadFiles.filter(x => x.status === 'ready' || (replaceExisting && x.status === 'exists'))
    if (!candidates.length) { setUploadStatus({type:'info',msg:'Nothing new to upload.'}); return }
    setUploading(true)
    setUploadFiles(items => items.map(x => candidates.includes(x) ? {...x,status:'uploading',note: replaceExisting && x.status==='exists' ? 'Replacing…' : 'Indexing…'} : x))
    const formData = new FormData(); candidates.forEach(x => formData.append('files', x.file))
    try {
      const res = await apiFetch(`${API_BASE}/upload?replace_existing=${replaceExisting ? 'true' : 'false'}`, {method:'POST',body:formData})
      const data = await res.json().catch(()=>({}))
      if (!res.ok) throw new Error(typeof data.detail==='string'?data.detail:`Upload failed (${res.status})`)
      const uploaded = new Set(data.uploaded_files || [])
      setUploadFiles(items => items.map(x => uploaded.has(x.file.name) ? {...x,status:'done',note:'Indexed successfully'} : x.status==='uploading' ? {...x,status:'exists',note:'Already in Knowledge Base'} : x))
      setHealth(prev=>({...prev,chunks:data.total_chunks}))
      setUploadStatus({type: uploaded.size ? 'success':'info', msg: uploaded.size ? `${uploaded.size} judgment PDF${uploaded.size===1?'':'s'} added to the Legal Knowledge Base.` : 'No new judgments were added.'})
      if (data.suggested_questions?.length) setCustomExamples({filename:data.source_filename || [...uploaded][0] || 'Uploaded Document',questions:data.suggested_questions})
      setTimeout(()=>setUploadStatus(null),4500)
    } catch(err) {
      setUploadFiles(items=>items.map(x=>x.status==='uploading'?{...x,status:'error',note:err.message}:x))
      setUploadStatus({type:'error',msg:err.message})
    } finally { setUploading(false); if(fileInputRef.current) fileInputRef.current.value='' }
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
          <div className="product-mode-nav" role="tablist" aria-label="LEXAI mode">
            <button className={appMode==='research'?'active':''} onClick={()=>{setAppMode('research');setCitizenResult(null);setActiveCaseId('');setCasesOpen(false)}}>Advocate Research</button>
            <button className={appMode==='citizen'?'active':''} onClick={()=>{setAppMode('citizen');setActiveCaseId('');setCasesOpen(false);setError(null)}}>Citizen Advisor</button>
          </div>
          <input type="file" ref={fileInputRef} onChange={(e)=>stageJudgments(e.target.files)} multiple accept=".pdf" style={{display:'none'}} />
          <div className="health-wrap"><button className={`status ${health.state}`} onClick={()=>setHealthOpen(v=>!v)} title="System status"><i aria-hidden="true" />{health.state==='ok'?'System':health.state==='down'?'Offline':'Connecting'}</button>{healthOpen&&<div className="health-popover"><b>LEXAI System</b><div><span>Legal Knowledge Base</span><strong className={health.state==='ok'?'ok':'warn'}>{health.state==='ok'?'Indexed & Ready':'Unavailable'}</strong></div><div><span>Groq</span><strong className={health.providers?.groq?.configured?'ok':'warn'}>{health.providers?.groq?.configured?'Configured':'Not configured'}</strong></div><div><span>Gemini</span><strong className={health.providers?.gemini?.configured&&health.providers?.gemini?.sdk_available?'ok':'warn'}>{health.providers?.gemini?.configured?(health.providers?.gemini?.sdk_available?'Configured':'SDK issue'):'Not configured'}</strong></div><small>Health view does not consume provider quota.</small></div>}</div>
          <div className="user-chip" title={user.email}><span className="user-avatar">{(user.name || user.email).charAt(0).toUpperCase()}</span><span className="user-chip-text"><b>{user.name}</b><small>{user.email}</small></span></div>
          <button className="btn-quiet" onClick={onLogout} title="Sign out">Sign out</button>
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
          appMode={appMode}
          globalCorpusAvailable={globalCorpusAvailable}
          onUploadResearch={()=>{setAppMode('research');setActiveCaseId('');setCasesOpen(false);setTimeout(()=>quickPdfInputRef.current?.click(),50)}}
          onGlobal={()=>{setAppMode('research');setActiveCaseId('');setCasesOpen(false);newResearch()}}
          onCases={()=>{setAppMode('research');setActiveCaseId('');setCasesOpen(true);setActiveId(null);setCitizenResult(null)}}
          onMoot={()=>{setMootQuery(question||'');setMootOpen(true)}}
          onDraft={()=>{setDraftPrefill(null);setCitizenDraftOpen(true)}}
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
                value={question}
                onTranscript={(text) => setQuestion(text)}
                disabled={loading || citizenLoading}
              />
              <button className="btn-primary" type="submit" disabled={loading || question.trim().length < 3}>{loading ? 'Researching…' : 'Ask'}</button>
              <button type="button" className="btn-quiet" onClick={() => setSettingsOpen((s) => !s)} aria-expanded={settingsOpen}>Options</button>
            </div>
            {settingsOpen && (
              <div className="options">
                <label className="check">
                  <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />
                  {activeCaseId ? 'Verify citations against uploaded case PDF' : 'Verify legal citations and propositions'}
                </label>
                <label className="check">
                  <input type="checkbox" checked={useStreaming} onChange={(e) => setUseStreaming(e.target.checked)} />
                  Stream answer as it is generated
                </label>
                <div className="appearance-setting">
                  <div className="appearance-heading"><div><b>Appearance</b><small>Accent color</small></div><span className="accent-current">{accent}</span></div>
                  <div className="accent-picker" role="radiogroup" aria-label="Accent color">
                    {[
                      ['indigo','#6366f1'],['blue','#3b82f6'],['emerald','#22c55e'],
                      ['teal','#14b8a6'],['purple','#8b5cf6'],['gold','#f59e0b']
                    ].map(([name,color]) => (
                      <button key={name} type="button" role="radio" aria-checked={accent===name}
                        className={`accent-swatch ${accent===name?'active':''}`}
                        onClick={()=>setAccent(name)} title={`${name[0].toUpperCase()+name.slice(1)} accent`}>
                        <span style={{background:color}} />{name}
                      </button>
                    ))}
                  </div>
                  <small className="appearance-note">Green, amber and red remain reserved for verification, warnings and errors.</small>
                </div>
                {developerToolsAvailable && globalCorpusAvailable && <details className="rag-inspector-settings" open={ragInspector}>
                  <summary onClick={(e)=>{e.preventDefault();setRagInspector(!ragInspector)}}>Developer · RAG Inspector</summary>
                  <p>Technical retrieval controls are hidden from normal research. Use these for evaluation and viva demonstrations.</p>
                  <div className="rag-lab-launch-row">
                    <button type="button" className="btn-primary rag-lab-launch" onMouseDown={(e)=>e.stopPropagation()} onClick={openRagLab}>Open RAG Lab</button>
                    <small>Inspector · 100-question benchmark · Adaptive V4.1</small>
                  </div>
                  <label>Retrieved candidates: <b>{topK}</b><input type="range" min="1" max="10" value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></label>
                </details>}
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

          {!loading && !citizenLoading && !entry && !citizenResult && !error && casesOpen && (
            <CasesDashboard cases={cases} onCreate={makeCase} onDelete={deleteCaseById} onOpen={(id)=>{setActiveCaseId(id);setCasesOpen(false)}} />
          )}
          {!loading && !citizenLoading && !entry && !citizenResult && !error && activeCase && !casesOpen && (
            <CaseWorkspace
              activeCase={activeCase}
              capabilities={health.capabilities||{}}
              onCaseChanged={refreshCases}
              onBack={()=>{setActiveCaseId('');setCasesOpen(true);setInitialCaseTab('overview');setInitialCaseMode(null)}}
              onDeleteCase={()=>deleteCaseById(activeCase.id)}
              initialTab={initialCaseTab}
              initialQuestion={question}
              initialMode={initialCaseMode}
            />
          )}

          {!loading && !citizenLoading && !entry && !citizenResult && !error && !activeCase && !casesOpen && (
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
                  <>Analyze your case.<br />Ground every fact in evidence.</>
                )}
              </h1>
              <p className="hero-subtitle">
                {appMode === 'citizen'
                  ? 'Tell us your issue in plain English or Hinglish. We identify the applicable Indian laws, your legal rights, and give you an exact 3-step action roadmap.'
                  : 'Ask any legal question for instant analysis, or upload a case PDF to ground every fact and argument in evidence.'}
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
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Citation & Evidence Verification</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Moot Court Simulation</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Legal Draft Generator</TiltCard>
                  <TiltCard as="span" className="feature-pill" maxTilt={8}><span className="dot" />Private Document Research</TiltCard>
                </div>
              )}

              {appMode === 'research' && (
                <div className="advocate-tool-strip" aria-label="Advocate tools">
                  <input
                    ref={quickPdfInputRef}
                    type="file"
                    accept=".pdf,application/pdf"
                    style={{ display: 'none' }}
                    onChange={handleQuickPdfUpload}
                  />
                  <button
                    type="button"
                    onClick={() => quickPdfInputRef.current?.click()}
                    disabled={quickPdfUploading}
                    className="quick-upload-card"
                  >
                    <span>📄</span>
                    <b>{quickPdfUploading ? 'Indexing PDF…' : 'Upload & Research PDF'}</b>
                    <small>Judgment, order or case file · ask questions with verified sources</small>
                  </button>
                  {globalCorpusAvailable && <button type="button" onClick={openJudgmentUpload} disabled={uploading}><span>📁</span><b>{uploading ? 'Indexing PDFs…' : 'Upload Judgments'}</b><small>Add judgments to the research corpus</small></button>}
                  <button type="button" onClick={() => setCasesOpen(true)}><span>🗂️</span><b>My Cases</b><small>Open private case workspaces</small></button>
                  <button type="button" onClick={() => { setMootQuery(question || ''); setMootOpen(true) }}><span>⚖️</span><b>Moot Court</b><small>Simulate arguments before an AI bench</small></button>
                  <button type="button" onClick={() => { setDraftPrefill(null); setCitizenDraftOpen(true) }}><span>✎</span><b>Legal Drafting</b><small>Prepare a structured legal draft</small></button>
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
                      <button
                        type="button"
                        className="hero-attach-pdf-btn"
                        onClick={() => quickPdfInputRef.current?.click()}
                        disabled={quickPdfUploading}
                        title="Upload a PDF case file to ask questions and verify citations"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          padding: '6px 12px',
                          borderRadius: '8px',
                          border: '1px solid var(--rule)',
                          background: 'color-mix(in srgb, var(--gold) 10%, transparent)',
                          color: 'var(--gold)',
                          fontSize: '12px',
                          fontWeight: '600',
                          cursor: 'pointer',
                          transition: 'all 0.2s ease'
                        }}
                      >
                        <span>📎</span> {quickPdfUploading ? 'Indexing PDF…' : 'Attach PDF'}
                      </button>
                      <VoiceInput
                        value={question}
                        onTranscript={(text) => setQuestion(text)}
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
      {globalCorpusAvailable && uploadOpen && <div className="modal-backdrop" onMouseDown={(e)=>{if(e.target===e.currentTarget&&!uploading)setUploadOpen(false)}}><section className="judgment-upload-modal" role="dialog" aria-modal="true" aria-label="Upload judgments"><header><div><span className="eyebrow">LEGAL KNOWLEDGE BASE</span><h2>Upload Judgments</h2><p>Add PDF judgments without exposing raw indexed passages.</p></div><button className="modal-close" disabled={uploading} onClick={()=>setUploadOpen(false)}>✕</button></header><button className="judgment-dropzone" type="button" onClick={()=>fileInputRef.current?.click()} onDragOver={(e)=>e.preventDefault()} onDrop={(e)=>{e.preventDefault();stageJudgments(e.dataTransfer.files)}} disabled={uploading}><span>📄</span><b>Select judgment PDFs</b><small>PDF only · duplicates are detected before indexing</small></button>{uploadFiles.length>0&&<div className="judgment-file-list">{uploadFiles.map((x,i)=><div className={`judgment-file-row ${x.status}`} key={`${x.file.name}-${i}`}><span className="file-icon">📄</span><div><b>{x.file.name}</b><small>{(x.file.size/1024/1024).toFixed(2)} MB · {x.note}</small></div><span className="file-state">{x.status==='done'?'✓':x.status==='uploading'?'…':x.status==='exists'?'↻':x.status==='error'?'!':x.status==='invalid'?'×':'Ready'}</span></div>)}</div>}{uploadFiles.some(x=>x.status==='exists')&&<label className="replace-check"><input type="checkbox" checked={replaceExisting} onChange={e=>setReplaceExisting(e.target.checked)}/><span><b>Replace existing judgments</b><small>Re-index selected files that already exist. Existing corpus entries are replaced, not duplicated.</small></span></label>}<footer><button className="btn-quiet" disabled={uploading} onClick={()=>setUploadOpen(false)}>Close</button><button className="btn-primary" disabled={uploading||!uploadFiles.some(x=>x.status==='ready'||(replaceExisting&&x.status==='exists'))} onClick={uploadStagedJudgments}>{uploading?'Indexing…':'Add to Knowledge Base'}</button></footer></section></div>}
      {developerToolsAvailable && globalCorpusAvailable && <RagLab open={ragLabOpen} onClose={()=>setRagLabOpen(false)} initialQuery={question} />}
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
