// Did the auth service answer, and what did it say? A redirect to /login is right
// only when it said the session is no good. A failure to reach it says nothing about
// the session, so that gets a retry. Neither state grants anything: the page shows no
// account content, and the backend verifies the token on every request regardless.
export type AuthCheck = 'ok' | 'expired' | 'unavailable'

interface AuthFailure {
  name?: string
  status?: number
}

export function classifyAuth(hasUser: boolean, error?: AuthFailure | null): AuthCheck {
  if (hasUser) return 'ok'
  if (!error) return 'expired'
  if (error.name === 'AuthRetryableFetchError') return 'unavailable'
  const status = error.status ?? 0
  const rejected = status >= 400 && status < 500 && status !== 408 && status !== 429
  return rejected ? 'expired' : 'unavailable'
}
