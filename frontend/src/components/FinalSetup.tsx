'use client'

/**
 * The last step: ask the lifecycle to take this tenant as far as it safely can.
 *
 * THE CUSTOMER DOES NOT CHOOSE. Whether they end up with their permanent number
 * or a temporary test line depends on what the PROVIDER says about their filing,
 * read fresh on the server. This screen starts the work and reports what came
 * back; it decides nothing, and there is no control here that could.
 *
 * Idempotent by construction — the endpoint wakes a lifecycle that converges, so
 * a double click, a refresh or a retry costs one provider read and changes
 * nothing twice.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { authedFetch, API } from '@/lib/api'

export type SetupState = {
  needs_regulatory_verification: boolean
  regulatory: { done: boolean; blocked: boolean } | null
  integration_connected: boolean
  notifications_set: boolean
  phone: { permanent: string | null; temporary_test: string | null }
  trial: { started: boolean; ends_at: string | null; pending_activation: boolean }
  next_stage: string
}

export default function FinalSetup({
  tenantId, onDone, onBlocked,
}: {
  tenantId: string
  onDone: (s: SetupState) => void
  onBlocked: (message: string) => void
}) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const started = useRef(false)

  const run = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const res = await authedFetch(`${API}/onboarding/finalize/${tenantId}`,
                                    { method: 'POST' })
      if (!res.ok) throw new Error(String(res.status))
      const st: SetupState = await res.json()

      // A filing needing correction outranks everything: nothing downstream can
      // succeed while it waits, so the customer goes back rather than watching
      // a spinner that will never finish.
      if (st.regulatory?.blocked) {
        onBlocked('Your verification needs a few corrections before we can '
                  + 'finish setting up your number.')
        return
      }
      if (st.phone.permanent || st.phone.temporary_test) { onDone(st); return }

      // Nothing yet. Not an error: a regulator may simply still be reading, and
      // the autonomous lifecycle keeps working without the customer waiting here.
      onDone(st)
    } catch {
      // Never surface a provider error string. Retryable, and the customer's
      // setup is already saved.
      setError("We couldn't finish setting up your line just yet. "
               + 'Your details are saved — please try again.')
    } finally {
      setBusy(false)
    }
  }, [tenantId, onDone, onBlocked])

  useEffect(() => {
    if (started.current) return
    started.current = true
    void run()
  }, [run])

  if (error) {
    return (
      <div className="np">
        <h2 className="np-title">Almost there</h2>
        <p className="np-sub">{error}</p>
        <div className="np-actions">
          <button type="button" className="np-primary" onClick={() => void run()}>
            Try again →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="np" aria-busy={busy}>
      <h2 className="np-title">Setting up your phone line…</h2>
      <p className="np-sub">
        This takes a few moments. You don&apos;t need to do anything.
      </p>
      <div className="fs-spinner" role="status" aria-label="Setting up" />
    </div>
  )
}
