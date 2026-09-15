import { supabase } from '@/lib/supabase'
import { shareInflight, clearResponseCache } from '@/lib/requestCache'

export { peekJson, clearResponseCache } from '@/lib/requestCache'

// Backend API base. Mirrors the per-page `const API = …` so callers can keep
// passing full `${API}/…` URLs to authedFetch.
export const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Drop-in replacement for `fetch` for all tenant-scoped dashboard API calls.
 *
 * - Attaches the current Supabase session access token as a Bearer header so the
 *   backend can verify the caller actually owns the tenant in the URL.
 * - Handles missing/expired sessions cleanly: if there is no token we still send
 *   the request (so genuinely public endpoints keep working), and if the backend
 *   rejects it with 401 we bounce the user to /login.
 *
 * - Identical GETs issued at the same moment share one request, and each
 *   successful GET body is remembered for peekJson(); any mutation clears that
 *   memory. See lib/requestCache.ts.
 *
 * Usage: identical to fetch — `authedFetch(`${API}/leads/${tenantId}`)`.
 */
export async function authedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  if (method !== 'GET') {
    // Before AND after: a GET racing the mutation must not repaint stale data.
    clearResponseCache()
    try { return await send(input, init) } finally { clearResponseCache() }
  }
  // Only plain URL GETs are shared; a caller with its own AbortSignal keeps its own request.
  if (init.signal || !(typeof input === 'string' || input instanceof URL)) return send(input, init)
  return shareInflight(String(input), () => send(input, init))
}

async function send(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  let token: string | undefined
  try {
    const { data } = await supabase.auth.getSession()
    token = data.session?.access_token
  } catch {
    token = undefined
  }

  const headers = new Headers(init.headers ?? {})
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(input, { ...init, headers })

  // Session missing or expired — the backend rejected us. Send to login.
  if (res.status === 401 && typeof window !== 'undefined') {
    window.location.href = '/login'
  }

  return res
}
