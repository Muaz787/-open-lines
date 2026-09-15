"""
Backfill auth users' app_metadata.tenant_id from the tenants.user_id owner link.

Tenant ownership used to be read from user_metadata.tenant_id, which the signed-in
user can rewrite themselves -- an account could grant itself another tenant's data
(confirmed exploitable, 2026-09-15). The fix reads app_metadata.tenant_id instead,
which only the service-role key can write. This script populates app_metadata for
accounts created before the fix.

MUST run against production BEFORE deploying the security.py change: until an account
has app_metadata.tenant_id it is denied (no fallback to the editable field), so the
backfill has to precede the read-side switch. Old code ignores app_metadata, so
running this early is safe.

The source of truth is tenants.user_id -- the server-written owner link -- NEVER the
user-editable user_metadata, so a tampered claim cannot be cemented into app_metadata.

Dry-run by default; pass --apply to write. Idempotent and safe to re-run.

  python -m scripts.backfill_app_metadata_tenant           # dry run
  python -m scripts.backfill_app_metadata_tenant --apply    # write
"""
import sys

from db.supabase import get_client


def main(apply: bool) -> int:
    client = get_client()

    tenants = client.table("tenants").select("id,user_id").execute().data or []
    owner_tenant: dict[str, str] = {}
    ownerless = []
    for t in tenants:
        uid = t.get("user_id")
        if uid:
            # If one account somehow owns two tenants, the newest write wins; log it.
            if uid in owner_tenant and owner_tenant[uid] != t["id"]:
                print(f"WARN account {uid[:8]} owns >1 tenant "
                      f"({owner_tenant[uid][:8]}, {t['id'][:8]}); using {t['id'][:8]}")
            owner_tenant[uid] = t["id"]
        else:
            ownerless.append(t["id"])

    print(f"tenants: {len(tenants)} | with owner: {len(owner_tenant)} | "
          f"ownerless (skipped, need manual owner): {len(ownerless)}")
    for tid in ownerless:
        print(f"  ownerless tenant: {tid}")

    set_count = already = conflict = 0
    for uid, tenant_id in owner_tenant.items():
        try:
            user = client.auth.admin.get_user_by_id(uid).user
        except Exception as e:
            print(f"  SKIP {uid[:8]}: cannot load auth user ({e})")
            continue
        if user is None:
            print(f"  SKIP {uid[:8]}: no such auth user (stale tenants.user_id)")
            continue

        app_meta = dict(getattr(user, "app_metadata", None) or {})
        current = app_meta.get("tenant_id")
        if current == tenant_id:
            already += 1
            continue
        if current and current != tenant_id:
            # app_metadata already names a DIFFERENT tenant than the owner link.
            # Don't silently overwrite; a human should reconcile which is correct.
            conflict += 1
            print(f"  CONFLICT {uid[:8]}: app_metadata={current[:8]} but owns {tenant_id[:8]} — left unchanged")
            continue

        set_count += 1
        if apply:
            app_meta["tenant_id"] = tenant_id
            client.auth.admin.update_user_by_id(uid, {"app_metadata": app_meta})
            print(f"  SET {uid[:8]} -> {tenant_id[:8]}")
        else:
            print(f"  would set {uid[:8]} -> {tenant_id[:8]}")

    verb = "set" if apply else "would set"
    print(f"\n{verb}: {set_count} | already correct: {already} | conflicts (manual): {conflict}")
    if not apply and set_count:
        print("dry run — re-run with --apply to write")
    return 1 if conflict else 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv[1:]))
