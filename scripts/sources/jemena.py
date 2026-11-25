"""Jemena electricity outage feed.

Source: https://poweroutages.jemena.com.au/

The Azure blob this used to read (outagesiteprd101.blob.core.windows.net) no
longer exists: by Nov 2026 the hostname did not resolve and every run logged
"jemena FAILED", so Jemena was missing from the public map altogether. The
map app now serves the same JSON from its own origin, which only answers
inside Australia, so it is read through the Nexy CRM relay (Vercel Sydney),
with the direct URL as a fallback for runs from an Australian network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common import fetch_json, log, make_record, point_from_geometry

ENDPOINTS = [
    "https://crm.nexusenergy.au/api/jemena-feed",
    "https://poweroutages.jemena.com.au/data/all-outages.json",
]
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
    data, last_err = None, None
    for url in ENDPOINTS:
        try:
            data = fetch_json(url, SOURCE)
            break
        except Exception as e:  # noqa: BLE001 - try the next source
            last_err = e
            log(SOURCE, f"{url} failed: {e}")
    if data is None:
        raise RuntimeError(f"all Jemena sources failed: {last_err}")
    # Anything that started more than a week ago and is still listed is a
    # leftover, not a live outage (replaces a hard-coded 2026-04-19 cut-off).
    stale_before = (datetime.now(timezone.utc) + timedelta(hours=10) - timedelta(days=7)).strftime("%Y-%m-%d")
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
        if row.get("IsShowOutage") is False or (row.get("Status") or "").strip().lower() in ("completed", "complete", "resolved", "cancelled", "closed", "restored") or ((row.get("StartTime") or "")[:10] and (row.get("StartTime") or "")[:10] < stale_before):
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
        # The feed also carries the de-energised area as a polygon. Prefer it:
        # it is what Jemena's own map draws, and it locates events whose
        # Location is still empty.
        area = row.get("ImpactedAreaGeoJson") if isinstance(row.get("ImpactedAreaGeoJson"), dict) else None
        area_geom = area.get("geometry") if isinstance(area, dict) and isinstance(area.get("geometry"), dict) else None
        if area_geom:
            inner_geom = area_geom
        if lat is None or lon is None:
            lat, lon = point_from_geometry(inner_geom)
        planned = (row.get("Type") or "").strip().lower() == "planned"

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
                postcode=next((str(s.get("PostCode") or s.get("Postcode") or s.get("PostalCode") or "").strip() for s in (row.get("ImpactedSuburbs") or []) if isinstance(s, dict) and (s.get("PostCode") or s.get("Postcode") or s.get("PostalCode"))), None),
                area_description=suburb,
                customers_affected=row.get("ImpactedCustomers") if isinstance(row.get("ImpactedCustomers"), int) else None,
                reported_at=(row.get("PlannedStartTime") if planned else None) or row.get("StartTime"),
                estimated_restoration=row.get("EstimatedRestorationTime") or (row.get("PlannedEndTime") if planned else None),
                crew_status=(row.get("Status") or "").strip() or None,
                latitude=float(lat) if isinstance(lat, (int, float)) else None,
                longitude=float(lon) if isinstance(lon, (int, float)) else None,
                geometry=inner_geom,
            )
        )

    log(SOURCE, f"normalized {len(records)} records")
    return records
