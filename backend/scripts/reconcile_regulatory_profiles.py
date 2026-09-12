#!/usr/bin/env python3
"""W9G — reconcile nonterminal regulatory profiles against Twilio.

DRY RUN BY DEFAULT.

    python scripts/reconcile_regulatory_profiles.py            # report only
    python scripts/reconcile_regulatory_profiles.py --apply     # apply transitions

Intended to be invoked by an external scheduler (the same way scripts/recrawl_cron.py
is), not by an in-process daemon. Terminal profiles are never polled.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import regulatory_reconcile as rec   # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually apply transitions")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    summary = await rec.reconcile_all(dry_run=not args.apply, limit=args.limit)
    if args.json:
        print(json.dumps(summary, indent=2, default=str)); return
    print(f"\n{'DRY RUN' if summary['dry_run'] else 'APPLYING'}   "
          f"inspected={summary['inspected']}")
    print(f"  counts: {summary['counts']}")
    for r in summary["results"]:
        print(f"    {r['profile_id'][:8]}  {r['state']:24s} {r['outcome']:22s} "
              f"{r.get('provider_status', '-')}")


if __name__ == "__main__":
    asyncio.run(main())
