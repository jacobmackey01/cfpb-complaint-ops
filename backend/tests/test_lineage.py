from __future__ import annotations

from cfpb_triage.data.lineage import (
    canonical_json_sha256,
    canonical_request_plan,
)


def test_canonical_request_hash_is_order_stable_and_records_pagination_contract() -> (
    None
):
    assert canonical_json_sha256({"b": 2, "a": 1}) == canonical_json_sha256(
        {"a": 1, "b": 2}
    )
    plan = canonical_request_plan(
        endpoint="https://example.test/api",
        page_size_max=100,
        windows=[
            {
                "name": "2026-01",
                "date_received_min": "2026-01-01",
                "date_received_max_exclusive": "2026-02-01",
                "selection_cap": 500,
            }
        ],
    )
    assert plan["pagination"]["offset_parameter"] == "frm"
    assert plan["pagination"]["page_size_max"] == 100
    assert plan["date_semantics"]["date_received_max"] == "exclusive"
    assert plan["fixed_parameters"]["no_aggs"] == "true"
