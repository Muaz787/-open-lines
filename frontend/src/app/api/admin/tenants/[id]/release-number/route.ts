import type { NextRequest } from 'next/server'
import { requireAdmin, logAdminAction } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// POST — release this tenant's phone number back to Twilio. IRREVERSIBLE.
//
// The caller must pass the number it expects to release, and the backend rejects
// the request unless it matches the tenant's current one. A mistyped tenant id
// then releases nothing, instead of destroying a different business's line.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const { supabase, userId } = auth

  const body = await req.json().catch(() => ({}))
  const confirmNumber = String(body?.confirm_number ?? '')
  if (!confirmNumber) {
    return Response.json({ error: 'confirm_number is required' }, { status: 400 })
  }

  const res = await fetch(
    `${BACKEND}/admin/tenants/${id}/release-number?confirm_number=${encodeURIComponent(confirmNumber)}`,
    { method: 'POST', headers: { 'x-admin-key': ADMIN_KEY } },
  )

  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    return Response.json({ error: data.detail ?? 'Release failed' }, { status: res.status })
  }

  await logAdminAction(supabase, userId, 'tenant_number_released', 'tenant', id)
  return Response.json(data)
}
