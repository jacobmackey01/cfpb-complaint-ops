from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from cfpb_triage.data.quality import file_sha256
from cfpb_triage.paths import DUCKDB_PATH, SNAPSHOT_PATH

SCHEMA_VERSION = "1.0.0"
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _batches(path: Path, size: int = 5_000) -> Iterator[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            batch.append(
                (
                    row.get("complaint_id"),
                    row.get("date_received"),
                    row.get("product"),
                    row.get("sub_product"),
                    row.get("issue"),
                    row.get("sub_issue"),
                    row.get("company"),
                    row.get("state"),
                    row.get("submitted_via"),
                    row.get("date_sent_to_company"),
                    row.get("company_response"),
                    row.get("company_public_response"),
                    row.get("timely"),
                    row.get("narrative"),
                    row.get("has_narrative"),
                )
            )
            if len(batch) >= size:
                yield batch
                batch = []
    if batch:
        yield batch


def initialize_review_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS route_reviews (
            complaint_id VARCHAR NOT NULL,
            reviewer_id VARCHAR NOT NULL,
            decision VARCHAR NOT NULL,
            approved_route VARCHAR,
            notes VARCHAR,
            reviewed_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE IF NOT EXISTS summary_drafts (
            summary_id VARCHAR PRIMARY KEY,
            complaint_id VARCHAR NOT NULL,
            payload_json JSON NOT NULL,
            status VARCHAR NOT NULL,
            requested_by VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE IF NOT EXISTS summary_reviews (
            summary_id VARCHAR NOT NULL,
            complaint_id VARCHAR NOT NULL,
            reviewer_id VARCHAR NOT NULL,
            decision VARCHAR NOT NULL,
            notes VARCHAR,
            reviewed_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_events (
            event_id VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            success BOOLEAN NOT NULL,
            latency_ms BIGINT,
            cost_usd DOUBLE,
            detail VARCHAR,
            occurred_at TIMESTAMPTZ NOT NULL
        );
        """
    )


def build_warehouse(
    snapshot_path: Path = SNAPSHOT_PATH,
    *,
    database_path: Path = DUCKDB_PATH,
) -> dict[str, Any]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        for view in (
            "operational_cases",
            "daily_product_volume",
            "daily_issue_volume",
            "monthly_response_metrics",
        ):
            connection.execute(f"DROP VIEW IF EXISTS {view}")
        connection.execute("DROP TABLE IF EXISTS complaints")
        connection.execute(
            """
            CREATE TABLE complaints (
                complaint_id VARCHAR PRIMARY KEY,
                date_received DATE NOT NULL,
                product VARCHAR NOT NULL,
                sub_product VARCHAR,
                issue VARCHAR NOT NULL,
                sub_issue VARCHAR,
                company VARCHAR,
                state VARCHAR,
                submitted_via VARCHAR,
                date_sent_to_company DATE,
                company_response VARCHAR,
                company_public_response VARCHAR,
                timely BOOLEAN,
                narrative VARCHAR,
                has_narrative BOOLEAN NOT NULL,
                predicted_product VARCHAR,
                prediction_confidence DOUBLE,
                prediction_abstained BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        insert_sql = """
            INSERT INTO complaints (
                complaint_id, date_received, product, sub_product, issue, sub_issue,
                company, state, submitted_via, date_sent_to_company,
                company_response, company_public_response, timely, narrative, has_narrative
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for batch in _batches(snapshot_path):
            connection.executemany(insert_sql, batch)
        initialize_review_tables(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lineage_metadata (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        snapshot_hash = file_sha256(snapshot_path)
        now = datetime.now(timezone.utc)
        for key, value in (
            ("schema_version", SCHEMA_VERSION),
            ("snapshot_sha256", snapshot_hash),
            ("snapshot_filename", snapshot_path.name),
        ):
            connection.execute(
                "INSERT OR REPLACE INTO lineage_metadata VALUES (?, ?, ?)",
                [key, value, now],
            )
        connection.execute((SQL_DIR / "operational_views.sql").read_text("utf-8"))
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_received ON complaints(date_received)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_product ON complaints(product)"
        )
        connection.execute("COMMIT")
        row_count = connection.execute("SELECT count(*) FROM complaints").fetchone()[0]
        min_date, max_date = connection.execute(
            "SELECT min(date_received), max(date_received) FROM complaints"
        ).fetchone()
        return {
            "database_path": str(database_path),
            "snapshot_sha256": snapshot_hash,
            "row_count": row_count,
            "min_date_received": min_date.isoformat() if min_date else None,
            "max_date_received": max_date.isoformat() if max_date else None,
            "schema_version": SCHEMA_VERSION,
        }
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
