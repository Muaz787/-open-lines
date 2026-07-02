import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — manually set a tenant's plan (comp grant of plan-gated features)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth
  const body = await req.json().catch(() => ({}))

  const res = await fetch(`${BACKEND}/admin/tenants/${id}/plan`, {
    method: 'PATCH',
    headers: { 'x-admin-key': ADMIN_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan: body.plan ?? null }),
  })

  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }))
    return Response.json({ error: b?.detail ?? 'Failed' }, { status: res.status })
  }

  const data = await res.json()
  await logAdminAction(supabase, userId, 'tenant_plan_set', 'tenant', id)
  return Response.json(data)
}
