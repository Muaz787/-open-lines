"""
Transactional email via Resend — call summary notifications sent to tenants.
"""

import logging
import os

import resend

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "notifications@openlines.ai")


def _build_html(business_name: str, analysis: dict, caller_number: str) -> str:
    caller_name = analysis.get("caller_name") or "Unknown"
    key_details: dict = analysis.get("key_details") or {}
    urgency = (analysis.get("urgency") or "unknown").lower()
    summary = analysis.get("summary") or ""
    next_step = analysis.get("suggested_next_step") or ""

    urgency_color = {"hot": "#e53e3e", "warm": "#dd6b20", "cold": "#3182ce"}.get(urgency, "#718096")
    urgency_bg    = {"hot": "#fff5f5", "warm": "#fffaf0", "cold": "#ebf8ff"}.get(urgency, "#f7fafc")

    detail_rows = "".join(
        f"<tr><td style='padding:4px 0;color:#718096;font-size:13px;width:140px'>{k.replace('_',' ').title()}</td>"
        f"<td style='padding:4px 0;color:#16161a;font-size:13px;font-weight:500'>{v}</td></tr>"
        for k, v in key_details.items()
    )

    details_block = (
        f"<table cellpadding='0' cellspacing='0' style='width:100%;margin-top:4px'>{detail_rows}</table>"
        if detail_rows else ""
    )

    phone_line = (
        f"<p style='margin:0 0 4px;font-size:13px;color:#718096'>📱 {caller_number}</p>"
        if caller_number else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f3f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f3f0;padding:32px 16px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%">

        <!-- Header -->
        <tr><td style="background:#16161a;border-radius:12px 12px 0 0;padding:20px 28px;display:block">
          <span style="color:#fff;font-size:15px;font-weight:600">📞 New Call — {business_name}</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:#ffffff;border-radius:0 0 12px 12px;padding:24px 28px">

          <!-- Caller -->
          <p style="margin:0 0 2px;font-size:16px;font-weight:700;color:#16161a">👤 {caller_name}</p>
          {phone_line}

          <!-- Details table -->
          {details_block}

          <div style="height:1px;background:#f0ede8;margin:16px 0"></div>

          <!-- Urgency badge -->
          <span style="display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;
                       color:{urgency_color};background:{urgency_bg};border:1px solid {urgency_color}33">
            {urgency.upper()}
          </span>

          <!-- Summary -->
          <p style="margin:14px 0 4px;font-size:13px;font-weight:600;color:#16161a">Summary</p>
          <p style="margin:0;font-size:13px;color:#444;line-height:1.6">{summary}</p>

          <!-- Next step -->
          {"<p style='margin:14px 0 4px;font-size:13px;font-weight:600;color:#16161a'>Suggested next step</p><p style='margin:0;font-size:13px;color:#444;line-height:1.6'>" + next_step + "</p>" if next_step else ""}

          <div style="height:1px;background:#f0ede8;margin:20px 0"></div>
          <p style="margin:0;font-size:11px;color:#aaa;text-align:center">
            Open Lines AI · <a href="https://openlines.ai" style="color:#15803d;text-decoration:none">openlines.ai</a>
            · <a href="https://openlines.ai/dashboard" style="color:#15803d;text-decoration:none">View dashboard</a>
          </p>

        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def send_call_summary_email(
    to: str,
    business_name: str,
    analysis: dict,
    caller_number: str = "",
) -> bool:
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set — skipping email notification")
        return False
    caller_name = analysis.get("caller_name") or "Unknown"
    try:
        resend.Emails.send({
            "from": f"Open Lines <{EMAIL_FROM}>",
            "to": [to],
            "subject": f"📞 New call from {caller_name} — {business_name}",
            "html": _build_html(business_name, analysis, caller_number),
        })
        logger.info("Email summary sent to %s for business %s", to, business_name)
        return True
    except Exception as e:
        logger.error("Failed to send email summary to %s: %s", to, e)
        return False
