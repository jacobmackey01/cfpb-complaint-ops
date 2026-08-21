from __future__ import annotations

from datetime import date

from cfpb_triage.data.sampling import PAGINATION_METHOD, allocate_daily_caps


def test_daily_allocation_is_proportional_capped_and_deterministic() -> None:
    totals = [
        (date(2026, 1, 1), 100),
        (date(2026, 1, 2), 200),
        (date(2026, 1, 3), 300),
        (date(2026, 1, 4), 0),
    ]
    first = allocate_daily_caps(totals, cap=60)
    second = allocate_daily_caps(totals, cap=60)
    assert first == second
    assert [item.cap for item in first] == [10, 20, 30, 0]
    assert sum(item.cap for item in first) == 60
    assert all(item.cap <= item.source_total for item in first)


def test_daily_allocation_returns_all_available_when_below_cap() -> None:
    allocations = allocate_daily_caps(
        [(date(2026, 1, 1), 2), (date(2026, 1, 2), 1)], cap=10
    )
    assert [item.cap for item in allocations] == [2, 1]


def test_pagination_method_is_explicitly_recorded() -> None:
    assert PAGINATION_METHOD == "frm_plus_search_after_break_points"
