// Did the auth service say this session is no good? A redirect to /login is right only
// then. Anything else says nothing about the session, including most 4xx responses: a
// disabled API key is a 401 and a validation problem is a 400. Those get a retry.
// Neither state grants anything: the page shows no account content, and the backend
// verifies the token on every request regardless.
export type AuthCheck = 'ok' | 'expired' | 'unavailable'

interface AuthFailure {
  name?: string
  status?: number
  code?: string
  message?: string
}

// Supabase Auth's own codes for a missing, expired or rejected session.
const SESSION_REJECTED = new Set([
  'bad_jwt',
  'no_authorization',
  'session_expired',
  'session_not_found',
  'refresh_token_not_found',
  'refresh_token_already_used',
  'user_not_found',
  'user_banned',
])

export function classifyAuth(hasUser: boolean, error?: AuthFailure | null): AuthCheck {
  if (hasUser) return 'ok'
  if (!error) return 'expired' // Auth answered: there is no session.
  if (error.name === 'AuthSessionMissingError') return 'expired'
  return error.code && SESSION_REJECTED.has(error.code) ? 'expired' : 'unavailable'
}

// Supabase's client deletes the stored session on any refresh failure it doesn't count
// as temporary, including a 500 or a 429, so its result arrives too late to read. A
// failure that isn't a session rejection is reported to it as a 503, which it retries
// and which keeps the session. No token is issued by this.
export async function keepSessionUnlessRejected(url: string, res: Response): Promise<Response> {
  if (res.ok || !url.includes('grant_type=refresh_token')) return res
  const body = await res.clone().json().catch(() => null)
  return SESSION_REJECTED.has(body?.code ?? body?.error_code) ? res : new Response(null, { status: 503 })
}

// A failed password check, as opposed to one that never ran.
export function isWrongPassword(error: AuthFailure): boolean {
  return error.code === 'invalid_credentials'
}
