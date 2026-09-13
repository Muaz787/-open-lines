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
 *
 * ONE IMPLEMENTATION, TWO SURFACES. The onboarding wizard and the dashboard
 * route both render this. There is no second form, no second validation, and no
 * second set of API calls -- a fork would be two regulatory contracts drifting
 * apart, which is the last place that should happen.
 *
 * RESUME IS FREE, AND DELIBERATELY SO. The step is derived on mount from the
 * server's `next_step` and the authorisation rows, never from React state. So a
 * refresh, a new tab, a sign-out and back in, or arriving from the dashboard
 * instead of onboarding all land on the same step, because the server is the
 * one that knows.
 */

import { Fragment, useCallback, useEffect, useState } from 'react'
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

/** Input type and browser autofill hints. Purely presentational: the server
 *  validates every one of these, and none of them gates what may be sent. */
const DETAIL_INPUT: Record<string, { type: string; autoComplete?: string; placeholder?: string }> = {
  business_name:                { type: 'text',  autoComplete: 'organization' },
  business_registration_number: { type: 'text' },
  business_website:             { type: 'url',   autoComplete: 'url', placeholder: 'https://' },
  authorized_rep_first_name:    { type: 'text',  autoComplete: 'given-name' },
  authorized_rep_last_name:     { type: 'text',  autoComplete: 'family-name' },
  authorized_rep_email:         { type: 'email', autoComplete: 'email' },
}

const ADDRESS_FIELDS: { name: string; label: string; hint?: string; required: boolean; autoComplete?: string }[] = [
  { name: 'street',           label: 'Address line 1', required: true,  autoComplete: 'address-line1' },
  { name: 'street_secondary', label: 'Address line 2', required: false, autoComplete: 'address-line2' },
  { name: 'city',             label: 'Town or city',   required: true,  autoComplete: 'address-level2' },
  { name: 'region',           label: 'County',         required: false, autoComplete: 'address-level1' },
  { name: 'postal_code',      label: 'Eircode', hint: 'For example, V94 HT0X', required: true, autoComplete: 'postal-code' },
]

const STEPS: { key: Step; label: string }[] = [
  { key: 'details', label: 'Business details' },
  { key: 'address', label: 'Business address' },
  { key: 'review',  label: 'Review & authorise' },
]

