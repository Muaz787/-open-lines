'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import MicButton from '@/app/components/MicButton'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface CalendarStatus {
  connected: boolean
  appointment_duration_minutes: number
  calendar_timezone: string
}

interface Appointment {
  id: string
  caller_name?: string
  caller_phone?: string
  service?: string
  appointment_datetime: string
  duration_minutes?: number
  status?: string
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

function isUpcoming(iso: string): boolean {
  return new Date(iso) > new Date()
}

function CalendarPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [tenant, setTenant]               = useState<Tenant | null>(null)
  const [appointments, setAppointments]   = useState<Appointment[]>([])
  const [loading, setLoading]             = useState(true)
  const [calStatus, setCalStatus]         = useState<CalendarStatus | null>(null)
  const [calDisconnecting, setCalDisconnecting] = useState(false)
  const [toast, setToast]                 = useState<string | null>(null)
  const [showPast, setShowPast]           = useState(false)

  // Availability settings
  const [bhStart, setBhStart]   = useState<number>(9)
  const [bhEnd, setBhEnd]       = useState<number>(17)
  const [bizDays, setBizDays]   = useState<number[]>([0, 1, 2, 3, 4])
  const [breakOn, setBreakOn]   = useState<boolean>(false)
  const [breakStart, setBreakStart] = useState<number>(12)
  const [breakEnd, setBreakEnd]     = useState<number>(13)
  const [bookingInstructions, setBookingInstructions] = useState<string>('')
  const [bhSaving, setBhSaving] = useState(false)

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, aRes, cRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/calendar/appointments/${tenantId}`),
          fetch(`${API}/calendar/status/${tenantId}`),
        ])
        if (tRes.ok) {
          const t = await tRes.json()
          setTenant(t)
          if (t.business_hours_start != null) setBhStart(t.business_hours_start)
          if (t.business_hours_end   != null) setBhEnd(t.business_hours_end)
          if (Array.isArray(t.business_days)) setBizDays(t.business_days)
          if (t.break_start != null && t.break_end != null) {
            setBreakOn(true); setBreakStart(t.break_start); setBreakEnd(t.break_end)
          }
          if (t.booking_instructions) setBookingInstructions(t.booking_instructions)
        }
        if (aRes.ok) {
          const data = await aRes.json()
          setAppointments(Array.isArray(data) ? data : [])
        }
        if (cRes.ok) setCalStatus(await cRes.json())
      } finally {
        setLoading(false)
      }
    }
    init()

    // pick up ?calendar=connected redirect from OAuth flow
    const params = new URLSearchParams(window.location.search)
    const calParam = params.get('calendar')
    if (calParam === 'connected') {
      showToast('Google Calendar connected!')
      fetch(`${API}/calendar/status/${tenantId}`).then(r => r.ok && r.json()).then(d => d && setCalStatus(d))
      window.history.replaceState({}, '', window.location.pathname)
    } else if (calParam === 'error') {
      showToast('Calendar connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [tenantId])

  const disconnectCalendar = async () => {
    if (!confirm('Disconnect Google Calendar? The AI will no longer be able to book appointments in real time.')) return
    setCalDisconnecting(true)
    try {
      await fetch(`${API}/calendar/disconnect/${tenantId}`, { method: 'POST' })
      const r = await fetch(`${API}/calendar/status/${tenantId}`)
      if (r.ok) setCalStatus(await r.json())
    } finally {
      setCalDisconnecting(false)
    }
  }

  const saveBusinessHours = async () => {
    if (bhStart >= bhEnd) { showToast('Opening time must be before closing time'); return }
    if (bizDays.length === 0) { showToast('Select at least one operating day'); return }
    if (breakOn && breakStart >= breakEnd) { showToast('Break start must be before break end'); return }
    setBhSaving(true)
    try {
      const res = await fetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          business_hours_start: bhStart,
          business_hours_end:   bhEnd,
          business_days:        [...bizDays].sort((a, b) => a - b),
          break_start:          breakOn ? breakStart : null,
          break_end:            breakOn ? breakEnd : null,
          booking_instructions: bookingInstructions.trim(),
        }),
      })
      if (res.ok) showToast('Availability settings saved')
      else showToast('Failed to save — try again')
    } catch {
      showToast('Failed to save — try again')
    } finally {
      setBhSaving(false)
    }
  }

  const toggleDay = (d: number) => {
    setBizDays(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d])
  }

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const upcoming = appointments.filter(a => a.status !== 'cancelled' && isUpcoming(a.appointment_datetime))
  const past     = appointments.filter(a => a.status === 'cancelled' || !isUpcoming(a.appointment_datetime))

  const displayed = showPast ? past : upcoming

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    )
  }

  return (
    <>

        {/* Toast */}
        <AnimatePresence>
          {toast && (
            <motion.div
              initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              style={{
                position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
                background: '#16161a', color: '#fff', padding: '10px 20px',
                borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 300,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              }}
            >
              {toast}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Calendar</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: '#888' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dba72', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">

          {/* Google Calendar connection banner */}
          {calStatus && !calStatus.connected && (
            <div style={{
              background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
              padding: '18px 20px', marginBottom: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 12,
            }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#16161a', marginBottom: 3 }}>
                  Connect Google Calendar
                </div>
                <div style={{ fontSize: 12, color: '#888', lineHeight: 1.5 }}>
                  Allow the AI to check availability and book appointments in real time.
                </div>
              </div>
              <a
                href={`${API}/calendar/connect/${tenantId}`}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  background: '#16161a', color: '#fff',
                  borderRadius: 8, padding: '9px 18px',
                  fontSize: 12, fontWeight: 500, textDecoration: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                Connect Google Calendar
              </a>
            </div>
          )}

          {calStatus?.connected && (
            <div style={{
              background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10,
              padding: '12px 16px', marginBottom: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 10,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14 }}>✓</span>
                <span style={{ fontSize: 12, fontWeight: 500, color: '#16a34a' }}>Google Calendar connected</span>
              </div>
              <button
                onClick={disconnectCalendar}
                disabled={calDisconnecting}
                style={{
                  fontSize: 11, color: '#888', background: 'none', border: '1px solid #e8e6e0',
                  borderRadius: 6, padding: '5px 12px', cursor: 'pointer',
                  fontFamily: 'var(--font-dm), sans-serif',
                }}
              >
                {calDisconnecting ? 'Disconnecting…' : 'Disconnect'}
              </button>
            </div>
          )}

          {/* Availability settings */}
          <div style={{
            background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
            padding: '18px 20px', marginBottom: 16,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#16161a', marginBottom: 4 }}>
              Availability
            </div>
            <div style={{ fontSize: 11, color: '#aaa', marginBottom: 16 }}>
              The AI will only offer and book appointments within these days, hours, and rules.
            </div>

            {/* Operating days */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#555', marginBottom: 8 }}>Operating days</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => {
                  const on = bizDays.includes(i)
                  return (
                    <button
                      key={i}
                      onClick={() => toggleDay(i)}
                      style={{
                        fontSize: 12, fontWeight: 500, padding: '6px 12px', borderRadius: 7,
                        border: '1px solid', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif',
                        borderColor: on ? '#3dba72' : '#e8e6e0',
                        background: on ? '#eafaf2' : '#fff',
                        color: on ? '#1a7a45' : '#888',
                      }}
                    >
                      {d}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Hours */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#555', marginBottom: 8 }}>Hours</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 12, color: '#888' }}>Opens at</label>
                  <select value={bhStart} onChange={e => setBhStart(Number(e.target.value))}
                    style={{ fontSize: 12, background: '#f4f3f0', border: '1px solid #e8e6e0', borderRadius: 6, padding: '5px 8px', color: '#16161a', fontFamily: 'var(--font-dm), sans-serif', cursor: 'pointer' }}>
                    {Array.from({ length: 24 }, (_, h) => (
                      <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                    ))}
                  </select>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 12, color: '#888' }}>Closes at</label>
                  <select value={bhEnd} onChange={e => setBhEnd(Number(e.target.value))}
                    style={{ fontSize: 12, background: '#f4f3f0', border: '1px solid #e8e6e0', borderRadius: 6, padding: '5px 8px', color: '#16161a', fontFamily: 'var(--font-dm), sans-serif', cursor: 'pointer' }}>
                    {Array.from({ length: 24 }, (_, h) => (
                      <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Daily break */}
            <div style={{ marginBottom: 18 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: breakOn ? 10 : 0 }}>
                <input type="checkbox" checked={breakOn} onChange={e => setBreakOn(e.target.checked)} style={{ cursor: 'pointer' }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: '#555' }}>Daily break (e.g. lunch)</span>
              </label>
              {breakOn && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', paddingLeft: 24 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 12, color: '#888' }}>From</label>
                    <select value={breakStart} onChange={e => setBreakStart(Number(e.target.value))}
                      style={{ fontSize: 12, background: '#f4f3f0', border: '1px solid #e8e6e0', borderRadius: 6, padding: '5px 8px', color: '#16161a', fontFamily: 'var(--font-dm), sans-serif', cursor: 'pointer' }}>
                      {Array.from({ length: 24 }, (_, h) => (
                        <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                      ))}
                    </select>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 12, color: '#888' }}>To</label>
                    <select value={breakEnd} onChange={e => setBreakEnd(Number(e.target.value))}
                      style={{ fontSize: 12, background: '#f4f3f0', border: '1px solid #e8e6e0', borderRadius: 6, padding: '5px 8px', color: '#16161a', fontFamily: 'var(--font-dm), sans-serif', cursor: 'pointer' }}>
                      {Array.from({ length: 24 }, (_, h) => (
                        <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                      ))}
                    </select>
                  </div>
                  <span style={{ fontSize: 11, color: '#aaa' }}>No appointments during this window</span>
                </div>
              )}
            </div>

            {/* Booking instructions */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 4 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#555' }}>
                  Special instructions for the booking agent
                </div>
                <MicButton onResult={t => setBookingInstructions(prev => (prev.trim() ? prev.trim() + ' ' : '') + t)} />
              </div>
              <div style={{ fontSize: 11, color: '#aaa', marginBottom: 8 }}>
                Plain English rules the AI should follow — type, or tap the mic to dictate.
                e.g. &quot;Always ask if they&apos;re a new or returning client&quot; or &quot;Mention parking is free out back.&quot;
              </div>
              <textarea
                value={bookingInstructions}
                onChange={e => setBookingInstructions(e.target.value)}
                placeholder="Add any booking rules or notes for the AI…"
                rows={3}
                style={{
                  width: '100%', boxSizing: 'border-box', fontSize: 13, padding: '10px 12px',
                  border: '1px solid #e8e6e0', borderRadius: 8, background: '#fafafa',
                  color: '#16161a', resize: 'vertical', fontFamily: 'var(--font-dm), sans-serif',
                  lineHeight: 1.5, outline: 'none',
                }}
              />
            </div>

            <button
              onClick={saveBusinessHours}
              disabled={bhSaving}
              style={{
                fontSize: 12, fontWeight: 600, padding: '8px 20px',
                background: '#16161a', color: '#fff', border: 'none',
                borderRadius: 7, cursor: bhSaving ? 'default' : 'pointer',
                opacity: bhSaving ? 0.6 : 1, fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              {bhSaving ? 'Saving…' : 'Save availability'}
            </button>
          </div>

          {/* Toggle upcoming / past */}
          <div className="cal-toggle-bar">
            <button
              onClick={() => setShowPast(false)}
              style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                border: '1px solid',
                borderColor: !showPast ? '#3dba72' : '#e8e6e0',
                background: !showPast ? '#eafaf2' : '#fff',
                color: !showPast ? '#1a7a45' : '#666',
                cursor: 'pointer',
                fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Upcoming ({upcoming.length})
            </button>
            <button
              onClick={() => setShowPast(true)}
              style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                border: '1px solid',
                borderColor: showPast ? '#3dba72' : '#e8e6e0',
                background: showPast ? '#eafaf2' : '#fff',
                color: showPast ? '#1a7a45' : '#666',
                cursor: 'pointer',
                fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Past &amp; Cancelled ({past.length})
            </button>
          </div>

          {/* Appointment list */}
          {displayed.length === 0 ? (
            <div style={{
              background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
              padding: '40px 20px', textAlign: 'center', color: '#aaa', fontSize: 13,
            }}>
              {showPast
                ? 'No past appointments.'
                : 'No upcoming appointments — they appear here when callers book via the AI.'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {displayed
                .slice()
                .sort((a, b) => new Date(a.appointment_datetime).getTime() - new Date(b.appointment_datetime).getTime())
                .map(appt => {
                  const upcoming = isUpcoming(appt.appointment_datetime)
                  const cancelled = appt.status === 'cancelled'
                  return (
                    <div
                      key={appt.id}
                      className="cal-appt-card"
                      style={{
                        borderColor: cancelled ? '#fee2e2' : upcoming ? '#d1fae5' : '#e8e6e0',
                        opacity: cancelled ? 0.7 : 1,
                      }}
                    >
                      {/* Date block */}
                      <div
                        className="cal-appt-date-block"
                        style={{ background: cancelled ? '#fef2f2' : upcoming ? '#eafaf2' : '#f4f3f0' }}
                      >
                        <div style={{ fontSize: 18, fontWeight: 700, color: '#16161a', lineHeight: 1 }}>
                          {new Date(appt.appointment_datetime).getDate()}
                        </div>
                        <div style={{ fontSize: 10, color: '#888', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>
                          {new Date(appt.appointment_datetime).toLocaleDateString('en-US', { month: 'short' })}
                        </div>
                      </div>

                      {/* Info */}
                      <div className="cal-appt-info">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 14, fontWeight: 600, color: '#16161a' }}>
                            {appt.caller_name || 'Unknown caller'}
                          </span>
                          {appt.service && (
                            <span style={{ fontSize: 11, color: '#666', background: '#f4f3f0', padding: '2px 7px', borderRadius: 4 }}>
                              {appt.service}
                            </span>
                          )}
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4,
                            textTransform: 'uppercase', letterSpacing: '0.04em', marginLeft: 'auto',
                            background: cancelled ? '#fee2e2' : upcoming ? '#d1fae5' : '#f4f3f0',
                            color: cancelled ? '#dc2626' : upcoming ? '#16a34a' : '#666',
                          }}>
                            {cancelled ? 'Cancelled' : upcoming ? 'Confirmed' : 'Completed'}
                          </span>
                        </div>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#555' }}>
                          {fmtDate(appt.appointment_datetime)} · {fmtTime(appt.appointment_datetime)}
                          {appt.duration_minutes && ` · ${appt.duration_minutes} min`}
                        </div>
                        {appt.caller_phone && (
                          <div style={{ marginTop: 2, fontSize: 11, color: '#aaa' }}>{appt.caller_phone}</div>
                        )}
                      </div>
                    </div>
                  )
                })}
            </div>
          )}
        </div>
    </>
  )
}

export default function CalendarPageWrapper() {
  return <CalendarPage />
}
