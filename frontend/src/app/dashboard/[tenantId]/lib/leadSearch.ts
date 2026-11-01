// Search over the leads already loaded. Phone numbers match on digits alone, so
// "(647) 763" finds +16477633632.
interface Searchable {
  name?: string
  phone?: string
  summary?: string
}

export function matchesLead(lead: Searchable, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (`${lead.name ?? ''} ${lead.summary ?? ''}`.toLowerCase().includes(q)) return true
  const digits = q.replace(/\D/g, '')
  return digits.length > 0 && (lead.phone ?? '').replace(/\D/g, '').includes(digits)
}
