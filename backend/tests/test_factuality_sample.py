from __future__ import annotations

import csv
from datetime import date

import pytest

import duckdb
from cfpb_triage.evaluation import (
    SUMMARY_REVIEW_TEMPLATE_COLUMNS,
    export_summary_review_template,
    freeze_summary_factuality_sample,
)


def _database(path) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE complaints (
                complaint_id VARCHAR, date_received DATE, product VARCHAR,
                has_narrative BOOLEAN, narrative VARCHAR
            );
            CREATE TABLE lineage_metadata (key VARCHAR, value VARCHAR);
            INSERT INTO lineage_metadata VALUES ('snapshot_sha256', 'abc123');
            """
        )
        rows = []
        for month in (1, 2):
            for product in ("Credit card", "Mortgage"):
                for index in range(5):
                    rows.append(
                        (
                            f"{month}-{product}-{index}",
                            date(2026, month, index + 1),
                            product,
                            True,
                            "Narrative",
                        )
                    )
        connection.executemany("INSERT INTO complaints VALUES (?, ?, ?, ?, ?)", rows)
    finally:
        connection.close()


def test_factuality_sample_is_deterministic_stratified_and_parented(tmp_path) -> None:
    database = tmp_path / "sample.duckdb"
    _database(database)
    first = freeze_summary_factuality_sample(
        database_path=database,
        output_path=tmp_path / "first.json",
        sample_size=8,
        seed=42,
    )
    second = freeze_summary_factuality_sample(
        database_path=database,
        output_path=tmp_path / "second.json",
        sample_size=8,
        seed=42,
    )
    assert first["items"] == second["items"]
    assert len(first["items"]) == 8
    assert {(item["month"], item["product"]) for item in first["items"]} == {
        ("2026-01", "Credit card"),
        ("2026-01", "Mortgage"),
        ("2026-02", "Credit card"),
        ("2026-02", "Mortgage"),
    }
    assert first["parent_snapshot_sha256"] == "abc123"
    assert first["rubric_version"] == "summary-factuality-v1"
    assert first["sample_manifest_sha256"]


def test_review_template_is_id_only_blank_and_never_review_evidence(tmp_path) -> None:
    database = tmp_path / "sample.duckdb"
    _database(database)
    sample_path = tmp_path / "sample.json"
    frozen = freeze_summary_factuality_sample(
        database_path=database,
        output_path=sample_path,
        sample_size=4,
        seed=42,
    )
    output_path = tmp_path / "review.csv"
    result = export_summary_review_template(
        sample_path=sample_path,
        output_path=output_path,
    )

    assert result["status"] == "template_exported_not_reviewed"
    assert result["reviewed_sample_count"] == 0
    assert result["contains_narratives"] is False
    assert result["source_sample_manifest_sha256"] == frozen["sample_manifest_sha256"]

    rows = list(csv.DictReader(output_path.open(encoding="utf-8", newline="")))
    assert len(rows) == 4
    assert tuple(rows[0]) == SUMMARY_REVIEW_TEMPLATE_COLUMNS
    assert all(row["summary_id"] == "" for row in rows)
    assert all(row["reviewer_id"] == "" for row in rows)
    assert all(row["factuality_score_1_to_5"] == "" for row in rows)
    assert all(row["included_in_review_sample"] == "" for row in rows)
    assert "Narrative" not in output_path.read_text(encoding="utf-8")
    assert "narrative" not in output_path.read_text(encoding="utf-8").lower()


def test_review_template_refuses_a_non_frozen_sample(tmp_path) -> None:
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(
        '{"status": "reviewed", "items": []}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frozen_unreviewed"):
        export_summary_review_template(
            sample_path=sample_path,
            output_path=tmp_path / "review.csv",
        )
