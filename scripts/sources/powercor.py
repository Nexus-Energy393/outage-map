"""CitiPower & Powercor outage feed.

Source: https://www.powercor.com.au/power-outages-and-emergencies/live-outage-map/
Endpoint discovered from the live map's network traffic: an unauthenticated
S3-hosted JSON feed covering both Powercor and CitiPower networks (BUSINESS
field distinguishes them).
"""
from __future__ import annotations

from datetime import datetime
from ..common import (
    fetch_json,
    log,
    make_record,
    point_from_geometry,
)

ENDPOINT = "https://s3-ap-southeast-2.amazonaws.com/cppc-outage/outages.json"
POWERCOR_PAGE = "https://www.powercor.com.au/power-outages-and-emergencies/live-outage-map/"
CITIPOWER_PAGE = "https://www.citipower.com.au/power-outages-and-emergencies/live-outage-map/"
SOURCE = "powercor"


def _parse_dt(s: str | None) -> str | None:
    """Parse 'HH:MM dd-mm-yyyy' as used by the CPPC feed into ISO 8601."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M %d-%m-%Y").isoformat()
    except ValueError:
        return s  # keep original if format unexpected


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fetch() -> list[dict]:
    data = fetch_json(ENDPOINT, SOURCE)
    rows = (data or {}).get("ROWSET", {}).get("ROW", []) or []
    log(SOURCE, f"received {len(rows)} rows from feed")

    records: list[dict] = []
    for row in rows:
        order_id = str(row.get("ORDER_ID") or "").strip()
        if not order_id:
            continue
        business = (row.get("BUSINESS") or "").strip() or "Powercor"
        cause = (row.get("CAUSE") or "").strip()
        outage_type = "planned" if "planned" in cause.lower() else "unplanned"
        geom = row.get("geometry") if isinstance(row.get("geometry"), dict) else None
        lat, lon = point_from_geometry(geom)

        records.append(
            make_record(
                record_id=f"cppc-{order_id}",
                source=business,
                source_url=CITIPOWER_PAGE if business.lower() == "citipower" else POWERCOR_PAGE,
                distributor=business,
                outage_type=outage_type,
                status=(row.get("CREW_STATUS") or "").strip() or None,
                suburb=(row.get("TOWN") or row.get("AREA") or "").strip() or None,
                postcode=(str(row.get("POSTCODE") or "").strip() or None),
                area_description=(row.get("PRIVATISED") or row.get("AREA") or "").strip() or None,
                customers_affected=_to_int(row.get("CUSTOMERS")),
                reported_at=_parse_dt(row.get("START_TIME")),
                estimated_restoration=_parse_dt(row.get("ETR")),
                crew_status=(row.get("CREW_STATUS") or "").strip() or None,
                latitude=lat,
                longitude=lon,
                geometry=geom,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
