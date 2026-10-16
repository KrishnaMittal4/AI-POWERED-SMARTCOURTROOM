import { useState } from 'react'
import { authenticate } from '../lib/auth.js'

export default function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault(); setError(''); setBusy(true)
    try {
      const user = await authenticate(mode === 'login' ? 'login' : 'signup', mode === 'login' ? { email, password } : { name, email, password })
      onAuthenticated(user)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <main className="auth-page">
    <section className="auth-card" aria-labelledby="auth-title">
      <div className="auth-mark">⚖</div>
      <div className="auth-kicker">SMART COURTROOM</div>
      <h1 id="auth-title">{mode === 'login' ? 'Welcome back' : 'Create your legal workspace'}</h1>
      <p className="auth-copy">{mode === 'login' ? 'Sign in to access your private research workspace and history.' : 'Your account keeps your research history separate from other Smart Courtroom users.'}</p>
      <div className="auth-tabs" role="tablist">
        <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError('') }}>Sign in</button>
        <button type="button" className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError('') }}>Create account</button>
      </div>
      <form className="auth-form" onSubmit={submit}>
        {mode === 'signup' && <label>Full name<input value={name} onChange={e => setName(e.target.value)} autoComplete="name" minLength={2} required placeholder="Your name" /></label>}
        <label>Email address<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required placeholder="you@example.com" /></label>
        <label>Password<div className="auth-password"><input type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required placeholder="At least 8 characters" /><button type="button" onClick={() => setShowPassword(v => !v)}>{showPassword ? 'Hide' : 'Show'}</button></div></label>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <button className="auth-submit" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in to Smart Courtroom' : 'Create my workspace'}</button>
      </form>
      <p className="auth-note">🔒 Passwords are salted and hashed. Your session is protected by a signed access token.</p>
    </section>
  </main>
}
