"""AusNet Services outage feed (outagetracker.com.au).

Source: https://www.outagetracker.com.au/outage-list
Endpoint discovered by inspecting the front-end's API calls (different
subdomain from the public site):
"""
from __future__ import annotations

from ..common import fetch_json, log, make_record

ENDPOINT = "https://outagetrackerservice.ausnetservices.com.au/api/v1/outages/combinedoutage"
PAGE_URL = "https://www.outagetracker.com.au/outage-list"
SOURCE = "ausnet"

# AusNet's incidentStatus values that indicate the outage is over and should
# not appear on a "current outages" map.
RESOLVED_STATUSES = {"resolved", "cancelled", "restored", "closed"}


def _outage_type(row: dict) -> str:
    t = (row.get("type") or "").strip().lower()
    if t in ("planned", "unplanned"):
        return t
    # Fallback: incident IDs ending in -U are Unplanned, -W/-P are planned works.
    incident = (row.get("incident") or row.get("id") or "").upper()
    if incident.endswith("-U"):
        return "unplanned"
    return "planned"


def fetch() -> list[dict]:
    data = fetch_json(ENDPOINT, SOURCE)
    rows = data.get("data") if isinstance(data, dict) else None
    rows = rows or []
    log(SOURCE, f"received {len(rows)} rows from feed")

    records: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        incident = row.get("incident") or row.get("id")
        if not incident:
            continue
        incident_status = (row.get("incidentStatus") or "").strip()
        if incident_status.lower() in RESOLVED_STATUSES:
            continue

        outage_type = _outage_type(row)
        lat = row.get("latitude")
        lon = row.get("longitude")

        records.append(
            make_record(
                record_id=f"ausnet-{incident}",
                source="AusNet",
                source_url=PAGE_URL,
                distributor="AusNet",
                outage_type=outage_type,
                status=incident_status or (row.get("status") or "").strip() or None,
                suburb=None,  # AusNet's combinedoutage feed does not include suburb names; details[] is empty.
                postcode=None,
                area_description=row.get("categoryId") or None,
                customers_affected=row.get("nmiCount") if isinstance(row.get("nmiCount"), int) else None,
                reported_at=row.get("unplannedStartTime") or row.get("plannedStartTime") or None,
                estimated_restoration=row.get("latestEstimatedTimeToRestoration") or row.get("initialEstimatedTimeToRestoration") or None,
                crew_status=row.get("status") or None,
                latitude=float(lat) if isinstance(lat, (int, float)) else None,
                longitude=float(lon) if isinstance(lon, (int, float)) else None,
                geometry=None,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
