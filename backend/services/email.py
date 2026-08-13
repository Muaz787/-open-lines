"""
Transactional & lifecycle email via Resend.

Every email shares one branded ("Warm Studio") layout, ships a plain-text
alternative, sets reply-to to support@, and carries the company's physical
mailing address in the footer (CASL). Promotional emails (the trial nudges)
additionally include an unsubscribe link + List-Unsubscribe headers; callers
must skip them when the tenant has marketing_unsubscribed_at set.

All interpolated values are HTML-escaped — call analysis, caller names and
business names are user/AI-supplied and must not be trusted as markup.
"""

import hashlib
import hmac
import html
import logging
import os
import re

from urllib.parse import urlparse

import resend

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM    = os.getenv("EMAIL_FROM", "notifications@openlines.ai")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@openlines.ai")

_PROD_FRONTEND = "https://openlines.ai"
_PROD_BACKEND  = "https://backend-production-71174.up.railway.app"
_LOCAL_HOSTS   = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _resolve_public_url(env_var: str, default: str) -> str:
    """Normalize a public URL from env, and refuse a LOCAL one when this process
    is actually sending mail.

    Every link in every email is built from these two constants. A local value is
    harmless in dev — without RESEND_API_KEY, _send() no-ops — but in production
    it mails dead localhost links to real customers.

    That has now happened TWICE, on two different Railway services. The web
    service and the scheduled cron service have INDEPENDENT env vars, so fixing
    FRONTEND_URL on one leaves the other broken, and the two send different
    emails: welcome from the web service, trial reminders from the cron. The
    second failure was invisible until a customer clicked a reminder.

    So: if Resend is configured we are sending real mail to real people, and a
    localhost link is a misconfiguration rather than an intent. Fall back to the
    production default and log loudly rather than mail a link that cannot work.
    """
    raw = (os.getenv(env_var, default) or "").strip()
    # A var that exists but is blank is easy to create in the Railway UI, and
    # would otherwise build the string "https://" — worse than no link at all.
    if not raw:
        raw = default
    url  = raw if raw.startswith("http") else f"https://{raw}"
    host = (urlparse(url).hostname or "").lower()

    if host in _LOCAL_HOSTS or host.endswith(".local"):
        if resend.api_key:
            logger.error(
                "%s is set to a local address (%s) on a process that sends real email — "
                "falling back to %s. Fix %s on THIS Railway service; the web service and "
                "the scheduled cron service have separate environment variables.",
                env_var, url, default, env_var,
            )
            return default
        logger.info(
            "%s is local (%s), but email sending is disabled here (no RESEND_API_KEY), "
            "so links are left pointing at the local dev server.",
            env_var, url,
        )
    return url


FRONTEND_URL = _resolve_public_url("FRONTEND_URL", _PROD_FRONTEND)
BACKEND_URL  = _resolve_public_url("APP_BACKEND_URL", _PROD_BACKEND)

COMPANY_NAME    = "Open Lines Technologies Inc."
COMPANY_ADDRESS = "201-5255 Yonge St, North York, ON M2N 6P4, Canada"

# Warm Studio palette
_INK    = "#001F3F"
_GREEN  = "#15803d"   # accessible green for text/links
_GREENF = "#1f7a4d"   # button fill
_MUTE   = "#5A6A7A"
_FAINT  = "#9AAABB"
_BG     = "#F4F2EC"
_CARD   = "#FFFFFF"
_BORDER = "#E7E2D6"

