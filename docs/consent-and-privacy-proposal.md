# Consent and privacy-policy proposal

**Status: draft for review. Nothing here is implemented.** This is an engineering
proposal, not legal advice, and it does not establish compliance with any law.
Questions for counsel are marked **[Counsel]**.

## What runs today

Everything below is loaded for every visitor on every route, including the
authenticated dashboard, from `frontend/src/app/layout.tsx` and
`frontend/src/instrumentation-client.ts`. No banner, consent state, Google Consent
Mode or opt-out exists in the code.

| Tool | Identifier | What it does | Consent gate |
|---|---|---|---|
| Google Analytics 4 | `G-06VMJV17HC` | Page and event analytics; first-party cookies | None |
| Google Ads tag | `AW-18323006317` | Conversions; stores click IDs in `_gcl_*` cookies | None |
| OpenAI Ads pixel | `MuZXtrxLm9EAMNURQggmNL` | Page views and `trial_started` | None |
| OpenAI Conversions API | Backend, `services/openai_ads.py` | Server-side `trial_started`, keyed on tenant id | None |
| PostHog | `NEXT_PUBLIC_POSTHOG_KEY` | Product analytics; `identifyUser` sends email, tenant id and business name for signed-in users. Autocapture and session recording are off | None |
| Vercel Analytics | `@vercel/analytics` | Site analytics. Confirm its current cookie behaviour | None |
| First-touch record | `ol_first_touch` in localStorage | UTM values, referrer, landing page; written only when PostHog is configured | None |
| Conversion de-duplication | `ol_ads_trial_sent:*`, `ol_ads_trial_pending:*` in localStorage (new) | Holds a tenant id per browser | None |

## Statements that do not match the code

| Location | Current text or gap | Problem |
|---|---|---|
| `privacy/page.tsx:112` | "We do not use advertising or cross-site tracking cookies." | Google Ads and OpenAI Ads tags run site-wide |
| `privacy/page.tsx:112` | Names PostHog as the analytics tool | Omits GA4, Google Ads, OpenAI Ads and Vercel Analytics |
| `subprocessors/page.tsx` | Google listed for Calendar only; OpenAI for language models only | Neither advertising or analytics use is listed |
| `privacy/page.tsx:10` | `LAST_UPDATED = 'July 10, 2026'` | Must change with any edit |

The unmerged `pipeda-legal-docs` branch has no cookie or advertising disclosure of
its own, so it needs the same review before merging.

These statements appear accurate and should stay, provided the tag scope below is
kept: "We do not use caller data for advertising" and "We do not sell personal data
to third parties". **[Counsel]** Confirm the second one holds under US state privacy
laws that treat some ad-related sharing as a sale or sharing.

## Proposed implementation

### 1. Limit where advertising tags run

Move the Google Ads and OpenAI tags out of the root layout and into the marketing
and onboarding routes. The dashboard shows leads and call data, and an advertising
tag has no need to run there. One dependency: the delayed Irish conversion fires
from the dashboard, so it would have to move to `/onboarding` or use Consent-aware
loading on that one event.

### 2. Add a consent layer

Create one small client module that stores the choice in a first-party cookie, and
is the only thing that loads optional tools.

| Category | Tools | Before a choice |
|---|---|---|
| Strictly necessary | Sign-in session, Stripe, signup resume keys | Always on |
| Analytics | GA4, PostHog, Vercel Analytics | Off in opt-in regions |
| Advertising | Google Ads, OpenAI pixel, OpenAI Conversions API | Off in opt-in regions |

Banner: equally prominent **Accept** and **Reject** buttons, a **Manage** panel, and
a permanent "Cookie settings" footer link so a choice can be changed later.

### 3. Set Google Consent Mode before any tag configuration

```js
gtag('consent', 'default', {
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
  analytics_storage: 'denied',
  wait_for_update: 500,
  region: [/* opt-in regions, see below */],
});
gtag('js', new Date());
gtag('config', GA_ID);
gtag('config', GADS_ID);
```

