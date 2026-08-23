from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import duckdb
from pydantic import Field

from cfpb_triage.paths import ARTIFACT_DIR, DUCKDB_PATH
from cfpb_triage.schemas import StrictModel

RUBRIC_VERSION = "summary-factuality-v1"
SAMPLE_FRAME = "frozen evaluation set selected before review"
SAMPLE_SEED = 42
SAMPLE_STRATA = ["month", "product"]
SUMMARY_EVAL_SAMPLE_PATH = ARTIFACT_DIR / "summary_factuality_sample.json"


def _sample_metadata(sample_path: Path) -> tuple[int | None, str | None, str | None]:
    if not sample_path.exists():
        return None, None, None
    try:
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        selection = sample.get("sample_selection", {})
        return (
            int(selection.get("selected_sample_size", 0)),
            sample.get("sample_manifest_sha256"),
            sample.get("parent_snapshot_sha256"),
        )
    except (OSError, TypeError, ValueError):
        # A malformed local sample must not turn monitoring into a 500. The
        # release gate remains visibly unavailable until the sample is repaired.
        return None, None, None


def _review_contract(
    count: int,
    *,
    expected_count: int | None = None,
) -> dict[str, Any]:
    if count == 0:
        status = "unavailable_until_frozen_sample_reviewed"
    elif expected_count is not None and count < expected_count:
        status = "partially_reviewed"
    else:
        status = "reviewed"
    return {
        "status": status,
        "rubric_version": RUBRIC_VERSION,
        "sample_frame": SAMPLE_FRAME,
        "sample_selection": {
            "method": "deterministic_hash_rank_round_robin_by_stratum",
            "seed": SAMPLE_SEED,
            "strata": SAMPLE_STRATA,
        },
        "expected_review_sample_count": expected_count,
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
        sample_path: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.sample_path = sample_path or SUMMARY_EVAL_SAMPLE_PATH
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
                reviewed_at TIMESTAMPTZ NOT NULL,
                complaint_id VARCHAR,
                model VARCHAR,
                draft_sha256 VARCHAR,
                review_manifest_sha256 VARCHAR
            )
            """
        )
        for column, column_type in (
            ("complaint_id", "VARCHAR"),
            ("model", "VARCHAR"),
            ("draft_sha256", "VARCHAR"),
            ("review_manifest_sha256", "VARCHAR"),
        ):
            connection.execute(
                f"ALTER TABLE summary_factuality_reviews "
                f"ADD COLUMN IF NOT EXISTS {column} {column_type}"
            )

    def record(
        self,
        summary_id: str,
        review: SummaryFactualityReview,
        *,
        lineage: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        lineage = lineage or {}
        row = {
            "summary_id": summary_id,
            **review.model_dump(),
            "reviewed_at": datetime.now(timezone.utc),
            "complaint_id": lineage.get("complaint_id"),
            "model": lineage.get("model"),
            "draft_sha256": lineage.get("draft_sha256"),
            "review_manifest_sha256": lineage.get("review_manifest_sha256"),
        }
        if self.demo_mode:
            with self._lock:
                self._demo_rows.append(row)
            return row
        connection = duckdb.connect(str(self.database_path))
        try:
            self._initialize(connection)
            connection.execute(
                """
                INSERT INTO summary_factuality_reviews (
                    summary_id, reviewer_id, factuality_score, all_claims_supported,
                    quotes_exact, included_in_review_sample, notes, reviewed_at,
                    complaint_id, model, draft_sha256, review_manifest_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    summary_id,
                    review.reviewer_id,
                    review.factuality_score,
                    review.all_claims_supported,
                    review.quotes_exact,
                    review.included_in_review_sample,
                    review.notes,
                    row["reviewed_at"],
                    row["complaint_id"],
                    row["model"],
                    row["draft_sha256"],
                    row["review_manifest_sha256"],
                ],
            )
        finally:
            connection.close()
        return row

    def bind_existing_review(self, summary_id: str, *, lineage: dict[str, str]) -> None:
        if self.demo_mode:
            with self._lock:
                for row in self._demo_rows:
                    if row["summary_id"] == summary_id:
                        for key in (
                            "complaint_id",
                            "model",
                            "draft_sha256",
                            "review_manifest_sha256",
                        ):
                            existing = row.get(key)
                            value = lineage.get(key)
                            if existing and existing != value:
                                raise ValueError(
                                    f"summary_id {summary_id} has conflicting review lineage"
                                )
                            row[key] = value
                        return
            raise ValueError(f"summary_id {summary_id} is not present")
        connection = duckdb.connect(str(self.database_path))
        try:
            self._initialize(connection)
            row = connection.execute(
                """
                SELECT complaint_id, model, draft_sha256, review_manifest_sha256
                FROM summary_factuality_reviews WHERE summary_id = ?
                """,
                [summary_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"summary_id {summary_id} is not present")
            for index, key in enumerate(
                ("complaint_id", "model", "draft_sha256", "review_manifest_sha256")
            ):
                if row[index] is not None and str(row[index]) != lineage.get(key):
                    raise ValueError(
                        f"summary_id {summary_id} has conflicting review lineage"
                    )
            connection.execute(
                """
                UPDATE summary_factuality_reviews
                SET complaint_id = ?, model = ?, draft_sha256 = ?, review_manifest_sha256 = ?
                WHERE summary_id = ?
                """,
                [
                    lineage.get("complaint_id"),
                    lineage.get("model"),
                    lineage.get("draft_sha256"),
                    lineage.get("review_manifest_sha256"),
                    summary_id,
                ],
            )
        finally:
            connection.close()

    def metrics(self) -> dict[str, Any]:
        expected_count, sample_manifest_sha256, parent_snapshot_sha256 = (
            _sample_metadata(self.sample_path)
        )
        if self.demo_mode:
            with self._lock:
                rows = [
                    row for row in self._demo_rows if row["included_in_review_sample"]
                ]
            count = len(rows)
            return {
                **_review_contract(count, expected_count=expected_count),
                "reviewed_sample_count": count,
                "sample_manifest_sha256": sample_manifest_sha256,
                "parent_snapshot_sha256": parent_snapshot_sha256,
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
                "lineage_bound_review_count": sum(
                    bool(row.get("review_manifest_sha256")) for row in rows
                ),
                "distinct_reviewed_models": len(
                    {row.get("model") for row in rows if row.get("model")}
                ),
                "review_manifest_sha256": next(
                    (
                        row.get("review_manifest_sha256")
                        for row in rows
                        if row.get("review_manifest_sha256")
                    ),
                    None,
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
                       avg(quotes_exact::INTEGER),
                       count(*) FILTER (WHERE review_manifest_sha256 IS NOT NULL),
                       count(DISTINCT model) FILTER (WHERE model IS NOT NULL),
                       min(review_manifest_sha256) FILTER (WHERE review_manifest_sha256 IS NOT NULL)
                FROM summary_factuality_reviews
                WHERE included_in_review_sample IS TRUE
                """
            ).fetchone()
        finally:
            connection.close()
        return {
            **_review_contract(int(row[0]), expected_count=expected_count),
            "reviewed_sample_count": row[0],
            "sample_manifest_sha256": sample_manifest_sha256,
            "parent_snapshot_sha256": parent_snapshot_sha256,
            "mean_factuality_score": row[1],
            "all_claims_supported_rate": row[2],
            "exact_quote_rate": row[3],
            "lineage_bound_review_count": row[4],
            "distinct_reviewed_models": row[5],
            "review_manifest_sha256": row[6],
            "measurement_basis": "manual_reviewed_sample"
            if row[0]
            else "no_manually_reviewed_sample",
        }
