import type { NextRequest } from 'next/server'
import { requireAdmin } from '@/lib/admin-auth'

export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req)
  if (auth instanceof Response) return auth

  const { data: adminRow } = await auth.supabase
    .from('admin_users')
    .select('user_id, email, created_at')
    .eq('user_id', auth.userId)
    .single()

  return Response.json({ user_id: auth.userId, email: adminRow?.email ?? '' })
}
