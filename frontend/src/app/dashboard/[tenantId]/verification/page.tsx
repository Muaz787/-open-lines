'use client'

/**
 * Irish business verification (W9I-C).
 *
 * Every decision here is the backend's. The field list comes from the provider's
 * live Regulation, the review comes from persisted rows, the consent wording is
 * server-owned, and the error text is the server's controlled contract — this
 * page renders them, it does not decide them. A hardcoded Irish field list would
 * keep collecting the old shape the day Twilio changes what Ireland requires.
 *
 * It also STOPS at "ready for filing". Nothing here submits anything to a
 * regulator, and the copy must never suggest otherwise.
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { authedFetch, API } from '@/lib/api'

type Step = 'intro' | 'details' | 'address' | 'review' | 'ready'

interface Field {
  name: string
  label: string
  help?: string
  required: boolean
  options: string[]
}

interface Requirements {
  iso_country: string
  explanation: string
  fields: Field[]
}

interface AddressRow {
  regulatory_address_id: string
  street: string
  street_secondary: string | null
  city: string
  region: string | null
  postal_code: string | null
  iso_country: string
  validated: boolean
}

interface VerificationState {
  iso_country: string
  details: Record<string, string | null>
  details_complete: boolean
  addresses: AddressRow[]
  authorizations: { regulatory_address_id: string; authorized: boolean; status: string }[]
  next_step: string
}

interface Fact { name: string; label: string; value: string }

interface ReviewSnapshot {
  scope: { regulatory_address_id: string; iso_country: string }
  facts: Fact[]
  requirements_context: { known: boolean; note: string }
  review_token: string
  consent_statement: string
}

/** The server's controlled error shape. Anything else is a bug, not a message. */
interface ApiError {
  status: string
  message: string
  action_required: boolean
  revisit_step?: string
  missing?: string[]
}

const GENERIC_ERROR: ApiError = {
  status: 'unexpected',
  message: 'Something went wrong. Please try again, or contact us if it keeps happening.',
  action_required: false,
}

/** The backend owns every customer-visible message; never invent one from a body. */
async function readError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json()
    const d = body?.detail
    if (d && typeof d === 'object' && typeof d.message === 'string') return d as ApiError
  } catch { /* fall through */ }
  return GENERIC_ERROR
}

const DETAIL_FIELDS = [
  'business_name',
  'business_registration_number',
  'business_website',
  'authorized_rep_first_name',
  'authorized_rep_last_name',
  'authorized_rep_email',
] as const

const ADDRESS_FIELDS: { name: string; label: string; hint?: string; required: boolean }[] = [
  { name: 'street',           label: 'Address line 1', required: true },
  { name: 'street_secondary', label: 'Address line 2', required: false },
  { name: 'city',             label: 'Town or city',   required: true },
  { name: 'region',           label: 'County',         required: false },
  { name: 'postal_code',      label: 'Eircode', hint: 'For example, V94 HT0X', required: true },
]

const STEPS: { key: Step; label: string }[] = [
  { key: 'details', label: 'Business details' },
  { key: 'address', label: 'Business address' },
  { key: 'review',  label: 'Review & authorise' },
]

