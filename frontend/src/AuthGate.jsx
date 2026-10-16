import { useEffect, useState } from 'react'
import App from './App.jsx'
import AuthScreen from './components/AuthScreen.jsx'
import { clearSession, getStoredUser, getToken, validateSession } from './lib/auth.js'

export default function AuthGate() {
  const [user, setUser] = useState(() => getToken() ? getStoredUser() : null)
  const [checking, setChecking] = useState(() => Boolean(getToken()))
  useEffect(() => { if (!getToken()) return; validateSession().then(u => { setUser(u); setChecking(false) }) }, [])
  useEffect(() => {
    const logout = () => { clearSession(); setUser(null); setChecking(false) }
    window.addEventListener('smartcourtroom:unauthorized', logout)
    return () => window.removeEventListener('smartcourtroom:unauthorized', logout)
  }, [])
  if (checking && !user) return <div className="auth-page"><div className="auth-loading">⚖ Verifying secure session…</div></div>
  if (!user) return <AuthScreen onAuthenticated={setUser} />
  return <App user={user} onLogout={() => { clearSession(); setUser(null) }} />
}