export default function BusinessVerification({
  tenantId, onReady, embedded = false,
}: {
  tenantId: string
  /** Called once the filing is authorised and ready for submission. Lets the
   *  onboarding wizard advance; the dashboard route simply omits it. */
  onReady?: () => void
  embedded?: boolean
}) {
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

  /** Chrome belongs to the surface, not to the form.
   *  The wizard already prints its own "Verify your business" heading, so the
   *  embedded render is the form alone — it used to add a sticky dashboard
   *  topbar and a second page heading on top of the wizard's, which is what
   *  put "Verification" across the first field. The dashboard route, which has
   *  no heading of its own, still gets both. */
  function shell(children: React.ReactNode) {
    if (embedded) return <div className="bv">{children}</div>
    return (
      <>
        <div className="db-topbar"><span className="db-topbar-title">Verification</span></div>
        <div className="db-content">
          <div className="bv" style={{ maxWidth: 720 }}>
            <header>
              <h1 className="bv-h" style={{ fontSize: 20 }}>Business verification</h1>
              <p className="bv-lede" style={{ marginTop: 6 }}>
                Required before an Irish phone number can be issued.
              </p>
            </header>
            {children}
          </div>
        </div>
      </>
    )
  }

  if (loading) {
    return shell(
      <div className="bv-loading"><span className="bv-spinner" aria-hidden />Loading your details…</div>,
    )
  }

  const detailField = (name: string) =>
    requirements?.fields.find(f => f.name === fieldToProvider(name))
  const detailFieldLabel = (name: string) => detailField(name)?.label ?? FALLBACK_LABELS[name]
  const detailFieldHelp = (name: string) => detailField(name)?.help
  /** Only the provider knows what Ireland insists on, so a field is marked
   *  optional only where the live Regulation says so — never by our guess. */
  const detailFieldOptional = (name: string) => detailField(name)?.required === false

  const stepIndex = STEPS.findIndex(x => x.key === step)

  return shell(
    <>
      {step !== 'intro' && (
        <ol className="bv-steps" aria-label="Verification progress">
          {STEPS.map((s, i) => {
            const done = step === 'ready' || stepIndex > i
            const now = s.key === step
            return (
              <Fragment key={s.key}>
                {i > 0 && <li className="bv-step-rule" aria-hidden />}
                <li className={`bv-step${now ? ' is-now' : done ? ' is-done' : ''}`}
                    aria-current={now ? 'step' : undefined}>
                  <span className="bv-step-n" aria-hidden>{done ? '✓' : i + 1}</span>
                  <span className="bv-step-l">{s.label}</span>
                </li>
              </Fragment>
            )
          })}
        </ol>
      )}

      {error && (
        <div role="alert" className={`bv-alert${error.action_required ? ' is-blocking' : ''}`}>
          {error.message}
          {error.missing?.length ? (
            <p className="bv-alert-more">
              Still needed: {error.missing.map(m => FALLBACK_LABELS[m] ?? m).join(', ')}
            </p>
          ) : null}
        </div>
      )}

      {step === 'intro' && (
        <section className="bv-panel">
          <h2 className="bv-h">Why this is needed</h2>
          <p className="bv-prose">
            {requirements?.explanation ??
              'Phone numbers in this country are regulated. Before a number can be issued, the telecoms regulator requires the registered details of the business it belongs to, a named representative, and a verified business address in that country.'}
          </p>
          <p className="bv-note">
            It takes a few minutes. You can stop and come back — everything you enter is saved.
          </p>
          <div className="bv-actions">
            <button type="button" className="bv-btn bv-btn--primary" onClick={() => setStep('details')}>
              Start verification →
            </button>
          </div>
        </section>
      )}

      {step === 'details' && (
        <section className="bv-panel">
          <h2 className="bv-h">Your business</h2>
          <p className="bv-lede">Enter these exactly as they appear on your official registration.</p>
          <div className="bv-fields">
            {DETAIL_FIELDS.map(name => {
              const help = detailFieldHelp(name)
              return (
                <div className="bv-field" key={name}>
                  <label className="bv-label" htmlFor={`bv-${name}`}>
                    {detailFieldLabel(name)}
                    {detailFieldOptional(name) && <span className="bv-opt">Optional</span>}
                  </label>
                  <input
                    id={`bv-${name}`}
                    className="bv-input"
                    type={DETAIL_INPUT[name]?.type ?? 'text'}
                    autoComplete={DETAIL_INPUT[name]?.autoComplete}
                    placeholder={DETAIL_INPUT[name]?.placeholder}
                    aria-describedby={help ? `bv-${name}-help` : undefined}
                    value={details[name] ?? ''}
                    onChange={e => setDetails({ ...details, [name]: e.target.value })}
                  />
                  {help && <p className="bv-help" id={`bv-${name}-help`}>{help}</p>}
                </div>
              )
            })}
          </div>
          <div className="bv-actions">
            <button type="button" className="bv-btn bv-btn--primary bv-btn--grow"
                    onClick={saveDetails} disabled={busy}>
              {busy ? 'Saving…' : 'Save and continue →'}
            </button>
          </div>
        </section>
      )}

      {step === 'address' && (
        <section className="bv-panel">
          <h2 className="bv-h">Your Irish business address</h2>
          <p className="bv-lede">This must be the premises the number is registered to.</p>
          <div className="bv-fields">
            {ADDRESS_FIELDS.map(f => (
              <div className="bv-field" key={f.name}>
                <label className="bv-label" htmlFor={`bv-addr-${f.name}`}>
                  {f.label}
                  {!f.required && <span className="bv-opt">Optional</span>}
                </label>
                <input
                  id={`bv-addr-${f.name}`}
                  className="bv-input"
                  autoComplete={f.autoComplete}
                  aria-describedby={f.hint ? `bv-addr-${f.name}-help` : undefined}
                  value={address[f.name] ?? ''}
                  onChange={e => setAddress({ ...address, [f.name]: e.target.value })}
                />
                {f.hint && <p className="bv-help" id={`bv-addr-${f.name}-help`}>{f.hint}</p>}
              </div>
            ))}
          </div>
          <div className="bv-actions">
            <button type="button" className="bv-btn bv-btn--primary bv-btn--grow"
                    onClick={validateAddress} disabled={busy}>
              {busy ? 'Checking…' : 'Check this address →'}
            </button>
            <button type="button" className="bv-btn bv-btn--ghost"
                    onClick={() => setStep('details')} disabled={busy}>
              Back
            </button>
          </div>
        </section>
      )}

      {step === 'review' && (
        <section className="bv-panel">
          <h2 className="bv-h">Review the information that will be submitted</h2>
          <p className="bv-lede">
            {snapshot?.requirements_context.note ??
              'These are the details your regulator currently requires.'}
          </p>

          {!snapshot ? (
            <div className="bv-loading"><span className="bv-spinner" aria-hidden />Loading your details…</div>
          ) : (
            <>
              <dl className="bv-facts">
                {snapshot.facts.map(f => (
                  <div className="bv-fact" key={f.name}>
                    <dt>{f.label}</dt>
                    <dd className={f.value ? undefined : 'is-empty'}>{f.value || 'Not provided'}</dd>
                  </div>
                ))}
              </dl>

              {/* Never pre-checked: consent is an affirmative act. */}
              <label className="bv-consent">
                <input type="checkbox" checked={consent}
                       onChange={e => setConsent(e.target.checked)} />
                <span>{snapshot.consent_statement}</span>
              </label>

              <div className="bv-actions">
                <button type="button" className="bv-btn bv-btn--primary bv-btn--grow"
                        onClick={authorize} disabled={busy || !consent}>
                  {busy ? 'Submitting…' : 'Confirm and authorise →'}
                </button>
                <button type="button" className="bv-btn bv-btn--ghost"
                        onClick={() => { setSnapshot(null); setStep('details') }}
                        disabled={busy}>
                  Change something
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {step === 'ready' && (
        <section className="bv-panel">
          <div className="bv-tick" aria-hidden>✓</div>
          <h2 className="bv-h">Your information is ready for regulatory submission</h2>
          {/* Deliberately does NOT say "submitted" or "approved". Neither has
              happened: W9I-D files, and the regulator decides. */}
          <p className="bv-prose">
            Thanks — we have everything we need. We will complete the registration
            with our telecoms provider and let you know as soon as your Irish
            number is ready. Nothing further is needed from you right now.
          </p>
          {authorizedAt && (
            <p className="bv-note">Authorised on {new Date(authorizedAt).toLocaleString()}</p>
          )}
          <div className="bv-actions">
            {embedded && onReady && (
              <button type="button" className="bv-btn bv-btn--primary bv-btn--grow" onClick={onReady}>
                Continue setup →
              </button>
            )}
            <button type="button" className="bv-btn bv-btn--ghost"
                    onClick={() => { setSnapshot(null); setStep('details') }}>
              Update my details
            </button>
          </div>
        </section>
      )}
    </>,
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