export default function VerificationPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const base = `${API}/regulatory/${tenantId}/verification`

  const [step, setStep] = useState<Step>('intro')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const [requirements, setRequirements] = useState<Requirements | null>(null)
  const [state, setState] = useState<VerificationState | null>(null)
  const [details, setDetails] = useState<Record<string, string>>({})
  const [address, setAddress] = useState<Record<string, string>>({})
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null)
  const [consent, setConsent] = useState(false)
  const [authorizedAt, setAuthorizedAt] = useState<string>('')

  /** Canonical state always wins over whatever the browser was holding. */
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sRes, rRes] = await Promise.all([
        authedFetch(`${base}/state`),
        authedFetch(`${base}/requirements`),
      ])
      if (!sRes.ok) { setError(await readError(sRes)); return }
      const s: VerificationState = await sRes.json()
      setState(s)
      setDetails(Object.fromEntries(
        DETAIL_FIELDS.map(f => [f, (s.details?.[f] as string) ?? '']),
      ))
      const validated = s.addresses.find(a => a.validated) ?? s.addresses[0]
      if (validated) {
        setAddress({
          street: validated.street ?? '',
          street_secondary: validated.street_secondary ?? '',
          city: validated.city ?? '',
          region: validated.region ?? '',
          postal_code: validated.postal_code ?? '',
        })
      }
      // A requirements outage must not block the whole page: the customer can
      // still read and confirm facts we already hold.
      if (rRes.ok) setRequirements(await rRes.json())

      const done = s.authorizations.some(a => a.authorized)
      setStep(done ? 'ready'
        : s.next_step === 'details' ? 'intro'
        : (s.next_step as Step) ?? 'intro')
    } catch {
      setError(GENERIC_ERROR)
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => { void load() }, [load])

  /** Send the customer where the server said to go. */
  function applyError(e: ApiError) {
    setError(e)
    if (e.revisit_step && ['details', 'address', 'review'].includes(e.revisit_step)) {
      setStep(e.revisit_step as Step)
      if (e.revisit_step === 'review') setSnapshot(null)
    }
  }

  async function saveDetails() {
    if (busy) return                       // duplicate clicks are inert
    setBusy(true); setError(null)
    try {
      const res = await authedFetch(`${base}/details`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.fromEntries(
          DETAIL_FIELDS.map(f => [f, details[f] ?? '']))),
      })
      if (!res.ok) { applyError(await readError(res)); return }
      const body = await res.json()
      setStep(body.details_complete ? 'address' : 'details')
    } catch { setError(GENERIC_ERROR) } finally { setBusy(false) }
  }

  async function validateAddress() {
    if (busy) return
    setBusy(true); setError(null)
    try {
      const res = await authedFetch(`${base}/address`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
      })
      if (!res.ok) { applyError(await readError(res)); return }
      await load()
      setStep('review')
    } catch { setError(GENERIC_ERROR) } finally { setBusy(false) }
  }

  const openReview = useCallback(async (addressId: string) => {
    setBusy(true); setError(null); setConsent(false)
    try {
      const res = await authedFetch(
        `${base}/review?regulatory_address_id=${encodeURIComponent(addressId)}`)
      if (!res.ok) { applyError(await readError(res)); return }
      setSnapshot(await res.json())
      setStep('review')
    } catch { setError(GENERIC_ERROR) } finally { setBusy(false) }
  }, [base])

  // Entering the review step fetches a fresh snapshot, so the facts on screen are
  // the facts on the server at the moment they are read.
  useEffect(() => {
    if (step !== 'review' || snapshot || busy) return
    const validated = state?.addresses.find(a => a.validated)
    if (validated) void openReview(validated.regulatory_address_id)
  }, [step, snapshot, busy, state, openReview])

  async function authorize() {
    if (busy || !snapshot || !consent) return
    setBusy(true); setError(null)
    try {
      const res = await authedFetch(`${base}/authorize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          consent: true,
          regulatory_address_id: snapshot.scope.regulatory_address_id,
          review_token: snapshot.review_token,
        }),
      })
      if (!res.ok) {
        // A stale or expired review is a controlled re-review, not a dead end:
        // clearing the snapshot makes the effect above fetch the updated facts.
        applyError(await readError(res))
        return
      }
      const body = await res.json()
      setAuthorizedAt(body.authorized_at ?? '')
      await load()
      setStep('ready')
    } catch { setError(GENERIC_ERROR) } finally { setBusy(false) }
  }

  if (loading) {
    return <div className="db-content"><div className="db-loading">Loading…</div></div>
  }

  const detailFieldLabel = (name: string) =>
    requirements?.fields.find(f => f.name === fieldToProvider(name))?.label ?? FALLBACK_LABELS[name]
  const detailFieldHelp = (name: string) =>
    requirements?.fields.find(f => f.name === fieldToProvider(name))?.help

  return (
    <>
    <div className="db-topbar"><span className="db-topbar-title">Verification</span></div>
    <div className="db-content" style={{ maxWidth: 760 }}>
      <header style={{ marginBottom: 24 }}>
        <div className="db-page-heading">Business verification</div>
        <p style={{ fontSize: 13, color: 'var(--db-text-2)', margin: '6px 0 0' }}>
          Required before an Irish phone number can be issued.
        </p>
      </header>

      {step !== 'intro' && (
        <ol style={{
          display: 'flex', gap: 8, listStyle: 'none', padding: 0,
          margin: '0 0 20px', fontSize: 12,
        }}>
          {STEPS.map((s, i) => {
            const done = STEPS.findIndex(x => x.key === step) > i || step === 'ready'
            const now = s.key === step
            return (
              <li key={s.key} style={{
                flex: 1, padding: '8px 10px', borderRadius: 8,
                background: now ? 'var(--db-accent-bg)' : 'var(--db-card)',
                border: `1px solid ${now ? 'var(--db-accent-border)' : 'var(--db-border)'}`,
                color: now ? 'var(--db-accent-text)' : done ? 'var(--db-text-2)' : 'var(--db-text-2)',
                fontWeight: now ? 600 : 500,
              }}>
                {done && !now ? '✓ ' : `${i + 1}. `}{s.label}
              </li>
            )
          })}
        </ol>
      )}

      {error && (
        <div role="alert" style={{
          padding: '12px 14px', borderRadius: 9, marginBottom: 18, fontSize: 13,
          background: error.action_required ? 'var(--db-danger-bg)' : 'var(--db-card)',
          border: `1px solid ${error.action_required ? 'var(--db-danger-text)' : 'var(--db-border)'}`,
          color: 'var(--db-text)',
        }}>
          {error.message}
          {error.missing?.length ? (
            <div style={{ marginTop: 6, color: 'var(--db-text-2)', fontSize: 12 }}>
              Still needed: {error.missing.map(m => FALLBACK_LABELS[m] ?? m).join(', ')}
            </div>
          ) : null}
        </div>
      )}

      {step === 'intro' && (
        <section className="db-card" style={{ padding: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 10px', color: 'var(--db-text)' }}>
            Why this is needed
          </h2>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--db-text-2)', margin: '0 0 16px' }}>
            {requirements?.explanation ??
              'Phone numbers in this country are regulated. Before a number can be issued, the telecoms regulator requires the registered details of the business it belongs to, a named representative, and a verified business address in that country.'}
          </p>
          <p style={{ fontSize: 13, color: 'var(--db-text-2)', margin: '0 0 20px' }}>
            It takes a few minutes. You can stop and come back — everything you enter is saved.
          </p>
          <button className="db-btn db-btn--primary" onClick={() => setStep('details')}>
            Start verification
          </button>
        </section>
      )}

      {step === 'details' && (
        <section className="db-card" style={{ padding: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--db-text)' }}>
            Your business
          </h2>
          <p style={{ fontSize: 13, color: 'var(--db-text-2)', margin: '0 0 18px' }}>
            Enter these exactly as they appear on your official registration.
          </p>
          {DETAIL_FIELDS.map(name => (
            <label key={name} style={{ display: 'block', marginBottom: 14 }}>
              <span style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 5 }}>
                {detailFieldLabel(name)}
              </span>
              <input
                className="db-input"
                value={details[name] ?? ''}
                onChange={e => setDetails({ ...details, [name]: e.target.value })}
                style={{ width: '100%' }}
              />
              {detailFieldHelp(name) && (
                <span style={{ display: 'block', fontSize: 12, color: 'var(--db-text-2)', marginTop: 4 }}>
                  {detailFieldHelp(name)}
                </span>
              )}
            </label>
          ))}
          <button className="db-btn db-btn--primary" onClick={saveDetails} disabled={busy}>
            {busy ? 'Saving…' : 'Save and continue'}
          </button>
        </section>
      )}

      {step === 'address' && (
        <section className="db-card" style={{ padding: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--db-text)' }}>
            Your Irish business address
          </h2>
          <p style={{ fontSize: 13, color: 'var(--db-text-2)', margin: '0 0 18px' }}>
            This must be the premises the number is registered to.
          </p>
          {ADDRESS_FIELDS.map(f => (
            <label key={f.name} style={{ display: 'block', marginBottom: 14 }}>
              <span style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 5 }}>
                {f.label}{!f.required && <span style={{ color: 'var(--db-text-2)', fontWeight: 500 }}> (optional)</span>}
              </span>
              <input
                className="db-input"
                value={address[f.name] ?? ''}
                onChange={e => setAddress({ ...address, [f.name]: e.target.value })}
                style={{ width: '100%' }}
              />
              {f.hint && (
                <span style={{ display: 'block', fontSize: 12, color: 'var(--db-text-2)', marginTop: 4 }}>
                  {f.hint}
                </span>
              )}
            </label>
          ))}
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="db-btn db-btn--ghost" onClick={() => setStep('details')} disabled={busy}>
              Back
            </button>
            <button className="db-btn db-btn--primary" onClick={validateAddress} disabled={busy}>
              {busy ? 'Checking…' : 'Check this address'}
            </button>
          </div>
        </section>
      )}

      {step === 'review' && (
        <section className="db-card" style={{ padding: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--db-text)' }}>
            Review the information that will be submitted
          </h2>
          <p style={{ fontSize: 13, color: 'var(--db-text-2)', margin: '0 0 18px' }}>
            {snapshot?.requirements_context.note ??
              'These are the details your regulator currently requires.'}
          </p>

          {!snapshot ? (
            <div style={{ color: 'var(--db-text-2)', fontSize: 13 }}>Loading your details…</div>
          ) : (
            <>
              <dl style={{
                margin: '0 0 20px', display: 'grid',
                gridTemplateColumns: 'minmax(140px, 38%) 1fr',
                borderTop: '1px solid var(--db-border-lt)',
              }}>
                {snapshot.facts.map(f => (
                  <div key={f.name} style={{ display: 'contents' }}>
                    <dt style={{
                      padding: '10px 12px 10px 0', fontSize: 13, color: 'var(--db-text-2)',
                      borderBottom: '1px solid var(--db-border-lt)',
                    }}>{f.label}</dt>
                    <dd style={{
                      padding: '10px 0', margin: 0, fontSize: 13, fontWeight: 600,
                      color: f.value ? 'var(--db-text)' : 'var(--db-text-2)',
                      borderBottom: '1px solid var(--db-border-lt)', wordBreak: 'break-word',
                    }}>{f.value || '—'}</dd>
                  </div>
                ))}
              </dl>

              <label style={{
                display: 'flex', gap: 10, alignItems: 'flex-start', padding: '14px',
                border: '1px solid var(--db-border)', borderRadius: 9,
                background: 'var(--db-bg)', marginBottom: 18, cursor: 'pointer',
              }}>
                {/* Never pre-checked: consent is an affirmative act. */}
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={e => setConsent(e.target.checked)}
                  style={{ marginTop: 2, flexShrink: 0 }}
                />
                <span style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--db-text)' }}>
                  {snapshot.consent_statement}
                </span>
              </label>

              <div style={{ display: 'flex', gap: 10 }}>
                <button className="db-btn db-btn--ghost"
                        onClick={() => { setSnapshot(null); setStep('details') }}
                        disabled={busy}>
                  Change something
                </button>
                <button className="db-btn db-btn--primary" onClick={authorize} disabled={busy || !consent}>
                  {busy ? 'Submitting…' : 'Confirm and authorise'}
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {step === 'ready' && (
        <section className="db-card" style={{ padding: 24 }}>
          <div style={{ fontSize: 30, marginBottom: 8 }}>✓</div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 8px', color: 'var(--db-text)' }}>
            Your information is ready for regulatory submission
          </h2>
          {/* Deliberately does NOT say "submitted" or "approved". Neither has
              happened: W9I-D files, and the regulator decides. */}
          <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--db-text-2)', margin: '0 0 14px' }}>
            Thanks — we have everything we need. We will complete the registration
            with our telecoms provider and let you know as soon as your Irish
            number is ready. Nothing further is needed from you right now.
          </p>
          {authorizedAt && (
            <p style={{ fontSize: 12, color: 'var(--db-text-2)', margin: '0 0 16px' }}>
              Authorised on {new Date(authorizedAt).toLocaleString()}
            </p>
          )}
          <button className="db-btn db-btn--ghost"
                  onClick={() => { setSnapshot(null); setStep('details') }}>
            Update my details
          </button>
        </section>
      )}
    </div>
    </>
  )
}

/** Our column names vs the provider's field names, for looking up a label. */
function fieldToProvider(name: string): string {
  return ({
    authorized_rep_first_name: 'first_name',
    authorized_rep_last_name: 'last_name',
    authorized_rep_email: 'email',
  } as Record<string, string>)[name] ?? name
}

const FALLBACK_LABELS: Record<string, string> = {
  business_name: 'Registered business name',
  business_registration_number: 'Company registration (CRO) number',
  business_website: 'Business website',
  authorized_rep_first_name: 'Representative first name',
  authorized_rep_last_name: 'Representative last name',
  authorized_rep_email: 'Representative email',
}