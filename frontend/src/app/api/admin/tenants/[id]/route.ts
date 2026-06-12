import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth

  const [tenantRes, callsRes, apptRes, kbRes] = await Promise.all([
    supabase.from('tenants').select(`
      id, business_name, industry, owner_name, email,
      subscription_plan, subscription_status, stripe_customer_id, stripe_subscription_id,
      twilio_phone_number, vapi_assistant_id, is_active, created_at,
      google_refresh_token, appointment_duration_minutes, calendar_timezone,
      kb_files, website_url, extra_instructions, whatsapp_number,
      minutes_used_this_period, overage_minutes_reported, billing_period_anchor,
      business_hours_start, business_hours_end, business_days, break_start, break_end,
      agent_name
    `).eq('id', id).single(),
    supabase.from('calls')
      .select('id, created_at, duration_secs, vapi_call_id, lead_id')
      .eq('tenant_id', id)
      .order('created_at', { ascending: false })
      .limit(5),
    supabase.from('appointments')
      .select('id, created_at, appointment_datetime, caller_name, caller_phone, service, status, duration_minutes, google_event_id')
      .eq('tenant_id', id)
      .order('created_at', { ascending: false })
      .limit(5),
    supabase.from('kb_entries')
      .select('id, type, label, added_at')
      .eq('tenant_id', id)
      .order('added_at', { ascending: false }),
  ])

  if (!tenantRes.data) return Response.json({ error: 'Not found' }, { status: 404 })

  const t = tenantRes.data

  // Setup health checks
  const issues: string[] = []
  if (!t.twilio_phone_number) issues.push('No dedicated phone number assigned')
  if (!t.vapi_assistant_id) issues.push('No Vapi assistant configured')
  if (!t.google_refresh_token) issues.push('Google Calendar not connected')
  const kbCount = (kbRes.data ?? []).length
  const kbFiles = (t.kb_files as unknown[]) ?? []
  if (kbCount === 0 && kbFiles.length === 0) issues.push('No knowledge base content uploaded')

  // Mask caller phones in appointments
  const appointments = (apptRes.data ?? []).map(a => ({
    ...a,
    caller_phone: a.caller_phone
      ? a.caller_phone.slice(0, 2) + '*'.repeat(Math.max(0, a.caller_phone.length - 6)) + a.caller_phone.slice(-4)
      : '—',
  }))

  await logAdminAction(supabase, userId, 'tenant_viewed', 'tenant', id)

  return Response.json({
    tenant: {
      id: t.id,
      business_name: t.business_name,
      industry: t.industry,
      owner_name: t.owner_name,
      email: t.email,
      agent_name: t.agent_name,
      subscription_plan: t.subscription_plan,
      subscription_status: t.subscription_status,
      stripe_customer_id: t.stripe_customer_id,
      stripe_subscription_id: t.stripe_subscription_id,
      twilio_phone_number: t.twilio_phone_number,
      vapi_assistant_id: t.vapi_assistant_id,
      is_active: t.is_active,
      created_at: t.created_at,
      has_calendar: Boolean(t.google_refresh_token),
      calendar_timezone: t.calendar_timezone,
      appointment_duration_minutes: t.appointment_duration_minutes,
      website_url: t.website_url,
      whatsapp_number: t.whatsapp_number,
      minutes_used_this_period: t.minutes_used_this_period,
      billing_period_anchor: t.billing_period_anchor,
      business_hours_start: t.business_hours_start,
      business_hours_end: t.business_hours_end,
    },
    issues,
    recent_calls: callsRes.data ?? [],
    recent_appointments: appointments,
    kb_entries: kbRes.data ?? [],
    kb_count: kbCount,
  })
}
