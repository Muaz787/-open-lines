import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

function dayBuckets(days: number): string[] {
  const buckets: string[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    buckets.push(d.toISOString().slice(0, 10))
  }
  return buckets
}

function countByDay(rows: { created_at: string }[], days: number): { date: string; count: number }[] {
  const buckets = dayBuckets(days)
  const map: Record<string, number> = {}
  for (const b of buckets) map[b] = 0
  for (const r of rows) {
    const d = r.created_at.slice(0, 10)
    if (d in map) map[d]++
  }
  return buckets.map(d => ({ date: d, count: map[d] }))
}

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  const weekStart = new Date(now.getTime() - 7 * 86400000).toISOString()
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
  const days30 = new Date(now.getTime() - 30 * 86400000).toISOString()

  const PLAN_PRICE: Record<string, number> = { starter: 99, pro: 199, business: 379 }

  const [
    tenantsRes,
    callsRes,
    appointmentsRes,
  ] = await Promise.all([
    supabase.from('tenants').select('id, created_at, subscription_status, subscription_plan, is_active'),
    supabase.from('calls').select('id, created_at, duration_secs, tenant_id'),
    supabase.from('appointments').select('id, created_at'),
  ])

  const tenants = tenantsRes.data ?? []
  const calls = callsRes.data ?? []
  const appointments = appointmentsRes.data ?? []

  const totalTenants = tenants.length
  const signupsToday = tenants.filter(t => t.created_at >= todayStart).length
  const signupsWeek = tenants.filter(t => t.created_at >= weekStart).length
  const activeTenants = tenants.filter(t => t.is_active).length
  const paidTenants = tenants.filter(t => t.subscription_status === 'active').length
  const trialTenants = tenants.filter(t => t.subscription_status === 'trialing').length
  const failedPayments = tenants.filter(t => t.subscription_status === 'past_due').length
  const mrr = tenants
    .filter(t => t.subscription_status === 'active' && t.subscription_plan)
    .reduce((sum, t) => sum + (PLAN_PRICE[t.subscription_plan ?? ''] ?? 0), 0)

  const callsToday = calls.filter(c => c.created_at >= todayStart).length
  const callsWeek = calls.filter(c => c.created_at >= weekStart).length
  const minutesMonth = Math.round(
    calls.filter(c => c.created_at >= monthStart).reduce((s, c) => s + (c.duration_secs ?? 0), 0) / 60
  )

  const apptMonth = appointments.filter(a => a.created_at >= monthStart).length

  const signups30d = countByDay(
    tenants.filter(t => t.created_at >= days30).map(t => ({ created_at: t.created_at })),
    30,
  )
  const calls30d = countByDay(
    calls.filter(c => c.created_at >= days30).map(c => ({ created_at: c.created_at })),
    30,
  )
  const appts30d = countByDay(
    appointments.filter(a => a.created_at >= days30).map(a => ({ created_at: a.created_at })),
    30,
  )

  const { data: recentSignups } = await supabase
    .from('tenants')
    .select('id, business_name, industry, email, owner_name, subscription_status, subscription_plan, created_at')
    .order('created_at', { ascending: false })
    .limit(10)

  return Response.json({
    total_tenants: totalTenants,
    signups_today: signupsToday,
    signups_week: signupsWeek,
    active_tenants: activeTenants,
    paid_tenants: paidTenants,
    trial_tenants: trialTenants,
    calls_today: callsToday,
    calls_week: callsWeek,
    minutes_month: minutesMonth,
    appointments_month: apptMonth,
    mrr,
    failed_payments: failedPayments,
    signups_30d: signups30d,
    calls_30d: calls30d,
    appointments_30d: appts30d,
    recent_signups: recentSignups ?? [],
  })
}
