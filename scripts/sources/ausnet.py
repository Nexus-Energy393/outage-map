"""AusNet Services outage feed (outagetracker.com.au).

Source: https://www.outagetracker.com.au/outage-list
Endpoint discovered by inspecting the front-end's API calls (different
subdomain from the public site):
"""
from __future__ import annotations

from common import fetch_json, log, make_record

ENDPOINT = "https://outagetrackerservice.ausnetservices.com.au/api/v1/outages/combinedoutage"
PAGE_URL = "https://www.outagetracker.com.au/outage-list"
SOURCE = "ausnet"

# AusNet's incidentStatus values that indicate the outage is over and should
# not appear on a "current outages" map.
RESOLVED_STATUSES = {"resolved", "cancelled", "restored", "closed"}

# Map AusNet's raw crew-status codes to the customer-facing labels used on
# https://www.outagetracker.com.au/outage-list. Keys are uppercased before lookup.
STATUS_MAP = {
        "SCHEDULED": "Scheduled",
        "IN PROGRESS": "Repair in progress",
        "RESPONDING": "Crew assigned",
        "DELAYED": "Delayed",
        "RESTORED": "Restored",
        "CANCELLED": "Cancelled",
        "OUTAGE REPORTED": "Outage reported",
        "AWAITING ASSESSMENT": "Awaiting assessment",
        "AWAITING CONSTRUCTION": "Awaiting construction",
        "MAKING SAFE": "Making safe",
        "CONSTRUCTION SCHEDULED": "Construction scheduled",
        "CONSTRUCTION RESPONDING": "Construction responding",
}


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

        # AusNet's combinedoutage feed exposes the affected localities inside details[]
        # as a list of {townName, postCode, customerCount}. Earlier versions of this
        # scraper assumed details[] was always empty -- that is no longer the case.
        details = row.get("details") if isinstance(row.get("details"), list) else []
        towns: list[str] = []
        postcodes: list[str] = []
        detail_customers = 0
        for d in details:
            if not isinstance(d, dict):
                continue
            town = (d.get("townName") or "").strip()
            if town and town not in towns:
                towns.append(town)
            pc = d.get("postCode")
            if pc not in (None, "") and str(pc) not in postcodes:
                postcodes.append(str(pc))
            cc = d.get("customerCount")
            if isinstance(cc, (int, float)):
                detail_customers += int(cc)

        suburb = ", ".join(t.title() for t in towns) or None
        postcode = postcodes[0] if len(postcodes) == 1 else (", ".join(postcodes) or None)

        nmi_count = row.get("nmiCount") if isinstance(row.get("nmiCount"), int) else None
        if detail_customers > 0:
            customers_affected: int | None = detail_customers
        else:
            customers_affected = nmi_count

        # category_id values like "HVP" (High Voltage Powerline) and "LVP" describe the
        # network segment, not a locality. Keep them in area_description as a fallback
        # for display only when no town names are available.
        category_id = row.get("categoryId") or None
        area_description = None if suburb else category_id

        # For planned outages the upstream feed populates plannedEndTime with the
        # scheduled "power on" timestamp; use it as the ETR when no explicit ETR exists.
        estimated_restoration = (
            row.get("latestEstimatedTimeToRestoration")
            or row.get("initialEstimatedTimeToRestoration")
            or row.get("plannedEndTime")
            or None
        )

        reported_at = (
            row.get("unplannedStartTime")
            or row.get("plannedStartTime")
            or row.get("plannedDate")
            or None
        )

        records.append(
            make_record(
                record_id=f"ausnet-{incident}",
                source="AusNet",
                source_url=PAGE_URL,
                distributor="AusNet",
                outage_type=outage_type,
                status=STATUS_MAP.get((row.get("status") or "").strip().upper(), (row.get("status") or "").strip().title() or None) or incident_status or None,
                suburb=suburb,
                postcode=postcode,
                area_description=area_description,
                customers_affected=customers_affected,
                reported_at=reported_at,
                estimated_restoration=estimated_restoration,
                crew_status=row.get("status"),
                latitude=lat,
                longitude=lon,
                geometry=None,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
