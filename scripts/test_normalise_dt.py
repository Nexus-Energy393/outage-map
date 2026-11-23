"""Unit tests for common.normalise_dt and common.is_current_outage.

Run with:  python -m pytest scripts/test_normalise_dt.py
(or)        python scripts/test_normalise_dt.py   # falls back to a simple runner

Covers each real-world timestamp format observed across the four Victorian
DNSP feeds, plus the "currently active" filtering rules.
"""
from __future__ import annotations

from datetime import datetime

import common
from common import normalise_dt, is_current_outage, MELBOURNE_TZ


def _offset(iso: str) -> str:
    """Return the trailing +HH:MM / -HH:MM offset of an ISO string."""
    return iso[-6:]


def test_jemena_iso_passes_through_with_offset():
    out = normalise_dt("2026-06-13T07:34:22")
    assert out is not None
    assert out.startswith("2026-06-13T07:34:22")
    # Melbourne is +10:00 (AEST) or +11:00 (AEDT); June is AEST.
    assert _offset(out) == "+10:00"


def test_ausnet_ampm_no_space():
    out = normalise_dt("2026-07-26 08:30AM")
    assert out is not None
    assert out.startswith("2026-07-26T08:30:00")


def test_ausnet_ampm_pm():
    out = normalise_dt("2026-07-26 04:00PM")
    assert out is not None
    assert out.startswith("2026-07-26T16:00:00")


def test_ausnet_space_seconds_with_tz_label():
    out = normalise_dt("2024-01-25 16:52:03.480282 Australia/Melbourne")
    assert out is not None
    assert out.startswith("2024-01-25T16:52:03")
    # January is AEDT (+11:00).
    assert _offset(out) == "+11:00"


def test_utc_z_suffix_converts_to_melbourne():
    # 2026-06-12T22:11:54Z == 2026-06-13T08:11:54+10:00
    out = normalise_dt("2026-06-12T22:11:54Z")
    assert out is not None
    assert out.startswith("2026-06-13T08:11:54")
    assert _offset(out) == "+10:00"


def test_explicit_offset_preserved_as_melbourne():
    out = normalise_dt("2026-06-13T08:11:54+10:00")
    assert out is not None
    assert out.startswith("2026-06-13T08:11:54")


def test_empty_and_none_return_none():
    assert normalise_dt("") is None
    assert normalise_dt(None) is None
    assert normalise_dt("   ") is None


def test_unparseable_returns_none_and_counts_failure():
    common._PARSE_STATS["attempted"] = 0
    common._PARSE_STATS["failed"] = 0
    assert normalise_dt("not a date") is None
    assert common._PARSE_STATS["failed"] == 1


def _mk(status="Scheduled", customers=50, start=None, end=None):
    return {
        "status": status,
        "customersAffected": customers,
        "reportedAt": start,
        "estimatedRestoration": end,
    }


_NOW = datetime(2026, 6, 13, 8, 11, tzinfo=MELBOURNE_TZ)


def test_active_within_window_is_current():
    rec = _mk(start="2026-06-13T08:00:00+10:00", end="2026-06-13T16:00:00+10:00")
    assert is_current_outage(rec, now=_NOW) is True


def test_future_start_excluded():
    rec = _mk(start="2026-06-20T08:00:00+10:00", end="2026-06-20T16:00:00+10:00")
    assert is_current_outage(rec, now=_NOW) is False


def test_past_end_excluded():
    rec = _mk(start="2026-06-12T08:00:00+10:00", end="2026-06-12T16:00:00+10:00")
    assert is_current_outage(rec, now=_NOW) is False


def test_no_end_time_is_treated_as_active():
    rec = _mk(start="2026-06-13T05:48:00+10:00", end=None)
    assert is_current_outage(rec, now=_NOW) is True


def test_under_threshold_excluded():
    rec = _mk(customers=9, start="2026-06-13T08:00:00+10:00", end="2026-06-13T16:00:00+10:00")
    assert is_current_outage(rec, now=_NOW) is False


def test_resolved_status_excluded():
    rec = _mk(status="Restored", start="2026-06-13T08:00:00+10:00", end="2026-06-13T16:00:00+10:00")
    assert is_current_outage(rec, now=_NOW) is False


if __name__ == "__main__":
    # Minimal runner so the file is useful without pytest installed.
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError:
            failed += 1
            print(f"FAIL: {t.__name__}")
            traceback.print_exc()
    print(f"{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
