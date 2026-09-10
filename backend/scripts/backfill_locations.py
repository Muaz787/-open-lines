#!/usr/bin/env python3
"""
W1 backfill runner — give every tenant one default location + record any Square
location they already have as a provider binding.

DRY RUN BY DEFAULT, matching the NUMBER_RECLAIM_DRY_RUN convention: seeing what a
migration would do must never require risking that it does it.

    python scripts/backfill_locations.py              # report only, writes nothing
    python scripts/backfill_locations.py --apply      # actually write
    python scripts/backfill_locations.py --apply --tenant <uuid>

Safe to run repeatedly: every insert is guarded by a natural-key lookup and by the
unique indexes in migration 012.

Prerequisite: migration 012 must already be applied.
This script never calls Square and never writes to the tenants table.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import locations as db_loc          # noqa: E402
from services import location_backfill      # noqa: E402

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
        tenants = [t for t in await db_loc.list_all_tenants_for_backfill()
                   if str(t.get("id")) == args.tenant]
        if not tenants:
            sys.exit(f"No tenant {args.tenant}")
        result = await location_backfill.backfill_tenant(tenants[0], dry_run=dry_run)
        summary = {"dry_run": dry_run, "results": [result]}
    else:
        summary = await location_backfill.backfill_all(dry_run=dry_run)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for k, v in summary.items():
            if k != "results":
                print(f"  {k:28}: {v}")
        print(f"\n  {'tenant':38} {'location':16} binding")
        for r in summary["results"]:
            print(f"  {r.get('tenant_id',''):38} {r.get('location',''):16} {r.get('binding','')}")

    if dry_run:
        print("\n  DRY RUN — nothing was written. Re-run with --apply to commit.")


if __name__ == "__main__":
    asyncio.run(main())
