import { useEffect, useState } from 'react'
import App from './App.jsx'
import AuthScreen from './components/AuthScreen.jsx'
import PublicLanding from './components/PublicLanding.jsx'
import { clearSession, getStoredUser, getToken, validateSession } from './lib/auth.js'

export default function AuthGate() {
  const [user, setUser] = useState(() => getToken() ? getStoredUser() : null)
  const [checking, setChecking] = useState(() => Boolean(getToken()))
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [pendingAction, setPendingAction] = useState(null)

  useEffect(() => { if (!getToken()) return; validateSession().then(u => { setUser(u); setChecking(false) }).catch(() => setChecking(false)) }, [])
  useEffect(() => {
    const logout = () => { clearSession(); setUser(null); setChecking(false) }
    window.addEventListener('smartcourtroom:unauthorized', logout)
    return () => window.removeEventListener('smartcourtroom:unauthorized', logout)
  }, [])

  const openAuth = (mode='login', action=null) => { setAuthMode(mode); setPendingAction(action); setAuthOpen(true) }
  const authenticated = (u) => {
    if (pendingAction) sessionStorage.setItem('lexai:post-auth-action', pendingAction)
    setPendingAction(null); setAuthOpen(false); setUser(u)
  }

  if (checking && !user) return <div className="auth-page"><div className="auth-loading">⚖ Verifying secure session…</div></div>
  if (user) return <App user={user} onLogout={() => { clearSession(); setUser(null) }} />

  return <>
    <PublicLanding
      onRequireAuth={(action) => openAuth('login', action)}
      onSignIn={() => openAuth('login')}
      onCreateAccount={() => openAuth('signup')}
    />
    {authOpen && <div className="modal-backdrop auth-modal-backdrop" onMouseDown={(e)=>{if(e.target===e.currentTarget)setAuthOpen(false)}}>
      <AuthScreen embedded initialMode={authMode} onClose={()=>setAuthOpen(false)} onAuthenticated={authenticated} />
    </div>}
  </>
}
