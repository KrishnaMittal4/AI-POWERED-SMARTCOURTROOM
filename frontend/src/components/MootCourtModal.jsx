import { apiFetch } from '../lib/auth.js'
import { useState, useEffect, useRef } from 'react'
import { renderMarkdown } from '../lib/safeHtml.js'
import { playGavelSound, getPersonaVoiceConfig, cleanTextForSpeech } from '../lib/courtroomAudio.js'
import { exportCertifiedCourtOrder } from '../lib/courtOrderPdf.js'

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8000'

const SAMPLE_PROPOSITIONS = [
  {
    title: 'Director Liability — NI Act s.138',
    text: 'Whether an erstwhile director who tendered their resignation before the date of issuance of a dishonoured cheque can be held vicariously liable under Section 141 of the Negotiable Instruments Act without specific averments in the complaint.',
  },
  {
    title: 'Injunction Breach — Order 39 CPC',
    text: 'Whether a transfer of immovable property executed in direct violation of an order of temporary injunction is void ab initio, or whether the purchaser pendente lite can be impleaded under Order 1 Rule 10 CPC.',
  },
  {
    title: 'Anticipatory Bail — Economic Offences',
    text: 'Whether anticipatory bail under Section 438 CrPC can be granted in an economic offence where the prosecution alleges non-cooperation with investigation and custodial interrogation is sought.',
  },
]

const QUICK_JUDGE_QUESTIONS = [
  'Counsel, how do you address the statutory presumption against your client?',
  'Does your proposition hold if the party acted in an executive signatory capacity?',
  'What is your submission on the mandatory procedural timeline and limitation?',
  'How do you distinguish the precedent cited by the opposing counsel?',
]

const ARGUMENT_STARTERS = {
  petitioner: [
    {
      label: 'Strict Statutory Mandate',
      text: 'May it please Your Lordship, I appear for the Petitioner to submit that the statutory provisions impose a strict, non-negotiable obligation. The ingredients of the violation are established by unrebutted documentary record, and no statutory exception is available to the Respondent.',
    },
    {
      label: 'Vicarious Liability Averment',
      text: 'May it please the Bench, the Petitioner has made specific and unequivocal averments demonstrating that the Respondent was in active charge of and responsible for the business at the material time of the transaction.',
    },
    {
      label: 'Prima Facie Case for Relief',
      text: 'May it please Your Lordship, a strong prima facie case is established on record. The balance of convenience tilts entirely in favor of the Petitioner, and grave prejudice will ensue unless the prayer is granted.',
    },
  ],
  respondent: [
    {
      label: 'Preliminary Objection: Bar of Limitation',
      text: 'May it please the Bench, at the very threshold, I raise a preliminary objection as to the maintainability of this petition. The statutory timeline was disregarded, and the mandatory prerequisite notice was never served within the prescribed limitation.',
    },
    {
      label: 'Absence of Specific Averment',
      text: 'May it please Your Lordship, the petition suffers from a fatal lack of specific pleadings. A person cannot be roped in vicariously without cogent, particularised averments detailing their direct role in the alleged default.',
    },
    {
      label: 'Bona Fide Defense & Lack of Mens Rea',
      text: 'May it please the Bench, the record reveals bona fide discharge of obligations and absence of culpability. The dispute is purely civil in character and has been given a criminal cloak to exert undue pressure.',
    },
  ],
}

const LOADING_STAGES_AI = [
  { id: 1, icon: '📚', label: 'Retrieving precedents from judgment corpus…' },
  { id: 2, icon: '⚖️', label: 'Petitioner Senior Counsel preparing submissions…' },
  { id: 3, icon: '🛡️', label: 'Respondent Senior Counsel preparing rebuttal…' },
  { id: 4, icon: '🏛️', label: 'Presiding Bench deliberating judicial order…' },
]

const LOADING_STAGES_HUMAN = [
  { id: 1, icon: '📚', label: 'Examining human oral submission against corpus…' },
  { id: 2, icon: '⚔️', label: 'Opposing Senior Counsel formulating rebuttal…' },
  { id: 3, icon: '⚖️', label: 'Presiding Chief Justice assessing statutory precision…' },
  { id: 4, icon: '🏆', label: 'Bench compiling Advocacy Scorecard & Order…' },
]

function extractErrorMessage(errBody, status) {
  if (!errBody) return `Courtroom session failed (${status})`
  if (typeof errBody.detail === 'string') return errBody.detail
  if (Array.isArray(errBody.detail) && errBody.detail.length > 0) {
    const first = errBody.detail[0]
    return first.msg ? `${first.loc?.join('.') || 'Error'}: ${first.msg}` : JSON.stringify(first)
  }
  if (errBody.message) return errBody.message
  if (errBody.error) return errBody.error
  return `Courtroom session failed (${status})`
}

