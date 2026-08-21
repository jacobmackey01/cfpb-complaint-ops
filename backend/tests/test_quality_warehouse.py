from __future__ import annotations

import json
from datetime import date

import duckdb
from cfpb_triage.data.quality import file_sha256, run_quality_checks
from cfpb_triage.data.source_metrics import ingest_source_window_metrics
from cfpb_triage.data.warehouse import build_warehouse


def _row(complaint_id: str, *, received: str = "2026-01-02") -> dict:
    return {
        "complaint_id": complaint_id,
        "date_received": received,
        "product": "Credit card",
        "sub_product": None,
        "issue": "Billing dispute",
        "sub_issue": None,
        "company": "Example",
        "state": "NY",
        "zip_code": None,
        "submitted_via": "Web",
        "date_sent_to_company": "2026-01-03",
        "company_response": "Closed with explanation",
        "timely": True,
        "consumer_disputed": None,
        "narrative": "A sufficiently detailed narrative for a quality test.",
        "has_narrative": True,
    }


def _write_jsonl(path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_quality_checks_grain_schema_and_required_id(tmp_path) -> None:
    good_path = tmp_path / "good.jsonl"
    _write_jsonl(good_path, [_row("1"), _row("2")])
    report = run_quality_checks(good_path, output_path=None, as_of=date(2026, 1, 31))
    assert report.passed is True
    names = {check.name for check in report.checks}
    assert "complaint_id_present" in names
    assert "required_columns_present" in names

    bad_path = tmp_path / "bad.jsonl"
    _write_jsonl(bad_path, [_row(""), _row("2"), _row("2")])
    bad = run_quality_checks(bad_path, output_path=None, as_of=date(2026, 1, 31))
    failed = {check.name for check in bad.checks if not check.passed}
    assert "complaint_id_present" in failed
    assert "complaint_id_unique" in failed
    assert bad.passed is False


def test_warehouse_and_source_totals_keep_sample_basis_separate(tmp_path) -> None:
    snapshot = tmp_path / "complaints.jsonl"
    _write_jsonl(snapshot, [_row("1"), _row("2")])
    database = tmp_path / "complaints.duckdb"
    result = build_warehouse(snapshot, database_path=database)
    assert result["row_count"] == 2

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "snapshot_sha256": file_sha256(snapshot),
                "windows": [
                    {
                        "name": "2026-01",
                        "date_received_min": "2026-01-01",
                        "date_received_max_exclusive": "2026-02-01",
                        "complete_month": True,
                        "source_total": 1234,
                        "source_total_relation": "eq",
                        "retained_after_global_deduplication": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        ingest_source_window_metrics(database_path=database, manifest_path=manifest)
        == 1
    )
    connection = duckdb.connect(str(database), read_only=True)
    try:
        sample_count = connection.execute("SELECT count(*) FROM complaints").fetchone()[
            0
        ]
        source_total, selected = connection.execute(
            "SELECT source_total, selected_sample_rows FROM source_window_metrics"
        ).fetchone()
        attention = connection.execute(
            "SELECT requires_manual_attention FROM operational_cases ORDER BY complaint_id"
        ).fetchall()
    finally:
        connection.close()
    assert sample_count == 2
    assert source_total == 1234
    assert selected == 2
    assert attention == [(False,), (False,)]
