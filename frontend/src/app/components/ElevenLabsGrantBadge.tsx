import Image from 'next/image'

/* ElevenLabs Grants badge.
 *
 * Displaying this, linked back to elevenlabs.io/startup-grants, is a CONDITION of
 * the grant Openlines.ai received — an obligation to keep, not decoration to prune
 * in a future cleanup.
 *
 * It lives in its own component because the site has four separate footers: the
 * shared SiteFooter plus hand-rolled ones on the homepage, /docs and /support.
 * Adding the badge to SiteFooter alone left it off the homepage — the page most
 * likely to be checked. One component means the next footer that gets written can
 * drop it in, and none of the four can drift.
 *
 * Assets are self-hosted rather than hotlinked from eleven-public-cdn: if that URL
 * ever moves, the logo breaks silently and our compliance with it.
 *
 * Both variants ship because the footer inherits --bg and flips with
 * [data-theme="dark"]; CSS in globals.css picks one. Explicit width/height keeps
 * CLS at zero on every page that renders a footer.
 */
export default function ElevenLabsGrantBadge() {
  return (
    <a
      href="https://elevenlabs.io/startup-grants"
      target="_blank"
      rel="noopener noreferrer"
      className="ft-grant"
      aria-label="ElevenLabs Grants"
    >
      <Image
        src="/elevenlabs-grants-light.webp"
        alt="ElevenLabs Grants"
        width={170}
        height={15}
        className="ft-grant-light"
      />
      <Image
        src="/elevenlabs-grants-dark.webp"
        alt="ElevenLabs Grants"
        width={170}
        height={15}
        className="ft-grant-dark"
      />
    </a>
  )
}
