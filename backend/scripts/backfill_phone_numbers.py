#!/usr/bin/env python3
"""W9D backfill runner — represent each tenant's existing Twilio number as a
tenant_phone_numbers row.

DRY RUN BY DEFAULT. Writing requires --apply, explicitly, every time.

    python scripts/backfill_phone_numbers.py               # report only, writes nothing
    python scripts/backfill_phone_numbers.py --json        # same, machine readable
    python scripts/backfill_phone_numbers.py --apply       # actually write
    python scripts/backfill_phone_numbers.py --apply --tenant <uuid>

Safe to run repeatedly: every insert is guarded by a natural-key check and by the
partial unique indexes in migration 027.

Prerequisite: migration 027 must already be applied.
This script never writes to the tenants table and never mutates anything at Twilio.
Phone numbers are masked in the human-readable output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import phone_backfill          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--tenant", default="", help="backfill a single tenant id")
    ap.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = ap.parse_args()
    dry_run = not args.apply

    if args.tenant:
        tenants = [t for t in await phone_backfill.list_tenants_for_backfill()
                   if str(t.get("id")) == args.tenant]
        if not tenants:
            sys.exit(f"No tenant {args.tenant}")
        result = await phone_backfill.backfill_tenant(tenants[0], dry_run=dry_run)
        summary = {"dry_run": dry_run, "tenants": 1,
                   "counts": {result["action"]: 1},
                   "skip_reasons": ({result["reason"]: 1}
                                    if result["action"] == "skip" else {}),
                   "results": [result]}
    else:
        summary = await phone_backfill.backfill_all(dry_run=dry_run)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return

    print(f"\n{'DRY RUN — nothing written' if dry_run else 'APPLYING'}"
          f"   tenants={summary['tenants']}")
    print(f"  counts       : {summary['counts']}")
    print(f"  skip reasons : {summary['skip_reasons'] or '—'}\n")
    for r in summary["results"]:
        row = r.get("row") or {}
        extra = (f" country={row.get('iso_country')} "
                 f"activated_at_source={row.get('activated_at_source') or 'NULL'}"
                 if row else "")
        print(f"  {r['tenant_id'][:8]}  {r['number']:12s} {r['action']:9s} "
              f"{r['reason']}{extra}")


if __name__ == "__main__":
    asyncio.run(main())
