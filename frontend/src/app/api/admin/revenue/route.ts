import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

const PLAN_PRICE: Record<string, number> = { starter: 99, pro: 199, business: 379 }

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth

  const { data: tenants, error } = await supabase
    .from('tenants')
    .select('id, subscription_plan, subscription_status, created_at')

  if (error) return Response.json({ error: error.message }, { status: 500 })

  const all = tenants ?? []
  const active = all.filter(t => t.subscription_status === 'active')
  const trialing = all.filter(t => t.subscription_status === 'trialing')
  const pastDue = all.filter(t => t.subscription_status === 'past_due')
  const cancelled = all.filter(t => t.subscription_status === 'canceled')
  const none = all.filter(t => !t.subscription_status || t.subscription_status === 'none')

  const mrr = active.reduce((sum, t) => sum + (PLAN_PRICE[t.subscription_plan ?? ''] ?? 0), 0)

  const planDist: Record<string, { count: number; revenue: number }> = {}
  for (const plan of ['starter', 'pro', 'business']) {
    const planActive = active.filter(t => t.subscription_plan === plan)
    planDist[plan] = { count: planActive.length, revenue: planActive.length * PLAN_PRICE[plan] }
  }

  return Response.json({
    mrr,
    active_count: active.length,
    trial_count: trialing.length,
    past_due_count: pastDue.length,
    cancelled_count: cancelled.length,
    none_count: none.length,
    total: all.length,
    plan_distribution: planDist,
  })
}
