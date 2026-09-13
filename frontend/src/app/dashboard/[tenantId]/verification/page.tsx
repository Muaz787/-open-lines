'use client'

/**
 * Irish business verification, on the dashboard.
 *
 * A wrapper. The implementation lives in components/BusinessVerification so the
 * onboarding wizard and this route cannot drift into two regulatory forms. This
 * route stays because it is where a customer returns for corrections, for an
 * action_required request, or simply because they closed onboarding.
 */
import { useParams } from 'next/navigation'
import BusinessVerification from '@/components/BusinessVerification'

export default function VerificationPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  return <BusinessVerification tenantId={tenantId} />
}
