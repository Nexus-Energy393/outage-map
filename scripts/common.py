"""Shared helpers for outage scrapers.

Defines the canonical outage record shape consumed by docs/assets/app.js
and provides utilities for fetching JSON, deriving point coordinates from
polygon geometries, and writing the aggregated outages.json file.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

USER_AGENT = "NexusOutageBot/1.0 (+https://nexusenergy.au)"
DEFAULT_TIMEOUT = 30
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "outages.json"


def log(source: str, message: str) -> None:
    """Structured stderr log line, visible in GitHub Actions output."""
    print(f"[{source}] {message}", file=sys.stderr, flush=True)


def fetch_text(url: str, source: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Fetch a URL as text. Raises urllib errors; caller decides whether to swallow."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    log(source, f"GET {url} -> {len(body)} chars")
    return body


def fetch_json(url: str, source: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    body = fetch_text(url, source, timeout=timeout)
    return json.loads(body)


def polygon_centroid(coords: list[list[float]]) -> tuple[float, float] | None:
    """Compute the centroid (mean of vertices) of a polygon ring.

    Coordinates are [lon, lat] pairs per GeoJSON convention. Returns
    (lat, lon) or None if the ring is empty / malformed.
    """
    if not coords:
        return None
    xs, ys = [], []
    for pt in coords:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
        except (TypeError, ValueError):
            continue
    if not xs:
        return None
    lon = sum(xs) / len(xs)
    lat = sum(ys) / len(ys)
    return lat, lon


def point_from_geometry(geom: dict | None) -> tuple[float | None, float | None]:
    """Best-effort (lat, lon) extraction from a GeoJSON Point / Polygon."""
    if not isinstance(geom, dict):
        return None, None
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            return None, None
    if gtype == "Polygon" and isinstance(coords, list) and coords:
        c = polygon_centroid(coords[0])
        return c if c else (None, None)
    if gtype == "MultiPolygon" and isinstance(coords, list) and coords and coords[0]:
        c = polygon_centroid(coords[0][0])
        return c if c else (None, None)
    return None, None


def make_record(
    *,
    record_id: str,
    source: str,
    source_url: str,
    distributor: str,
    outage_type: str,
    status: str | None,
    suburb: str | None,
    postcode: str | None,
    area_description: str | None,
    customers_affected: int | None,
    reported_at: str | None,
    estimated_restoration: str | None,
    crew_status: str | None,
    latitude: float | None,
    longitude: float | None,
    geometry: dict | None,
    state: str = "VIC",
) -> dict:
    """Build a single outage record in the shape consumed by the frontend."""
    return {
        "id": record_id,
        "source": source,
        "sourceUrl": source_url,
        "state": state,
        "distributor": distributor,
        "type": outage_type,
        "status": status,
        "suburb": suburb,
        "postcode": postcode,
        "areaDescription": area_description,
        "customersAffected": customers_affected,
        "reportedAt": reported_at,
        "estimatedRestoration": estimated_restoration,
        "crewStatus": crew_status,
        "latitude": latitude,
        "longitude": longitude,
        "geometry": geometry,
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
    }


def write_outages(outages: Iterable[dict], out_path: Path = OUT_PATH) -> None:
    """Write the aggregated outages.json file in the shape the frontend expects."""
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "outages": list(outages),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log("write", f"wrote {len(payload['outages'])} outages -> {out_path}")
