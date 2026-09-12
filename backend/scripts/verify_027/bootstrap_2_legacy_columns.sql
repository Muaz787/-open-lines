-- W9E scratch bootstrap, part 2: pre-consolidation legacy columns.
-- migrations/000_consolidated_schema.sql UPDATEs tenants.email_notifications and
-- .notification_channel, and 011 indexes .twilio_phone_number, but none of the three
-- is ever CREATEd: they exist in production from before the consolidated file was
-- written. So 000 is applied, these are added, then 000 is applied AGAIN (it is written
-- to be idempotent) so its real CREATE TABLE still defines tenants faithfully rather
-- than being pre-empted by a stub. This is a defect in 000, not in 027.
alter table tenants add column if not exists email_notifications  boolean default true;
alter table tenants add column if not exists notification_channel text default 'email';
alter table tenants add column if not exists twilio_phone_number   text;
