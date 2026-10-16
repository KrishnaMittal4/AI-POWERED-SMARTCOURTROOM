const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'smart-courtroom:auth-token'
const USER_KEY = 'smart-courtroom:auth-user'

export function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }
export function getStoredUser() { try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null } }
export function saveSession(token, user) { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)) }
export function clearSession() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) }

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {})
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(url, { ...options, headers })
  if (res.status === 401 && !String(url).includes('/auth/')) window.dispatchEvent(new Event('smartcourtroom:unauthorized'))
  return res
}

export async function authenticate(mode, fields) {
  const res = await fetch(`${API_BASE}/auth/${mode}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Authentication failed.')
  saveSession(data.token, data.user)
  return data.user
}

export async function validateSession() {
  if (!getToken()) return null
  try {
    const res = await apiFetch(`${API_BASE}/auth/me`)
    if (!res.ok) { clearSession(); return null }
    const data = await res.json(); localStorage.setItem(USER_KEY, JSON.stringify(data.user)); return data.user
  } catch { return getStoredUser() }
}
