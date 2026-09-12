#!/usr/bin/env python3
"""W9F.1 — clear dangling phone pointers from a tenant whose number we provably no
longer own.

DRY RUN BY DEFAULT, and it will refuse on any ambiguity rather than proceed.

    python scripts/clear_stale_phone_pointers.py --tenant <uuid>
    python scripts/clear_stale_phone_pointers.py --tenant <uuid> --apply

Clears exactly two columns: tenants.twilio_phone_number and
tenants.vapi_phone_number_id. Never touches number_released_at (no authoritative
release timestamp exists) or twilio_subaccount_sid (the sub-account is still valid).
Calls no provider mutation.

--tenant is REQUIRED. There is deliberately no "clean everything" mode: this removes
routing state, and each tenant deserves its own decision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase import get_client                 # noqa: E402
from services import stale_phone_cleanup as cleanup  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, help="tenant id (full uuid or prefix)")
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = (get_client().table("tenants")
            .select("id, business_name, twilio_phone_number, twilio_subaccount_sid, "
                    "twilio_auth_token, vapi_phone_number_id, vapi_suborg_api_key, "
                    "is_active, subscription_status, number_released_at")
            .execute().data or [])
    matches = [r for r in rows if str(r["id"]).startswith(args.tenant)]
    if len(matches) != 1:
        sys.exit(f"--tenant matched {len(matches)} tenants; it must match exactly one")
    tenant = matches[0]

    result = await cleanup.clear_stale_pointers(tenant, dry_run=not args.apply)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    print(f"\n{'DRY RUN — nothing written' if result['dry_run'] else 'APPLYING'}")
    print(f"  tenant        : {str(tenant['id'])[:8]}  {tenant.get('business_name')!r}")
    print(f"  number        : {result['number']}")
    print(f"  eligible      : {result['eligible']}")
    print(f"  reason        : {result['reason'] or '-'}")
    print(f"  action        : {result.get('action', '-')}")
    print(f"  rows changed  : {result['rows_changed']}")
    print("  checks        :")
    for k, v in (result.get("checks") or {}).items():
        print(f"      {k:32s} {v}")
    if result["rows_changed"] not in (0, 1):
        sys.exit("CRITICAL: unexpected row count")


if __name__ == "__main__":
    asyncio.run(main())
