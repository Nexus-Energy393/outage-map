#!/usr/bin/env python3
"""Aggregate outage data from all Victorian DNSP sources.

Runs each per-distributor adapter independently; one source failing does not
prevent the others from being written. Applies the "current outages only"
filter (currently active, affecting >= MIN_CUSTOMERS customers) before writing
the merged result to docs/data/outages.json in the shape consumed by
docs/assets/app.js.
"""
from __future__ import annotations

import sys
import traceback

from common import is_current_outage, log, write_outages
from sources import powercor, jemena, ausnet, unitedenergy

ADAPTERS = [
    ("powercor", powercor.fetch),
    ("jemena", jemena.fetch),
    ("ausnet", ausnet.fetch),
    ("unitedenergy", unitedenergy.fetch),
]

# Only outages affecting at least this many customers are shown, to keep the
# map focused on material, current events rather than single-property or
# trivial outages.
MIN_CUSTOMERS = 10


def main() -> int:
    all_records: list[dict] = []
    failures: list[str] = []

    for name, fetch in ADAPTERS:
        try:
            recs = fetch() or []
            all_records.extend(recs)
            log("scrape_all", f"{name}: {len(recs)} records")
        except Exception as e:  # noqa: BLE001 - we want broad isolation per source
            failures.append(name)
            log("scrape_all", f"{name} FAILED: {e}")
            traceback.print_exc(file=sys.stderr)

    # Dedupe defensively by id (shouldn't collide across sources due to prefixes).
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_records:
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        unique.append(r)

    # Keep only outages that are currently affecting customers (present, not
    # past or future) and meet the customer-count threshold. Outages with no
    # estimated restoration time are treated as active and shown; they stay on
    # the map until a restoration time appears or the status flips to a
    # resolved state in a later scrape.
    before = len(unique)
    current = [r for r in unique if is_current_outage(r, min_customers=MIN_CUSTOMERS)]
    log(
        "scrape_all",
        f"current-filter: kept {len(current)} of {before} "
        f"(>= {MIN_CUSTOMERS} customers, active now)",
    )

    write_outages(current)
    log(
        "scrape_all",
        f"total {len(current)} records across "
        f"{len(ADAPTERS) - len(failures)}/{len(ADAPTERS)} sources",
    )

    # Exit non-zero only if EVERY source failed - partial success is still useful.
    if failures and len(failures) == len(ADAPTERS):
        log("scrape_all", "all sources failed; exiting 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
