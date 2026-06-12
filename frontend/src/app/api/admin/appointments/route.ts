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
  const status = searchParams.get('status') ?? ''
  const dateFrom = searchParams.get('date_from') ?? ''
  const dateTo = searchParams.get('date_to') ?? ''

  let query = supabase
    .from('appointments')
    .select(`
      id, created_at, appointment_datetime, caller_name, caller_phone,
      service, status, duration_minutes, google_event_id, vapi_call_id, tenant_id,
      tenants:tenant_id (business_name)
    `, { count: 'exact' })
    .order('created_at', { ascending: false })
    .range((page - 1) * perPage, page * perPage - 1)

  if (tenantId) query = query.eq('tenant_id', tenantId)
  if (status) query = query.eq('status', status)
  if (dateFrom) query = query.gte('created_at', dateFrom)
  if (dateTo) query = query.lte('created_at', dateTo + 'T23:59:59Z')

  const { data, count, error } = await query
  if (error) return Response.json({ error: error.message }, { status: 500 })

  const appointments = (data ?? []).map((a: Record<string, unknown>) => {
    const tenant = a.tenants as { business_name?: string } | null
    return {
      id: a.id,
      created_at: a.created_at,
      appointment_datetime: a.appointment_datetime,
      caller_name: a.caller_name,
      caller_phone: maskPhone(a.caller_phone as string | null),
      service: a.service,
      status: a.status,
      duration_minutes: a.duration_minutes,
      has_calendar_event: Boolean(a.google_event_id),
      tenant_id: a.tenant_id,
      business_name: tenant?.business_name ?? '—',
    }
  })

  return Response.json({ appointments, total: count ?? 0, page, per_page: perPage })
}
