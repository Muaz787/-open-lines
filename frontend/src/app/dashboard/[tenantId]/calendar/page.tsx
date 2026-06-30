'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import MicButton from '@/app/components/MicButton'
import { trackEvent } from '@/lib/analytics'
import { Toast } from '../components/Toast'
import { LoadingState, EmptyState } from '../components/PageStates'
import SquareAppointmentsCard from './SquareAppointmentsCard'

import { authedFetch } from '@/lib/api'
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface CalendarStatus {
  connected: boolean
  google_connected: boolean
  microsoft_connected: boolean
  microsoft_user_email?: string | null
  appointment_duration_minutes: number
  calendar_timezone: string
  slot_capacity?: number
}

interface Appointment {
  id: string
  caller_name?: string
  caller_phone?: string
  service?: string
  staff_name?: string
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
  const [msDisconnecting, setMsDisconnecting]   = useState(false)
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
  const [slotCapacity, setSlotCapacity] = useState<number>(1)
  const [staff, setStaff] = useState<{ id: string; name: string }[]>([])
  const [newStaff, setNewStaff] = useState('')
  const [staffBusy, setStaffBusy] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [bhSaving, setBhSaving] = useState(false)

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, aRes, cRes, sRes] = await Promise.all([
          authedFetch(`${API}/onboarding/status/${tenantId}`),
          authedFetch(`${API}/calendar/appointments/${tenantId}`),
          authedFetch(`${API}/calendar/status/${tenantId}`),
          authedFetch(`${API}/staff/${tenantId}`),
        ])
        if (sRes.ok) {
          const sd = await sRes.json()
          setStaff(Array.isArray(sd.staff) ? sd.staff : [])
        }
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
          if (t.slot_capacity != null) setSlotCapacity(t.slot_capacity)
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

    // pick up ?calendar=* redirect from OAuth flow
    const params = new URLSearchParams(window.location.search)
    const calParam = params.get('calendar')
    if (calParam === 'connected' || calParam === 'ms_connected') {
      showToast(calParam === 'ms_connected' ? 'Microsoft Outlook connected!' : 'Google Calendar connected!')
      authedFetch(`${API}/calendar/status/${tenantId}`).then(r => r.ok && r.json()).then(d => d && setCalStatus(d))
      window.history.replaceState({}, '', window.location.pathname)
    } else if (calParam === 'error' || calParam === 'ms_error') {
      showToast('Calendar connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [tenantId])

  // Owner-authenticated connect: mint the OAuth URL via authedFetch, then redirect.
  const startConnect = async (path: string, provider: string) => {
    trackEvent('calendar_connect_started', { location: 'calendar_page', provider, tenant_id: tenantId })
    try {
      const res = await authedFetch(`${API}${path}`)
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.url) window.location.href = data.url
      // On 401 authedFetch already redirects to /login.
    } catch {}
  }

  const disconnectCalendar = async () => {
    if (!confirm('Disconnect Google Calendar? The AI will no longer be able to book appointments in real time.')) return
    setCalDisconnecting(true)
    try {
      await authedFetch(`${API}/calendar/disconnect/${tenantId}`, { method: 'POST' })
      const r = await authedFetch(`${API}/calendar/status/${tenantId}`)
      if (r.ok) setCalStatus(await r.json())
    } finally {
      setCalDisconnecting(false)
    }
  }

  const disconnectOutlook = async () => {
    if (!confirm('Disconnect Microsoft Outlook? The AI will no longer be able to book appointments in real time.')) return
    setMsDisconnecting(true)
    try {
      await authedFetch(`${API}/calendar/microsoft/disconnect/${tenantId}`, { method: 'POST' })
      const r = await authedFetch(`${API}/calendar/status/${tenantId}`)
      if (r.ok) setCalStatus(await r.json())
    } finally {
      setMsDisconnecting(false)
    }
  }

  const saveBusinessHours = async () => {
    if (bhStart >= bhEnd) { showToast('Opening time must be before closing time'); return }
    if (bizDays.length === 0) { showToast('Select at least one operating day'); return }
    if (breakOn && breakStart >= breakEnd) { showToast('Break start must be before break end'); return }
    setBhSaving(true)
    try {
      const res = await authedFetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          business_hours_start: bhStart,
          business_hours_end:   bhEnd,
          business_days:        [...bizDays].sort((a, b) => a - b),
          break_start:          breakOn ? breakStart : null,
          break_end:            breakOn ? breakEnd : null,
          booking_instructions: bookingInstructions.trim(),
          slot_capacity:        Math.max(1, Math.min(50, Math.round(slotCapacity) || 1)),
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

  const addStaff = async () => {
    const name = newStaff.trim()
    if (!name) return
    setStaffBusy(true)
    try {
      const res = await authedFetch(`${API}/staff/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (res.ok) {
        const s = await res.json()
        setStaff(prev => [...prev, { id: s.id, name: s.name }])
        setNewStaff('')
      } else showToast('Failed to add — try again')
    } catch { showToast('Failed to add — try again') }
    finally { setStaffBusy(false) }
  }

  const removeStaff = async (id: string) => {
    setStaffBusy(true)
    try {
      const res = await authedFetch(`${API}/staff/${tenantId}/${id}`, { method: 'DELETE' })
      if (res.ok) setStaff(prev => prev.filter(s => s.id !== id))
      else showToast('Failed to remove — try again')
    } catch { showToast('Failed to remove — try again') }
    finally { setStaffBusy(false) }
  }

  const renameStaff = async (id: string) => {
    const name = editName.trim()
    if (!name) return
    setStaffBusy(true)
    try {
      const res = await authedFetch(`${API}/staff/${tenantId}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (res.ok) {
        setStaff(prev => prev.map(s => (s.id === id ? { ...s, name } : s)))
        setEditingId(null)
      } else showToast('Failed to rename — try again')
    } catch { showToast('Failed to rename — try again') }
    finally { setStaffBusy(false) }
  }

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const upcoming = appointments.filter(a => a.status !== 'cancelled' && isUpcoming(a.appointment_datetime))
  const past     = appointments.filter(a => a.status === 'cancelled' || !isUpcoming(a.appointment_datetime))

  const displayed = showPast ? past : upcoming

  if (loading) {
    return <LoadingState />
  }

  return (
    <>

        {/* Toast */}
        <Toast message={toast} />

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Calendar</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: 'var(--db-accent)', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">

          {/* Calendar integration section */}
          <div className="db-card" style={{ padding: '18px 20px', marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>
              Calendar Integration
            </div>
            <div style={{ fontSize: 11, color: 'var(--db-faint)', marginBottom: 16, lineHeight: 1.5 }}>
              Connect a calendar so the AI can check availability and book appointments in real time.
              {calStatus?.google_connected && calStatus?.microsoft_connected && (
                <span style={{ color: 'var(--db-accent-text)', display: 'block', marginTop: 4 }}>
                  Both calendars connected — Google Calendar takes priority for bookings.
                </span>
              )}
            </div>

            {/* Google Calendar row */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 10, paddingBottom: 14,
              borderBottom: '1px solid var(--db-border)', marginBottom: 14,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <rect width="24" height="24" rx="4" fill="#fff"/>
                  <path d="M21.805 10.023H21V10h-9v4h5.651C16.785 15.933 14.557 17 12 17c-2.761 0-5-2.239-5-5s2.239-5 5-5c1.266 0 2.418.48 3.292 1.265l2.828-2.828C16.595 3.93 14.407 3 12 3 7.03 3 3 7.03 3 12s4.03 9 9 9 9-4.03 9-9c0-.604-.062-1.193-.195-1.757" fill="#4285F4"/>
                  <path d="M4.306 7.691l3.286 2.41A4.996 4.996 0 0 1 12 7c1.266 0 2.418.48 3.292 1.265l2.828-2.828C16.595 3.93 14.407 3 12 3c-3.316 0-6.185 1.79-7.694 4.691" fill="#34A853"/>
                  <path d="M12 21c2.361 0 4.51-.899 6.127-2.366l-2.83-2.395A4.974 4.974 0 0 1 12 17c-2.548 0-4.772-1.058-6.338-2.933l-3.27 2.52C4.034 19.08 7.825 21 12 21" fill="#FBBC05"/>
                  <path d="M21.805 10.023H21V10h-9v4h5.651a5.016 5.016 0 0 1-2.479 2.239l2.829 2.395C17.786 18.146 21 15 21 12c0-.604-.062-1.193-.195-1.757" fill="#EA4335"/>
                </svg>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text)' }}>Google Calendar</div>
                  {calStatus?.google_connected && (
                    <div style={{ fontSize: 11, color: 'var(--db-accent-text)', marginTop: 1 }}>Connected</div>
                  )}
                </div>
              </div>
              {calStatus?.google_connected ? (
                <button
                  className="db-btn db-btn--ghost db-btn--sm"
                  onClick={disconnectCalendar}
                  disabled={calDisconnecting}
                >
                  {calDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              ) : (
                <button
                  type="button"
                  className="db-btn db-btn--dark"
                  style={{ fontSize: 12 }}
                  onClick={() => startConnect(`/calendar/connect/${tenantId}`, 'google')}
                >
                  Connect
                </button>
              )}
            </div>

            {/* Microsoft Outlook row */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 10,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <rect width="24" height="24" rx="4" fill="#0078D4"/>
                  <path d="M13 5h7v7h-7z" fill="#fff" opacity=".8"/>
                  <path d="M13 12h7v7h-7z" fill="#fff" opacity=".5"/>
                  <path d="M6 12h7v7H6z" fill="#fff" opacity=".5"/>
                  <rect x="4" y="7" width="8" height="8" rx="4" fill="#fff" opacity=".9"/>
                  <circle cx="8" cy="11" r="2.5" fill="#0078D4"/>
                </svg>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text)' }}>Microsoft Outlook</div>
                  {calStatus?.microsoft_connected && (
                    <div style={{ fontSize: 11, color: 'var(--db-accent-text)', marginTop: 1 }}>
                      Connected{calStatus.microsoft_user_email ? ` · ${calStatus.microsoft_user_email}` : ''}
                    </div>
                  )}
                </div>
              </div>
              {calStatus?.microsoft_connected ? (
                <button
                  className="db-btn db-btn--ghost db-btn--sm"
                  onClick={disconnectOutlook}
                  disabled={msDisconnecting}
                >
                  {msDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              ) : (
                <button
                  type="button"
                  className="db-btn db-btn--dark"
                  style={{ fontSize: 12 }}
                  onClick={() => startConnect(`/calendar/microsoft/connect?tenant_id=${tenantId}`, 'microsoft')}
                >
                  Connect
                </button>
              )}
            </div>
          </div>

          {/* Square Appointments — book into the merchant's own Square calendar */}
          <SquareAppointmentsCard tenantId={tenantId} />

          {/* Availability settings */}
          <div className="db-card" style={{ padding: '18px 20px', marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>
              Availability
            </div>
            <div style={{ fontSize: 11, color: 'var(--db-faint)', marginBottom: 16 }}>
              The AI will only offer and book appointments within these days, hours, and rules.
            </div>

            {/* Operating days */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 8 }}>Operating days</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => (
                  <button
                    key={i}
                    className={`db-pill${bizDays.includes(i) ? ' active' : ''}`}
                    onClick={() => toggleDay(i)}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* Hours */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 8 }}>Hours</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 12, color: 'var(--db-muted)' }}>Opens at</label>
                  <select className="db-select" value={bhStart} onChange={e => setBhStart(Number(e.target.value))} style={{ fontSize: 12, padding: '5px 8px' }}>
                    {Array.from({ length: 24 }, (_, h) => (
                      <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                    ))}
                  </select>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 12, color: 'var(--db-muted)' }}>Closes at</label>
                  <select className="db-select" value={bhEnd} onChange={e => setBhEnd(Number(e.target.value))} style={{ fontSize: 12, padding: '5px 8px' }}>
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
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)' }}>Daily break (e.g. lunch)</span>
              </label>
              {breakOn && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', paddingLeft: 24 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 12, color: 'var(--db-muted)' }}>From</label>
                    <select className="db-select" value={breakStart} onChange={e => setBreakStart(Number(e.target.value))} style={{ fontSize: 12, padding: '5px 8px' }}>
                      {Array.from({ length: 24 }, (_, h) => (
                        <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                      ))}
                    </select>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 12, color: 'var(--db-muted)' }}>To</label>
                    <select className="db-select" value={breakEnd} onChange={e => setBreakEnd(Number(e.target.value))} style={{ fontSize: 12, padding: '5px 8px' }}>
                      {Array.from({ length: 24 }, (_, h) => (
                        <option key={h} value={h}>{h === 0 ? '12:00 AM' : h < 12 ? `${h}:00 AM` : h === 12 ? '12:00 PM' : `${h - 12}:00 PM`}</option>
                      ))}
                    </select>
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--db-faint)' }}>No appointments during this window</span>
                </div>
              )}
            </div>

            {/* Team & capacity */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 4 }}>
                Team &amp; capacity
              </div>
              <div style={{ fontSize: 11, color: 'var(--db-faint)', marginBottom: 10, lineHeight: 1.5 }}>
                {staff.length > 0
                  ? `Bookings are spread across your ${staff.length} team member${staff.length === 1 ? '' : 's'} — each takes one appointment per slot, and the AI can book a caller with whoever they ask for.`
                  : 'Set how many you can serve at once, or add named team members to track who handles each booking and let callers request someone by name.'}
              </div>

              {/* Pooled capacity — only when no named staff */}
              {staff.length === 0 && (
                <div style={{ marginBottom: 14 }}>
                  <label style={{ fontSize: 11, color: 'var(--db-faint)', display: 'block', marginBottom: 4 }}>
                    How many can you serve at the same time? (e.g. 4 chairs = 4)
                  </label>
                  <input
                    type="number" min={1} max={50} step={1}
                    value={slotCapacity}
                    onChange={e => setSlotCapacity(Math.max(1, Math.min(50, Math.round(Number(e.target.value)) || 1)))}
                    className="db-input"
                    style={{ width: 120 }}
                  />
                </div>
              )}

              {/* Named staff list */}
              {staff.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
                  {staff.map(s => (
                    <div key={s.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '8px 12px', border: '1px solid var(--db-border)', borderRadius: 8 }}>
                      {editingId === s.id ? (
                        <>
                          <input
                            className="db-input"
                            value={editName}
                            onChange={e => setEditName(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') renameStaff(s.id); if (e.key === 'Escape') setEditingId(null) }}
                            maxLength={60}
                            autoFocus
                            style={{ flex: 1, height: 30, fontSize: 13 }}
                          />
                          <button className="db-btn db-btn--dark db-btn--sm" onClick={() => renameStaff(s.id)} disabled={staffBusy || !editName.trim()}>Save</button>
                          <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => setEditingId(null)} disabled={staffBusy}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <span style={{ fontSize: 13, color: 'var(--db-text)' }}>{s.name}</span>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => { setEditingId(s.id); setEditName(s.name) }} disabled={staffBusy}>Rename</button>
                            <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => removeStaff(s.id)} disabled={staffBusy}>Remove</button>
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Add team member */}
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  className="db-input"
                  placeholder="Add a team member (e.g. Sam)"
                  value={newStaff}
                  onChange={e => setNewStaff(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addStaff()}
                  maxLength={60}
                  style={{ flex: 1 }}
                />
                <button className="db-btn db-btn--dark db-btn--sm" onClick={addStaff} disabled={staffBusy || !newStaff.trim()}>
                  Add
                </button>
              </div>
            </div>

            {/* Booking instructions */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 4 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)' }}>
                  Special instructions for the booking agent
                </div>
                <MicButton onResult={t => setBookingInstructions(prev => (prev.trim() ? prev.trim() + ' ' : '') + t)} />
              </div>
              <div style={{ fontSize: 11, color: 'var(--db-faint)', marginBottom: 8 }}>
                Plain English rules the AI should follow — type, or tap the mic to dictate.
                e.g. &quot;Always ask if they&apos;re a new or returning client&quot; or &quot;Mention parking is free out back.&quot;
              </div>
              <textarea
                className="db-textarea"
                value={bookingInstructions}
                onChange={e => setBookingInstructions(e.target.value)}
                placeholder="Add any booking rules or notes for the AI…"
                rows={3}
              />
            </div>

            <button
              className="db-btn db-btn--dark"
              onClick={saveBusinessHours}
              disabled={bhSaving}
            >
              {bhSaving ? 'Saving…' : 'Save availability'}
            </button>
          </div>

          {/* Toggle upcoming / past */}
          <div className="cal-toggle-bar">
            <button
              className={`db-pill${!showPast ? ' active' : ''}`}
              onClick={() => setShowPast(false)}
            >
              Upcoming ({upcoming.length})
            </button>
            <button
              className={`db-pill${showPast ? ' active' : ''}`}
              onClick={() => setShowPast(true)}
            >
              Past &amp; Cancelled ({past.length})
            </button>
          </div>

          {/* Appointment list */}
          {displayed.length === 0 ? (
            <div className="db-card">
              <EmptyState
                icon={
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
                  </svg>
                }
                title={showPast ? 'No past appointments.' : 'No upcoming appointments.'}
                sub={showPast ? undefined : 'They appear here when callers book via the AI.'}
              />
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
                        borderColor: cancelled ? 'var(--db-danger-bg)' : upcoming ? 'var(--db-accent-border)' : 'var(--db-border)',
                        opacity: cancelled ? 0.7 : 1,
                      }}
                    >
                      {/* Date block */}
                      <div
                        className="cal-appt-date-block"
                        style={{ background: cancelled ? 'var(--db-danger-bg)' : upcoming ? 'var(--db-accent-bg)' : 'var(--db-bg)' }}
                      >
                        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--db-text)', lineHeight: 1 }}>
                          {new Date(appt.appointment_datetime).getDate()}
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--db-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>
                          {new Date(appt.appointment_datetime).toLocaleDateString('en-US', { month: 'short' })}
                        </div>
                      </div>

                      {/* Info */}
                      <div className="cal-appt-info">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)' }}>
                            {appt.caller_name || 'Unknown caller'}
                          </span>
                          {appt.service && (
                            <span className="db-chip">{appt.service}</span>
                          )}
                          {appt.staff_name && (
                            <span className="db-chip" style={{ background: 'var(--db-accent-bg)', color: 'var(--db-accent-text)' }}>
                              with {appt.staff_name}
                            </span>
                          )}
                          <span
                            className={`cal-appt-status db-badge ${cancelled ? 'db-badge--danger' : upcoming ? 'db-badge--success' : 'db-badge--neutral'}`}
                            style={{ marginLeft: 'auto' }}
                          >
                            {cancelled ? 'Cancelled' : upcoming ? 'Confirmed' : 'Completed'}
                          </span>
                        </div>
                        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--db-text-2)' }}>
                          {fmtDate(appt.appointment_datetime)} · {fmtTime(appt.appointment_datetime)}
                          {appt.duration_minutes && ` · ${appt.duration_minutes} min`}
                        </div>
                        {appt.caller_phone && (
                          <div style={{ marginTop: 2, fontSize: 11, color: 'var(--db-faint)' }}>{appt.caller_phone}</div>
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
