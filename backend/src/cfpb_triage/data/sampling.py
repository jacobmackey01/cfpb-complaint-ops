from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from cfpb_triage.data.lineage import canonical_json_sha256
from cfpb_triage.data.snapshot import (
    MAX_CFPB_PAGE_SIZE,
    OBSERVED_MAX_BOUNDARY,
    CFPBSnapshotClient,
    SelectionWindow,
    SnapshotBoundaryError,
    _source_total,
    observed_query_max,
)

PAGINATION_METHOD = "frm_plus_search_after_break_points"


@dataclass(frozen=True)
class DailyAllocation:
    day: date
    source_total: int
    cap: int


class SnapshotClientProtocol(Protocol):
    def _request(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def fetch_window(
        self, window: SelectionWindow
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...


def allocate_daily_caps(
    daily_totals: list[tuple[date, int]], *, cap: int
) -> list[DailyAllocation]:
    """Proportionally allocate a monthly cap with deterministic largest remainders."""

    if cap < 0:
        raise ValueError("cap cannot be negative")
    available = sum(max(total, 0) for _, total in daily_totals)
    target = min(cap, available)
    if available == 0:
        return [DailyAllocation(day, 0, 0) for day, _ in daily_totals]
    exact = [target * max(total, 0) / available for _, total in daily_totals]
    allocations = [
        min(int(value), max(daily_totals[index][1], 0))
        for index, value in enumerate(exact)
    ]
    remaining = target - sum(allocations)
    order = sorted(
        range(len(daily_totals)),
        key=lambda index: (
            exact[index] - int(exact[index]),
            daily_totals[index][1],
            -daily_totals[index][0].toordinal(),
        ),
        reverse=True,
    )
    while remaining:
        progressed = False
        for index in order:
            if allocations[index] < max(daily_totals[index][1], 0):
                allocations[index] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return [
        DailyAllocation(day, max(total, 0), allocations[index])
        for index, (day, total) in enumerate(daily_totals)
    ]


def _source_meta(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("_meta", {})
    if not isinstance(raw, dict):
        return {}
    return {
        key: raw.get(key)
        for key in (
            "license",
            "last_updated",
            "last_indexed",
            "is_data_stale",
            "has_data_issue",
            "total_record_count",
        )
        if key in raw
    }


def _probe(
    client: SnapshotClientProtocol,
    *,
    start: date,
    end_exclusive: date,
    stratum: str,
) -> tuple[int, str, dict[str, Any], dict[str, Any]]:
    payload = client._request(
        {
            "size": 1,
            "frm": 0,
            "sort": "created_date_desc",
            "date_received_min": start.isoformat(),
            "date_received_max": observed_query_max(end_exclusive).isoformat(),
            "no_aggs": "true",
            "no_highlight": "true",
        }
    )
    total, relation = _source_total(payload)
    return (
        total,
        relation,
        _source_meta(payload),
        {
            "stratum": stratum,
            "frm": 0,
            "size": 1,
            "probe": True,
            "canonical_json_sha256": canonical_json_sha256(payload),
        },
    )


def fetch_daily_stratified_window(
    client: CFPBSnapshotClient | SnapshotClientProtocol,
    window: SelectionWindow,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sample deterministic weekly strata to preserve time coverage under WAF limits."""

    monthly_total, monthly_relation, source_meta, monthly_hash = _probe(
        client,
        start=window.start,
        end_exclusive=window.end_exclusive,
        stratum=f"{window.name}:monthly-total-probe",
    )
    strata: list[tuple[date, date]] = []
    start_day = window.start
    while start_day < window.end_exclusive:
        end_day = min(start_day + timedelta(days=7), window.end_exclusive)
        strata.append((start_day, end_day))
        start_day = end_day

    stratum_totals: list[tuple[date, int]] = []
    stratum_relations: dict[str, str] = {}
    page_hashes = [monthly_hash]
    for interval_start, interval_end in strata:
        total, relation, _, page_hash = _probe(
            client,
            start=interval_start,
            end_exclusive=interval_end,
            stratum=f"{interval_start.isoformat()}:{interval_end.isoformat()}",
        )
        stratum_totals.append((interval_start, total))
        stratum_relations[interval_start.isoformat()] = relation
        page_hashes.append(page_hash)

    allocations = allocate_daily_caps(stratum_totals, cap=window.cap)
    records: list[dict[str, Any]] = []
    allocation_metadata: list[dict[str, Any]] = []
    data_requests = 0
    for allocation, (_, interval_end) in zip(allocations, strata, strict=True):
        interval_start = allocation.day
        if allocation.cap == 0:
            allocation_metadata.append(
                {
                    "date_received_min": interval_start.isoformat(),
                    "date_received_max_exclusive": interval_end.isoformat(),
                    "source_total": allocation.source_total,
                    "source_total_relation": stratum_relations[
                        interval_start.isoformat()
                    ],
                    "selection_cap": 0,
                    "retrieved": 0,
                }
            )
            continue
        stratum_window = SelectionWindow(
            name=f"{window.name}:{interval_start.isoformat()}",
            start=interval_start,
            end_exclusive=interval_end,
            cap=allocation.cap,
            complete_month=window.complete_month,
        )
        stratum_records, metadata = client.fetch_window(stratum_window)
        records.extend(stratum_records)
        data_requests += int(metadata.get("requests", 0))
        page_hashes.extend(metadata.get("page_response_hashes", []))
        allocation_metadata.append(
            {
                "date_received_min": interval_start.isoformat(),
                "date_received_max_exclusive": interval_end.isoformat(),
                "source_total": allocation.source_total,
                "source_total_relation": stratum_relations[interval_start.isoformat()],
                "selection_cap": allocation.cap,
                "retrieved": len(stratum_records),
            }
        )

    stratum_total_sum = sum(total for _, total in stratum_totals)
    boundary_verified = monthly_relation == "eq" and all(
        relation == "eq" for relation in stratum_relations.values()
    )
    if boundary_verified and stratum_total_sum != monthly_total:
        raise SnapshotBoundaryError(
            "CFPB date-boundary calibration failed: weekly totals do not reconcile "
            "with the monthly total"
        )
    return records[: window.cap], {
        "name": window.name,
        "date_received_min": window.start.isoformat(),
        "date_received_max_exclusive": window.end_exclusive.isoformat(),
        "date_received_max_query_inclusive": observed_query_max(
            window.end_exclusive
        ).isoformat(),
        "date_max_boundary_mode": OBSERVED_MAX_BOUNDARY,
        "complete_month": window.complete_month,
        "selection_cap": window.cap,
        "source_total": monthly_total,
        "source_total_relation": monthly_relation,
        "source_meta": source_meta,
        "sampling_method": (
            "weekly_source_total_proportional_largest_remainder_then_"
            "created_date_desc_within_week"
        ),
        "stratum_allocations": allocation_metadata,
        "stratum_source_totals_sum": stratum_total_sum,
        "stratum_to_monthly_total_delta": stratum_total_sum - monthly_total,
        "boundary_calibration_verified": boundary_verified,
        "retrieved_before_global_deduplication": len(records),
        "requests": 1 + len(strata) + data_requests,
        "api_page_size_max": MAX_CFPB_PAGE_SIZE,
        "pagination_method": PAGINATION_METHOD,
        "page_response_hashes": page_hashes,
    }
