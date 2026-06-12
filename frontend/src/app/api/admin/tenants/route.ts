import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth
  const { searchParams } = req.nextUrl
  const page = Math.max(1, Number(searchParams.get('page') ?? 1))
  const perPage = 50
  const search = searchParams.get('search') ?? ''
  const status = searchParams.get('status') ?? ''
  const hasCalendar = searchParams.get('has_calendar') ?? ''
  const hasKb = searchParams.get('has_kb') ?? ''

  let query = supabase
    .from('tenants')
    .select(`
      id, business_name, email, owner_name, industry,
      subscription_plan, subscription_status, twilio_phone_number,
      google_refresh_token, kb_files, is_active, created_at,
      calls(count),
      kb_entries(count)
    `, { count: 'exact' })
    .order('created_at', { ascending: false })
    .range((page - 1) * perPage, page * perPage - 1)

  if (search) {
    query = query.or(`business_name.ilike.%${search}%,email.ilike.%${search}%,owner_name.ilike.%${search}%`)
  }
  if (status) {
    query = query.eq('subscription_status', status)
  }

  const { data, count, error } = await query

  if (error) return Response.json({ error: error.message }, { status: 500 })

  let tenants = (data ?? []).map((t: Record<string, unknown>) => {
    const callCount = (t.calls as { count: number }[] | null)?.[0]?.count ?? 0
    const kbCount = (t.kb_entries as { count: number }[] | null)?.[0]?.count ?? 0
    const kbFiles = (t.kb_files as unknown[]) ?? []
    return {
      id: t.id,
      business_name: t.business_name,
      email: t.email,
      owner_name: t.owner_name,
      industry: t.industry,
      subscription_plan: t.subscription_plan,
      subscription_status: t.subscription_status,
      twilio_phone_number: t.twilio_phone_number,
      has_calendar: Boolean(t.google_refresh_token),
      has_kb: kbCount > 0 || kbFiles.length > 0,
      is_active: t.is_active,
      created_at: t.created_at,
      call_count: callCount,
    }
  })

  // Client-side calendar/kb filter (PostgREST can't filter on IS NOT NULL easily for optional cols)
  if (hasCalendar === 'yes') tenants = tenants.filter(t => t.has_calendar)
  if (hasCalendar === 'no') tenants = tenants.filter(t => !t.has_calendar)
  if (hasKb === 'yes') tenants = tenants.filter(t => t.has_kb)
  if (hasKb === 'no') tenants = tenants.filter(t => !t.has_kb)

  return Response.json({ tenants, total: count ?? 0, page, per_page: perPage })
}
