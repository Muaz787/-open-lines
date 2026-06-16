'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

function SuccessContent() {
  const params = useSearchParams()
  const sessionId = params.get('session_id')

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#0d1117',
      padding: '24px 16px',
    }}>
      <div style={{
        maxWidth: 420,
        width: '100%',
        background: '#161b22',
        border: '1px solid #30363d',
        borderRadius: 16,
        padding: '40px 32px',
        textAlign: 'center',
      }}>
        {/* Check circle */}
        <div style={{
          width: 64,
          height: 64,
          borderRadius: '50%',
          background: 'rgba(52,199,89,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 20px',
        }}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#34c759" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>

        <h1 style={{
          fontSize: 22,
          fontWeight: 700,
          color: '#e6edf3',
          margin: '0 0 10px',
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        }}>
          Payment successful!
        </h1>

        <p style={{
          fontSize: 15,
          color: '#8b949e',
          margin: '0 0 28px',
          lineHeight: 1.6,
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        }}>
          Your deposit has been received and your appointment is now confirmed.
          You&apos;ll receive a text message confirming your booking details shortly.
        </p>

        <div style={{
          background: '#0d1117',
          border: '1px solid #30363d',
          borderRadius: 10,
          padding: '14px 18px',
          marginBottom: 28,
        }}>
          <p style={{
            fontSize: 13,
            color: '#8b949e',
            margin: 0,
            lineHeight: 1.6,
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          }}>
            If you have any questions, please contact the business directly.
            A receipt has been sent to your email address.
          </p>
        </div>

        <p style={{
          fontSize: 12,
          color: '#484f58',
          margin: 0,
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
        }}>
          <svg width="11" height="13" viewBox="0 0 11 13" fill="none" aria-hidden="true">
            <path d="M5.5 0C3.567 0 2 1.343 2 3v1H1a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1H9V3C9 1.343 7.433 0 5.5 0Zm0 1.5C6.88 1.5 7.5 2.2 7.5 3v1h-4V3c0-.8.62-1.5 2-1.5ZM5.5 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" fill="currentColor"/>
          </svg>
          Secured by Stripe · Powered by Open Lines
        </p>
      </div>
    </div>
  )
}

export default function PaymentSuccessPage() {
  return (
    <Suspense>
      <SuccessContent />
    </Suspense>
  )
}
