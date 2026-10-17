import ParticleBackground from './ParticleBackground.jsx'

export default function PublicLanding({ onRequireAuth, onSignIn, onCreateAccount }) {
  const gate = (action) => () => onRequireAuth(action)
  return <div className="public-shell">
    <ParticleBackground />
    <header className="public-topbar">
      <div className="public-brand"><div className="public-mark">⚖</div><div><b>LEXAI</b><small>LEGAL INTELLIGENCE · VERIFIED EVIDENCE</small></div></div>
      <div className="public-auth-actions"><button className="btn-quiet" onClick={onSignIn}>Sign in</button><button className="btn-primary" onClick={onCreateAccount}>Create account</button></div>
    </header>
    <main className="public-main">
      <section className="public-hero">
        <span className="hero-eyebrow">⚖ INDIAN LEGAL INTELLIGENCE SYSTEM</span>
        <h1>ANALYZE YOUR CASE.<br/>GROUND EVERY FACT IN <em>EVIDENCE.</em></h1>
        <p>Upload a judgment, court order or case PDF, ask grounded questions, and verify every important claim against the exact source page and passage.</p>
        <div className="public-badges"><span>● Citation & Evidence Verification</span><span>● Private Document Research</span><span>● Moot Court Simulation</span><span>● Legal Draft Generator</span></div>
        <div className="public-tools">
          <button className="public-primary-upload" onClick={gate('upload')}><strong>📄 Upload & Research a PDF</strong><small>Judgment, court order or case file · private indexing · page-level verification.</small><b>Upload & ask →</b></button>
          <button onClick={gate('moot')}><strong>⚖ Moot Court</strong><small>Practice arguments against an AI bench using your case context.</small><b>Try Moot Court →</b></button>
          <button onClick={gate('draft')}><strong>✎ Legal Drafting</strong><small>Prepare structured legal drafts and notices.</small><b>Start drafting →</b></button>
        </div>
        <section className="public-privacy"><div>🔒</div><div><b>Your case files belong to your private workspace.</b><p>Sign in before uploading. LEXAI keeps case ownership attached to your account and verifies answers against uploaded evidence.</p></div></section>
      </section>
    </main>
  </div>
}
