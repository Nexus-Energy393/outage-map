#!/usr/bin/env python3
"""Scrape United Energy outage list and write docs/data/outages.json."""
import json, re, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
from html.parser import HTMLParser

URL = "https://www.unitedenergy.com.au/outage-map/"
OUT = Path("docs/data/outages.json")

# Suburb -> [lat, lon] for common UE areas. Extend as needed.
GEO = {
    "mount waverley": [-37.8779, 145.1300],
    "flinders": [-38.4742, 145.0297],
    "frankston": [-38.1413, 145.1228],
    "dandenong": [-37.9874, 145.2149],
    "cranbourne": [-38.1110, 145.2830],
    "pakenham": [-38.0703, 145.4844],
    "mornington": [-38.2196, 145.0383],
    "rosebud": [-38.3590, 144.9050],
    "sorrento": [-38.3399, 144.7445],
    "rye": [-38.3704, 144.8208],
    "hastings": [-38.3066, 145.1881],
    "berwick": [-38.0357, 145.3457],
    "narre warren": [-38.0286, 145.3025],
    "endeavour hills": [-37.9783, 145.2592],
    "noble park": [-37.9667, 145.1750],
    "springvale": [-37.9474, 145.1525],
    "clayton": [-37.9220, 145.1170],
    "oakleigh": [-37.8995, 145.0890],
    "chadstone": [-37.8870, 145.0830],
    "mulgrave": [-37.9275, 145.1664],
    "glen waverley": [-37.8780, 145.1640],
    "rowville": [-37.9293, 145.2353],
    "vermont": [-37.8338, 145.1965],
    "ringwood": [-37.8167, 145.2294],
    "boronia": [-37.8580, 145.2843],
    "ferntree gully": [-37.8842, 145.2914],
    "belgrave": [-37.9118, 145.3551],
    "emerald": [-37.9326, 145.4429],
}

def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (NexusOutageBot/1.0; +https://nexusenergy.au)",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def parse_outages(html):
    """Heuristic parse: UE renders outages as repeated blocks with suburb header,
    cause, customers affected, est restoration, fault location, status badge."""
    outages = []
    # Strip scripts/styles
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    # Find outage blocks. UE structure varies; we look for any block containing
    # both "Customers affected" and a heading.
    blocks = re.findall(
        r"(<(?:article|div|section)[^>]*>(?:(?!<(?:article|div|section)\b)[\s\S])*?Customers\s*affected[\s\S]*?</(?:article|div|section)>)",
        html, re.I
    )
    if not blocks:
        # Fallback: split by "Customers affected" and look backwards
        chunks = re.split(r"(?i)customers\s*affected", html)
        for i in range(1, len(chunks)):
            blocks.append(chunks[i-1][-2000:] + "Customers affected" + chunks[i][:2000])
    for b in blocks:
        text = re.sub(r"<[^>]+>", " ", b)
        text = re.sub(r"\s+", " ", text).strip()
        if "Customers affected" not in text:
            continue
        # Suburb: first heading-ish chunk (try h2/h3 first)
        h = re.search(r"<h[1-4][^>]*>([^<]+)</h[1-4]>", b, re.I)
        suburb = (h.group(1) if h else text.split("Cause")[0]).strip()
        suburb = re.sub(r"\s+", " ", suburb)[:80]
        cust = re.search(r"Customers\s*affected[:\s]*([0-9,]+)", text, re.I)
        cust_n = int(cust.group(1).replace(",", "")) if cust else None
        cause = re.search(r"Cause[:\s]*([^,;]+?)(?=\s+(?:Customers|Est|Fault|Status|Unplanned|Planned)|$)", text, re.I)
        cause_s = (cause.group(1).strip() if cause else "Under investigation")[:120]
        etr = re.search(r"Est(?:imated)?\.?\s*restoration[:\s]*([^,;]+?)(?=\s+(?:Fault|Status|Cause|Customers|Unplanned|Planned)|$)", text, re.I)
        etr_s = etr.group(1).strip() if etr else None
        fault = re.search(r"Fault\s*location[:\s]*([^,;]+?)(?=\s+(?:Status|Cause|Customers|Est|Unplanned|Planned)|$)", text, re.I)
        fault_s = fault.group(1).strip() if fault else None
        otype = "planned" if re.search(r"\bplanned\b", text, re.I) and not re.search(r"\bunplanned\b", text, re.I) else "unplanned"
        key = suburb.lower().split(",")[0].strip()
        ll = GEO.get(key)
        oid = hashlib.md5(f"ue|{suburb}|{fault_s}|{cust_n}".encode()).hexdigest()[:12]
        outages.append({
            "id": f"ue-{oid}",
            "source": "United Energy",
            "sourceUrl": URL,
            "state": "VIC",
            "distributor": "United Energy",
            "type": otype,
            "status": cause_s,
            "suburb": suburb,
            "postcode": None,
            "areaDescription": fault_s or suburb,
            "customersAffected": cust_n,
            "reportedAt": None,
            "estimatedRestoration": etr_s,
            "crewStatus": None,
            "latitude": ll[0] if ll else None,
            "longitude": ll[1] if ll else None,
            "geometry": None,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "raw": None,
        })
    # Dedupe by id
    seen, uniq = set(), []
    for o in outages:
        if o["id"] in seen: continue
        seen.add(o["id"]); uniq.append(o)
    return uniq

def main():
    try:
        html = fetch_html(URL)
        outages = parse_outages(html)
    except Exception as e:
        print(f"ERROR fetching United Energy: {e}", file=sys.stderr)
        outages = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "outages": outages,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(outages)} outages to {OUT}")

if __name__ == "__main__":
    main()
