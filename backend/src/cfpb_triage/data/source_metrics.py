from __future__ import annotations

import json
from pathlib import Path

import duckdb

from cfpb_triage.paths import DUCKDB_PATH, MANIFEST_PATH


def ingest_source_window_metrics(
    *,
    database_path: Path = DUCKDB_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> int:
    """Persist exact CFPB window totals separately from capped sample rows."""

    manifest = json.loads(manifest_path.read_text("utf-8"))
    rows = [
        (
            item["name"],
            item["date_received_min"],
            item["date_received_max_exclusive"],
            bool(item["complete_month"]),
            int(item["source_total"]),
            str(item.get("source_total_relation", "eq")),
            int(item.get("retained_after_global_deduplication", 0)),
        )
        for item in manifest.get("windows", [])
    ]
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute("DROP TABLE IF EXISTS source_window_metrics")
        connection.execute(
            """
            CREATE TABLE source_window_metrics (
                window_name VARCHAR PRIMARY KEY,
                date_received_min DATE NOT NULL,
                date_received_max_exclusive DATE NOT NULL,
                complete_month BOOLEAN NOT NULL,
                source_total BIGINT NOT NULL,
                source_total_relation VARCHAR NOT NULL,
                selected_sample_rows BIGINT NOT NULL
            )
            """
        )
        if rows:
            connection.executemany(
                "INSERT INTO source_window_metrics VALUES (?, ?, ?, ?, ?, ?, ?)", rows
            )
        connection.execute("COMMIT")
        return len(rows)
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
