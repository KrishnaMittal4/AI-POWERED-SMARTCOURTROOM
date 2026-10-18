import { useState, useCallback, useEffect } from "react"
import { speakLegalAdvice, stopSpeaking } from "../lib/courtAudio.js"

const HELPLINE_ICONS = {
  phone: "📞",
  web: "🌐",
  phone_and_web: "📞",
}

function exportAdvisoryPDF(advice) {
  const date = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })
  const refNo = `LA/${new Date().getFullYear()}/CIT-${Math.floor(1000 + Math.random() * 9000)}`

  const lawRows = (advice.applicable_laws || []).map(l => `
    <tr>
      <td style="padding:8px 10px;border:1px solid #e2c56b;font-family:monospace;font-size:12px;color:#b8860b;font-weight:700">${l.section}</td>
      <td style="padding:8px 10px;border:1px solid #e2c56b;font-size:12px;font-weight:700">${l.act}</td>
      <td style="padding:8px 10px;border:1px solid #e2c56b;font-size:12px">${l.title}</td>
      <td style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;color:#7c3aed">${l.nature}</td>
      <td style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px">${l.penalty_or_relief}</td>
    </tr>`).join("")

  const stepHtml = (advice.action_plan || []).map(s => `
    <div style="display:flex;gap:14px;margin-bottom:14px">
      <div style="width:28px;height:28px;border-radius:50%;background:#b8860b;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0">${s.step_number}</div>
      <div>
        <div style="font-weight:700;font-size:13px;margin-bottom:3px">${s.title}</div>
        <div style="font-size:12px;line-height:1.6;color:#444">${s.action}</div>
        <div style="font-size:11px;margin-top:4px;color:#b8860b;font-weight:600">📍 ${s.authority_or_portal}</div>
      </div>
    </div>`).join("")

  const helplineHtml = (advice.helplines_and_portals || []).map(h => `
    <li style="margin-bottom:6px;font-size:12px">
      <strong>${h.name}</strong>
      ${h.contact ? ` — <a href="tel:${h.contact}" style="color:#b8860b">${h.contact}</a>` : ""}
      ${h.url && h.url.startsWith("http") ? ` — <a href="${h.url}" style="color:#b8860b">${h.url}</a>` : ""}
    </li>`).join("")

  const win = window.open("", "_blank", "width=900,height=1100")
  if (!win) { alert("Allow pop-ups to export the advisory PDF."); return }

  win.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Citizen Legal Advisory — ${refNo}</title>
