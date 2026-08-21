from __future__ import annotations

import json
from datetime import date

import httpx
from cfpb_triage.data.snapshot import (
    CFPBSnapshotClient,
    SelectionWindow,
    build_selection_windows,
    normalize_source,
    write_snapshot,
)


def test_selection_spans_complete_months_and_current_slice() -> None:
    windows = build_selection_windows(
        as_of=date(2026, 8, 21), max_records=100_000, complete_months=12
    )
    assert len(windows) == 13
    assert windows[0].start == date(2025, 8, 1)
    assert windows[0].end_exclusive == date(2025, 9, 1)
    assert windows[-2].start == date(2026, 7, 1)
    assert windows[-2].end_exclusive == date(2026, 8, 1)
    assert windows[-1].start == date(2026, 8, 1)
    assert windows[-1].end_exclusive == date(2026, 8, 22)
    assert windows[-1].complete_month is False
    assert sum(window.cap for window in windows) == 100_000


def test_api_uses_cfpb_pagination_and_exclusive_max() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params["frm"])
        remaining = 120 - offset
        count = max(0, min(int(request.url.params["size"]), remaining))
        hits = [
            {
                "_source": {
                    "complaint_id": str(offset + index),
                    "date_received": "2026-01-10T23:59:58Z",
                    "product": "Credit card",
                    "issue": "Billing dispute",
                    "complaint_what_happened": "Narrative supplied for testing.",
                    "has_narrative": True,
                }
            }
            for index in range(count)
        ]
        return httpx.Response(
            200,
            json={
                "_meta": {
                    "license": "CC0",
                    "last_updated": "2026-01-12",
                    "is_data_stale": False,
                    "break_points": (
                        {"2": ["1760000000000", "100"]} if offset == 0 else {}
                    ),
                },
                "hits": {"total": {"value": 120, "relation": "eq"}, "hits": hits},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CFPBSnapshotClient(client=http_client)
    window = SelectionWindow("2026-01", date(2026, 1, 1), date(2026, 2, 1), 150, True)
    records, metadata = client.fetch_window(window)
    assert len(records) == 120
    assert len(requests) == 2
    for request in requests:
        params = request.url.params
        assert int(params["size"]) <= 100
        assert "frm" in params
        assert "from" not in params
        assert "format" not in params
        assert params["date_received_max"] == "2026-01-31"
        assert params["no_aggs"] == "true"
        assert params["no_highlight"] == "true"
    assert metadata["source_total"] == 120
    assert metadata["source_meta"]["license"] == "CC0"
    assert metadata["pagination_method"] == "frm_plus_search_after_break_points"


def test_current_narrative_fields_are_normalized() -> None:
    normalized = normalize_source(
        {
            "complaint_id": 123,
            "date_received": "2026-01-01",
            "product": "Mortgage",
            "issue": "Payment issue",
            "complaint_what_happened": "  Exact narrative.  ",
            "has_narrative": "true",
            "company_public_response": "Company acted",
            "tags": ["Servicemember"],
        }
    )
    assert normalized["complaint_id"] == "123"
    assert normalized["narrative"] == "Exact narrative."
    assert normalized["has_narrative"] is True
    assert normalized["company_public_response"] == "Company acted"
    assert "tags" not in normalized
    assert "zip_code" not in normalized
    assert "consumer_disputed" not in normalized
    assert "consumer_consent_provided" not in normalized


def test_snapshot_hash_is_deterministic(tmp_path) -> None:
    records = [
        {
            "complaint_id": "1",
            "date_received": "2026-01-01",
            "product": "Mortgage",
            "issue": "Payment",
        }
    ]
    first = write_snapshot(
        records=records,
        manifest={"as_of_date": "2026-01-02"},
        snapshot_path=tmp_path / "first.jsonl",
        manifest_path=tmp_path / "first.manifest.json",
    )
    second = write_snapshot(
        records=records,
        manifest={"as_of_date": "2026-01-02"},
        snapshot_path=tmp_path / "second.jsonl",
        manifest_path=tmp_path / "second.manifest.json",
    )
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert (
        json.loads((tmp_path / "first.manifest.json").read_text("utf-8"))[
            "snapshot_sha256"
        ]
        == first["snapshot_sha256"]
    )