function renderCitationList(citations, isPetitioner) {
  if (!citations || !Array.isArray(citations) || citations.length === 0) return null

  const badgeBg = isPetitioner ? 'rgba(30, 64, 128, 0.08)' : 'rgba(139, 0, 0, 0.08)'
  const badgeBorder = isPetitioner ? 'rgba(30, 64, 128, 0.22)' : 'rgba(139, 0, 0, 0.22)'
  const badgeColor = isPetitioner ? '#2563eb' : '#dc2626'

  return (
    <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--rule)' }}>
      <div style={{
        fontSize: '11px',
        fontWeight: 700,
        color: 'var(--muted)',
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        marginBottom: '8px',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
      }}>
        <span>Corpus Precedents Cited</span>
        <span style={{ fontSize: '10px', opacity: 0.7 }}>({citations.length})</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {citations.slice(0, 4).map((c, idx) => {
          const title = typeof c === 'string'
            ? c
            : (c?.case_name || (c?.source_file ? c.source_file.replace(/\.pdf$/i, '') : `Precedent #${idx + 1}`))
          const court = typeof c === 'object' && c?.court ? c.court : null
          const snippet = typeof c === 'object' && c?.text ? c.text.trim() : null

          return (
            <div
              key={idx}
              style={{
                padding: '9px 12px',
                borderRadius: '8px',
                background: badgeBg,
                border: `1px solid ${badgeBorder}`,
                fontSize: '12.5px',
              }}
            >
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: '8px',
                flexWrap: 'wrap',
              }}>
                <span style={{ fontWeight: 700, color: badgeColor }}>
                  📜 {title}
                </span>
                {court && (
                  <span style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 500 }}>
                    {court}
                  </span>
                )}
              </div>
              {snippet && (
                <div style={{
                  fontSize: '12px',
                  color: 'var(--ink-2)',
                  lineHeight: 1.5,
                  marginTop: '4px',
                  fontStyle: 'italic',
                  opacity: 0.88,
                }}>
                  "{snippet.length > 200 ? snippet.slice(0, 200) + '…' : snippet}"
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function MootCourtModal({ isOpen, onClose, initialQuery = '' }) {
  // Mode: 'ai_vs_ai' or 'human_vs_ai'
  const [trialMode, setTrialMode] = useState('ai_vs_ai')
  const [userRole, setUserRole] = useState('petitioner') // 'petitioner' or 'respondent'
  const [userArgument, setUserArgument] = useState('')

  const [dispute, setDispute] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState(1)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [showGuide, setShowGuide] = useState(true)

  // Audio Courtroom Narration State
  const [activeSpeaker, setActiveSpeaker] = useState(null) // null | 'petitioner' | 'respondent' | 'bench' | string
  const [isPlayingAll, setIsPlayingAll] = useState(false)
  const playAllAbortRef = useRef(false)

  // Interlocutory Q&A
  const [targetCounsel, setTargetCounsel] = useState('respondent')
  const [judgeQuestion, setJudgeQuestion] = useState('')
  const [askingInterlocutory, setAskingInterlocutory] = useState(false)
  const [interlocutoryError, setInterlocutoryError] = useState(null)
  const [interlocutoryThreads, setInterlocutoryThreads] = useState([])

  // Live Courtroom Chat (Human vs AI multi-turn debate)
  const [debateThreads, setDebateThreads] = useState([])
  const [replyText, setReplyText] = useState('')
  const [sendingReply, setSendingReply] = useState(false)
  const [replyError, setReplyError] = useState(null)
  const debateChatEndRef = useRef(null)
  const replyInputRef = useRef(null)

  useEffect(() => {
    if (isOpen) setShowGuide(true)
    if (isOpen && initialQuery && !dispute) {
      setDispute(initialQuery)
    }
  }, [isOpen, initialQuery])

  // Stop any active speech on modal close or unmount
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
    }
  }, [isOpen])

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && !loading) {
        stopAllAudio()
        onClose()
      }
    }
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, loading, onClose])

  useEffect(() => {
    if (!loading) return
    setLoadingStage(1)
    const t1 = setTimeout(() => setLoadingStage(2), 2500)
    const t2 = setTimeout(() => setLoadingStage(3), 5500)
    const t3 = setTimeout(() => setLoadingStage(4), 9500)
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3) }
  }, [loading])

  function stopAllAudio() {
    playAllAbortRef.current = true
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    setActiveSpeaker(null)
    setIsPlayingAll(false)
  }

  function speakText(role, rawText, onEnd) {
    if (typeof window === 'undefined' || !window.speechSynthesis || !rawText) return
    window.speechSynthesis.cancel()
    setActiveSpeaker(role)

    const text = cleanTextForSpeech(rawText)
    const utterance = new SpeechSynthesisUtterance(text)
    const voices = window.speechSynthesis.getVoices()
    const config = getPersonaVoiceConfig(role, voices)

    if (config.voice) utterance.voice = config.voice
    utterance.pitch = config.pitch
    utterance.rate = config.rate

    utterance.onend = () => {
      setActiveSpeaker(null)
      if (onEnd) onEnd()
    }
    utterance.onerror = () => {
      setActiveSpeaker(null)
      if (onEnd) onEnd()
    }

    window.speechSynthesis.speak(utterance)
  }

  function handlePlayAll() {
    if (!result) return
    if (isPlayingAll || activeSpeaker) {
      stopAllAudio()
      return
    }

    playAllAbortRef.current = false
    setIsPlayingAll(true)

    // 1. Petitioner speaks
    speakText('petitioner', result.petitioner.argument, () => {
      if (playAllAbortRef.current) return
      setTimeout(() => {
        if (playAllAbortRef.current) return
        // 2. Respondent speaks
        speakText('respondent', result.respondent.argument, () => {
          if (playAllAbortRef.current) return
          setTimeout(() => {
            if (playAllAbortRef.current) return
            // 3. Bench gavel sounds
            playGavelSound()
            setTimeout(() => {
              if (playAllAbortRef.current) return
              // 4. Bench delivers verdict
              speakText('bench', result.bench.verdict, () => {
                setIsPlayingAll(false)
              })
            }, 750)
          }, 1000)
        })
      }, 1000)
    })
  }

  if (!isOpen) return null

  async function handleStartTrial(e) {
    if (e) e.preventDefault()
    if (!dispute.trim()) return
    if (trialMode === 'human_vs_ai' && userArgument.trim().length < 15) return

    stopAllAudio()
    setLoading(true)
    setError(null)
    setResult(null)
    setInterlocutoryThreads([])
    setDebateThreads([])
    setReplyText('')
    setReplyError(null)
    setJudgeQuestion('')

    try {
      const endpoint = trialMode === 'human_vs_ai'
        ? `${API_BASE}/moot-court/human-counsel`
        : `${API_BASE}/moot-court`

      const payload = trialMode === 'human_vs_ai'
        ? {
            dispute: dispute.trim(),
            user_role: userRole,
            user_argument: userArgument.trim(),
          }
        : { dispute: dispute.trim() }

      const res = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(extractErrorMessage(body, res.status))
      }
      const data = await res.json()
      setResult(data)
      playGavelSound()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleAskInterlocutory(e) {
    if (e) e.preventDefault()
    if (!result || !judgeQuestion.trim() || askingInterlocutory) return
    setAskingInterlocutory(true)
    setInterlocutoryError(null)
    const isPet = targetCounsel === 'petitioner'
    const counselArg = isPet ? result.petitioner.argument : result.respondent.argument
    const counselCites = isPet ? result.petitioner.citations : result.respondent.citations
    try {
      const res = await apiFetch(`${API_BASE}/moot-court/interlocutory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dispute: result.dispute,
          target_counsel: targetCounsel,
          counsel_argument: counselArg,
          judge_question: judgeQuestion.trim(),
          citations: counselCites || [],
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(extractErrorMessage(body, res.status))
      }
      const answerData = await res.json()
      setInterlocutoryThreads((prev) => [
        ...prev,
        {
          id: Date.now(),
          target: targetCounsel,
          question: judgeQuestion.trim(),
          response: answerData.response,
          counselTitle: answerData.counsel_title,
          model: answerData.model,
        },
      ])
      setJudgeQuestion('')
    } catch (err) {
      setInterlocutoryError(err.message)
    } finally {
      setAskingInterlocutory(false)
    }
  }

  async function handleSendReply(e) {
    if (e) e.preventDefault()
    if (!result || !replyText.trim() || sendingReply) return
    setSendingReply(true)
    setReplyError(null)

    const roundNum = debateThreads.length + 2
    // Build prior exchange context from existing debate threads
    const priorExchange = []
    // Add initial round
    const initHuman = result.mode === 'human_vs_ai'
      ? (result.user_role === 'petitioner' ? result.petitioner.argument : result.respondent.argument)
      : null
    if (initHuman) priorExchange.push({ role: 'human', text: initHuman })
    const initAI = result.mode === 'human_vs_ai'
      ? (result.user_role === 'petitioner' ? result.respondent.argument : result.petitioner.argument)
      : null
    if (initAI) priorExchange.push({ role: 'ai', text: initAI })
    debateThreads.forEach((t) => {
      priorExchange.push({ role: 'human', text: t.human_reply })
      priorExchange.push({ role: 'ai', text: t.opponent_rebuttal })
    })

    try {
      const res = await apiFetch(`${API_BASE}/moot-court/human-reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dispute: result.dispute,
          user_role: result.user_role || userRole,
          user_reply: replyText.trim(),
          round_number: roundNum,
          prior_exchange: priorExchange,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(extractErrorMessage(body, res.status))
      }
      const data = await res.json()
      setDebateThreads((prev) => [...prev, { ...data, id: Date.now() }])
      setReplyText('')
      // Scroll to bottom after update
      setTimeout(() => debateChatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    } catch (err) {
      setReplyError(err.message)
    } finally {
      setSendingReply(false)
      setTimeout(() => replyInputRef.current?.focus(), 100)
    }
  }

  function handleCopyTranscript() {
    if (!result) return
    let text = `# MOOT COURT TRANSCRIPT (${result.mode === 'human_vs_ai' ? 'Step In As Counsel: Human vs AI' : 'AI vs AI Debate'})\n`
    text += `Dispute: ${result.dispute}\n\n`
    if (result.scorecard) {
      text += `## CHIEF JUSTICE ADVOCACY SCORECARD\n`
      text += `Advocate Grade: ${result.scorecard.grade} (Total: ${result.scorecard.total_score}/30)\n`
      text += `- Statutory Precision: ${result.scorecard.statutory_precision}/10\n`
      text += `- Relevance of Precedents: ${result.scorecard.precedents_score}/10\n`
      text += `- Courtroom Etiquette: ${result.scorecard.courtroom_etiquette}/10\n`
      if (result.scorecard.bench_guidance) text += `Judicial Advisory: "${result.scorecard.bench_guidance}"\n`
      text += `\n`
    }
    text += `## PETITIONER (${result.petitioner.model || 'Groq'})\n${result.petitioner.argument}\n\n`
    if (result.petitioner.citations?.length) {
      text += `Precedents cited:\n` + result.petitioner.citations.map((c) => `- ${c.case_name || c.source_file || c}`).join('\n') + '\n\n'
    }
    text += `## RESPONDENT (${result.respondent.model || 'Groq'})\n${result.respondent.argument}\n\n`
    if (result.respondent.citations?.length) {
      text += `Precedents cited:\n` + result.respondent.citations.map((c) => `- ${c.case_name || c.source_file || c}`).join('\n') + '\n\n'
    }
    text += `## BENCH — ${result.bench.disposition}\nPrevailing: ${result.bench.prevailing_party}\nModel: ${result.bench.model || 'Gemini'}\n\n${result.bench.verdict}`
    if (interlocutoryThreads.length > 0) {
      text += `\n\n## INTERLOCUTORY Q&A\n`
      interlocutoryThreads.forEach((th, i) => {
        text += `\n[Q${i + 1}] Bench: "${th.question}"\n${th.counselTitle}: ${th.response}\n`
      })
    }
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Disposition badge color
  const dispColor = result
    ? result.bench.prevailing_party === 'Petitioner'
      ? '#2563eb'
      : result.bench.prevailing_party === 'Respondent'
        ? '#059669'
        : '#d97706'
    : 'var(--gold)'

  return (
    <div
      className="modal-scrim moot-scrim"
      onClick={loading ? undefined : () => { stopAllAudio(); onClose() }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="moot-title"
    >
      <div className="moot-modal moot-fullscreen" onClick={(e) => e.stopPropagation()}>

        {/* ── COURT HEADER (Sticky Fullscreen Bar) ── */}
        <div className="court-header">
          <div className="court-header-inner">
            <div className="court-title-group">
              <div className="court-eyebrow">Virtual Courtroom Arena · Division Bench</div>
              <h2 className="court-title" id="moot-title">⚖ Moot Court</h2>
              <p className="court-subtitle">
                High-Stakes Adversarial Trial Arena · AI vs AI Simulation & Interactive "Step In As Counsel" Practice
              </p>
            </div>
            <div className="court-header-actions">
              <button type="button" className="btn-quiet" onClick={() => setShowGuide(true)}>How to use</button>
            <button
              className="court-exit-btn"
              onClick={() => { stopAllAudio(); onClose() }}
              disabled={loading}
              aria-label="Exit Courtroom Arena"
            >
              <span>✕</span>
              <span>Exit Courtroom</span>
              <kbd>Esc</kbd>
            </button>
            </div>
          </div>
        </div>

        {showGuide && (
          <div className="moot-guide-overlay" role="dialog" aria-modal="true" aria-label="Moot Court user guide">
            <div className="moot-guide-card">
              <div className="moot-guide-icon">⚖️</div>
              <div>
                <div className="court-eyebrow">Quick user manual</div>
                <h3>How to use the Moot Court</h3>
                <p>Practice a complete AI trial or step in as counsel. LEXAI retrieves relevant judgments before the advocates and bench respond.</p>
              </div>
              <div className="moot-guide-steps">
                <div><b>1</b><span><strong>Choose a mode</strong><small>AI vs AI for a full simulation, or Human vs AI to practise advocacy.</small></span></div>
                <div><b>2</b><span><strong>Enter the dispute</strong><small>Paste facts or a precise question of law. You can also use a sample proposition.</small></span></div>
                <div><b>3</b><span><strong>Run the hearing</strong><small>Review both submissions, corpus precedents, the bench decision and advocacy score.</small></span></div>
                <div><b>4</b><span><strong>Continue interactively</strong><small>Ask bench questions, reply as counsel, listen to arguments or export the decree.</small></span></div>
              </div>
              <div className="moot-guide-note">AI courtroom output is a research and learning aid. Verify authorities and legal conclusions before professional use.</div>
              <button type="button" className="hero-ask-btn moot-guide-start" onClick={() => setShowGuide(false)}>Enter Courtroom</button>
            </div>
          </div>
        )}

        {/* ── SCROLLABLE COURTROOM FLOOR ── */}
        <div className="court-scroll-body">

        {/* ── SETUP FORM (no result yet) ── */}
        {!result && !loading && (
          <div className="court-setup-wrap">
          <div className="court-setup">
            {/* Mode Selector Tabs */}
            <div className="court-mode-tabs" role="tablist" aria-label="Trial Mode">
              <button
                type="button"
                className={`mode-tab-btn ${trialMode === 'ai_vs_ai' ? 'active' : ''}`}
                onClick={() => setTrialMode('ai_vs_ai')}
              >
                <span>🏛️</span>
                <span>Full Trial (AI vs AI)</span>
              </button>
              <button
                type="button"
                className={`mode-tab-btn ${trialMode === 'human_vs_ai' ? 'active' : ''}`}
                onClick={() => setTrialMode('human_vs_ai')}
              >
                <span>⚔️</span>
                <span>Step In As Counsel (Human vs AI)</span>
              </button>
            </div>

            <form onSubmit={handleStartTrial}>
              {/* If Human vs AI: Role selection */}
              {trialMode === 'human_vs_ai' && (
                <div style={{ marginBottom: '18px' }}>
                  <label className="court-setup-label">Select Your Podium & Role</label>
                  <div className="role-selector-row">
                    <button
                      type="button"
                      className={`role-card-btn ${userRole === 'petitioner' ? 'active petitioner' : ''}`}
                      onClick={() => setUserRole('petitioner')}
                    >
                      <span className="role-card-icon">⚖️</span>
                      <div>
                        <div className="role-card-title">Argue for Petitioner</div>
                        <div className="role-card-desc">Lead the Prosecution · Establish statutory breach</div>
                      </div>
                    </button>
                    <button
                      type="button"
                      className={`role-card-btn ${userRole === 'respondent' ? 'active respondent' : ''}`}
                      onClick={() => setUserRole('respondent')}
                    >
                      <span className="role-card-icon">🛡️</span>
                      <div>
                        <div className="role-card-title">Argue for Respondent</div>
                        <div className="role-card-desc">Lead the Defense · Rebut claims & cite exceptions</div>
                      </div>
                    </button>
                  </div>
                </div>
              )}

              {/* Legal Proposition / Dispute facts */}
              <label htmlFor="moot-input" className="court-setup-label">
                Dispute Facts or Question of Law
              </label>
              <textarea
                id="moot-input"
                className="court-textarea"
                rows={3}
                value={dispute}
                onChange={(e) => setDispute(e.target.value)}
                placeholder="State the factual background or proposition of law — e.g. Whether liability attaches to an accused director when cheques bounced after resignation…"
              />

              <div className="court-samples">
                {SAMPLE_PROPOSITIONS.map((prop, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="sample-chip"
                    onClick={() => setDispute(prop.text)}
                  >
                    ⚖ {prop.title}
                  </button>
                ))}
              </div>

              {/* If Human vs AI: Human Advocate Oral Submission Area */}
              {trialMode === 'human_vs_ai' && (
                <div style={{ marginTop: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
                    <label htmlFor="user-arg-input" className="court-setup-label" style={{ margin: 0 }}>
                      Your Oral Submission to the Bench ({userRole === 'petitioner' ? 'Petitioner Counsel' : 'Respondent Counsel'})
                    </label>
                    <span style={{ fontSize: '11px', color: 'var(--muted)' }}>
                      Min 15 characters · Practice courtroom advocacy
                    </span>
                  </div>
                  <textarea
                    id="user-arg-input"
                    className="court-textarea"
                    rows={4}
                    value={userArgument}
                    onChange={(e) => setUserArgument(e.target.value)}
                    placeholder={
                      userRole === 'petitioner'
                        ? 'Address the Bench: "May it please Your Lordship, I appear for the Petitioner to submit that the mandatory statutory provisions have been violated..."'
                        : 'Address the Bench: "May it please Your Lordship, I appear for the Respondent to submit that the complaint is untenable and lacks the essential statutory ingredients..."'
                    }
                  />

                  {/* Starter Argument Chips */}
                  <div style={{ marginTop: '10px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                      Argument Starters:
                    </span>
                    <div className="argument-starters">
                      {(ARGUMENT_STARTERS[userRole] || []).map((st, i) => (
                        <button
                          key={i}
                          type="button"
                          className="starter-chip"
                          onClick={() => setUserArgument(st.text)}
                          title="Click to insert argument skeleton"
                        >
                          ✦ {st.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {error && (
                <div className="error" role="alert" style={{ marginTop: '16px' }}>
                  {error}
                </div>
              )}

              <button
                type="submit"
                className="court-go-btn"
                disabled={
                  dispute.trim().length < 10 ||
                  (trialMode === 'human_vs_ai' && userArgument.trim().length < 15)
                }
              >
                <span>{trialMode === 'human_vs_ai' ? '⚔️' : '🏛️'}</span>
                <span>
                  {trialMode === 'human_vs_ai'
                    ? 'Take the Podium & Present to Bench'
                    : 'Commence AI Courtroom Trial'}
                </span>
              </button>
            </form>
          </div>
          </div>
        )}

        {/* ── LOADING STAGE ── */}
        {loading && (
          <div className="court-loading">
            <div className="court-loading-gavel">⚖️</div>
            <div className="court-loading-title">
              {trialMode === 'human_vs_ai'
                ? 'Court in Session · Evaluating Human Counsel vs AI Opponent'
                : 'Court in Session · Hearing Oral Arguments'}
            </div>
            <div className="court-loading-stages">
              {(trialMode === 'human_vs_ai' ? LOADING_STAGES_HUMAN : LOADING_STAGES_AI).map((stage) => (
                <div
                  key={stage.id}
                  className={`loading-stage ${loadingStage === stage.id ? 'active' : loadingStage > stage.id ? 'done' : ''}`}
                >
                  <span className="stage-icon">{loadingStage > stage.id ? '✅' : stage.icon}</span>
                  <span>{stage.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── COURTROOM ARENA (3-Pod layout + Scorecard) ── */}
        {result && (
          <>
            {/* Disposition Banner */}
            <div style={{
              padding: '14px 28px',
              background: 'var(--gold-bg)',
              borderBottom: '1px solid var(--gold-border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
            }}>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{
                  fontFamily: 'var(--cinzel)',
                  fontSize: '11px',
                  fontWeight: 700,
                  letterSpacing: '0.15em',
                  color: 'var(--muted)',
                  textTransform: 'uppercase',
                }}>
                  Disposition
                </span>
                <span style={{ fontWeight: 700, color: dispColor, fontSize: '15px' }}>
                  {result.bench.disposition}
                </span>
                <span style={{
                  fontWeight: 600,
                  fontSize: '13px',
                  padding: '3px 12px',
                  borderRadius: '99px',
                  background: 'var(--surface)',
                  border: '1px solid var(--rule)',
                  color: 'var(--muted)',
                }}>
                  Prevailing: <strong style={{ color: dispColor }}>{result.bench.prevailing_party}</strong>
                </span>
                {result.graph_execution && (
                  <span
                    style={{
                      fontSize: '11.5px',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: '99px',
                      background: 'rgba(99, 102, 241, 0.12)',
                      border: '1px solid rgba(99, 102, 241, 0.3)',
                      color: '#818cf8',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                    title={`Orchestrated by ${result.graph_execution.orchestrator}: ${result.graph_execution.nodes_executed?.join(' → ')}`}
                  >
                    🕸️ LangGraph StateGraph
                  </span>
                )}
                {result.mode === 'human_vs_ai' && (
                  <span style={{
                    fontSize: '11.5px',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: '99px',
                    background: 'linear-gradient(135deg, rgba(184,134,11,0.2) 0%, rgba(212,160,23,0.3) 100%)',
                    border: '1px solid var(--gold-border)',
                    color: 'var(--gold)',
                  }}>
                    ⚔️ Step In As Counsel Mode
                  </span>
                )}
              </div>

              {/* Action Buttons: Audio, Certified Decree, Copy, New Trial */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                <button
                  type="button"
                  className={`btn-primary small audio-hero-btn ${isPlayingAll ? 'active' : ''}`}
                  onClick={handlePlayAll}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    fontSize: '12.5px',
                    background: isPlayingAll ? 'linear-gradient(135deg, #b91c1c 0%, #dc2626 100%)' : undefined,
                  }}
                  title={isPlayingAll ? 'Stop Trial Narration' : 'Narrate oral submissions and bench order with audio'}
                >
                  <span>{isPlayingAll ? '⏹️' : '🎙️'}</span>
                  <span>{isPlayingAll ? 'Stop Trial Audio' : 'Listen to Oral Arguments'}</span>
                </button>

                <button
                  type="button"
                  className="btn-quiet small"
                  onClick={() => exportCertifiedCourtOrder(result, interlocutoryThreads)}
                  title="Export official Certified Court Decree and Print/Save as PDF"
                >
                  📜 Certified Decree
                </button>

                <button
                  type="button"
                  className="btn-quiet small"
                  onClick={() => playGavelSound()}
                  title="Sound the judicial gavel"
                >
                  🔨 Strike Gavel
                </button>

                <button type="button" className="btn-quiet small" onClick={handleCopyTranscript}>
                  {copied ? '✅ Copied!' : '📋 Copy Transcript'}
                </button>

                <button
                  type="button"
                  className="btn-quiet small"
                  onClick={() => {
                    stopAllAudio()
                    setResult(null)
                    setInterlocutoryThreads([])
                    setDebateThreads([])
                    setReplyText('')
                    setUserArgument('')
                  }}
                >
                  🔄 New Trial
                </button>
              </div>
            </div>

            <div className="courtroom-arena">
              {/* ── ADVOCACY SCORECARD (If Human vs AI Mode) ── */}
              {result.scorecard && (
                <div className="advocacy-scorecard">
                  <div className="scorecard-header">
                    <div className="scorecard-title-group">
                      <span style={{ fontSize: '26px' }}>🏆</span>
                      <div>
                        <div style={{
                          fontFamily: 'var(--cinzel)',
                          fontSize: '15px',
                          fontWeight: 800,
                          letterSpacing: '0.08em',
                          textTransform: 'uppercase',
                          color: 'var(--gold)',
                        }}>
                          Chief Justice's Advocacy Evaluation
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                          Scored on statutory precision, precedents cited, and courtroom persuasion
                        </div>
                      </div>
                    </div>
                    <div className="scorecard-badge">
                      Advocacy Grade: {result.scorecard.grade || `${result.scorecard.total_score || 0}/30`}
                    </div>
                  </div>

                  <div className="scorecard-body">
                    {/* 3 Metric Gauges */}
                    <div className="score-gauges-grid">
                      <div className="gauge-card">
                        <span className="gauge-label">Statutory Precision</span>
                        <div className="gauge-val-row">
                          <span className="gauge-num">{result.scorecard.statutory_precision || 0}</span>
                          <span className="gauge-max">/ 10</span>
                        </div>
                        <div className="gauge-bar-track">
                          <div
                            className="gauge-bar-fill"
                            style={{ width: `${Math.min(100, (result.scorecard.statutory_precision || 0) * 10)}%` }}
                          />
                        </div>
                      </div>

                      <div className="gauge-card">
                        <span className="gauge-label">Relevance of Precedents</span>
                        <div className="gauge-val-row">
                          <span className="gauge-num">{result.scorecard.precedents_score || 0}</span>
                          <span className="gauge-max">/ 10</span>
                        </div>
                        <div className="gauge-bar-track">
                          <div
                            className="gauge-bar-fill"
                            style={{ width: `${Math.min(100, (result.scorecard.precedents_score || 0) * 10)}%` }}
                          />
                        </div>
                      </div>

                      <div className="gauge-card">
                        <span className="gauge-label">Courtroom Etiquette</span>
                        <div className="gauge-val-row">
                          <span className="gauge-num">{result.scorecard.courtroom_etiquette || 0}</span>
                          <span className="gauge-max">/ 10</span>
                        </div>
                        <div className="gauge-bar-track">
                          <div
                            className="gauge-bar-fill"
                            style={{ width: `${Math.min(100, (result.scorecard.courtroom_etiquette || 0) * 10)}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Strengths & Vulnerabilities */}
                    <div className="scorecard-critique-row">
                      <div className="critique-col strengths">
                        <div className="critique-title" style={{ color: 'var(--yes)' }}>
                          <span>✅</span> Key Strengths of Your Submission
                        </div>
                        <ul className="critique-list">
                          {(result.scorecard.strengths || ['Clear opening submission']).map((s, i) => (
                            <li key={i}><span>•</span> <span>{s}</span></li>
                          ))}
                        </ul>
                      </div>

                      <div className="critique-col vulnerabilities">
                        <div className="critique-title" style={{ color: '#d97706' }}>
                          <span>⚠️</span> Statutory Gaps & Points Exploited by Opponent
                        </div>
                        <ul className="critique-list">
                          {(result.scorecard.vulnerabilities || ['Address counter-authorities more directly']).map((v, i) => (
                            <li key={i}><span>•</span> <span>{v}</span></li>
                          ))}
                        </ul>
                      </div>
                    </div>

                    {/* Bench Guidance */}
                    {result.scorecard.bench_guidance && (
                      <div className="bench-guidance-box">
                        <span style={{ fontSize: '20px' }}>📜</span>
                        <div>
                          <strong>Presiding Chief Justice's Courtroom Advice: </strong>
                          <em>"{result.scorecard.bench_guidance}"</em>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── 3-Pod Row: Petitioner | VS | Respondent ── */}
              <div className="court-pods-row">
                {/* Petitioner Pod */}
                <div className={`counsel-pod ${result.petitioner.is_human ? 'human-advocate-pod' : ''} ${activeSpeaker === 'petitioner' ? 'active-speaking' : ''}`}>
                  <div className="pod-header">
                    <div className="pod-avatar petitioner">⚖</div>
                    <div className="pod-meta">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className="pod-role">Petitioner</span>
                        {result.petitioner.is_human && (
                          <span style={{
                            fontSize: '9.5px',
                            fontWeight: 800,
                            padding: '1px 6px',
                            borderRadius: '4px',
                            background: 'var(--gold)',
                            color: '#fff',
                            letterSpacing: '0.06em',
                          }}>
                            YOU · HUMAN ADVOCATE
                          </span>
                        )}
                      </div>
                      <span className="pod-name">Senior Counsel</span>
                      {result.petitioner.model && (
                        <span style={{ fontSize: '11px', color: 'var(--muted)' }}>{result.petitioner.model}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      className={`btn-quiet small audio-pod-btn ${activeSpeaker === 'petitioner' ? 'speaking' : ''}`}
                      onClick={() => activeSpeaker === 'petitioner' ? stopAllAudio() : speakText('petitioner', result.petitioner.argument)}
                      title="Listen to Petitioner oral submission"
                    >
                      <span>{activeSpeaker === 'petitioner' ? '⏹️' : '🔊'}</span>
                      <span>{activeSpeaker === 'petitioner' ? 'Stop' : 'Listen'}</span>
                    </button>
                  </div>
                  <div className="pod-body">
                    <div
                      className="answer-content"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(result.petitioner.argument) }}
                    />
                    {renderCitationList(result.petitioner.citations, true)}
                  </div>
                </div>

                {/* VS Divider */}
                <div className="court-vs-divider">
                  <div className="vs-line" />
                  <div className="vs-badge">VS</div>
                  <div className="vs-line" />
                </div>

                {/* Respondent Pod */}
                <div className={`counsel-pod ${result.respondent.is_human ? 'human-advocate-pod' : ''} ${activeSpeaker === 'respondent' ? 'active-speaking' : ''}`}>
                  <div className="pod-header">
                    <div className="pod-avatar respondent">🛡</div>
                    <div className="pod-meta">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className="pod-role">Respondent</span>
                        {result.respondent.is_human && (
                          <span style={{
                            fontSize: '9.5px',
                            fontWeight: 800,
                            padding: '1px 6px',
                            borderRadius: '4px',
                            background: 'var(--gold)',
                            color: '#fff',
                            letterSpacing: '0.06em',
                          }}>
                            YOU · HUMAN ADVOCATE
                          </span>
                        )}
                      </div>
                      <span className="pod-name">Senior Counsel</span>
                      {result.respondent.model && (
                        <span style={{ fontSize: '11px', color: 'var(--muted)' }}>{result.respondent.model}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      className={`btn-quiet small audio-pod-btn ${activeSpeaker === 'respondent' ? 'speaking' : ''}`}
                      onClick={() => activeSpeaker === 'respondent' ? stopAllAudio() : speakText('respondent', result.respondent.argument)}
                      title="Listen to Respondent counter-submission"
                    >
                      <span>{activeSpeaker === 'respondent' ? '⏹️' : '🔊'}</span>
                      <span>{activeSpeaker === 'respondent' ? 'Stop' : 'Listen'}</span>
                    </button>
                  </div>
                  <div className="pod-body">
                    <div
                      className="answer-content"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(result.respondent.argument) }}
                    />
                    {renderCitationList(result.respondent.citations, false)}
                  </div>
                </div>
              </div>

              {/* ── Bench / Verdict Pod (full width) ── */}
              <div className={`bench-pod ${activeSpeaker === 'bench' ? 'active-speaking' : ''}`}>
                <div className="bench-header">
                  <span className="bench-gavel" onClick={playGavelSound} title="Click to strike Gavel" style={{ cursor: 'pointer' }}>
                    🏛️
                  </span>
                  <div>
                    <div className="bench-title">Judicial Order of the Bench</div>
                    <div className="bench-subtitle">{result.bench.model} · Presiding Judge</div>
                  </div>
                  <button
                    type="button"
                    className={`btn-quiet small audio-pod-btn ${activeSpeaker === 'bench' ? 'speaking' : ''}`}
                    onClick={() => {
                      if (activeSpeaker === 'bench') {
                        stopAllAudio()
                      } else {
                        playGavelSound()
                        setTimeout(() => speakText('bench', result.bench.verdict), 600)
                      }
                    }}
                    title="Listen to Presiding Bench Order (with Gavel strike)"
                    style={{ marginLeft: 'auto' }}
                  >
                    <span>{activeSpeaker === 'bench' ? '⏹️' : '🔊'}</span>
                    <span>{activeSpeaker === 'bench' ? 'Stop' : 'Read Order'}</span>
                  </button>
                </div>
                <div className="bench-verdict-body">
                  <div
                    className="answer-content"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(result.bench.verdict) }}
                  />
                </div>
              </div>

              {/* ── LIVE COURTROOM CHAT (Human vs AI Multi-turn Debate) ── */}
              {result.mode === 'human_vs_ai' && (
                <div className="debate-chat-panel">
                  <div className="debate-chat-header">
                    <span style={{ fontSize: '20px' }}>⚔️</span>
                    <div>
                      <div className="debate-chat-title">Live Courtroom Debate</div>
                      <div className="debate-chat-subtitle">Continue arguing — submit follow-up rebuttals to the AI opponent</div>
                    </div>
                    <span style={{
                      marginLeft: 'auto',
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: '99px',
                      background: 'var(--gold-bg)',
                      border: '1px solid var(--gold-border)',
                      color: 'var(--gold)',
                    }}>
                      Round {debateThreads.length + 1} of Debate
                    </span>
                  </div>

                  {/* Thread of multi-turn exchanges */}
                  <div className="debate-thread-scroll">
                    {/* Show initial round summary */}
                    <div className="debate-round-label">⚖ Round 1 — Opening Submissions</div>

                    {debateThreads.map((thread, idx) => (
                      <div key={thread.id} className="debate-exchange">
                        <div className="debate-round-label">⚔️ Round {idx + 2} — Continued Argument</div>

                        {/* Human's message */}
                        <div className="debate-msg human-msg">
                          <div className="debate-msg-header">
                            <span className="debate-msg-avatar human-avatar">YOU</span>
                            <span className="debate-msg-role">
                              {thread.user_role === 'petitioner' ? '⚖️ Petitioner Counsel' : '🛡️ Respondent Counsel'}
                            </span>
                            <span className="debate-msg-badge human-badge">Human Advocate</span>
                          </div>
                          <div className="debate-msg-body">{thread.human_reply}</div>
                        </div>

                        {/* AI Opponent's rebuttal */}
                        <div className="debate-msg ai-msg">
                          <div className="debate-msg-header">
                            <span className="debate-msg-avatar ai-avatar">AI</span>
                            <span className="debate-msg-role">
                              {thread.user_role === 'petitioner' ? '🛡️ Respondent Counsel (AI)' : '⚖️ Petitioner Counsel (AI)'}
                            </span>
                            <span className="debate-msg-badge ai-badge">{thread.opponent_model}</span>
                            <button
                              type="button"
                              className="btn-quiet small audio-pod-btn"
                              style={{ marginLeft: 'auto', fontSize: '11px', padding: '2px 7px' }}
                              onClick={() => activeSpeaker === `reply-${thread.id}` ? stopAllAudio() : speakText(`reply-${thread.id}`, thread.opponent_rebuttal)}
                            >
                              {activeSpeaker === `reply-${thread.id}` ? '⏹️' : '🔊'}
                            </button>
                          </div>
                          <div
                            className="debate-msg-body"
                            dangerouslySetInnerHTML={{ __html: renderMarkdown(thread.opponent_rebuttal) }}
                          />
                        </div>

                        {/* Bench interjection */}
                        {thread.bench_observation && (
                          <div className="bench-interjection">
                            <span style={{ fontSize: '16px' }}>🏛️</span>
                            <div>
                              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--gold)', marginBottom: '3px' }}>
                                Bench Judicial Observation
                              </div>
                              <div style={{ fontSize: '13px', fontStyle: 'italic', color: 'var(--ink-2)', lineHeight: 1.6 }}>
                                {thread.bench_observation}
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={debateChatEndRef} />
                  </div>

                  {/* Reply Input Area */}
                  <form className="debate-reply-form" onSubmit={handleSendReply}>
                    <div className="debate-reply-header">
                      <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--ink)' }}>
                        Your Next Submission
                      </span>
                      <span style={{ fontSize: '11px', color: 'var(--muted)', marginLeft: 'auto' }}>
                        {replyText.length}/4000 chars
                      </span>
                    </div>
                    <textarea
                      ref={replyInputRef}
                      id="debate-reply-input"
                      className="debate-reply-textarea"
                      rows={4}
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      disabled={sendingReply}
                      placeholder={`Continue your oral argument to the Bench... (e.g., "May it please Your Lordship, my learned friend has failed to address the core statutory mandate — the irreversible prejudice caused...")`}
                    />
                    {replyError && (
                      <div className="error" role="alert" style={{ margin: '0 0 4px' }}>{replyError}</div>
                    )}
                    <div className="debate-reply-actions">
                      <div className="debate-quick-replies">
                        {[
                          'The precedent cited by my learned friend is distinguishable on facts…',
                          'May it please the Bench, I press my submission on the mandatory statutory notice…',
                          'With respect, the Bench may note that the exception carved out by the statute is inapplicable here…',
                        ].map((q, i) => (
                          <button
                            key={i}
                            type="button"
                            className="quick-reply-chip"
                            onClick={() => setReplyText(q)}
                            disabled={sendingReply}
                          >
                            ✦ {q.length > 55 ? q.slice(0, 55) + '…' : q}
                          </button>
                        ))}
                      </div>
                      <button
                        type="submit"
                        className="debate-send-btn"
                        disabled={sendingReply || replyText.trim().length < 5}
                        id="debate-send-btn"
                      >
                        {sendingReply ? (
                          <><span className="debate-send-spinner">⏳</span> Awaiting AI Rebuttal…</>
                        ) : (
                          <>⚔️ Submit Reply to Court</>
                        )}
                      </button>
                    </div>
                  </form>
                </div>
              )}

              {/* ── Interlocutory Q&A Panel ── */}
              <div className="interlocutory-panel">
                <div className="interlocutory-header">
                  <span style={{ fontSize: '18px' }}>🏛️</span>
                  <span className="interlocutory-title">Bench Interlocutory Inquiry</span>
                  <span className="muted" style={{ fontSize: '12px', marginLeft: 'auto' }}>
                    Put a pointed question to either counsel
                  </span>
                </div>
                <div className="interlocutory-body">
                  <form className="interlocutory-form" onSubmit={handleAskInterlocutory}>
                    <div className="quick-questions">
                      {QUICK_JUDGE_QUESTIONS.map((q, i) => (
                        <button
                          key={i}
                          type="button"
                          className="quick-q-btn"
                          onClick={() => setJudgeQuestion(q)}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                    <div className="interlocutory-row">
                      <select
                        className="counsel-select"
                        value={targetCounsel}
                        onChange={(e) => setTargetCounsel(e.target.value)}
                      >
                        <option value="petitioner">⚖ Petitioner Counsel</option>
                        <option value="respondent">🛡 Respondent Counsel</option>
                      </select>
                      <input
                        type="text"
                        className="interlocutory-input"
                        value={judgeQuestion}
                        onChange={(e) => setJudgeQuestion(e.target.value)}
                        placeholder="Enter bench question for counsel…"
                      />
                      <button
                        type="submit"
                        className="btn-primary"
                        disabled={askingInterlocutory || !judgeQuestion.trim()}
                        style={{ flexShrink: 0 }}
                      >
                        {askingInterlocutory ? 'Addressing…' : 'Ask Counsel ›'}
                      </button>
                    </div>
                  </form>

                  {interlocutoryError && (
                    <div className="error" role="alert" style={{ margin: 0 }}>
                      {interlocutoryError}
                    </div>
                  )}

                  {interlocutoryThreads.length > 0 && (
                    <div className="interlocutory-threads">
                      {interlocutoryThreads.map((th) => (
                        <div key={th.id} className="qa-thread">
                          <div className="qa-question">
                            <span>⚖️ {th.question}</span>
                            <span className="qa-counsel-label">{th.counselTitle}</span>
                            <button
                              type="button"
                              className="btn-quiet small audio-pod-btn"
                              style={{ padding: '2px 8px', fontSize: '11px' }}
                              onClick={() => activeSpeaker === String(th.id) ? stopAllAudio() : speakText(th.target, th.response)}
                            >
                              {activeSpeaker === String(th.id) ? '⏹️' : '🔊'}
                            </button>
                          </div>
                          <div className="qa-answer">
                            <div
                              className="answer-content"
                              dangerouslySetInnerHTML={{ __html: renderMarkdown(th.response) }}
                            />
                            {th.model && (
                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '8px', textAlign: 'right' }}>
                                Delivered via {th.model}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
        </div>
      </div>
    </div>
  )
}
