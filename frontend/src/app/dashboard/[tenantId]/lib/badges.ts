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
