"""Shared helpers for outage scrapers.

Defines the canonical outage record shape consumed by docs/assets/app.js
and provides utilities for fetching JSON, deriving point coordinates from
polygon geometries, normalising timestamps, and writing the aggregated
outages.json file.

Timestamp policy
----------------
Every outage record's reportedAt / estimatedRestoration is normalised to a
single canonical format before being written: timezone-aware ISO 8601 in
Australia/Melbourne local time (e.g. "2026-06-13T08:11:54+10:00"). Source
scrapers may pass whatever raw string the upstream feed provides; make_record
runs it through normalise_dt so the frontend's Date parsing never fails and
"is this happening now?" comparisons are always apples-to-apples.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo
    MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")  # DST-aware (AEST/AEDT)
except Exception:  # pragma: no cover - zoneinfo missing/no tzdata
    # Fallback to fixed +10:00 if the tz database is unavailable. This is only
    # a last resort; prefer installing tzdata so DST is handled correctly.
    MELBOURNE_TZ = timezone(timedelta(hours=10))

USER_AGENT = "NexusOutageBot/1.0 (+https://nexusenergy.au)"
DEFAULT_TIMEOUT = 30
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "outages.json"

# If more than this fraction of supplied timestamps fail to parse, the build
# should fail loudly rather than silently publishing a half-empty map. Counts
# are tracked process-wide and asserted in write_outages().
MAX_PARSE_FAILURE_RATE = 0.25

_PARSE_STATS = {"attempted": 0, "failed": 0}

# Datetime string formats seen across the four DNSP feeds, in priority order.
_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",        # Jemena ISO: 2026-06-13T07:34:22
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",     # AusNet with microseconds
    "%Y-%m-%d %H:%M:%S",        # space-separated seconds
    "%Y-%m-%d %I:%M%p",         # AusNet AM/PM: 2026-07-26 08:30AM
    "%Y-%m-%d %I:%M %p",        # AusNet AM/PM with space
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M%p",
)


def log(source: str, message: str) -> None:
    """Structured stderr log line, visible in GitHub Actions output."""
    print(f"[{source}] {message}", file=sys.stderr, flush=True)


def normalise_dt(value: str | None) -> str | None:
    """Normalise an upstream timestamp string to ISO 8601 in Melbourne time.

    Accepts the various formats the DNSP feeds emit (ISO, space-separated,
    AM/PM, with or without an "Australia/Melbourne" suffix or an explicit
    offset). Returns a timezone-aware ISO 8601 string, or None if the value is
    empty or cannot be parsed.

    Naive timestamps are assumed to already be Melbourne local time (which is
    what every Victorian DNSP feed publishes). Parse attempts/failures are
    tallied in _PARSE_STATS so write_outages can fail loudly on a bad feed.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    _PARSE_STATS["attempted"] += 1

    # Strip a trailing IANA tz label like "... Australia/Melbourne".
    s = re.sub(r"\s+[A-Za-z]+/[A-Za-z_]+\s*$", "", s).strip()

    # 1) Already ISO / has an explicit offset? Let fromisoformat handle it,
    #    then convert to Melbourne local time.
    iso_candidate = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MELBOURNE_TZ)
        return dt.astimezone(MELBOURNE_TZ).isoformat()
    except ValueError:
        pass

    # 2) Try each known explicit format. Parsed values are naive local times.
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=MELBOURNE_TZ).isoformat()
        except ValueError:
            continue

    _PARSE_STATS["failed"] += 1
    log("normalise_dt", f"unparseable timestamp: {value!r}")
    return None


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
    """Build a single outage record in the shape consumed by the frontend.

    reportedAt and estimatedRestoration are normalised to ISO 8601 in
    Melbourne time so the frontend can parse them reliably regardless of the
    format each upstream feed uses.
    """
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
        "reportedAt": normalise_dt(reported_at),
        "estimatedRestoration": normalise_dt(estimated_restoration),
        "crewStatus": crew_status,
        "latitude": latitude,
        "longitude": longitude,
        "geometry": geometry,
        "lastUpdated": datetime.now(timezone.utc).astimezone(MELBOURNE_TZ).isoformat(),
    }


# Statuses that mean the outage is over and must never show on a "current" map.
_RESOLVED_STATUSES = {
    "resolved", "cancelled", "restored", "closed", "complete", "completed",
}


def is_current_outage(record: dict, now: datetime | None = None, min_customers: int = 10) -> bool:
    """Return True if an outage is currently affecting >= min_customers customers.

    Rules (all must hold):
      * status is not a resolved/cancelled/restored/closed/completed state;
      * it has started (reportedAt <= now), or has no start time;
      * it has not yet ended (no estimatedRestoration, OR estimatedRestoration
        >= now). Outages with no end time are treated as ACTIVE and shown -
        they stay live until a restoration time appears or the status flips to
        a resolved state in a later scrape;
      * customersAffected >= min_customers.

    now defaults to the current Melbourne time.
    """
    if now is None:
        now = datetime.now(MELBOURNE_TZ)

    status = (record.get("status") or "").strip().lower()
    if status in _RESOLVED_STATUSES:
        return False

    cust = record.get("customersAffected")
    if not isinstance(cust, (int, float)) or cust < min_customers:
        return False

    start = _parse_iso(record.get("reportedAt"))
    if start is not None and start > now:
        return False  # hasn't started yet (future-scheduled)

    end = _parse_iso(record.get("estimatedRestoration"))
    if end is not None and end < now:
        return False  # already ended

    return True


def _parse_iso(s: str | None) -> datetime | None:
    """Parse one of our own normalised ISO strings back to an aware datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MELBOURNE_TZ)
        return dt
    except ValueError:
        return None


def assert_parse_health() -> None:
    """Fail loudly if too many timestamps failed to parse this run."""
    attempted = _PARSE_STATS["attempted"]
    failed = _PARSE_STATS["failed"]
    if attempted == 0:
        return
    rate = failed / attempted
    log("write", f"timestamp parse: {failed}/{attempted} failed ({rate:.1%})")
    if rate > MAX_PARSE_FAILURE_RATE:
        raise RuntimeError(
            f"Timestamp parse failure rate {rate:.1%} exceeds "
            f"{MAX_PARSE_FAILURE_RATE:.0%} threshold "
            f"({failed}/{attempted}). A feed format likely changed - failing "
            f"loudly instead of publishing a degraded map."
        )


def write_outages(outages: Iterable[dict], out_path: Path = OUT_PATH) -> None:
    """Write the aggregated outages.json file in the shape the frontend expects.

    Raises if the timestamp parse-failure rate for the run is too high, so a
    silently-broken feed does not get published.
    """
    outages = list(outages)
    assert_parse_health()
    payload = {
        "generatedAt": datetime.now(timezone.utc).astimezone(MELBOURNE_TZ).isoformat(),
        "outages": outages,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log("write", f"wrote {len(payload['outages'])} outages -> {out_path}")
