from __future__ import annotations

from datetime import date

from cfpb_triage.data.boundaries import (
    DateMaxMode,
    api_date_received_max,
    normalize_cfpb_date,
)


def test_cfpb_timestamps_normalize_to_utc_dates() -> None:
    assert normalize_cfpb_date("2026-07-02T23:59:58.000Z") == "2026-07-02"
    assert normalize_cfpb_date("2026-07-02") == "2026-07-02"
    assert normalize_cfpb_date(None) is None


def test_observed_inclusive_workaround_preserves_internal_half_open_windows() -> None:
    end_exclusive = date(2026, 7, 2)
    assert api_date_received_max(
        end_exclusive, mode=DateMaxMode.DOCUMENTED_EXCLUSIVE
    ) == date(2026, 7, 2)
    assert api_date_received_max(
        end_exclusive, mode=DateMaxMode.OBSERVED_INCLUSIVE
    ) == date(2026, 7, 1)
