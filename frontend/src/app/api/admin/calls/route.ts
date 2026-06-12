import type { NextRequest } from 'next/server'
import { requireAdmin, maskPhone } from '@/lib/admin-auth'

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth
  const { searchParams } = req.nextUrl
  const page = Math.max(1, Number(searchParams.get('page') ?? 1))
  const perPage = 50
  const tenantId = searchParams.get('tenant_id') ?? ''
  const dateFrom = searchParams.get('date_from') ?? ''
  const dateTo = searchParams.get('date_to') ?? ''
  const hasAppt = searchParams.get('has_appointment') ?? ''

  let query = supabase
    .from('calls')
    .select(`
      id, created_at, duration_secs, vapi_call_id, tenant_id,
      leads:lead_id (name, phone, urgency, status),
      tenants:tenant_id (business_name),
      appointments:vapi_call_id (id)
    `, { count: 'exact' })
    .order('created_at', { ascending: false })
    .range((page - 1) * perPage, page * perPage - 1)

  if (tenantId) query = query.eq('tenant_id', tenantId)
  if (dateFrom) query = query.gte('created_at', dateFrom)
  if (dateTo) query = query.lte('created_at', dateTo + 'T23:59:59Z')

  const { data, count, error } = await query
  if (error) return Response.json({ error: error.message }, { status: 500 })

  let calls = (data ?? []).map((c: Record<string, unknown>) => {
    const lead = c.leads as { name?: string; phone?: string; urgency?: string; status?: string } | null
    const tenant = c.tenants as { business_name?: string } | null
    const appts = c.appointments as unknown[]
    return {
      id: c.id,
      created_at: c.created_at,
      duration_secs: c.duration_secs,
      vapi_call_id: c.vapi_call_id,
      tenant_id: c.tenant_id,
      business_name: tenant?.business_name ?? '—',
      caller_phone: maskPhone(lead?.phone),
      urgency: lead?.urgency ?? null,
      lead_status: lead?.status ?? null,
      has_appointment: Array.isArray(appts) && appts.length > 0,
    }
  })

  if (hasAppt === 'yes') calls = calls.filter(c => c.has_appointment)
  if (hasAppt === 'no') calls = calls.filter(c => !c.has_appointment)

  return Response.json({ calls, total: count ?? 0, page, per_page: perPage })
}
