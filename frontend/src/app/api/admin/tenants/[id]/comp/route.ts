import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — comp / un-comp a tenant (billing_exempt)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth
  const body = await req.json().catch(() => ({}))
  const exempt = !!body.exempt

  const res = await fetch(`${BACKEND}/admin/tenants/${id}/comp`, {
    method: 'PATCH',
    headers: { 'x-admin-key': ADMIN_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ exempt }),
  })

  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }))
    return Response.json({ error: b?.detail ?? 'Failed' }, { status: res.status })
  }

  const data = await res.json()
  await logAdminAction(supabase, userId, exempt ? 'tenant_comped' : 'tenant_uncomped', 'tenant', id)
  return Response.json(data)
}
