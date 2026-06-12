import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

type CheckStatus = 'ok' | 'warning' | 'error'
interface HealthCheck { name: string; status: CheckStatus; message: string }

function envCheck(name: string, label: string): HealthCheck {
  const val = process.env[name]
  return {
    name: label,
    status: val ? 'ok' : 'error',
    message: val ? 'Configured' : 'Missing — set ' + name,
  }
}

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase } = auth
  const checks: HealthCheck[] = []

  // Supabase connection
  try {
    const { error } = await supabase.from('admin_users').select('user_id').limit(1)
    checks.push({
      name: 'Supabase',
      status: error ? 'error' : 'ok',
      message: error ? error.message : 'Connected',
    })
  } catch (e) {
    checks.push({ name: 'Supabase', status: 'error', message: String(e) })
  }

  // Env var checks
  checks.push(envCheck('SUPABASE_SERVICE_ROLE_KEY', 'Supabase service role key'))
  checks.push(envCheck('ADMIN_API_KEY', 'Admin API key'))
  checks.push(envCheck('NEXT_PUBLIC_POSTHOG_KEY', 'PostHog'))
  checks.push(envCheck('NEXT_PUBLIC_VAPI_PUBLIC_KEY', 'Vapi public key'))

  // Backend reachability
  const apiUrl = process.env.NEXT_PUBLIC_API_URL
  if (apiUrl) {
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 5000)
      const res = await fetch(apiUrl.replace(/\/$/, '') + '/docs', { signal: ctrl.signal })
      clearTimeout(t)
      checks.push({ name: 'Backend API', status: res.ok ? 'ok' : 'warning', message: res.ok ? 'Reachable' : `HTTP ${res.status}` })
    } catch {
      checks.push({ name: 'Backend API', status: 'error', message: 'Unreachable' })
    }
  } else {
    checks.push({ name: 'Backend API', status: 'warning', message: 'NEXT_PUBLIC_API_URL not set' })
  }

  // Recent webhook failures (last 24h)
  const since = new Date(Date.now() - 86400000).toISOString()
  const { data: failedWebhooks, count: failCount } = await supabase
    .from('webhook_events')
    .select('id, last_error, created_at', { count: 'exact' })
    .eq('status', 'failed')
    .gte('created_at', since)
    .order('created_at', { ascending: false })
    .limit(5)

  const { data: pendingWebhooks, count: pendingCount } = await supabase
    .from('webhook_events')
    .select('id', { count: 'exact' })
    .eq('status', 'pending')
    .lte('next_retry_at', new Date().toISOString())
    .limit(1)

  return Response.json({
    checks,
    webhook_failures_24h: failCount ?? 0,
    recent_failures: (failedWebhooks ?? []).map(w => ({
      id: w.id,
      error: w.last_error,
      at: w.created_at,
    })),
    stuck_webhooks: pendingCount ?? 0,
  })
}
