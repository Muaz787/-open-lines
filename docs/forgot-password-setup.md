# Forgot Password — Setup & Operations

Self-serve password recovery for OpenLines.ai, built on **Supabase Auth's native
recovery** (one-time, expiring, rate-limited links). No custom backend, no custom
tokens. This doc covers the one-time dashboard configuration plus testing and
rollback.

> Provisioning, tenant ownership, and `verify_tenant_owner` are **not** involved in
> this flow. Do not change them to support password reset.

---

## How it works

1. `/login` shows a **"Forgot your password?"** link.
2. `/forgot-password` collects an email and calls
   `supabase.auth.resetPasswordForEmail(email, { redirectTo: <origin>/reset-password })`.
   It always shows the same generic success message (no account enumeration).
3. Supabase emails a recovery link. Clicking it lands on `/reset-password`, where
   the supabase-js client auto-exchanges the recovery token into a session
   (`PASSWORD_RECOVERY`).
4. The user sets a new password via `supabase.auth.updateUser({ password })`, then
   **Continue to Dashboard** reuses the existing routing:
   `user_metadata.tenant_id` → `/dashboard/{tenantId}`, else admin probe → `/admin`.

**Pages/files:**
- `frontend/src/app/login/page.tsx` — added the link (login flow otherwise unchanged)
- `frontend/src/app/forgot-password/page.tsx` — new
- `frontend/src/app/reset-password/page.tsx` — new

---

## 1. Supabase — Site URL

**Dashboard → Authentication → URL Configuration → Site URL**

Set to your canonical production origin (a single value):

```
https://www.openlines.ai
```

> `https://openlines.ai/` currently redirects to `www`, so `www` is the canonical
> origin. If you flip the canonical host later, update this to match.

---

## 2. Supabase — Redirect URLs (allowlist)

**Dashboard → Authentication → URL Configuration → Redirect URLs**

Add **all** of these. If the reset target isn't allowlisted, Supabase ignores
`redirectTo` and sends the user to the Site URL instead (the reset page never loads):

```
https://www.openlines.ai/reset-password
https://openlines.ai/reset-password
http://localhost:3000/reset-password
```

Optional — to test resets on a Vercel preview, also add that preview's URL, e.g.:

```
https://<branch>-openlines.vercel.app/reset-password
```

---

## 3. Environment variables

**None required.** The pages derive the redirect base from `window.location.origin`,
so localhost and production both work without configuration.

- *Optional:* `NEXT_PUBLIC_SITE_URL` (e.g. `https://www.openlines.ai`) forces a fixed
  base regardless of the current origin. If unset, the runtime origin is used.

---

## 4. Resend SMTP (auth emails from `no-reply@openlines.ai`)

By default, Supabase Auth uses its **built-in sender** (low rate limit, often flagged
as spam). Point it at Resend so recovery emails come from our own domain. This only
changes the **auth** sender — the backend's transactional Resend usage (call
summaries, trial reminders) is a separate path and is unaffected.

**Steps (do these in the dashboards; never commit the key):**

1. **Resend** → confirm the `openlines.ai` domain is **verified** (SPF + DKIM green).
   It should already be, since call-summary emails send from it. If not, add the DNS
   records Resend lists and wait for verification.
2. **Resend** → API Keys → create/reuse a key with **send** permission (`re_...`).
3. **Supabase** → **Authentication → Emails → SMTP Settings** → **Enable Custom SMTP**:

   | Field          | Value                          |
   | -------------- | ------------------------------ |
   | Sender email   | `no-reply@openlines.ai`        |
   | Sender name    | `OpenLines`                    |
   | Host           | `smtp.resend.com`              |
   | Port           | `465` (SSL) — or `587` (STARTTLS) |
   | Username       | `resend`                       |
   | Password       | *Resend API key — do not store here in git* |
   | Rate limit     | leave default                  |