On a choice, call `gtag('consent', 'update', {...})`. The `gtag` conversion call in
`lib/adsConversion.ts` does not need to change, because gtag applies consent state to
it.

### 4. Gate tools that Consent Mode does not cover

Consent Mode only governs Google tags.

- **OpenAI pixel:** load it only after advertising consent. Check with OpenAI whether
  it has a consent signal of its own.
- **OpenAI Conversions API:** the browser must tell the backend the choice, for
  example an `ads_consent` field on `/onboarding/provision`, and the backend must skip
  the event without it. Without this, the server event ignores the banner.
- **PostHog:** start it opted out where consent is required, and call
  `opt_in_capturing()` on acceptance.
- **Vercel Analytics:** render it only after analytics consent, unless counsel accepts
  it as non-identifying.

### 5. Decide the default for each region **[Counsel]**

| Region | Starting proposal |
|---|---|
| Ireland, EEA, UK | Opt-in. Nothing optional loads before a choice |
| Quebec | Treat as opt-in pending advice on Law 25 |
| Rest of Canada | Clear notice with a working opt-out; counsel to confirm for PIPEDA |
| United States | Notice with opt-out; counsel to confirm by state, including Global Privacy Control |

Denying everywhere by default is the simplest option and reports the fewest
conversions. Region rules rely on Vercel's country header and IP lookup, which can be
wrong near borders. Also for counsel: whether Google's EU user consent policy
requirements are met, and how long consent records must be kept.

### Expected effect on ad measurement

- With `ad_storage` denied, `_gcl_aw` is not written, so a click may not be linked to
  a later signup. `url_passthrough` can help within the session but changes URLs, so
  it needs its own review.
- Reported conversions will fall in opt-in regions, and Google may model some of them.
- Test with Tag Assistant's consent view before and after any change.

## Proposed policy wording for review

Replace the first paragraph of **6. Cookies & analytics** with:

> We use cookies and similar technologies for three purposes.
>
> **Essential.** These keep you signed in, secure your account and let you resume
> signup. The service cannot work without them.
>
> **Analytics.** We use PostHog, Google Analytics and Vercel Analytics to understand
> how our website and product are used. We do not enable session recording. When you
> are signed in, PostHog receives your email address, tenant ID and business name so
> we can understand how accounts use the product.
>
> **Advertising.** We use Google Ads and OpenAI Ads to measure whether our advertising
> leads to signups. These providers may set cookies or similar identifiers, receive
> your browser's details and IP address, and record that an ad click led to a page
> view or a started trial. We send a random account identifier so a signup is counted
> once. We do not send your name, email address or phone number with these conversion
> events. Depending on their own terms, these providers may use this information as
> described in their privacy policies.
>
> We do not use caller data, call transcripts or calendar data for advertising.
>
> You can change your choices at any time using **Cookie settings** in the footer of
> our website. You can also block or delete cookies in your browser settings; disabling
> essential cookies may affect how the dashboard works.

The paragraph above assumes the consent layer and "Cookie settings" link exist.
**Publish it with that work, not before.** If the banner will take time, an interim
correction that removes the false sentence and names the tools is possible, but it
must not mention controls that do not exist yet.

Add to `subprocessors/page.tsx`, subject to counsel's view on whether these providers
are sub-processors or independent controllers:

| Name | Purpose | Location |
|---|---|---|
| Google | Website analytics and advertising measurement | United States |
| OpenAI | Advertising measurement | United States |

Check `dpa/page.tsx` and any customer-facing sub-processor notice duties at the same
time.

## Decisions needed

1. Default behaviour by region. **[Counsel]**
2. Whether advertising tags leave the dashboard.
3. Whether to use a consent management platform or a small in-house banner. A Google
   certified platform may be required for EEA and UK advertising. **[Counsel]**
4. Whether to pause EEA and UK ad targeting until consent ships.
5. Final policy wording. **[Counsel]**
