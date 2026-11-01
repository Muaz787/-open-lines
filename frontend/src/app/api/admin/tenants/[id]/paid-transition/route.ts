import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — allow, or stop allowing, a complimentary or manual account to buy a plan
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth
  const body = await req.json().catch(() => ({}))
  const allow = !!body.allow

  const res = await fetch(`${BACKEND}/admin/tenants/${id}/paid-transition`, {
    method: 'PATCH',
    headers: { 'x-admin-key': ADMIN_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ allow }),
  })

  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }))
    return Response.json({ error: b?.detail ?? 'Failed' }, { status: res.status })
  }

  await logAdminAction(supabase, userId, allow ? 'paid_transition_allowed' : 'paid_transition_closed', 'tenant', id)
  return Response.json(await res.json())
}
