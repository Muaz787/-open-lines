import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — rebuild and re-push every tenant's Vapi assistant config.
//
// The repair path after something wrote bad values into live assistants. The
// scheduled cron did exactly that: with its own APP_BACKEND_URL and
// VAPI_SERVER_SECRET, its daily re-crawl pushed unreachable tool URLs and a
// secret the web service rejects, breaking caller lookup and booking mid-call.
// This re-pushes from THIS service, which has the correct values.
//
// Idempotent — a tenant whose config is already right is rewritten identically.
export async function POST(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { supabase, userId } = auth

  // Long-running: one sequential Vapi round-trip per tenant.
  const res = await fetch(`${BACKEND}/admin/reprompt-all`, {
    method: 'POST',
    headers: { 'x-admin-key': ADMIN_KEY },
  })

  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    return Response.json({ error: data.detail ?? 'Rebuild failed' }, { status: res.status })
  }

  await logAdminAction(supabase, userId, 'reprompt_all', 'tenant', 'all')
  return Response.json(data)
}
