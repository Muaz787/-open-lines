// What one call said about itself. Read only from the call row: the lead's summary
// and rating belong to the caller and are overwritten by their newest call, so
// borrowing them made every call from a caller look like the last one.

export interface CallInsightSource {
  summary?: string | null
  urgency?: string | null
  key_details?: Record<string, unknown> | null
  suggested_next_step?: string | null
}

export interface CallInsight {
  summary: string
  hasSummary: boolean
  urgency: 'hot' | 'warm' | 'cold' | null
  keyDetails: [string, string][]
  nextStep: string | null
}

const RATINGS = ['hot', 'warm', 'cold'] as const

export function callInsight(call: CallInsightSource): CallInsight {
  const summary = (call.summary ?? '').trim()
  const u = (call.urgency ?? '').trim().toLowerCase()
  const urgency = (RATINGS as readonly string[]).includes(u) ? (u as CallInsight['urgency']) : null
  const keyDetails = Object.entries(call.key_details ?? {})
    .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== '')
    .map(([k, v]): [string, string] => [k.replace(/_/g, ' '), String(v)])
  return {
    summary: summary || 'No summary saved for this call',
    hasSummary: summary !== '',
    urgency,
    keyDetails,
    nextStep: (call.suggested_next_step ?? '').trim() || null,
  }
}

// The quality filter's key for a call: its own rating, or 'unknown'.
export function callQuality(call: CallInsightSource): string {
  return callInsight(call).urgency ?? 'unknown'
}
