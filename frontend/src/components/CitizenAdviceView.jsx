import { useState } from 'react'

export default function CitizenAdviceView({ advice, onOpenDraft, onReset }) {
  const [copied, setCopied] = useState(false)

  if (!advice) return null

  const handleCopy = async () => {
    const text = `Citizen Legal Assessment: ${advice.incident_summary}
Category: ${advice.category}

Applicable Laws:
${(advice.applicable_laws || []).map((l) => `- ${l.section} (${l.act}): ${l.title} [${l.nature}] - ${l.penalty_or_relief}`).join('\n')}

Your Rights:
${advice.rights_summary}

Action Plan:
${(advice.action_plan || []).map((a) => `Step ${a.step_number}: ${a.title} - ${a.action} (Portal: ${a.authority_or_portal})`).join('\n')}

Urgency:
${advice.urgency_and_deadlines}`

    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

  return (
    <article className="citizen-view-container">
      {/* Top Header */}
      <div className="citizen-header-card">
        <div className="citizen-eyebrow-row">
          <span className="citizen-mode-tag">🛡️ Citizen Legal Advisor</span>
          <span className="citizen-category-tag">{advice.category || 'Everyday Legal Issue'}</span>
          <span className="citizen-remedy-tag">
            {advice.has_legal_remedy ? '✅ Legal Remedies Available' : 'ℹ️ Advisory Guidance'}
          </span>
        </div>

        <h2 className="citizen-issue-title">{advice.incident_summary || advice.incident}</h2>

        <div className="citizen-actions-bar">
          <button
            type="button"
            className="btn-primary"
            onClick={() => onOpenDraft && onOpenDraft(advice.recommended_draft)}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
          >
            <span>📝</span>
            <span>{advice.recommended_draft?.label || 'Generate Legal Notice / Complaint'}</span>
          </button>
          <button type="button" className="btn-quiet" onClick={handleCopy}>
            {copied ? '✅ Copied Summary' : '📋 Copy Advice'}
          </button>
          <button type="button" className="btn-quiet" onClick={onReset}>
            🔄 Ask Another Question
          </button>
        </div>
      </div>

      {/* Rights Summary Callout */}
      {advice.rights_summary && (
        <div className="citizen-rights-card">
          <div className="citizen-section-heading">
            <span>🛡️</span>
            <span>Your Rights & What the Law Guarantees You</span>
          </div>
          <p className="citizen-rights-text">{advice.rights_summary}</p>
        </div>
      )}

      {/* Grid of Applicable Laws */}
      <div className="citizen-laws-section">
        <h3 className="citizen-subheading">⚖️ Applicable Indian Laws & Punishments</h3>
        <div className="citizen-laws-grid">
          {(advice.applicable_laws || []).map((law, idx) => (
            <div key={idx} className="citizen-law-card">
              <div className="law-card-top">
                <span className="law-section-badge">{law.section}</span>
                <span className={`law-nature-badge ${String(law.nature || '').toLowerCase().includes('criminal') ? 'criminal' : 'civil'}`}>
                  {law.nature || 'Statutory Provision'}
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

      {/* 3-Step Action Roadmap */}
      <div className="citizen-roadmap-section">
        <h3 className="citizen-subheading">📋 Your 3-Step Practical Action Plan</h3>
        <div className="citizen-steps-list">
          {(advice.action_plan || []).map((step) => (
            <div key={step.step_number} className="citizen-step-card">
              <div className="step-number-circle">{step.step_number}</div>
              <div className="step-content">
                <div className="step-header-row">
                  <h4 className="step-title">{step.title}</h4>
                  {step.authority_or_portal && (
                    <span className="step-portal-badge">📍 {step.authority_or_portal}</span>
                  )}
                </div>
                <p className="step-action-desc">{step.action}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Limitation & Urgency Alert */}
      {advice.urgency_and_deadlines && (
        <div className="citizen-urgency-card">
          <div className="urgency-icon">⏳</div>
          <div className="urgency-body">
            <h4 className="urgency-title">Limitation Period & Time Sensitivity</h4>
            <p className="urgency-desc">{advice.urgency_and_deadlines}</p>
          </div>
        </div>
      )}

      {/* Grounded Precedents if matching from local index */}
      {advice.supporting_corpus_cases && advice.supporting_corpus_cases.length > 0 && (
        <div className="citizen-precedents-section">
          <h3 className="citizen-subheading">📚 Landmark Judgments in Local Corpus Supporting Your Stand</h3>
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

      {/* Bottom CTA to Draft Notice */}
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
          📝 {advice.recommended_draft?.label || 'Draft Legal Notice'} ›
        </button>
      </div>
    </article>
  )
}
