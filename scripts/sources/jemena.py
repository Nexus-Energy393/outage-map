"""Jemena electricity outage feed.

Source: https://poweroutages.jemena.com.au/
Endpoint discovered from the live map's network traffic: an unauthenticated
Azure Blob Storage JSON file.
"""
from __future__ import annotations

from common import fetch_json, log, make_record, point_from_geometry

ENDPOINT = "https://outagesiteprd101.blob.core.windows.net/outages/all-outages.json"
PAGE_URL = "https://poweroutages.jemena.com.au/"
SOURCE = "jemena"


def _suburb_str(impacted_suburbs) -> str | None:
    if not isinstance(impacted_suburbs, list) or not impacted_suburbs:
        return None
    names = []
    for s in impacted_suburbs:
        if isinstance(s, dict):
            n = s.get("SuburbName") or s.get("Name")
            if n:
                names.append(str(n).strip())
    return ", ".join(names) if names else None


def fetch() -> list[dict]:
    data = fetch_json(ENDPOINT, SOURCE)
    rows = data if isinstance(data, list) else (data.get("outages") if isinstance(data, dict) else None) or []
    log(SOURCE, f"received {len(rows)} rows from feed")

    records: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = row.get("EventId") or row.get("id")
        if not event_id:
            continue
        # Skip resolved/hidden incidents that the source flags as not for display.
        if row.get("IsShowOutage") is False:
            continue

        outage_type = (row.get("Type") or "Unplanned").strip().lower()
        if outage_type not in ("planned", "unplanned"):
            outage_type = "unplanned"

        # Prefer Location.Latitude/Longitude; fall back to GeoJSON.
        loc = row.get("Location") or {}
        lat = loc.get("Latitude") if isinstance(loc, dict) else None
        lon = loc.get("Longitude") if isinstance(loc, dict) else None
        geom = row.get("LocationGeoJson") if isinstance(row.get("LocationGeoJson"), dict) else None
        # LocationGeoJson is a Feature wrapper; unwrap to the inner geometry for our record.
        inner_geom = geom.get("geometry") if isinstance(geom, dict) else None
        if lat is None or lon is None:
            lat, lon = point_from_geometry(inner_geom)

        suburb = _suburb_str(row.get("ImpactedSuburbs"))

        records.append(
            make_record(
                record_id=f"jem-{event_id}",
                source="Jemena",
                source_url=PAGE_URL,
                distributor="Jemena",
                outage_type=outage_type,
                status=(row.get("Status") or "").strip() or None,
                suburb=suburb,
                postcode=None,
                area_description=suburb,
                customers_affected=row.get("ImpactedCustomers") if isinstance(row.get("ImpactedCustomers"), int) else None,
                reported_at=row.get("StartTime"),
                estimated_restoration=row.get("EstimatedRestorationTime"),
                crew_status=(row.get("Status") or "").strip() or None,
                latitude=float(lat) if isinstance(lat, (int, float)) else None,
                longitude=float(lon) if isinstance(lon, (int, float)) else None,
                geometry=inner_geom,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
