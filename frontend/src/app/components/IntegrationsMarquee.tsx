'use client'

// Infinite left-to-right marquee of the tools OpenLines integrates with.
// Pure CSS animation (transform-only, GPU-friendly); pauses on hover and
// freezes for users who prefer reduced motion — see .mq-* rules in globals.css.

const INTEGRATIONS: { name: string; src: string }[] = [
  { name: 'Google Calendar',     src: '/integrations/google-calendar.svg' },
  { name: 'Microsoft Outlook',   src: '/integrations/outlook.svg' },
  { name: 'Square',              src: '/integrations/square.svg' },
  { name: 'Square Appointments', src: '/integrations/square-appointments.svg' },
  { name: 'Stripe',              src: '/integrations/stripe.svg' },
  { name: 'HubSpot',             src: '/integrations/hubspot.svg' },
  { name: 'Slack',               src: '/integrations/slack.svg' },
]

// One visual group is the list doubled so a single group is wide enough to span
// the viewport; two identical groups in the track make the loop seamless.
const GROUP = [...INTEGRATIONS, ...INTEGRATIONS]

function Group({ hidden = false }: { hidden?: boolean }) {
  return (
    <ul className="mq-group" aria-hidden={hidden || undefined}>
      {GROUP.map((it, i) => (
        <li key={`${it.name}-${i}`} className="mq-item">
          <span className="mq-chip">
            {/* plain img: tiny static SVGs, fixed CSS size = no layout shift.
                next/image doesn't optimize SVGs, so it'd add config for no gain. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={it.src} alt="" width={32} height={32} loading="lazy" draggable={false} />
          </span>
          <span className="mq-name">{it.name}</span>
        </li>
      ))}
    </ul>
  )
}

export default function IntegrationsMarquee() {
  return (
    <div className="marquee" role="marquee" aria-label="Integrations">
      <div className="mq-track">
        <Group />
        <Group hidden />
      </div>
    </div>
  )
}
