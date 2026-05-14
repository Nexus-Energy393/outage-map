"""United Energy outage feed.

Replaces the previous HTML-regex scraper. The UE outage map page is a
client-rendered React/Gatsby app that hydrates from a CloudFront-hosted
JSON feed; we hit that feed directly.
"""
from __future__ import annotations

import hashlib
import time

from common import fetch_json, log, make_record, point_from_geometry

# Cache-busting timestamp is what the live page uses; harmless to include.
def _endpoint() -> str:
    return f"https://ds5ykmduea4ri.cloudfront.net/outages-v2.json?version={int(time.time()*1000)}"

PAGE_URL = "https://www.unitedenergy.com.au/outage-map/"
SOURCE = "unitedenergy"


def _hash_id(*parts) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:12]


def fetch() -> list[dict]:
    data = fetch_json(_endpoint(), SOURCE)
    outages = data.get("outages") if isinstance(data, dict) else None
    outages = outages or []
    log(SOURCE, f"received {len(outages)} rows from feed")

    records: list[dict] = []
    for row in outages:
        if not isinstance(row, dict):
            continue
        geom = row.get("geometry") if isinstance(row.get("geometry"), dict) else None
        lat, lon = point_from_geometry(geom)

        postcodes = row.get("postcodes") or []
        postcode = str(postcodes[0]).strip() if isinstance(postcodes, list) and postcodes else None
        suburb = row.get("suburb") or row.get("location") or row.get("area") or None
        cause = (row.get("cause") or "").strip()
        outage_type = (row.get("type") or "").strip().lower()
        if outage_type not in ("planned", "unplanned"):
            outage_type = "planned" if "planned" in cause.lower() or "scheduled" in cause.lower() else "unplanned"

        # UE records don't always carry a stable id; synthesise one from the
        # stable-ish fields so the same outage gets the same id across runs.
        rid = row.get("id") or row.get("incidentId") or _hash_id(
            postcode, cause, row.get("etr"), row.get("customersAffected"),
        )

        records.append(
            make_record(
                record_id=f"ue-{rid}",
                source="United Energy",
                source_url=PAGE_URL,
                distributor="United Energy",
                outage_type=outage_type,
                status=row.get("status") or cause or None,
                suburb=str(suburb).strip() if suburb else None,
                postcode=postcode,
                area_description=row.get("faultLocation") or (str(suburb).strip() if suburb else None),
                customers_affected=row.get("customersAffected") if isinstance(row.get("customersAffected"), int) else None,
                reported_at=row.get("startTime") or row.get("reportedAt"),
                estimated_restoration=row.get("etr"),
                crew_status=row.get("crewStatus") or row.get("status") or None,
                latitude=lat,
                longitude=lon,
                geometry=geom,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