4. **Save**, then send yourself a test reset and confirm it arrives from
   `no-reply@openlines.ai`.

> **Secret handling:** the Resend API key lives only in the Supabase SMTP password
> field. It must never appear in this repo, commits, or logs.

---

## 5. Reset email template

**Dashboard → Authentication → Emails → Reset Password**

**Subject:**

```
Reset your OpenLines password
```

**Message body (HTML):**

```html
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#1a1a1a">
  <!-- Replace the wordmark with <img src="https://www.openlines.ai/logo.png" .../> if you have a hosted logo -->
  <div style="font-size:18px;font-weight:600;letter-spacing:0.02em;margin-bottom:24px">open lines</div>

  <h1 style="font-size:20px;font-weight:600;margin:0 0 12px">Reset your password</h1>
  <p style="font-size:15px;line-height:1.6;color:#444;margin:0 0 20px">
    We received a request to reset the password for your OpenLines account.
    Click the button below to choose a new password.
  </p>

  <a href="{{ .ConfirmationURL }}"
     style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;
            font-size:15px;font-weight:600;padding:12px 22px;border-radius:8px">
    Reset password
  </a>

  <p style="font-size:13px;line-height:1.6;color:#888;margin:24px 0 0">
    This link expires in 1 hour and can only be used once.
  </p>
  <p style="font-size:13px;line-height:1.6;color:#888;margin:8px 0 0">
    If you didn't request a password reset, you can safely ignore this email —
    your password won't change.
  </p>
</div>
```

- `{{ .ConfirmationURL }}` is Supabase's recovery-link variable — keep it exactly.
- Email clients can't render the inline SVG brand mark; use a hosted PNG `<img>` if
  you have one, otherwise the text wordmark is fine.

---

## 6. Security defaults (verify ON — do not weaken)

**Dashboard → Authentication → Settings**

- Email provider enabled.
- Recovery links: one-time use, expiring (default 3600s / 1 hour).
- Rate limiting: default.
- No custom reset tokens, no changes to existing authentication.

The app never reveals whether an email exists — `/forgot-password` always shows the
same generic confirmation.

---

## 7. Testing checklist

- [ ] Existing email/password **login still works** and routes correctly.
- [ ] `/login` shows **"Forgot your password?"** → goes to `/forgot-password`.
- [ ] **Real account:** request reset → email arrives (from `no-reply@openlines.ai`
      once SMTP is set) → link opens `/reset-password` → set new password →
      "Password updated successfully" → **Continue to Dashboard** lands on
      `/dashboard/{tenantId}`.
- [ ] **Immediately log in** with the new password — succeeds.
- [ ] **Non-existent / mistyped email:** same generic "If an account exists…" message.
- [ ] **Expired / already-used link:** shows "This link is invalid or has expired" +
      "Request a new link" (no crash).
- [ ] **Admin account:** reset → Continue routes to `/admin`.
- [ ] Tenant and admin routing unchanged elsewhere.

**Manual verification order:**
1. Deploy lands on Vercel; confirm the login link renders.
2. Apply Site URL + Redirect URLs (sections 1–2) and SMTP (section 4) — until the
   redirect URLs are allowlisted, links bounce to the Site URL.
3. Run the real-account flow end to end.
4. Test one expired link (request two, use the first, then click it again).

---

## 8. Rollback

- **Code:** additive and isolated.
  - Full revert: `git revert <merge-commit>` and push — the login link disappears and
    the two pages 404; nothing else changes.
  - No-deploy hotfix: remove the `<Link href="/forgot-password">` block in
    `login/page.tsx` to hide the entry point while leaving the pages dormant.
- **SMTP:** if Resend misbehaves, toggle **Disable Custom SMTP** in Supabase Auth —
  it instantly falls back to the default sender; auth keeps working.
- **Email template:** each Supabase email template has a **Reset to default** option.
- **No database migration** to undo, and no provisioning/authz changes — there is no
  data-state to roll back.
