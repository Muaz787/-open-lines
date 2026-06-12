import type { NextRequest } from 'next/server'
import { createAdminSupabase } from './supabase-admin'

export function maskPhone(phone: string | null | undefined): string {
  if (!phone) return '—'
  const p = phone.replace(/\s/g, '')
  if (p.length < 6) return '***'
  return p.slice(0, 2) + '*'.repeat(Math.max(0, p.length - 6)) + p.slice(-4)
}

export async function requireAdmin(
  req: NextRequest,
): Promise<{ userId: string; supabase: ReturnType<typeof createAdminSupabase> } | Response> {
  const token = req.headers.get('Authorization')?.replace('Bearer ', '').trim()
  if (!token) return new Response('Unauthorized', { status: 401 })

  let supabase: ReturnType<typeof createAdminSupabase>
  try {
    supabase = createAdminSupabase()
  } catch {
    return new Response('Admin client not configured', { status: 503 })
  }

  const { data: { user }, error } = await supabase.auth.getUser(token)
  if (error || !user) return new Response('Unauthorized', { status: 401 })

  const { data: adminRow } = await supabase
    .from('admin_users')
    .select('user_id')
    .eq('user_id', user.id)
    .single()

  if (!adminRow) return new Response('Forbidden', { status: 403 })

  // Fire-and-forget audit log
  void supabase
    .from('admin_audit_logs')
    .insert({ admin_user_id: user.id, action: 'api_access', metadata: { path: req.nextUrl.pathname } })

  return { userId: user.id, supabase }
}

export async function logAdminAction(
  supabase: ReturnType<typeof createAdminSupabase>,
  adminUserId: string,
  action: string,
  resourceType?: string,
  resourceId?: string,
): Promise<void> {
  void supabase
    .from('admin_audit_logs')
    .insert({ admin_user_id: adminUserId, action, resource_type: resourceType, resource_id: resourceId })
}
