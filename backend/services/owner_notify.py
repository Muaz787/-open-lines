"""
Owner SMS + WhatsApp alerts for business events (deposit received, cancellation,
…), honoring the tenant's per-channel toggles. Email is event-specific and handled
by each caller; this covers the SMS (freeform) + WhatsApp (approved template)
channels so the logic isn't duplicated across payments/refunds. Non-fatal.
"""
import logging

logger = logging.getLogger(__name__)


async def send_owner_sms_whatsapp(
    tenant: dict,
    *,
    sms_body: str,
    wa_template_sid: str,
    wa_vars: dict,
    event: str = "event",
) -> None:
    """Send the owner an SMS and/or WhatsApp for a business event. Both channels
    go to the tenant's sms_alert_number (business_phone fallback). Each is gated
    on the tenant toggle, and each is independent and non-fatal."""
    from services import telephony, analytics

    # Normalize to E.164 — the number may be stored with formatting (spaces/parens),
    # which breaks Twilio SMS and 'whatsapp:<number>'.
    mobile_to = telephony.normalize_phone(tenant.get("sms_alert_number") or tenant.get("business_phone") or "")
    if not mobile_to:
        return
    tenant_id = tenant.get("id", "")
    distinct = analytics.distinct_id_for(tenant, tenant_id)

    # SMS (freeform, from the tenant's own Twilio line)
    if tenant.get("sms_enabled", False) and sms_body:
        try:
            sub_sid  = tenant.get("twilio_subaccount_sid", "")
            sub_tok  = tenant.get("twilio_auth_token", "")
            from_num = tenant.get("twilio_phone_number", "")
            if sub_sid and sub_tok and from_num:
                await telephony.send_sms(
                    subaccount_sid=sub_sid,
                    subaccount_token=sub_tok,
                    from_number=from_num,
                    to_number=mobile_to,
                    body=sms_body,
                )
                analytics.capture(distinct, "owner_notification_sent",
                                  {"tenant_id": tenant_id, "channel": "sms", "event": event})
        except Exception as e:
            logger.error("owner SMS (%s) failed for tenant %s: %s", event, tenant_id, e)

    # WhatsApp (approved Content Template, central OpenLines sender)
    if tenant.get("whatsapp_enabled", False) and wa_template_sid:
        try:
            sent = await telephony.send_whatsapp_template(mobile_to, wa_template_sid, wa_vars)
            if sent:
                analytics.capture(distinct, "owner_notification_sent",
                                  {"tenant_id": tenant_id, "channel": "whatsapp", "event": event})
        except Exception as e:
            logger.error("owner WhatsApp (%s) failed for tenant %s: %s", event, tenant_id, e)
