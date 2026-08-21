from __future__ import annotations

from datetime import date

import duckdb
from cfpb_triage.evaluation import freeze_summary_factuality_sample


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
