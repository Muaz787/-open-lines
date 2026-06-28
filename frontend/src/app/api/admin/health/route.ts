import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

type CheckStatus = 'ok' | 'warning' | 'error'
interface HealthCheck { name: string; status: CheckStatus; message: string }

function envCheck(name: string, label: string): HealthCheck {
  const val = process.env[name]
  return { name: label, status: val ? 'ok' : 'error', message: val ? 'Configured' : 'Missing — set ' + name }
}

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth
  const checks: HealthCheck[] = []

  // Railway / backend API + all backend service checks (Twilio, Stripe, Square,
  // Resend, Pinecone, Firecrawl, website crawl, daily cron, WhatsApp, …) come
  // from the backend health endpoint — those secrets live in the backend env.
  const apiUrl = process.env.NEXT_PUBLIC_API_URL
  const adminKey = process.env.ADMIN_API_KEY
  if (apiUrl && adminKey) {
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 12000)
      const res = await fetch(apiUrl.replace(/\/$/, '') + '/admin/health', {
        headers: { 'X-Admin-Key': adminKey },
        signal: ctrl.signal,
      })
      clearTimeout(t)
      if (res.ok) {
        const body = await res.json()
        checks.push({ name: 'Railway (backend API)', status: 'ok', message: 'Reachable' })
        for (const c of (body.checks ?? []) as HealthCheck[]) checks.push(c)
      } else {
        checks.push({ name: 'Railway (backend API)', status: 'error', message: `Health endpoint HTTP ${res.status}` })
      }
    } catch {
      checks.push({ name: 'Railway (backend API)', status: 'error', message: 'Unreachable' })
    }
  } else {
    checks.push({
      name: 'Railway (backend API)',
      status: 'warning',
      message: !apiUrl ? 'NEXT_PUBLIC_API_URL not set' : 'ADMIN_API_KEY not set (backend checks hidden)',
    })
  }

  // Frontend / Vercel env
  checks.push(envCheck('SUPABASE_SERVICE_ROLE_KEY', 'Supabase service role key (Vercel)'))
  checks.push(envCheck('NEXT_PUBLIC_POSTHOG_KEY', 'PostHog'))
  checks.push(envCheck('NEXT_PUBLIC_VAPI_PUBLIC_KEY', 'Vapi public key'))

  // Webhook queue health (read directly from Supabase)
  const since = new Date(Date.now() - 86400000).toISOString()
  const { data: failedWebhooks, count: failCount } = await supabase
    .from('webhook_events')
    .select('id, last_error, created_at', { count: 'exact' })
    .eq('status', 'failed')
    .gte('created_at', since)
    .order('created_at', { ascending: false })
    .limit(5)

  const { count: pendingCount } = await supabase
    .from('webhook_events')
    .select('id', { count: 'exact' })
    .eq('status', 'pending')
    .lte('next_retry_at', new Date().toISOString())
    .limit(1)

  return Response.json({
    checks,
    webhook_failures_24h: failCount ?? 0,
    recent_failures: (failedWebhooks ?? []).map(w => ({ id: w.id, error: w.last_error, at: w.created_at })),
    stuck_webhooks: pendingCount ?? 0,
  })
}
