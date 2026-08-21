from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from cfpb_triage.config import settings
from cfpb_triage.data.lineage import canonical_json_sha256, enrich_snapshot_manifest
from cfpb_triage.paths import (
    BACKEND_ROOT,
    MANIFEST_PATH,
    SNAPSHOT_PATH,
    ensure_local_directories,
)

MAX_CFPB_PAGE_SIZE = 100
DEFAULT_MAX_RECORDS = 100_000
DEFAULT_COMPLETE_MONTHS = 12
SNAPSHOT_SCHEMA_VERSION = "1.0.0"
DOCUMENTED_MAX_BOUNDARY = "exclusive"
OBSERVED_MAX_BOUNDARY = "inclusive_workaround"


class SnapshotBoundaryError(RuntimeError):
    "Raised when the live date-boundary calibration is inconsistent."


def observed_query_max(end_exclusive: date) -> date:
    "Translate a half-open selection window to the live inclusive query."
    return end_exclusive - timedelta(days=1)


@dataclass(frozen=True)
class SelectionWindow:
    name: str
    start: date
    end_exclusive: date
    cap: int
    complete_month: bool


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, months: int) -> date:
    absolute = value.year * 12 + (value.month - 1) + months
    return date(absolute // 12, absolute % 12 + 1, 1)


def build_selection_windows(
    *,
    as_of: date,
    max_records: int = DEFAULT_MAX_RECORDS,
    complete_months: int = DEFAULT_COMPLETE_MONTHS,
) -> list[SelectionWindow]:
    """Allocate a deterministic cap across complete months plus the current slice.

    ``date_received_max`` is intentionally exclusive, matching the CFPB API.
    Monthly caps avoid a deceptively narrow contiguous-day sample when recent
    daily volumes are high.
    """

    if not 1 <= max_records <= DEFAULT_MAX_RECORDS:
        raise ValueError("max_records must be between 1 and 100,000")
    if complete_months < 4:
        raise ValueError("at least four complete months are required")

    current_start = _month_start(as_of)
    raw: list[tuple[str, date, date, bool]] = []
    for offset in range(complete_months, 0, -1):
        start = _shift_month(current_start, -offset)
        raw.append((start.strftime("%Y-%m"), start, _shift_month(start, 1), True))
    raw.append(
        (
            f"{current_start:%Y-%m}-current-slice",
            current_start,
            as_of + timedelta(days=1),
            False,
        )
    )

    base, remainder = divmod(max_records, len(raw))
    caps = [base] * len(raw)
    if remainder:
        for index in range(len(raw) - remainder, len(raw)):
            caps[index] += 1
    return [
        SelectionWindow(name, start, end, caps[index], complete)
        for index, (name, start, end, complete) in enumerate(raw)
    ]


def _source_total(payload: dict[str, Any]) -> tuple[int, str]:
    total = payload.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value", 0)), str(total.get("relation", "eq"))
    return int(total or 0), "eq"


def _hit_source(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    return source if isinstance(source, dict) else hit


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    return None


def _normalize_source_date(value: Any) -> str | None:
    raw = _clean_text(value)
    if raw is None:
        return None
    try:
        if "T" in raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).date().isoformat()
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        # Preserve malformed source text so QA can fail closed visibly.
        return raw


def normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    narrative = _clean_text(source.get("complaint_what_happened"))
    reported_has_narrative = _to_bool(source.get("has_narrative"))
    return {
        "complaint_id": str(source.get("complaint_id", "")).strip(),
        "date_received": _normalize_source_date(source.get("date_received")),
        "product": _clean_text(source.get("product")),
        "sub_product": _clean_text(source.get("sub_product")),
        "issue": _clean_text(source.get("issue")),
        "sub_issue": _clean_text(source.get("sub_issue")),
        "company": _clean_text(source.get("company")),
        "state": _clean_text(source.get("state")),
        "submitted_via": _clean_text(source.get("submitted_via")),
        "date_sent_to_company": _normalize_source_date(
            source.get("date_sent_to_company")
        ),
        "company_response": _clean_text(source.get("company_response")),
        "company_public_response": _clean_text(source.get("company_public_response")),
        "timely": _to_bool(source.get("timely")),
        "narrative": narrative,
        "has_narrative": (
            reported_has_narrative
            if reported_has_narrative is not None
            else narrative is not None
        ),
    }


class CFPBSnapshotClient:
    def __init__(
        self,
        *,
        api_url: str = settings.cfpb_api_url,
        client: httpx.Client | None = None,
        timeout_seconds: float = 45.0,
        retries: int = 4,
    ) -> None:
        self.api_url = api_url
        self._owned_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (compatible; CFPBComplaintResearch/0.1; "
                    "+https://github.com/jacobmackey01)"
                ),
                "Referer": (
                    "https://www.consumerfinance.gov/data-research/consumer-complaints/"
                ),
            },
            follow_redirects=True,
        )
        self.retries = retries

    def close(self) -> None:
        if self._owned_client:
            self.client.close()

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(self.api_url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("CFPB API returned a non-object JSON payload")
                return payload
            except (httpx.HTTPError, TypeError, ValueError):
                if attempt >= self.retries:
                    raise
                time.sleep(min(2**attempt, 8))
        raise AssertionError("unreachable")

    def fetch_window(
        self, window: SelectionWindow
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        source_total = 0
        total_relation = "eq"
        source_meta: dict[str, Any] = {}
        page_hashes: list[dict[str, Any]] = []
        offset = 0
        request_count = 0
        search_after: str | None = None

        page_size = min(MAX_CFPB_PAGE_SIZE, window.cap)
        while len(records) < window.cap:
            params = {
                "size": page_size,
                "frm": offset,
                "sort": "created_date_desc",
                "date_received_min": window.start.isoformat(),
                "date_received_max": observed_query_max(
                    window.end_exclusive
                ).isoformat(),
                "no_aggs": "true",
                "no_highlight": "true",
            }
            if search_after:
                params["search_after"] = search_after
            payload = self._request(params)
            page_hashes.append(
                {
                    "stratum": window.name,
                    "frm": offset,
                    "size": page_size,
                    "canonical_json_sha256": canonical_json_sha256(payload),
                }
            )
            request_count += 1
            if request_count == 1:
                source_total, total_relation = _source_total(payload)
                raw_meta = payload.get("_meta", {})
                if isinstance(raw_meta, dict):
                    allowed = {
                        "license",
                        "last_updated",
                        "last_indexed",
                        "is_data_stale",
                        "has_data_issue",
                        "total_record_count",
                    }
                    source_meta = {
                        key: raw_meta[key] for key in allowed if key in raw_meta
                    }
            hits = payload.get("hits", {}).get("hits", [])
            if not isinstance(hits, list) or not hits:
                break
            records.extend(normalize_source(_hit_source(hit)) for hit in hits)
            offset += len(hits)
            break_points = payload.get("_meta", {}).get("break_points", {})
            next_value = (
                break_points.get(str(request_count + 1))
                if isinstance(break_points, dict)
                else None
            )
            if isinstance(next_value, list):
                next_search_after = "_".join(str(item) for item in next_value)
            elif next_value:
                next_search_after = str(next_value)
            else:
                next_search_after = None
            if len(hits) < page_size or offset >= source_total or not next_search_after:
                break
            search_after = next_search_after

        metadata = {
            "name": window.name,
            "date_received_min": window.start.isoformat(),
            "date_received_max_exclusive": window.end_exclusive.isoformat(),
            "date_received_max_query_inclusive": observed_query_max(
                window.end_exclusive
            ).isoformat(),
            "date_max_boundary_mode": OBSERVED_MAX_BOUNDARY,
            "complete_month": window.complete_month,
            "selection_cap": window.cap,
            "source_total": source_total,
            "source_total_relation": total_relation,
            "retrieved_before_global_deduplication": len(records),
            "requests": request_count,
            "source_meta": source_meta,
            "page_response_hashes": page_hashes,
            "pagination_method": "frm_plus_search_after_break_points",
        }
        return records[: window.cap], metadata


def _canonical_lines(records: Iterable[dict[str, Any]]) -> Iterable[bytes]:
    for record in records:
        yield (
            json.dumps(
                record, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")


def write_snapshot(
    *,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    snapshot_path: Path = SNAPSHOT_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_tmp = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    hasher = hashlib.sha256()
    byte_count = 0
    with snapshot_tmp.open("wb") as handle:
        for line in _canonical_lines(records):
            handle.write(line)
            hasher.update(line)
            byte_count += len(line)
    os.replace(snapshot_tmp, snapshot_path)

    final_manifest = {
        **manifest,
        "snapshot_path": snapshot_path.name,
        "snapshot_sha256": hasher.hexdigest(),
        "snapshot_bytes": byte_count,
        "record_count": len(records),
    }
    final_manifest = enrich_snapshot_manifest(
        final_manifest,
        workspace_root=BACKEND_ROOT,
        endpoint=settings.cfpb_api_url,
        page_size_max=MAX_CFPB_PAGE_SIZE,
    )
    manifest_tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_tmp.write_text(
        json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(manifest_tmp, manifest_path)
    return final_manifest


def download_recent_snapshot(
    *,
    as_of: date | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    complete_months: int = DEFAULT_COMPLETE_MONTHS,
    snapshot_path: Path = SNAPSHOT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    api_client: CFPBSnapshotClient | None = None,
) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc).date()
    windows = build_selection_windows(
        as_of=as_of,
        max_records=max_records,
        complete_months=complete_months,
    )
    ensure_local_directories()
    client = api_client or CFPBSnapshotClient()
    owned = api_client is None
    by_id: dict[str, dict[str, Any]] = {}
    window_metadata: list[dict[str, Any]] = []
    from cfpb_triage.data.sampling import fetch_daily_stratified_window

    try:
        for window in windows:
            records, metadata = fetch_daily_stratified_window(client, window)
            before = len(by_id)
            for record in records:
                complaint_id = record.get("complaint_id")
                if complaint_id:
                    by_id.setdefault(str(complaint_id), record)
            metadata["retained_after_global_deduplication"] = len(by_id) - before
            window_metadata.append(metadata)
    finally:
        if owned:
            client.close()

    selected = sorted(
        by_id.values(),
        key=lambda row: (str(row.get("date_received") or ""), row["complaint_id"]),
        reverse=True,
    )[:max_records]
    manifest = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of.isoformat(),
        "source": settings.cfpb_api_url,
        "source_owner": "Consumer Financial Protection Bureau",
        "selection_method": (
            "monthly_capped_recent_complete_months_plus_current_slice_"
            "with_equal_calendar_day_strata"
        ),
        "selection_sort": "created_date_desc_within_each_daily_stratum",
        "date_boundary_calibration": {
            "documented_max_semantics": DOCUMENTED_MAX_BOUNDARY,
            "observed_max_semantics": OBSERVED_MAX_BOUNDARY,
            "query_max_is_inclusive": True,
        },
        "max_records": max_records,
        "complete_months_requested": complete_months,
        "api_contract": {
            "page_size_max": MAX_CFPB_PAGE_SIZE,
            "offset_parameter": "frm",
            "date_received_max_semantics_documented": DOCUMENTED_MAX_BOUNDARY,
            "date_received_max_semantics_observed": OBSERVED_MAX_BOUNDARY,
            "boundary_calibration": "live adjacent-date probe on 2026-08-21; fail closed when daily totals do not reconcile to the monthly total",
            "format_parameter": "omitted_json_is_default",
            "narrative_field": "complaint_what_happened",
            "narrative_availability_field": "has_narrative",
        },
        "selected_source_fields": [
            "complaint_id",
            "date_received",
            "product",
            "sub_product",
            "issue",
            "sub_issue",
            "company",
            "state",
            "submitted_via",
            "date_sent_to_company",
            "company_response",
            "company_public_response",
            "timely",
            "complaint_what_happened",
            "has_narrative",
        ],
        "excluded_fields": {
            "zip_code": "not required for named operations decisions",
            "consumer_disputed": "not required and no longer populated in current data",
            "tags": "not required for named operations decisions",
        },
        "windows": window_metadata,
        "source_totals_sum_across_non_overlapping_windows": sum(
            int(item["source_total"]) for item in window_metadata
        ),
    }
    return write_snapshot(
        records=selected,
        manifest=manifest,
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
    )
