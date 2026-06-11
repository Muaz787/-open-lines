export function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export function formatCallDate(iso: string): string {
  const d = new Date(iso)
  const date = d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
  return `${date} · ${time}`
}

export function formatApptDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-CA', {
    weekday: 'short', month: 'short', day: 'numeric',
  }) + ' · ' + d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
}

export function formatDuration(secs?: number): string {
  if (!secs) return '—'
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

export function initials(name?: string, phone?: string): string {
  if (name) return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  return (phone ?? '??').slice(-2)
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
