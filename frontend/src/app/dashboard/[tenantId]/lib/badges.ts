export function urgBadgeClass(u?: string): string {
  switch (u?.toLowerCase()) {
    case 'hot':
    case 'high':   return 'db-urg-hot'
    case 'warm':
    case 'medium': return 'db-urg-warm'
    case 'cold':
    case 'low':    return 'db-urg-cold'
    default:       return 'db-urg-none'
  }
}

const STATUS_VARIANTS: Record<string, string> = {
  // leads
  new: 'warn',
  contacted: 'info',
  booked: 'success',
  converted: 'success',
  // subscription
  active: 'success',
  canceling: 'warn',
  past_due: 'danger',
  // appointments
  confirmed: 'success',
  upcoming: 'success',
  cancelled: 'danger',
  canceled: 'danger',
  past: 'neutral',
  // invoices
  paid: 'success',
  open: 'warn',
  void: 'neutral',
  uncollectible: 'danger',
}

export function statusBadgeClass(status?: string): string {
  const variant = STATUS_VARIANTS[status?.toLowerCase() ?? ''] ?? 'neutral'
  return `db-badge db-badge--${variant}`
}

// Call disposition (AI Overflow & Call Routing). Present only on routed calls.
const DISPOSITION_VARIANTS: Record<string, string> = {
  answered_by_ai:      'neutral',
  overflow_handled:    'info',
  transferred:         'success',
  transfer_unanswered: 'warn',
  callback_requested:  'info',
  urgent_escalated:    'danger',
  failed:              'danger',
  missed:              'warn',
}

const DISPOSITION_LABELS: Record<string, string> = {
  answered_by_ai:      'Answered by AI',
  overflow_handled:    'Overflow',
  transferred:         'Transferred',
  transfer_unanswered: 'Transfer unanswered',
  callback_requested:  'Callback requested',
  urgent_escalated:    'Urgent',
  failed:              'Failed',
  missed:              'Missed',
}

export function dispositionBadgeClass(disposition?: string): string {
  const variant = DISPOSITION_VARIANTS[disposition?.toLowerCase() ?? ''] ?? 'neutral'
  return `db-badge db-badge--${variant}`
}

export function dispositionLabel(disposition?: string): string {
  if (!disposition) return ''
  return DISPOSITION_LABELS[disposition.toLowerCase()] ?? disposition
}