# HMAC key for unsubscribe tokens — reuse an existing secret so no new env is
# strictly required; override with EMAIL_UNSUBSCRIBE_SECRET if you want to rotate.
_UNSUB_SECRET = (
    os.getenv("EMAIL_UNSUBSCRIBE_SECRET")
    or os.getenv("VAPI_SERVER_SECRET")
    or resend.api_key
    or "openlines-unsubscribe-fallback"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _text(s: str) -> str:
    """Crude HTML → text for the plain-text alternative."""
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def unsubscribe_token(tenant_id: str) -> str:
    return hmac.new(_UNSUB_SECRET.encode(), tenant_id.encode(), hashlib.sha256).hexdigest()[:32]


def verify_unsubscribe_token(tenant_id: str, token: str) -> bool:
    if not tenant_id or not token:
        return False
    return hmac.compare_digest(unsubscribe_token(tenant_id), token)


def _unsubscribe_url(tenant_id: str) -> str:
    return f"{BACKEND_URL}/email/unsubscribe?t={tenant_id}&k={unsubscribe_token(tenant_id)}"


def _layout(
    *,
    heading: str,
    body_html: str,
    cta: str | None = None,
    cta_url: str | None = None,
    preheader: str = "",
    unsubscribe_url: str | None = None,
) -> str:
    """Wrap already-built (and already-escaped) body HTML in the shared shell."""
    cta_html = ""
    if cta and cta_url:
        cta_html = (
            f'<div style="margin:24px 0 4px"><a href="{_esc(cta_url)}" '
            f'style="display:inline-block;background:{_GREENF};color:#fff;text-decoration:none;'
            f'font-weight:600;font-size:14px;padding:12px 22px;border-radius:8px">{_esc(cta)} &rarr;</a></div>'
        )
    unsub_html = ""
    if unsubscribe_url:
        unsub_html = (
            f'<br><a href="{_esc(unsubscribe_url)}" style="color:{_FAINT};text-decoration:underline">'
            f'Unsubscribe from these emails</a>'
        )
    pre = (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_esc(preheader)}</div>'
        if preheader else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
{pre}
<table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:32px 16px"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%">
  <tr><td style="background:{_INK};border-radius:12px 12px 0 0;padding:18px 28px">
    <span style="color:#fff;font-size:15px;font-weight:700;letter-spacing:.01em">Open Lines</span>
    <span style="color:{_FAINT};font-size:13px"> &middot; AI receptionist</span>
  </td></tr>
  <tr><td style="background:{_CARD};border-radius:0 0 12px 12px;padding:28px;border:1px solid {_BORDER};border-top:none">
    <h1 style="font-size:20px;margin:0 0 14px;color:{_INK}">{_esc(heading)}</h1>
    {body_html}
    {cta_html}
  </td></tr>
  <tr><td style="padding:20px 28px;text-align:center">
    <p style="margin:0;font-size:11px;color:{_FAINT};line-height:1.7">
      {_esc(COMPANY_NAME)} &middot; {_esc(COMPANY_ADDRESS)}<br>
      <a href="mailto:{SUPPORT_EMAIL}" style="color:{_GREEN};text-decoration:none">{SUPPORT_EMAIL}</a>
      &middot; <a href="{FRONTEND_URL}" style="color:{_GREEN};text-decoration:none">openlines.ai</a>
      {unsub_html}
    </p>
  </td></tr>
</table></td></tr></table>
</body></html>"""


def _send(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    headers: dict | None = None,
) -> bool:
    """Single choke-point for sending. Never raises — returns success as a bool."""
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set — skipping email '%s' to %s", subject, to)
        return False
    payload: dict = {
        "from": f"Open Lines <{EMAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "html": html_body,
        "text": text_body if text_body is not None else _text(html_body),
        "reply_to": SUPPORT_EMAIL,
    }
    if headers:
        payload["headers"] = headers
    try:
        resend.Emails.send(payload)
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error("Email send failed to %s (%s): %s", to, subject, e)
        return False


# ---------------------------------------------------------------------------
# Owner call-activity notifications (operational — no unsubscribe)
# ---------------------------------------------------------------------------

def _kv_table(details: dict) -> str:
    # Skip blank values and generic placeholder keys (key1/key2/…) that older custom
    # tenants produced — they render as ugly "Key1"/empty rows in the email.
    rows = "".join(
        f"<tr><td style='padding:4px 0;color:{_MUTE};font-size:13px;width:150px'>{_esc(str(k).replace('_',' ').title())}</td>"
        f"<td style='padding:4px 0;color:{_INK};font-size:13px;font-weight:500'>{_esc(v)}</td></tr>"
        for k, v in (details or {}).items()
        if str(v).strip() and not re.fullmatch(r"key[\s_]*\d+", str(k).strip(), re.IGNORECASE)
    )
    return f"<table cellpadding='0' cellspacing='0' style='width:100%;margin:4px 0 8px'>{rows}</table>" if rows else ""


def _urgency_badge(urgency: str) -> str:
    u = (urgency or "unknown").lower()
    color = {"hot": "#e53e3e", "warm": "#dd6b20", "cold": "#3182ce"}.get(u, "#718096")
    bg    = {"hot": "#fff5f5", "warm": "#fffaf0", "cold": "#ebf8ff"}.get(u, "#f7fafc")
    return (
        f"<span style='display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;"
        f"font-weight:600;color:{color};background:{bg};border:1px solid {color}33'>{_esc(u.upper())}</span>"
    )


async def send_call_summary_email(
    to: str,
    business_name: str,
    analysis: dict,
    caller_number: str = "",
    tenant_id: str = "",
) -> bool:
    """New-call summary to the business owner."""
    caller_name = analysis.get("caller_name") or "Unknown"
    summary     = analysis.get("summary") or ""
    next_step   = analysis.get("suggested_next_step") or ""
    details     = analysis.get("key_details") or {}

    phone_line = f"<p style='margin:0 0 8px;font-size:13px;color:{_MUTE}'>📱 {_esc(caller_number)}</p>" if caller_number else ""
    next_block = (
        f"<p style='margin:14px 0 4px;font-size:13px;font-weight:600;color:{_INK}'>Suggested next step</p>"
        f"<p style='margin:0;font-size:13px;color:#444;line-height:1.6'>{_esc(next_step)}</p>"
    ) if next_step else ""

    body = f"""
      <p style="margin:0 0 2px;font-size:16px;font-weight:700;color:{_INK}">👤 {_esc(caller_name)}</p>
      {phone_line}
      {_urgency_badge(analysis.get("urgency"))}
      {_kv_table(details)}
      <p style="margin:14px 0 4px;font-size:13px;font-weight:600;color:{_INK}">Summary</p>
      <p style="margin:0;font-size:13px;color:#444;line-height:1.6">{_esc(summary)}</p>
      {next_block}
    """
    html_body = _layout(
        heading=f"📞 New call — {business_name}",
        body_html=body,
        cta="View in dashboard",
        cta_url=(f"{FRONTEND_URL}/dashboard/{tenant_id}" if tenant_id else f"{FRONTEND_URL}/login"),
        preheader=f"{caller_name}: {summary[:90]}",
    )
    return _send(to=to, subject=f"📞 New call from {caller_name} — {business_name}", html_body=html_body)


async def send_deposit_received_email(
    to: str,
    business_name: str,
    caller_name: str,
    amount: str,
    service: str,
    caller_number: str = "",
    tenant_id: str = "",
) -> bool:
    """Deposit-paid notification to the owner (its own template, not a call summary)."""
    body = f"""
      <p style="margin:0 0 12px;font-size:14px;color:#444;line-height:1.6">
        A deposit was just paid and the appointment is confirmed.</p>
      {_kv_table({
          "Customer": caller_name or "Customer",
          **({"Phone": caller_number} if caller_number else {}),
          "Service": service or "—",
          "Amount": amount,
      })}
    """
    html_body = _layout(
        heading="💳 Deposit received",
        body_html=body,
        cta="View in dashboard",
        cta_url=(f"{FRONTEND_URL}/dashboard/{tenant_id}" if tenant_id else f"{FRONTEND_URL}/login"),
        preheader=f"{amount} deposit from {caller_name or 'a customer'} for {service}",
    )
    return _send(to=to, subject=f"💳 Deposit received — {amount} from {caller_name or 'a customer'}", html_body=html_body)


async def send_cancellation_email(
    to: str,
    business_name: str,
    caller_name: str,
    service: str,
    refunded: bool | None = None,
    amount: str | None = None,
    caller_number: str = "",
    tenant_id: str = "",
) -> bool:
    """Appointment-cancellation notice to the owner, with the refund outcome."""
    if amount is None:
        outcome = "No deposit was on file."
    elif refunded:
        outcome = f"Deposit of {amount} refunded to the customer."
    else:
        outcome = f"Deposit of {amount} forfeited (cancelled inside the refund window)."

    body = f"""
      <p style="margin:0 0 12px;font-size:14px;color:#444;line-height:1.6">
        An appointment was cancelled by the caller.</p>
      {_kv_table({
          "Customer": caller_name or "Customer",
          **({"Phone": caller_number} if caller_number else {}),
          "Service": service or "—",
          "Deposit": outcome,
      })}
      <p style="margin:12px 0 0;font-size:13px;color:{_MUTE}">
        Follow up with {_esc(caller_name or 'the customer')} if a rebooking is expected.</p>
    """
    html_body = _layout(
        heading="Appointment cancelled",
        body_html=body,
        cta="View in dashboard",
        cta_url=(f"{FRONTEND_URL}/dashboard/{tenant_id}" if tenant_id else f"{FRONTEND_URL}/login"),
        preheader=f"{service} cancelled — {outcome}",
    )
    return _send(to=to, subject=f"Appointment cancelled — {service or business_name}", html_body=html_body)


# ---------------------------------------------------------------------------
# Lifecycle emails to the account owner
# ---------------------------------------------------------------------------

async def send_welcome_email(
    to: str,
    business_name: str,
    tenant_id: str,
    phone_number: str = "",
    *,
    plan_name: str = "",
    trial_ends_at: str = "",   # already formatted, e.g. "August 16, 2026"
    amount_text: str = "",     # e.g. "$199 + tax"
) -> bool:
    """Sent right after onboarding provisions the tenant's live AI line.

    When the tenant started a card trial, this also carries the billing summary.
    Someone who just handed over a card is owed a written record of what they
    agreed to — the plan, the date, the amount — at the moment they agree to it,
    not first mention on day 3. Stripe raises a CA$0.00 invoice for the trial
    period but doesn't email it (and a $0 invoice would confuse more than it
    reassures), so this is the confirmation.

    It rides on the welcome email rather than being a second send, because two
    emails landing seconds apart reads as a system glitch.
    """
    num_line = (
        f"<p style='margin:0 0 4px;font-size:14px;color:{_INK}'>Your dedicated AI line: "
        f"<strong>{_esc(phone_number)}</strong></p>"
        if phone_number else ""
    )

    trial_block = ""
    if trial_ends_at:
        plan_row = (
            f"<tr><td style='padding:3px 0;font-size:13px;color:{_MUTE}'>Plan</td>"
            f"<td style='padding:3px 0;font-size:13px;color:{_INK};font-weight:600;text-align:right'>"
            f"{_esc(plan_name or 'Your plan')}</td></tr>"
            if plan_name else ""
        )
        amount_row = (
            f"<tr><td style='padding:3px 0;font-size:13px;color:{_MUTE}'>Then</td>"
            f"<td style='padding:3px 0;font-size:13px;color:{_INK};font-weight:600;text-align:right'>"
            f"{_esc(amount_text)} / month</td></tr>"
            if amount_text else ""
        )
        trial_block = f"""
      <table cellpadding="0" cellspacing="0" style="width:100%;margin:16px 0 4px;
             background:#F0FAF3;border:1px solid #CDEBD8;border-radius:10px">
        <tr><td style="padding:14px 16px">
          <table cellpadding="0" cellspacing="0" style="width:100%">
            <tr><td style="padding:0 0 6px;font-size:13px;color:{_MUTE}">Charged today</td>
                <td style="padding:0 0 6px;font-size:16px;color:{_GREEN};font-weight:700;text-align:right">$0.00</td></tr>
            {plan_row}
            <tr><td style="padding:3px 0;font-size:13px;color:{_MUTE}">Free until</td>
                <td style="padding:3px 0;font-size:13px;color:{_INK};font-weight:600;text-align:right">{_esc(trial_ends_at)}</td></tr>
            {amount_row}
          </table>
          <p style="margin:10px 0 0;font-size:12px;color:{_MUTE};line-height:1.6">
            Your card is saved but not charged. We&rsquo;ll email you before the first
            payment, and you can cancel from your dashboard any time before
            {_esc(trial_ends_at)} without being charged.</p>
        </td></tr>
      </table>
    """

    body = f"""
      <p style="margin:0 0 12px;font-size:14px;color:#444;line-height:1.6">
        {_esc(business_name)} is set up and your AI receptionist is answering calls 24/7. 🎉</p>
      {num_line}
      {trial_block}
      <p style="margin:16px 0 6px;font-size:14px;font-weight:600;color:{_INK}">A few things to try next:</p>
      <ul style="margin:0;padding-left:18px;font-size:14px;color:#444;line-height:1.7">
        <li>Call your new number and hear it in action</li>
        <li>Connect your calendar so it can book appointments</li>
        <li>Add your hours, services and FAQs to the knowledge base</li>
      </ul>
    """
    html_body = _layout(
        heading=f"Welcome to Open Lines, {business_name}",
        body_html=body,
        cta="Open your dashboard",
        cta_url=f"{FRONTEND_URL}/dashboard/{tenant_id}",
        preheader="Your AI receptionist is live and answering calls.",
    )
    return _send(to=to, subject=f"Welcome to Open Lines — {business_name} is live 🎉", html_body=html_body)


async def send_subscription_activated_email(
    to: str,
    business_name: str,
    tenant_id: str,
    plan: str,
) -> bool:
    """Confirmation when a paid plan activates."""
    plan_label = (plan or "").title() or "your"
    body = f"""
      <p style="margin:0 0 12px;font-size:14px;color:#444;line-height:1.6">
        Thanks for subscribing! {_esc(business_name)} is now on the
        <strong>{_esc(plan_label)}</strong> plan and your AI receptionist will keep
        answering, qualifying and booking without interruption.</p>
      <p style="margin:0;font-size:14px;color:#444;line-height:1.6">
        You can view invoices, usage and manage your plan any time from your dashboard.</p>
    """
    html_body = _layout(
        heading=f"You're on the {plan_label} plan 🎉",
        body_html=body,
        cta="Manage subscription",
        cta_url=f"{FRONTEND_URL}/dashboard/{tenant_id}/subscription",
        preheader=f"{business_name} is now on the {plan_label} plan.",
    )
    return _send(to=to, subject=f"You're subscribed — {business_name} is on {plan_label}", html_body=html_body)


# ---------------------------------------------------------------------------
# Internal ops alerts (to the founder — operational, no unsubscribe)
# ---------------------------------------------------------------------------
# Architecture & migration plan for replacing Vapi (see memory: vapi_migration_plan).
_VAPI_PLAN_URL = "https://claude.ai/code/artifact/65108f16-b8aa-48dc-b02e-c9bb910c8d3d"


async def send_platform_minutes_alert_email(*, total_minutes: int, threshold: int) -> bool:
    """One-time-per-threshold ops nudge to the founder when platform call-minutes
    cross the level where self-hosting the voice stack starts to pay off."""
    to = os.getenv("PLATFORM_ALERT_EMAIL", SUPPORT_EMAIL)
    body = f"""
      <p style="margin:0 0 14px;font-size:15px;color:{_INK}">
        Open Lines just crossed <strong>{total_minutes:,} call-minutes</strong> this
        billing period — past the <strong>{threshold:,}/month</strong> mark you set as
        the point to revisit replacing Vapi with a first-party voice stack.</p>
      <p style="margin:0 0 14px;font-size:14px;color:#444;line-height:1.6">
        This is the volume where self-hosting starts to pay off. The biggest lever is
        the TTS provider (e.g. ElevenLabs &rarr; Cartesia / Deepgram Aura), which can
        roughly halve per-minute cost. The full architecture &amp; migration plan —
        recommendation, cost model, and the zero-downtime phased rollout — is here:</p>
    """
    html_body = _layout(
        heading="📈 You hit the Vapi-migration threshold",
        body_html=body,
        cta="Open the migration plan",
        cta_url=_VAPI_PLAN_URL,
        preheader=f"{total_minutes:,} call-minutes — time to revisit the voice-stack plan.",
    )
    return _send(
        to=to,
        subject=f"Open Lines hit {threshold:,} call-minutes/month — revisit the Vapi migration",
        html_body=html_body,
    )


# ---------------------------------------------------------------------------
# Trial reminders (promotional — unsubscribe required; skip if opted out)
# ---------------------------------------------------------------------------

async def send_trial_reminder_email(
    to: str,
    business_name: str,
    kind: str,           # 'active' | 'ending' | 'ended'
    tenant_id: str,
    days_remaining: int,
) -> bool:
    """Free-trial nudge. Includes unsubscribe (CASL). Caller must skip when the
    tenant has opted out of marketing email."""
    cta_url = f"{FRONTEND_URL}/dashboard/{tenant_id}/subscription"

    if kind == "ended":
        subject = f"Your Open Lines trial has ended — reactivate {business_name}"
        heading = "Your free trial has ended"
        body_txt = ("Your AI receptionist is paused until you choose a plan. Subscribe now to "
                    "reactivate your phone line — your number, settings and knowledge base are all still here.")
        cta = "Reactivate my line"
    elif kind == "ending":
        when    = "today" if days_remaining <= 0 else "tomorrow"
        subject = f"Your Open Lines free trial ends {when}"
        heading = f"Your free trial ends {when}"
        body_txt = ("Add a plan now to avoid any interruption to your AI receptionist. "
                    "It takes under a minute and your line stays live the whole time.")
        cta = "Choose a plan"
    else:  # active (day-3 nudge)
        subject = f"How's your Open Lines AI receptionist working out, {business_name}?"
        heading = f"You have {days_remaining} days left in your free trial"
        body_txt = ("Your AI receptionist is live and answering calls. When you're ready, pick a plan "
                    "to keep it running past your trial — no interruption, cancel anytime.")
        cta = "View plans"

    unsub = _unsubscribe_url(tenant_id)
    html_body = _layout(
        heading=heading,
        body_html=f'<p style="margin:0;font-size:14px;line-height:1.6;color:#444">{_esc(body_txt)}</p>',
        cta=cta,
        cta_url=cta_url,
        preheader=body_txt[:100],
        unsubscribe_url=unsub,
    )
    headers = {
        "List-Unsubscribe": f"<{unsub}>, <mailto:{SUPPORT_EMAIL}?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    ok = _send(to=to, subject=subject, html_body=html_body, headers=headers)
    if ok:
        logger.info("Trial reminder (%s) sent to %s for tenant %s", kind, to, tenant_id)
    return ok


# ---------------------------------------------------------------------------
# Card-trial notices (TRANSACTIONAL — no unsubscribe, sent regardless of
# marketing opt-out)
# ---------------------------------------------------------------------------
# These are service messages about money leaving someone's card, not marketing.
# CASL's commercial-electronic-message rules and US ROSCA both treat an advance
# notice of an automatic charge as required disclosure, so unlike
# send_trial_reminder_email() these carry NO unsubscribe link and callers must NOT
# skip them for tenants with marketing_unsubscribed_at set. Suppressing the
# "we're charging you tomorrow" email is precisely what turns a legitimate trial
# into a negative-option billing complaint.

async def send_card_trial_email(
    *,
    to: str,
    business_name: str,
    kind: str,                      # 'day3' | 'day6' | 'converted' | 'failed'
    tenant_id: str,
    plan_name: str = "",
    amount_text: str = "",          # e.g. "$224.87 CAD (incl. tax)"
    charge_date: str = "",          # e.g. "August 16, 2026"
    card_last4: str = "",
    days_remaining: int = 0,
    minutes_used: int = 0,
    minutes_total: int = 0,
    converted_reason: str = "",     # 'time' | 'minutes' | 'manual'
) -> bool:
    sub_url = f"{FRONTEND_URL}/dashboard/{tenant_id}/subscription"
    card    = f" ending in {card_last4}" if card_last4 else " on file"
    plan    = plan_name or "your plan"
    amount  = amount_text or "your plan price"

    if kind == "day6":
        # The one that legally matters: names the amount, the date and the card.
        subject = f"Tomorrow: {amount} for Open Lines {plan}"
        heading = "Your free trial ends tomorrow"
        paras = [
            f"Your 7-day free trial ends tomorrow. On <strong>{_esc(charge_date)}</strong> we&rsquo;ll charge "
            f"<strong>{_esc(amount)}</strong> to the card{_esc(card)}, and your {_esc(plan)} plan continues "
            f"month to month.",
            "You don&rsquo;t need to do anything to continue. If you&rsquo;d rather not, you can cancel from "
            "your dashboard before then and you won&rsquo;t be charged at all.",
        ]
        cta = "Manage my plan"
    elif kind == "day3":
        used = (f"You&rsquo;ve used {minutes_used} of your {minutes_total} trial minutes so far. "
                if minutes_total else "")
        subject = f"{days_remaining} days left in your Open Lines trial"
        heading = f"{days_remaining} days left in your free trial"
        paras = [
            f"Your AI receptionist is live and answering calls. {used}"
            f"Nothing has been charged yet.",
            f"When the trial ends on <strong>{_esc(charge_date)}</strong>, your {_esc(plan)} plan starts at "
            f"<strong>{_esc(amount)}</strong> per month on the card{_esc(card)}. Cancel anytime before then.",
        ]
        cta = "View my dashboard"
    elif kind == "converted":
        why = ("You used all your trial minutes, so your plan started early to keep your line answering "
               "without interruption. " if converted_reason == "minutes" else "")
        subject = f"You're now on Open Lines {plan}"
        heading = f"Your {plan} plan is active"
        paras = [
            f"{why}Your free trial has ended and <strong>{_esc(amount)}</strong> has been charged to the "
            f"card{_esc(card)}. Your receipt is in your dashboard.",
            "Your minute allowance has reset for the new billing month, and your number, settings and "
            "knowledge base are all unchanged.",
        ]
        cta = "View invoices"
    else:  # failed
        subject = "Action needed — your Open Lines payment didn't go through"
        heading = "We couldn't process your payment"
        paras = [
            f"We tried to charge <strong>{_esc(amount)}</strong> to the card{_esc(card)} at the end of your "
            f"free trial, but it was declined. <strong>Your AI receptionist is paused</strong> until the "
            f"payment goes through.",
            "Updating your card takes under a minute, and your line comes straight back on — your number, "
            "settings and knowledge base are all still here.",
        ]
        cta = "Update my card"

    body_html = "".join(
        f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#444">{p}</p>' for p in paras
    )
    html_body = _layout(
        heading=heading,
        body_html=body_html,
        cta=cta,
        cta_url=sub_url,
        preheader=subject,
        # Deliberately no unsubscribe_url — see the module note above.
    )
    ok = _send(to=to, subject=subject, html_body=html_body)
    if ok:
        logger.info("Card-trial email (%s) sent to %s for tenant %s", kind, to, tenant_id)
    return ok


async def send_number_release_warning(
    *,
    to: str,
    business_name: str,
    tenant_id: str,
    number: str,
    release_date: str,   # already formatted, e.g. "September 8, 2026"
    final: bool = False,
) -> bool:
    """Warn that an inactive account's phone number is about to be released.

    Transactional: it announces the permanent loss of a phone number, which is a
    service notice rather than marketing, so it carries no unsubscribe and is
    sent regardless of marketing preferences.

    Releasing is irreversible and Twilio may reassign the number, so the wording
    is deliberately blunt about that — the whole point of warning twice is to give
    a business that still wants the number a real chance to keep it.
    """
    sub_url = f"{FRONTEND_URL}/dashboard/{tenant_id}/subscription"

    if final:
        subject = f"Final notice — {number} will be released on {release_date}"
        heading = "Your phone number is about to be released"
        opening = (f"This is the last reminder. On <strong>{_esc(release_date)}</strong> we&rsquo;ll release "
                   f"<strong>{_esc(number)}</strong> and it will no longer reach {_esc(business_name)}.")
    else:
        subject = f"{number} will be released on {release_date}"
        heading = "We're about to release your phone number"
        opening = (f"Your Open Lines account has been inactive for a while. On "
                   f"<strong>{_esc(release_date)}</strong> we&rsquo;ll release "
                   f"<strong>{_esc(number)}</strong> unless you reactivate.")

    body = f"""
      <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#444">{opening}</p>
      <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#444">
        <strong>This can&rsquo;t be undone.</strong> Once released, the number goes back to our
        carrier and may be reassigned to another business — calls to it will stop reaching you
        permanently.</p>
      <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#444">
        To keep it, choose a plan before then. Your settings, knowledge base and call history
        are all still here.</p>
    """
    html_body = _layout(
        heading=heading,
        body_html=body,
        cta="Keep my number",
        cta_url=sub_url,
        preheader=subject,
    )
    ok = _send(to=to, subject=subject, html_body=html_body)
    if ok:
        logger.info("Number-release warning (%s) sent to %s for tenant %s",
                    "final" if final else "first", to, tenant_id)
    return ok
