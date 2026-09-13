-- 037 — an independent WhatsApp destination, and the difference between
-- "chose nothing" and "was never asked"   (REVIEW DRAFT — NOT APPLIED)
--
-- Two columns. No data is rewritten, nothing is backfilled, and no existing
-- tenant's effective behaviour changes when this is applied.
--
-- 1. WHATSAPP NEEDS ITS OWN DESTINATION.
--    Today SMS and WhatsApp both resolve to `sms_alert_number OR business_phone`.
--    A business whose WhatsApp is the owner's personal mobile and whose texts go
--    to the shop mobile cannot say so, and switching one channel off silently
--    moves the other.
--
-- 2. notification_prefs_set_at SEPARATES A CHOICE FROM AN ABSENCE.
--    With three booleans alone, a tenant who deliberately wants nothing external
--    is byte-identical to one who was never offered the question. It is
--    DELIBERATELY NOT BACKFILLED: NULL means "legacy semantics, never asked
--    through the new model", and stamping it for tenants who merely happen to
--    have a channel enabled today would assert a choice they never made and move
--    them out of the compatibility path they currently depend on.
--
--    NULL      -> legacy: the dispatcher's historical fallback still applies.
--    NOT NULL  -> explicit: every enabled channel must carry its own
--                 destination, and no cross-channel fallback exists.
--
--    The transition happens exactly once, in the application, on a successful
--    explicit save. It is one-way.
--
-- ROLLBACK — AND ITS WINDOW CLOSES
--
-- BEFORE the application release that writes these columns, dropping them is
-- structurally reversible: they are empty, nothing reads them, and re-applying
-- this file restores the schema exactly.
--
-- AFTER customers begin saving explicit preferences, dropping them DESTROYS
-- USER DATA -- every nominated WhatsApp destination, and every record of which
-- tenants chose their channels rather than never being asked. Reapplying the
-- migration would bring the columns back empty, silently returning explicit
-- tenants to legacy semantics, which is the one transition this design
-- guarantees cannot happen.
--
-- So from that release onward the recovery strategy is FORWARD FIX, not column
-- removal. The statements below are the pre-release rollback only:
--   alter table tenants
--     drop constraint if exists tenants_whatsapp_alert_number_chk;
--   alter table tenants
--     drop column if exists whatsapp_alert_number,
--     drop column if exists notification_prefs_set_at;

alter table tenants
    add column if not exists whatsapp_alert_number     text        null;

alter table tenants
    add column if not exists notification_prefs_set_at timestamptz null;

-- A destination is either absent or a storable E.164 number: '+', a non-zero
-- country digit, then 6-14 more -- 7 to 15 digits in total, the ITU maximum.
--
-- This is the SAME rule as telephony.E164_RE, which the application applies to
-- the normalised value before writing. They are stated twice because one lives
-- in Postgres and one in Python; a test asserts they accept and reject exactly
-- the same strings, so the API can never accept what this would reject.
alter table tenants
    drop constraint if exists tenants_whatsapp_alert_number_chk;
alter table tenants
    add  constraint tenants_whatsapp_alert_number_chk
    check (whatsapp_alert_number is null
           or whatsapp_alert_number ~ '^\+[1-9][0-9]{6,14}$');

comment on column tenants.whatsapp_alert_number is
    'Owner WhatsApp destination for call summaries. Independent of '
    'sms_alert_number by design: the two channels are separately selectable and '
    'need not reach the same handset. Never defaulted from business_phone.';

comment on column tenants.notification_prefs_set_at is
    'Server-stamped when the tenant explicitly chose their call-summary '
    'channels. NULL means never asked -- legacy semantics -- which is NOT the '
    'same as choosing none and must never be treated as one. Client-supplied '
    'values are ignored; the column is never cleared.';