<style>
  @import url("https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap");
  body{margin:0;padding:40px 48px;font-family:"Source Serif 4",Georgia,serif;color:#1a1a1a;background:#fff}
  h1,h2,h3{font-family:Cinzel,serif}
  table{border-collapse:collapse;width:100%}
  @media print{body{padding:24px}}
</style>
</head>
<body>
  <div style="text-align:center;border-bottom:3px double #b8860b;padding-bottom:20px;margin-bottom:24px">
    <div style="font-size:11px;letter-spacing:.2em;color:#b8860b;font-weight:700;text-transform:uppercase">LEXAI — Citizen Legal Advisory</div>
    <h1 style="font-size:22px;margin:8px 0 4px">🛡️ Legal Rights &amp; Action Report</h1>
    <div style="font-size:11px;color:#666">Ref: ${refNo} &nbsp;|&nbsp; Date: ${date}</div>
  </div>
  <div style="background:#fffbeb;border:1px solid #e2c56b;border-radius:8px;padding:16px 20px;margin-bottom:20px">
    <div style="font-size:10px;font-weight:700;letter-spacing:.15em;color:#b8860b;text-transform:uppercase;margin-bottom:6px">Incident Summary</div>
    <div style="font-size:14px;font-weight:600">${advice.incident_summary || advice.incident}</div>
    <div style="margin-top:6px;font-size:11px;color:#666">Category: ${advice.category}</div>
  </div>
  <h3 style="font-size:13px;letter-spacing:.08em;margin-bottom:10px">YOUR LEGAL RIGHTS</h3>
  <p style="font-size:13px;line-height:1.7;color:#333;margin-bottom:20px">${advice.rights_summary}</p>
  <h3 style="font-size:13px;letter-spacing:.08em;margin-bottom:10px">APPLICABLE LAWS &amp; PROVISIONS</h3>
  <table style="margin-bottom:20px">
    <thead><tr style="background:#fffbeb">
      <th style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;text-align:left">Section</th>
      <th style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;text-align:left">Act</th>
      <th style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;text-align:left">Provision</th>
      <th style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;text-align:left">Nature</th>
      <th style="padding:8px 10px;border:1px solid #e2c56b;font-size:11px;text-align:left">Remedy</th>
    </tr></thead>
    <tbody>${lawRows}</tbody>
  </table>
  <h3 style="font-size:13px;letter-spacing:.08em;margin-bottom:14px">3-STEP ACTION ROADMAP</h3>
  ${stepHtml}
  <div style="background:#fffbeb;border:1px solid #e2c56b;border-radius:6px;padding:14px 18px;margin:20px 0">
    <div style="font-weight:700;font-size:12px;color:#b8860b;margin-bottom:6px">⏳ LIMITATION PERIOD &amp; TIME SENSITIVITY</div>
    <div style="font-size:12px;line-height:1.6">${advice.urgency_and_deadlines}</div>
  </div>
  <h3 style="font-size:13px;letter-spacing:.08em;margin-bottom:8px">OFFICIAL HELPLINES &amp; PORTALS</h3>
  <ul style="padding-left:20px;margin-bottom:20px">${helplineHtml}</ul>
  <div style="margin-top:32px;border-top:1px solid #e2c56b;padding-top:12px;font-size:10px;color:#888;text-align:center">
    This advisory is for informational purposes only. Consult a licensed advocate for formal legal proceedings.<br/>
    Generated by LEXAI — AI-Powered Smart Courtroom | ${date}
  </div>
  <script>window.onload=()=>{window.print()}<\/script>
</body></html>`)
  win.document.close()
}

export default function CitizenAdviceView({ advice, onOpenDraft, onReset, lang, onChangeLang, onOpenScanNotice }) {
  const [copied, setCopied] = useState(false)
  const [checkedSteps, setCheckedSteps] = useState({})
  const [speaking, setSpeaking] = useState(false)

  // Stop speaking when unmounted or advice changes
  useEffect(() => {
    return () => stopSpeaking()
  }, [advice])

  if (!advice) return null

  const handleToggleSpeech = () => {
    if (speaking) {
      stopSpeaking()
      setSpeaking(false)
      return
    }

    const narrationText = [
      advice.rights_summary ? `Your Legal Rights: ${advice.rights_summary}` : "",
      "Action Roadmap:",
      ...(advice.action_plan || []).map(s => `Step ${s.step_number}. ${s.title}: ${s.action}.`),
      advice.urgency_and_deadlines ? `Important Deadlines: ${advice.urgency_and_deadlines}` : ""
    ].filter(Boolean).join(" ")

    const started = speakLegalAdvice(narrationText, lang || "en", {
      onStart: () => setSpeaking(true),
      onEnd: () => setSpeaking(false),
      onError: () => setSpeaking(false),
    })
    if (started) setSpeaking(true)
  }

  const toggleStep = useCallback((n) => {
    setCheckedSteps(prev => ({ ...prev, [n]: !prev[n] }))
  }, [])

  const handleShareWhatsApp = () => {
    const text = [
      "🛡️ *CITIZEN LEGAL ADVISORY — LEXAI*",
      `*Issue:* ${advice.incident_summary || advice.incident}`,
      `*Category:* ${advice.category}`,
      "",
      "⚖️ *YOUR LEGAL RIGHTS:*",
      advice.rights_summary,
      "",
      "📋 *RECOMMENDED ACTION STEPS:*",
      ...(advice.action_plan || []).map(s => `${s.step_number}. *${s.title}*: ${s.action} (Portal: ${s.authority_or_portal})`),
      "",
      `⏳ *DEADLINE / URGENCY:* ${advice.urgency_and_deadlines}`,
      "",
      "📞 *OFFICIAL HELPLINES:*",
      ...(advice.helplines_and_portals || []).map(h => `• ${h.name}${h.contact ? " — Call " + h.contact : ""}${h.url ? " — " + h.url : ""}`)
    ].join("\n")

    const url = `https://wa.me/?text=${encodeURIComponent(text)}`
    window.open(url, "_blank")
  }

  const handleCopy = async () => {
    const text = [
      "CITIZEN LEGAL ADVISORY — LEXAI",
      "==============================",
      `Issue: ${advice.incident_summary || advice.incident}`,
      `Category: ${advice.category}`,
      "",
      "YOUR RIGHTS:",
      advice.rights_summary,
      "",
      "APPLICABLE LAWS:",
      ...(advice.applicable_laws || []).map(l => `• ${l.section} (${l.act}): ${l.title} [${l.nature}] — ${l.penalty_or_relief}`),
      "",
      "ACTION PLAN:",
      ...(advice.action_plan || []).map(a => `Step ${a.step_number}: ${a.title}\n  ${a.action}\n  Portal: ${a.authority_or_portal}`),
      "",
      `URGENCY: ${advice.urgency_and_deadlines}`,
      "",
      "HELPLINES:",
      ...(advice.helplines_and_portals || []).map(h => `• ${h.name}${h.contact ? " — " + h.contact : ""}${h.url && h.url.startsWith("http") ? " — " + h.url : ""}`)
    ].join("\n")

    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* ignore */ }
  }

  const completedCount = Object.values(checkedSteps).filter(Boolean).length
  const totalSteps = (advice.action_plan || []).length
  const progressPct = totalSteps > 0 ? (completedCount / totalSteps) * 100 : 0

  return (
    <article className="citizen-view-container">

      {/* ── Header Card ── */}
      <div className="citizen-header-card">
        <div className="citizen-eyebrow-row">
          <span className="citizen-mode-tag">🛡️ Citizen Legal Advisor</span>
          <span className="citizen-category-tag">{advice.category || "Everyday Legal Issue"}</span>
          <span className="citizen-remedy-tag">
            {advice.has_legal_remedy ? "✅ Legal Remedies Available" : "ℹ️ Advisory Guidance"}
          </span>
          {advice.llm_provider && (
            <span className="citizen-provider-tag">
              {advice.llm_provider === "gemini" ? "✦ Gemini" : "⚡ Groq"}
            </span>
          )}
        </div>

        <h2 className="citizen-issue-title">{advice.incident_summary || advice.incident}</h2>

        {/* Language toggle */}
        <div className="citizen-lang-bar">
          <span className="citizen-lang-label">Language:</span>
          <button
            type="button"
            className={`citizen-lang-btn${lang === "en" ? " active" : ""}`}
            onClick={() => onChangeLang && onChangeLang("en")}
          >🇬🇧 English</button>
          <button
            type="button"
            className={`citizen-lang-btn${lang === "hi" ? " active" : ""}`}
            onClick={() => onChangeLang && onChangeLang("hi")}
          >🇮🇳 हिन्दी</button>
          {lang === "hi" && (
            <span className="citizen-lang-note">Re-submit your incident to get advice in Hindi</span>
          )}
        </div>

        <div className="citizen-actions-bar">
          <button
            type="button"
            className="btn-primary"
            onClick={() => onOpenDraft && onOpenDraft(advice.recommended_draft)}
            style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}
          >
            <span>📝</span>
            <span>{advice.recommended_draft?.label || "Generate Legal Notice / Complaint"}</span>
          </button>
          <button
            type="button"
            className={`btn-quiet ${speaking ? "btn-speaking" : ""}`}
            onClick={handleToggleSpeech}
            title={speaking ? "Stop voice playback" : "Listen to legal advice read aloud"}
          >
            {speaking ? "⏹️ Stop Voice" : "🔊 Listen to Advice"}
          </button>
          <button type="button" className="btn-quiet" onClick={() => onOpenScanNotice && onOpenScanNotice()}>
            📄 Scan Notice / Contract
          </button>
          <button type="button" className="btn-quiet" onClick={() => exportAdvisoryPDF(advice)}>
            🖨️ Export PDF
          </button>
          <button
            type="button"
            className="btn-quiet citizen-whatsapp-btn"
            onClick={handleShareWhatsApp}
            title="Share this legal advice via WhatsApp"
          >
            💬 WhatsApp
          </button>
          <button type="button" className="btn-quiet" onClick={handleCopy}>
            {copied ? "✅ Copied" : "📋 Copy Advice"}
          </button>
          <button type="button" className="btn-quiet" onClick={onReset}>
            🔄 New Question
          </button>
        </div>
      </div>

      {/* ── Rights Summary ── */}
      {advice.rights_summary && (
        <div className="citizen-rights-card">
          <div className="citizen-section-heading">
            <span>🛡️</span>
            <span>Your Rights &amp; What the Law Guarantees You</span>
          </div>
          <p className="citizen-rights-text">{advice.rights_summary}</p>
        </div>
      )}

      {/* ── Applicable Laws Grid ── */}
      <div className="citizen-laws-section">
        <h3 className="citizen-subheading">⚖️ Applicable Indian Laws &amp; Punishments</h3>
        <div className="citizen-laws-grid">
          {(advice.applicable_laws || []).map((law, idx) => (
            <div key={idx} className="citizen-law-card">
              <div className="law-card-top">
                <span className="law-section-badge">{law.section}</span>
                <span className={`law-nature-badge ${String(law.nature || "").toLowerCase().includes("criminal") ? "criminal" : "civil"}`}>
                  {law.nature || "Statutory Provision"}
                </span>
              </div>
              <h4 className="law-act-title">{law.act}</h4>
              <p className="law-provision-title">{law.title}</p>
              {law.penalty_or_relief && (
                <div className="law-relief-box">
                  <span className="relief-label">Remedy / Penalty:</span>
                  <span className="relief-text">{law.penalty_or_relief}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Interactive Step Checklist ── */}
      <div className="citizen-roadmap-section">
        <div className="citizen-roadmap-header">
          <h3 className="citizen-subheading" style={{ margin: 0 }}>📋 Your 3-Step Practical Action Plan</h3>
          {totalSteps > 0 && (
            <div className="citizen-progress-track">
              <div className="citizen-progress-bar">
                <div className="citizen-progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
              <span className="citizen-progress-label">{completedCount}/{totalSteps} done</span>
            </div>
          )}
        </div>
        <div className="citizen-steps-list">
          {(advice.action_plan || []).map((step) => (
            <div
              key={step.step_number}
              className={`citizen-step-card${checkedSteps[step.step_number] ? " step-done" : ""}`}
              onClick={() => toggleStep(step.step_number)}
              role="checkbox"
              aria-checked={!!checkedSteps[step.step_number]}
              tabIndex={0}
              onKeyDown={(e) => (e.key === " " || e.key === "Enter") && toggleStep(step.step_number)}
              style={{ cursor: "pointer" }}
            >
              <div className={`step-number-circle${checkedSteps[step.step_number] ? " step-circle-done" : ""}`}>
                {checkedSteps[step.step_number] ? "✓" : step.step_number}
              </div>
              <div className="step-content">
                <div className="step-header-row">
                  <h4 className="step-title">{step.title}</h4>
                  {step.authority_or_portal && (
                    <span className="step-portal-badge">📍 {step.authority_or_portal}</span>
                  )}
                </div>
                <p className="step-action-desc">{step.action}</p>
              </div>
              <div className="step-checkbox-wrap">
                <span className={`step-checkbox${checkedSteps[step.step_number] ? " checked" : ""}`}>
                  {checkedSteps[step.step_number] ? "✓" : ""}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Urgency Alert ── */}
      {advice.urgency_and_deadlines && (
        <div className="citizen-urgency-card">
          <div className="urgency-icon">⏳</div>
          <div className="urgency-body">
            <h4 className="urgency-title">Limitation Period &amp; Time Sensitivity</h4>
            <p className="urgency-desc">{advice.urgency_and_deadlines}</p>
          </div>
        </div>
      )}

      {/* ── Clickable Helplines & Portals ── */}
      {advice.helplines_and_portals && advice.helplines_and_portals.length > 0 && (
        <div className="citizen-helplines-section">
          <h3 className="citizen-subheading">📞 Helplines &amp; Official Portals — Take Action Now</h3>
          <div className="citizen-helplines-grid">
            {advice.helplines_and_portals.map((h, i) => (
              <div key={i} className="citizen-helpline-card">
                <div className="helpline-icon">{HELPLINE_ICONS[h.type] || "📞"}</div>
                <div className="helpline-body">
                  <div className="helpline-name">{h.name}</div>
                  <div className="helpline-links">
                    {h.contact && (
                      <a
                        href={`tel:${h.contact}`}
                        className="helpline-btn helpline-call"
                        onClick={(e) => e.stopPropagation()}
                      >
                        📞 {h.contact}
                      </a>
                    )}
                    {h.url && h.url.startsWith("http") && (
                      <a
                        href={h.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="helpline-btn helpline-web"
                        onClick={(e) => e.stopPropagation()}
                      >
                        🌐 Visit Portal
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Supporting Corpus Precedents ── */}
      {advice.supporting_corpus_cases && advice.supporting_corpus_cases.length > 0 && (
        <div className="citizen-precedents-section">
          <h3 className="citizen-subheading">📚 Landmark Judgments Supporting Your Stand</h3>
          <div className="citizen-precedents-list">
            {advice.supporting_corpus_cases.map((c, i) => (
              <div key={i} className="citizen-precedent-card">
                <div className="precedent-card-header">
                  <strong>{c.case_name}</strong>
                  <span className="court-tag">{c.court}</span>
                </div>
                <p className="precedent-snippet">{c.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Bottom CTA ── */}
      <div className="citizen-bottom-cta">
        <div className="cta-text-group">
          <h3>Ready to take legal action?</h3>
          <p>Generate a formal legal notice or complaint draft tailored to your incident in 1 click.</p>
        </div>
        <button
          type="button"
          className="btn-primary large"
          onClick={() => onOpenDraft && onOpenDraft(advice.recommended_draft)}
        >
          📝 {advice.recommended_draft?.label || "Draft Legal Notice"} ›
        </button>
      </div>

    </article>
  )
}
