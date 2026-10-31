import type { AccountView, Labelled } from '../lib/accountState'

function Item({ name, value }: { name: string; value: Labelled }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--db-muted)' }}>
      {name}
      <span className={`db-badge db-badge--${value.tone}`}>{value.label}</span>
    </span>
  )
}

// Phone line, features and subscription, always named, so one is never read as
// standing for the others.
export function AccountStatus({ view }: { view: AccountView }) {
  if (!view.subscription.label) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }} data-testid="account-status">
      <Item name="Phone line" value={view.phoneLine} />
      <Item name="Features" value={view.features} />
      <Item name="Subscription" value={view.subscription} />
    </div>
  )
}
