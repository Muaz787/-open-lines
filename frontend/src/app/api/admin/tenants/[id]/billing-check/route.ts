import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ADMIN_KEY = process.env.ADMIN_API_KEY ?? ''

// GET — read-only: the account state and live Stripe result behind the billing labels
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { id } = await params
  const res = await fetch(`${BACKEND}/admin/tenants/${id}/billing-check`, {
    headers: { 'x-admin-key': ADMIN_KEY },
  })

  if (!res.ok) return Response.json({ error: 'Billing check failed' }, { status: res.status })
  return Response.json(await res.json())
}
