'use client'

import { useState, useEffect, useCallback } from 'react'
import { authedFetch } from '@/lib/api'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface SquareService {
  square_variation_id: string
  name: string
  duration_minutes?: number | null
  available_for_booking?: boolean
}
interface SquareStaff {
  square_team_member_id: string
  display_name?: string | null
}
interface AppointmentsStatus {
  connected: boolean
  enabled: boolean
  bookable: boolean
  synced_at?: string | null
  location_timezone?: string | null
  services: SquareService[]
  staff: SquareStaff[]
}

function Switch({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      role="switch" aria-checked={on} onClick={onClick} disabled={disabled}
      style={{
        width: 40, height: 22, borderRadius: 11, border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer', flexShrink: 0,
        background: on ? 'var(--db-accent-text)' : 'var(--db-border)',
        position: 'relative', transition: 'background 0.2s', opacity: disabled ? 0.5 : 1,
      }}
    >
      <span style={{
        position: 'absolute', top: 3, left: on ? 21 : 3, width: 16, height: 16,
        borderRadius: '50%', background: '#fff', transition: 'left 0.2s',
      }} />
    </button>
  )
}

export default function SquareAppointmentsCard({ tenantId }: { tenantId: string }) {
  const [status, setStatus]   = useState<AppointmentsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy]       = useState(false)
  const [msg, setMsg]         = useState<string | null>(null)

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(null), 4000) }

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(`${API}/square-connect/appointments/${tenantId}`)
      if (r.ok) setStatus(await r.json())
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => { load() }, [load])

  const connect = async () => {
    setBusy(true)
    try {
      const r = await authedFetch(`${API}/square-connect/onboard/${tenantId}`, { method: 'POST' })
      if (!r.ok) { flash((await r.json().catch(() => ({}))).detail || 'Connect failed'); return }
      const { url } = await r.json()
      window.location.href = url
    } catch { flash('Network error — try again.') } finally { setBusy(false) }
  }

  const sync = async () => {
    setBusy(true)
    try {
      const r = await authedFetch(`${API}/square-connect/appointments/sync/${tenantId}`, { method: 'POST' })
      if (!r.ok) { flash((await r.json().catch(() => ({}))).detail || 'Sync failed'); return }
      const d = await r.json()
      flash(`Synced ${d.services?.length ?? 0} services and ${d.staff?.length ?? 0} team members.`)
      await load()
    } catch { flash('Network error — try again.') } finally { setBusy(false) }
  }

  const toggle = async () => {
    if (!status) return
    setBusy(true)
    try {
      const r = await authedFetch(`${API}/square-connect/appointments/enable/${tenantId}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !status.enabled }),
      })
      if (!r.ok) { flash((await r.json().catch(() => ({}))).detail || 'Could not update'); return }
      flash(!status.enabled ? 'Square Appointments is now your booking calendar.' : 'Square Appointments turned off.')
      await load()
    } catch { flash('Network error — try again.') } finally { setBusy(false) }
  }

  if (loading) return null

  const services = status?.services ?? []
  const staff    = status?.staff ?? []
  const hasServices = services.length > 0

  return (
    <div className="db-card" style={{ padding: '18px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>
            Square Appointments
          </div>
          <div style={{ fontSize: 12, color: 'var(--db-muted)', lineHeight: 1.5, maxWidth: 540 }}>
            Let the AI read availability and book directly into your existing Square Appointments
            calendar — no separate calendar to manage. Uses the same Square connection as deposits.
          </div>
        </div>
        {hasServices && (
          <Switch on={!!status?.enabled} onClick={toggle} disabled={busy || !status?.bookable} />
        )}
      </div>

      {msg && (
        <div style={{ fontSize: 12, color: 'var(--db-accent-text)', marginTop: 10 }}>{msg}</div>
      )}

      {/* Not connected */}
      {!status?.connected && (
        <button className="db-btn db-btn--dark" style={{ fontSize: 13, marginTop: 14 }}
          onClick={connect} disabled={busy}>
          {busy ? 'Opening Square…' : 'Connect Square'}
        </button>
      )}

      {/* Connected but nothing synced yet */}
      {status?.connected && !hasServices && (
        <div style={{ marginTop: 14 }}>
          <button className="db-btn db-btn--dark" style={{ fontSize: 13 }} onClick={sync} disabled={busy}>
            {busy ? 'Syncing…' : 'Sync services & staff'}
          </button>
          <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 8, lineHeight: 1.5 }}>
            If nothing appears after syncing, reconnect Square so it can grant booking access, and make
            sure Square Appointments is enabled on your Square account.
          </div>
        </div>
      )}

      {/* Synced */}
      {status?.connected && hasServices && (
        <div style={{ marginTop: 14 }}>
          {!status.bookable && (
            <div style={{ fontSize: 12, color: '#b45309', background: 'rgba(251,191,36,0.12)',
              padding: '8px 10px', borderRadius: 6, marginBottom: 12 }}>
              Square Appointments isn&apos;t active on your Square account yet — you can review your
              services below, but bookings can&apos;t be created until you enable Appointments in Square.
            </div>
          )}

          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 6 }}>
            Services ({services.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
            {services.map(s => (
              <span key={s.square_variation_id} style={{
                fontSize: 12, color: 'var(--db-text-2)', background: 'var(--db-bg-2)',
                padding: '4px 10px', borderRadius: 20,
                opacity: s.available_for_booking === false ? 0.5 : 1,
              }}>
                {s.name}{s.duration_minutes ? ` · ${s.duration_minutes}m` : ''}
              </span>
            ))}
          </div>

          {staff.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 6 }}>
                Team ({staff.length})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                {staff.map(m => (
                  <span key={m.square_team_member_id} style={{
                    fontSize: 12, color: 'var(--db-text-2)', background: 'var(--db-bg-2)',
                    padding: '4px 10px', borderRadius: 20,
                  }}>
                    {m.display_name || 'Team member'}
                  </span>
                ))}
              </div>
            </>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button className="db-btn db-btn--ghost db-btn--sm" onClick={sync} disabled={busy}>
              {busy ? 'Working…' : 'Resync'}
            </button>
            {status.synced_at && (
              <span style={{ fontSize: 11, color: 'var(--db-faint)' }}>
                Last synced {new Date(status.synced_at).toLocaleString()}
              </span>
            )}
          </div>

          {status.enabled && (
            <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 12, lineHeight: 1.5 }}>
              Bookings, reschedules and cancellations flow into your Square calendar. Deposits are handled
              by your Square Appointments prepayment settings (not Open Lines&apos; deposit collection).
            </div>
          )}
        </div>
      )}
    </div>
  )
}
