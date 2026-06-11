import { ReactNode } from 'react'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="db-loading">
      <span className="db-loading-spinner" />
      {label}
    </div>
  )
}

export function EmptyState({ icon, title, sub }: { icon?: ReactNode; title: string; sub?: string }) {
  return (
    <div className="db-empty-v2">
      {icon && <div className="db-empty-icon">{icon}</div>}
      <div className="db-empty-v2-title">{title}</div>
      {sub && <div className="db-empty-v2-sub">{sub}</div>}
    </div>
  )
}
