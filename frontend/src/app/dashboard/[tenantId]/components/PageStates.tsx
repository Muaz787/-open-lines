import { ReactNode } from 'react'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="db-loading">
      <span className="db-loading-spinner" />
      {label}
    </div>
  )
}

// A request failed. Never shown as an empty list: failing isn't the same as having
// no data.
export function ErrorState({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return (
    <div className="db-empty-v2" role="alert">
      <div className="db-empty-v2-title">{title}</div>
      <div className="db-empty-v2-sub">This may be temporary. Your data hasn’t changed.</div>
      {onRetry && (
        <div style={{ marginTop: 12 }}>
          <button className="db-btn db-btn--ghost db-btn--sm" onClick={onRetry}>Try again</button>
        </div>
      )}
    </div>
  )
}

export function EmptyState({ icon, title, sub, action }: { icon?: ReactNode; title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="db-empty-v2">
      {icon && <div className="db-empty-icon">{icon}</div>}
      <div className="db-empty-v2-title">{title}</div>
      {sub && <div className="db-empty-v2-sub">{sub}</div>}
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  )
}
