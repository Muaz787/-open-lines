'use client'

/**
 * Where every OAuth round trip lands, and nothing else.
 *
 * THE DEFECT THIS CLOSES
 * Callbacks used to redirect to a full dashboard page. When the authorisation
 * runs in a popup opened by onboarding, the popup loaded the whole dashboard --
 * session check, tenant fetch, appointments, call state -- painted it, and only
 * then got closed by the opener's next poll. A customer in the middle of signing
 * up watched a dashboard they had not asked for appear and vanish.
 *
 * So this page exists to render almost nothing. It pulls in no dashboard route,
 * no layout, no query, and it is deliberately NOT under /dashboard so none of
 * that can be reached by accident.
 *
 * IT DECIDES ONE THING THE SERVER CANNOT: whether this window has an opener.
 * Only the browser knows. With an opener it is our popup and closes; without
 * one the customer's browser blocked the popup and completed in this tab, so it
 * continues to the page the round trip began on.
 *
 * IT NEVER ACCEPTS A URL. The context is one of three known words and the
 * destination is built here from that word; a query string cannot express a
 * host, a scheme or a path segment. An unrecognised context resolves to the
 * default rather than being obeyed. Mirrors services/oauth_return.py, and
 * tests assert the two vocabularies match.
 */

import { useEffect, useState } from 'react'

const ORIGINS = ['onboarding', 'calendar', 'payments'] as const
type Origin = (typeof ORIGINS)[number]
const DEFAULT_ORIGIN: Origin = 'calendar'

/** Loose on purpose: this only decides whether a value is safe to interpolate
 *  into a path, not whether the tenant exists. The server already proved that. */
const TENANT_ID = /^[0-9a-fA-F-]{8,64}$/

/** The query the dashboard pages already listen for, so their toasts still fire. */
function dashboardQuery(provider: string, ok: boolean): string {
  if (provider === 'square') return `square=${ok ? 'connected' : 'error'}`
  if (provider === 'microsoft') return `calendar=${ok ? 'ms_connected' : 'ms_error'}`
  return `calendar=${ok ? 'connected' : 'error'}`
}

export function destinationFor(
  ctx: string, tenant: string, provider: string, status: string,
): string {
  const origin: Origin = (ORIGINS as readonly string[]).includes(ctx)
    ? (ctx as Origin) : DEFAULT_ORIGIN
  // Onboarding needs no tenant in the path: the wizard resumes from durable
  // server state, which is the only thing allowed to decide the stage.
  if (origin === 'onboarding') return '/onboarding'
  if (!TENANT_ID.test(tenant)) return '/'
  return `/dashboard/${tenant}/${origin}?${dashboardQuery(provider, status === 'connected')}`
}

export default function OAuthComplete() {
  const [manual, setManual] = useState(false)

  useEffect(() => {
    let params: URLSearchParams
    try { params = new URLSearchParams(window.location.search) } catch { return }
    const ctx = params.get('ctx') ?? ''
    const tenant = params.get('tenant') ?? ''
    const provider = params.get('provider') ?? ''
    const status = params.get('status') ?? ''

    // Our popup: close, and let the opener find out from the server whether the
    // connection actually succeeded. A closed window is not evidence of that.
    if (window.opener && !window.opener.closed) {
      try { window.close() } catch { /* fall through to the manual note */ }
      // close() is only honoured for script-opened windows. If we are still
      // here a moment later, say so rather than leaving a blank page.
      const t = window.setTimeout(() => setManual(true), 800)
      return () => window.clearTimeout(t)
    }

    window.location.replace(destinationFor(ctx, tenant, provider, status))
  }, [])

  return (
    <main style={{
      minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24,
      fontFamily: 'var(--font-dm), system-ui, sans-serif',
    }}>
      <p style={{ fontSize: 14, opacity: 0.75 }}>
        {manual ? 'All done — you can close this window.' : 'Finishing connection…'}
      </p>
    </main>
  )
}
