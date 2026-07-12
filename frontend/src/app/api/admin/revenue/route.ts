import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'
import { billingStatus } from '@/lib/billing'

const PLAN_PRICE: Record<string, number> = { starter: 99, pro: 199, business: 379 }

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth

  const { data: tenants, error } = await supabase
    .from('tenants')
    .select('id, subscription_plan, subscription_status, created_at, billing_exempt')

  if (error) return Response.json({ error: error.message }, { status: 500 })

  const all = tenants ?? []
  // Bucket by the SAME derived billing status the rest of the admin UI uses, so a
  // card-free trial counts as trialing (not "no subscription") and comps get their
  // own bucket. billingStatus() maps: comped | active | trialing | past_due |
  // canceled | trial (free) | expired (trial lapsed).
  const active    = all.filter(t => billingStatus(t) === 'active')
  const trialing  = all.filter(t => billingStatus(t) === 'trial')
  const comped    = all.filter(t => billingStatus(t) === 'comped')
  const pastDue   = all.filter(t => billingStatus(t) === 'past_due')
  const cancelled = all.filter(t => billingStatus(t) === 'canceled')
  const none      = all.filter(t => billingStatus(t) === 'expired')

  // MRR from paying (active) subs only — comps and free trials contribute $0.
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
    comped_count: comped.length,
    past_due_count: pastDue.length,
    cancelled_count: cancelled.length,
    none_count: none.length,
    total: all.length,
    plan_distribution: planDist,
  })
}
