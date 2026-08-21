from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import duckdb
from pydantic import Field

from cfpb_triage.paths import DUCKDB_PATH
from cfpb_triage.schemas import StrictModel

RUBRIC_VERSION = "summary-factuality-v1"
SAMPLE_FRAME = "frozen evaluation set selected before review"
SAMPLE_SEED = 42
SAMPLE_STRATA = ["month", "product"]


def _review_contract(count: int) -> dict[str, Any]:
    return {
        "status": ("reviewed" if count else "unavailable_until_frozen_sample_reviewed"),
        "rubric_version": RUBRIC_VERSION,
        "sample_frame": SAMPLE_FRAME,
        "sample_selection": {
            "method": "deterministic_hash_rank_round_robin_by_stratum",
            "seed": SAMPLE_SEED,
            "strata": SAMPLE_STRATA,
        },
    }


class SummaryFactualityReview(StrictModel):
    reviewer_id: str = Field(min_length=2, max_length=100)
    factuality_score: int = Field(ge=1, le=5)
    all_claims_supported: bool
    quotes_exact: bool
    included_in_review_sample: bool = True
    notes: str | None = Field(default=None, max_length=1000)


class SummaryEvaluationStore:
    def __init__(
        self,
        *,
        database_path: Path = DUCKDB_PATH,
        demo_mode: bool = False,
        source_kind: str | None = None,
    ) -> None:
        self.database_path = database_path
        self.demo_mode = demo_mode
        self.source_kind = source_kind or (
            "synthetic_offline_demo" if demo_mode else "cfpb_public"
        )
        self._demo_rows: list[dict[str, Any]] = []
        self._lock = RLock()

    def _initialize(self, connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_factuality_reviews (
                summary_id VARCHAR NOT NULL,
                reviewer_id VARCHAR NOT NULL,
                factuality_score INTEGER NOT NULL,
                all_claims_supported BOOLEAN NOT NULL,
                quotes_exact BOOLEAN NOT NULL,
                included_in_review_sample BOOLEAN NOT NULL,
                notes VARCHAR,
                reviewed_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    def record(
        self, summary_id: str, review: SummaryFactualityReview
    ) -> dict[str, Any]:
        row = {
            "summary_id": summary_id,
            **review.model_dump(),
            "reviewed_at": datetime.now(timezone.utc),
        }
        if self.demo_mode:
            with self._lock:
                self._demo_rows.append(row)
            return row
        connection = duckdb.connect(str(self.database_path))
        try:
            self._initialize(connection)
            connection.execute(
                "INSERT INTO summary_factuality_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    summary_id,
                    review.reviewer_id,
                    review.factuality_score,
                    review.all_claims_supported,
                    review.quotes_exact,
                    review.included_in_review_sample,
                    review.notes,
                    row["reviewed_at"],
                ],
            )
        finally:
            connection.close()
        return row

    def metrics(self) -> dict[str, Any]:
        if self.demo_mode:
            with self._lock:
                rows = [
                    row for row in self._demo_rows if row["included_in_review_sample"]
                ]
            count = len(rows)
            return {
                **_review_contract(count),
                "reviewed_sample_count": count,
                "mean_factuality_score": (
                    sum(row["factuality_score"] for row in rows) / count
                    if count
                    else None
                ),
                "all_claims_supported_rate": (
                    sum(row["all_claims_supported"] for row in rows) / count
                    if count
                    else None
                ),
                "exact_quote_rate": (
                    sum(row["quotes_exact"] for row in rows) / count if count else None
                ),
                "measurement_basis": f"manual_reviews_of_{self.source_kind}"
                if count
                else "no_manually_reviewed_sample",
            }
        connection = duckdb.connect(str(self.database_path))
        try:
            self._initialize(connection)
            row = connection.execute(
                """
                SELECT count(*), avg(factuality_score), avg(all_claims_supported::INTEGER),
                       avg(quotes_exact::INTEGER)
                FROM summary_factuality_reviews
                WHERE included_in_review_sample IS TRUE
                """
            ).fetchone()
        finally:
            connection.close()
        return {
            **_review_contract(int(row[0])),
            "reviewed_sample_count": row[0],
            "mean_factuality_score": row[1],
            "all_claims_supported_rate": row[2],
            "exact_quote_rate": row[3],
            "measurement_basis": "manual_reviewed_sample"
            if row[0]
            else "no_manually_reviewed_sample",
        }
