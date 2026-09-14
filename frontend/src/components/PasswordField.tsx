'use client'

/**
 * A password input you can read back.
 *
 * Typing a password blind into a field that gives no feedback is how people end
 * up locked out of an account they know the password for — and on a phone
 * keyboard it is most of the reason a correct password gets typed wrong twice.
 *
 * ONE IMPLEMENTATION. Onboarding grew a toggle; login, reset-password and
 * settings each kept a bare input. Six inputs, one of which behaved
 * differently, is how a customer learns the eye exists and then can't find it
 * where they need it most. The markup and the icons live here now.
 *
 * IT ONLY CHANGES THE INPUT'S TYPE. The value is never copied, never mirrored
 * into state of its own, and never logged. Revealed state is per-field and
 * resets on every mount, so a password is never left visible for the next
 * person at the machine.
 */

import { useId, useState } from 'react'

export default function PasswordField({
  value, onChange, className = 'form-input', autoComplete = 'current-password',
  placeholder, required, minLength, id, name, autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  /** `form-input` on the marketing/auth pages, `db-input` inside the dashboard. */
  className?: string
  autoComplete?: string
  placeholder?: string
  required?: boolean
  minLength?: number
  id?: string
  name?: string
  autoFocus?: boolean
}) {
  const [shown, setShown] = useState(false)
  const auto = useId()

  return (
    <div className="pw-wrap">
      <input
        id={id ?? auto}
        name={name}
        className={className}
        type={shown ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        minLength={minLength}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
      />
      {/* type="button" so it never submits the form it sits in. */}
      <button type="button" className="pw-toggle"
        onClick={() => setShown(v => !v)}
        aria-label={shown ? 'Hide password' : 'Show password'}
        aria-pressed={shown}>
        {shown ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"
            stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M3 3l18 18" />
            <path d="M10.6 10.6a2 2 0 002.8 2.8" />
            <path d="M9.4 5.2A9.7 9.7 0 0112 5c5 0 9 4.5 9 7a11 11 0 01-2.6 3.5" />
            <path d="M6.2 6.7C3.9 8.2 3 10.4 3 12c0 2.5 4 7 9 7a9.6 9.6 0 003.7-.7" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"
            stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M3 12s3.6-7 9-7 9 7 9 7-3.6 7-9 7-9-7-9-7z" />
            <circle cx="12" cy="12" r="2.6" />
          </svg>
        )}
      </button>
    </div>
  )
}
