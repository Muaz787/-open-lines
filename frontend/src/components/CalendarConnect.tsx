'use client'

/**
 * Connecting a booking system WITHOUT leaving onboarding.
 *
 * THE DEFECT THIS CLOSES
 * The step used to be a link to /dashboard/<id>/calendar. The customer clicked
 * it, authorised Google, and the provider's redirect landed them on the
 * dashboard -- so onboarding simply ended there, with notifications never set
 * and, for a regulated tenant, no filing made. Resume would have brought them
 * back, but nothing told them to, and the step that exists to show what the
 * receptionist can do was the one that threw them out of the flow.
 *
 * So the authorisation happens in a popup and the wizard stays on screen. We
 * cannot read the popup's location -- it is cross-origin the moment it reaches
 * Google -- so completion is established the only way it can be: by asking OUR
 * server whether the integration is connected. The popup's own redirect target
 * is unchanged, which is why this needed no OAuth change and no migration.
 *
 * A BLOCKED POPUP IS NOT A DEAD END. If window.open returns null the same URL
 * is opened in this tab, which is exactly the behaviour that shipped before
 * this component existed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { authedFetch, API } from '@/lib/api'
import { CALENDAR_PROVIDERS, type CalendarProviderId } from '@/lib/calendarProviders'

/** How often we ask the server, and for how long. A customer reading Google's
 *  consent screen is not stuck; they are reading. */
const POLL_MS = 2000
const GIVE_UP_MS = 5 * 60 * 1000

export default function CalendarConnect({
  tenantId, connected, onConnected,
}: {
  tenantId: string
  /** What the server said when this step was rendered. */
  connected: boolean
  /** Fired once the server confirms an integration. The wizard decides where to
   *  go next -- this component never names a stage. */
  onConnected: () => void
}) {
  const [busy, setBusy] = useState<CalendarProviderId | null>(null)
  const [error, setError] = useState('')
  const popup = useRef<Window | null>(null)
  const timers = useRef<{ poll?: number; stop?: number }>({})
  const done = useRef(false)

  const clearTimers = useCallback(() => {
    if (timers.current.poll) window.clearInterval(timers.current.poll)
    if (timers.current.stop) window.clearTimeout(timers.current.stop)
    timers.current = {}
  }, [])

  // Leaving the step mid-authorisation must not leave an interval running
  // against an unmounted component.
  useEffect(() => () => clearTimers(), [clearTimers])

  const finish = useCallback(() => {
    if (done.current) return
    done.current = true
    clearTimers()
    try { popup.current?.close() } catch { /* already gone, or cross-origin */ }
    onConnected()
  }, [clearTimers, onConnected])

  /** Ask OUR server, never the popup. */
  const poll = useCallback(async () => {
    try {
      const res = await authedFetch(`${API}/onboarding/setup-state/${tenantId}`)
      if (!res.ok) return
      const st = await res.json()
      if (st?.integration_connected) finish()
    } catch { /* transient; the next tick tries again */ }
  }, [tenantId, finish])

  const watch = useCallback(() => {
    clearTimers()
    timers.current.poll = window.setInterval(() => {
      // A closed popup is a reason to check once more, not a verdict: the
      // customer may have completed the connection in the instant before it
      // closed. Only the server's answer ends this.
      void poll()
      if (popup.current?.closed) { setBusy(null) }
    }, POLL_MS)
    timers.current.stop = window.setTimeout(() => { clearTimers(); setBusy(null) }, GIVE_UP_MS)
  }, [clearTimers, poll])

  async function start(id: CalendarProviderId) {
    const provider = CALENDAR_PROVIDERS.find(p => p.id === id)
    if (!provider || busy) return
    setBusy(id); setError('')

    // Opened synchronously from the click, before any await: a popup opened
    // after a network round trip is one the browser treats as unsolicited and
    // blocks. It is pointed at its destination once we have the URL.
    const win = window.open('', 'ol_calendar_connect',
                            'width=560,height=700,menubar=no,toolbar=no')
    popup.current = win

    try {
      let target: string
      if (provider.start.kind === 'page') {
        target = provider.start.path(tenantId)
      } else {
        const res = await authedFetch(`${API}${provider.start.path(tenantId)}`,
                                      { method: provider.start.method })
        const body = await res.json().catch(() => ({}))
        if (!res.ok || !body?.url) {
          // The server's own reason, when it gave one -- Square refuses a plan
          // that cannot use it, and inventing a message here would hide that.
          throw new Error(typeof body?.detail === 'string' ? body.detail : '')
        }
        target = body.url
      }

      if (win) { win.location.href = target; watch() }
      else {
        // Blocked. Fall back to the pre-popup behaviour rather than stranding
        // them: this tab goes to the provider and resume brings them back.
        window.location.assign(target)
      }
    } catch (e) {
      try { win?.close() } catch { /* nothing to close */ }
      setBusy(null)
      setError(e instanceof Error && e.message
        ? e.message
        : "We couldn't start that connection. Please try again.")
    }
  }

  if (connected) {
    return (
      <div className="np-actions">
        <p className="np-ok" role="status">✓ Booking system connected</p>
        <button type="button" className="np-primary" onClick={onConnected}>
          Continue →
        </button>
      </div>
    )
  }

  return (
    <>
      <div className="np-cards cc-cards">
        {CALENDAR_PROVIDERS.map(p => (
          <button key={p.id} type="button" className="np-card cc-card"
                  disabled={busy !== null} onClick={() => void start(p.id)}>
            <span className="np-card-title">{p.label}</span>
            <span className="np-card-copy">{p.blurb}</span>
            {p.start.kind === 'page' && (
              <span className="cc-note">{p.start.note}</span>
            )}
            {busy === p.id && (
              <span className="cc-note" role="status">
                Waiting for you to finish in the other window…
              </span>
            )}
          </button>
        ))}
      </div>
      {error && <p className="np-error" role="alert">{error}</p>}
    </>
  )
}
