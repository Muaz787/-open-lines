import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — buy this tenant a new phone number after theirs was reclaimed.
//
// Costs money (a real number, billed monthly). The backend refuses outright if
// the tenant already has one, so a double-click can't quietly buy a second.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth

  const res = await fetch(`${BACKEND}/admin/tenants/${id}/reprovision-number`, {
    method: 'POST',
    headers: { 'x-admin-key': ADMIN_KEY },
  })

  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    return Response.json({ error: data.detail ?? 'Provisioning failed' }, { status: res.status })
  }

  await logAdminAction(supabase, userId, 'tenant_number_reprovisioned', 'tenant', id)
  return Response.json(data)
}
