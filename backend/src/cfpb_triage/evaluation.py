from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from cfpb_triage.monitoring import SummaryEvaluationStore, SummaryFactualityReview
from cfpb_triage.paths import ARTIFACT_DIR, DUCKDB_PATH

SUMMARY_EVAL_SAMPLE_PATH = ARTIFACT_DIR / "summary_factuality_sample.json"
SUMMARY_EVAL_RUBRIC_VERSION = "summary-factuality-v1"
SUMMARY_EVAL_SEED = 42
SUMMARY_EVAL_STRATA = ("month", "product")
SUMMARY_REVIEW_TEMPLATE_PATH = ARTIFACT_DIR / "summary_factuality_review_template.csv"
SUMMARY_DRAFT_MANIFEST_PATH = ARTIFACT_DIR / "summary_draft_manifest.json"
SUMMARY_DRAFT_MANIFEST_SCHEMA = "summary-draft-manifest-v1"
SUMMARY_REVIEW_TEMPLATE_COLUMNS = (
    "review_row_id",
    "summary_id",
    "complaint_id",
    "month",
    "product",
    "reviewer_id",
    "factuality_score_1_to_5",
    "all_claims_supported",
    "quotes_exact",
    "included_in_review_sample",
)


def _rank(seed: int, complaint_id: str) -> str:
    return hashlib.sha256(f"{seed}|{complaint_id}".encode()).hexdigest()


def freeze_summary_factuality_sample(
    *,
    database_path: Path = DUCKDB_PATH,
    output_path: Path = SUMMARY_EVAL_SAMPLE_PATH,
    sample_size: int = 50,
    seed: int = SUMMARY_EVAL_SEED,
) -> dict[str, Any]:
    """Freeze an ID-only round-robin sample stratified by month and product."""

    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT complaint_id, strftime(date_received, '%Y-%m') AS month, product
            FROM complaints
            WHERE has_narrative IS TRUE AND narrative IS NOT NULL
            ORDER BY complaint_id
            """
        ).fetchall()
        lineage_rows = connection.execute(
            "SELECT key, value FROM lineage_metadata"
        ).fetchall()
    finally:
        connection.close()
    lineage = dict(lineage_rows)
    strata: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for complaint_id, month, product in rows:
        strata[(month, product)].append((complaint_id, month, product))
    queues: list[tuple[tuple[str, str], deque[tuple[str, str, str]]]] = []
    for key in sorted(strata):
        ranked = sorted(strata[key], key=lambda item: _rank(seed, item[0]))
        queues.append((key, deque(ranked)))

    selected: list[dict[str, str]] = []
    while queues and len(selected) < min(sample_size, len(rows)):
        remaining = []
        for key, queue in queues:
            if queue and len(selected) < sample_size:
                complaint_id, month, product = queue.popleft()
                selected.append(
                    {
                        "complaint_id": complaint_id,
                        "month": month,
                        "product": product,
                    }
                )
            if queue:
                remaining.append((key, queue))
        queues = remaining

    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_unreviewed",
        "rubric_version": SUMMARY_EVAL_RUBRIC_VERSION,
        "sample_selection": {
            "method": "deterministic_hash_rank_round_robin_by_stratum",
            "seed": seed,
            "strata": list(SUMMARY_EVAL_STRATA),
            "eligible_population": len(rows),
            "requested_sample_size": sample_size,
            "selected_sample_size": len(selected),
        },
        "parent_snapshot_sha256": lineage.get("snapshot_sha256"),
        "items": selected,
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    payload["sample_manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def build_summary_draft_manifest(
    *,
    pack_path: Path,
    output_path: Path = SUMMARY_DRAFT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Create a private ID-only manifest binding each review row to a draft."""

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    items = pack.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("summary pack must contain generated draft items")
    manifest_items: list[dict[str, str]] = []
    seen_complaints: set[str] = set()
    seen_summaries: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("draft"), dict):
            raise TypeError("summary pack item must contain a draft object")
        draft = item["draft"]
        complaint_id = str(
            item.get("complaint_id") or draft.get("complaint_id") or ""
        ).strip()
        summary_id = str(draft.get("summary_id") or "").strip()
        model = str(draft.get("model") or "").strip()
        if not complaint_id or not summary_id or not model:
            raise ValueError(
                "each draft manifest item needs complaint_id, summary_id, and model"
            )
        if complaint_id in seen_complaints or summary_id in seen_summaries:
            raise ValueError("draft manifest IDs must be unique")
        seen_complaints.add(complaint_id)
        seen_summaries.add(summary_id)
        canonical_draft = json.dumps(
            draft, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        manifest_items.append(
            {
                "complaint_id": complaint_id,
                "summary_id": summary_id,
                "model": model,
                "draft_sha256": hashlib.sha256(canonical_draft).hexdigest(),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": SUMMARY_DRAFT_MANIFEST_SCHEMA,
        "status": "private_generated_drafts",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sample_manifest_sha256": pack.get("sample_manifest_sha256"),
        "parent_snapshot_sha256": pack.get("parent_snapshot_sha256"),
        "draft_count": len(manifest_items),
        "items": manifest_items,
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    payload["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def export_summary_review_template(
    *,
    sample_path: Path = SUMMARY_EVAL_SAMPLE_PATH,
    output_path: Path = SUMMARY_REVIEW_TEMPLATE_PATH,
) -> dict[str, Any]:
    """Export a bounded, ID-only worksheet for private manual review.

    The worksheet contains no complaint narrative, generated summary, or free-text
    reviewer notes. It is intentionally a blank template and cannot change the
    frozen sample's 'frozen_unreviewed' status. Reviewers should use complaint
    IDs to inspect source material under the approved private data controls, then
    record evidence through the review workflow rather than copying narrative into
    this artifact.
    """

    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if sample.get("status") != "frozen_unreviewed":
        raise ValueError(
            "review worksheet export requires a frozen_unreviewed sample; "
            "review evidence must not be inferred or overwritten"
        )
    items = sample.get("items")
    if not isinstance(items, list):
        raise TypeError("frozen sample items must be a list")

    rows: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise TypeError("frozen sample item must be an object")
        required = ("complaint_id", "month", "product")
        if any(not str(item.get(key, "")).strip() for key in required):
            raise ValueError("frozen sample item is missing an ID or stratum field")
        rows.append(
            {
                "review_row_id": f"summary-review-{index:04d}",
                "summary_id": "",
                "complaint_id": str(item["complaint_id"]),
                "month": str(item["month"]),
                "product": str(item["product"]),
                "reviewer_id": "",
                "factuality_score_1_to_5": "",
                "all_claims_supported": "",
                "quotes_exact": "",
                "included_in_review_sample": "",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=SUMMARY_REVIEW_TEMPLATE_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    return {
        "status": "template_exported_not_reviewed",
        "source_sample_status": sample["status"],
        "reviewed_sample_count": 0,
        "contains_narratives": False,
        "contains_generated_summaries": False,
        "source_sample_manifest_sha256": sample.get("sample_manifest_sha256"),
        "row_count": len(rows),
        "output_path": str(output_path),
        "columns": list(SUMMARY_REVIEW_TEMPLATE_COLUMNS),
    }


def _review_text(value: Any, *, field: str, row_number: int, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"row {row_number}: {field} must be nonblank")
    if len(text) > maximum or any(ord(character) < 32 for character in text):
        raise ValueError(f"row {row_number}: {field} is invalid")
    return text


def _review_bool(value: Any, *, field: str, row_number: int) -> bool:
    text = str(value or "").strip().lower()
    if text not in {"true", "false"}:
        raise ValueError(f"row {row_number}: {field} must be exactly true or false")
    return text == "true"


def import_summary_review(
    *,
    sample_path: Path = SUMMARY_EVAL_SAMPLE_PATH,
    worksheet_path: Path = SUMMARY_REVIEW_TEMPLATE_PATH,
    database_path: Path = DUCKDB_PATH,
    manifest_path: Path = SUMMARY_DRAFT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Validate completed rows and bind them to a private generated-draft manifest."""

    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if sample.get("status") != "frozen_unreviewed":
        raise ValueError(
            "review import requires a frozen_unreviewed sample; "
            "the source sample is never marked reviewed by this command"
        )
    items = sample.get("items")
    if not isinstance(items, list):
        raise TypeError("frozen sample items must be a list")
    sample_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("frozen sample item must be an object")
        complaint_id = str(item.get("complaint_id", "")).strip()
        if not complaint_id or complaint_id in sample_by_id:
            raise ValueError("frozen sample complaint IDs must be unique and nonblank")
        sample_by_id[complaint_id] = item

    with worksheet_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != SUMMARY_REVIEW_TEMPLATE_COLUMNS:
            raise ValueError(
                "review worksheet columns must exactly match the ID-only template"
            )
        worksheet_rows = list(reader)
    if not worksheet_rows:
        raise ValueError("review worksheet must contain at least one completed row")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SUMMARY_DRAFT_MANIFEST_SCHEMA:
        raise ValueError("summary draft manifest schema is unsupported")
    if manifest.get("status") != "private_generated_drafts":
        raise ValueError(
            "summary draft manifest is not a private generated-draft manifest"
        )
    if manifest.get("source_sample_manifest_sha256") != sample.get(
        "sample_manifest_sha256"
    ):
        raise ValueError(
            "summary draft manifest does not match the frozen review sample"
        )
    manifest_items = manifest.get("items")
    if not isinstance(manifest_items, list):
        raise TypeError("summary draft manifest items must be a list")
    manifest_by_complaint: dict[str, dict[str, str]] = {}
    for item in manifest_items:
        if not isinstance(item, dict):
            raise TypeError("summary draft manifest item must be an object")
        complaint_id = str(item.get("complaint_id", "")).strip()
        summary_id = str(item.get("summary_id", "")).strip()
        if complaint_id not in sample_by_id or not summary_id:
            raise ValueError(
                "summary draft manifest complaint IDs must be in the frozen sample"
            )
        if complaint_id in manifest_by_complaint:
            raise ValueError("summary draft manifest complaint IDs must be unique")
        manifest_by_complaint[complaint_id] = {
            "complaint_id": complaint_id,
            "summary_id": summary_id,
            "model": str(item.get("model", "")).strip(),
            "draft_sha256": str(item.get("draft_sha256", "")).strip(),
        }
        if (
            not manifest_by_complaint[complaint_id]["model"]
            or len(manifest_by_complaint[complaint_id]["draft_sha256"]) != 64
        ):
            raise ValueError("summary draft manifest item has incomplete lineage")

    records: list[tuple[str, SummaryFactualityReview, dict[str, str]]] = []
    seen_complaint_ids: set[str] = set()
    seen_summary_ids: set[str] = set()
    for row_number, row in enumerate(worksheet_rows, start=2):
        if None in row:
            raise ValueError(f"row {row_number}: unexpected extra worksheet values")
        complaint_id = _review_text(
            row.get("complaint_id"),
            field="complaint_id",
            row_number=row_number,
            maximum=200,
        )
        sample_item = sample_by_id.get(complaint_id)
        if sample_item is None:
            raise ValueError(
                f"row {row_number}: complaint_id is not present in the frozen sample"
            )
        if complaint_id in seen_complaint_ids:
            raise ValueError(f"row {row_number}: duplicate complaint_id")
        seen_complaint_ids.add(complaint_id)
        month = _review_text(
            row.get("month"), field="month", row_number=row_number, maximum=20
        )
        product = _review_text(
            row.get("product"), field="product", row_number=row_number, maximum=200
        )
        if month != str(sample_item.get("month")) or product != str(
            sample_item.get("product")
        ):
            raise ValueError(
                f"row {row_number}: frozen sample ID/stratum values do not match"
            )
        summary_id = _review_text(
            row.get("summary_id"),
            field="summary_id",
            row_number=row_number,
            maximum=200,
        )
        manifest_item = manifest_by_complaint.get(complaint_id)
        if manifest_item is None or summary_id != manifest_item["summary_id"]:
            raise ValueError(
                f"row {row_number}: summary_id is not the generated draft bound to this complaint"
            )
        if summary_id in seen_summary_ids:
            raise ValueError(f"row {row_number}: duplicate summary_id")
        seen_summary_ids.add(summary_id)
        reviewer_id = _review_text(
            row.get("reviewer_id"),
            field="reviewer_id",
            row_number=row_number,
            maximum=100,
        )
        score_text = _review_text(
            row.get("factuality_score_1_to_5"),
            field="factuality_score_1_to_5",
            row_number=row_number,
            maximum=1,
        )
        try:
            factuality_score = int(score_text)
        except ValueError as exc:
            raise ValueError(
                f"row {row_number}: factuality_score_1_to_5 must be an integer from 1 to 5"
            ) from exc
        if factuality_score not in range(1, 6):
            raise ValueError(
                f"row {row_number}: factuality_score_1_to_5 must be an integer from 1 to 5"
            )
        lineage = {
            **manifest_item,
            "review_manifest_sha256": str(manifest["manifest_sha256"]),
        }
        records.append(
            (
                summary_id,
                SummaryFactualityReview(
                    reviewer_id=reviewer_id,
                    factuality_score=factuality_score,
                    all_claims_supported=_review_bool(
                        row.get("all_claims_supported"),
                        field="all_claims_supported",
                        row_number=row_number,
                    ),
                    quotes_exact=_review_bool(
                        row.get("quotes_exact"),
                        field="quotes_exact",
                        row_number=row_number,
                    ),
                    included_in_review_sample=_review_bool(
                        row.get("included_in_review_sample"),
                        field="included_in_review_sample",
                        row_number=row_number,
                    ),
                ),
                lineage,
            )
        )

    existing_summary_ids: set[str] = set()
    existing_bound_ids: set[str] = set()
    if database_path.exists():
        connection = duckdb.connect(str(database_path), read_only=True)
        try:
            table_exists = connection.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'summary_factuality_reviews'"
            ).fetchone()[0]
            if table_exists:
                rows = connection.execute(
                    """
                    SELECT summary_id, review_manifest_sha256
                    FROM summary_factuality_reviews
                    """
                ).fetchall()
                existing_summary_ids = {str(row[0]) for row in rows}
                existing_bound_ids = {str(row[0]) for row in rows if row[1] is not None}
        finally:
            connection.close()

    duplicate_summary_ids = {
        summary_id for summary_id, _, _ in records if summary_id in existing_bound_ids
    }
    if duplicate_summary_ids:
        raise ValueError("worksheet contains summary_id values already reviewed")

    store = SummaryEvaluationStore(database_path=database_path, sample_path=sample_path)
    inserted_count = 0
    rebound_count = 0
    for summary_id, review, lineage in records:
        if summary_id in existing_summary_ids:
            store.bind_existing_review(summary_id, lineage=lineage)
            rebound_count += 1
        else:
            store.record(summary_id, review, lineage=lineage)
            inserted_count += 1
    metrics = store.metrics()
    return {
        "status": "private_reviews_imported",
        "source_sample_status": sample["status"],
        "source_sample_manifest_sha256": sample.get("sample_manifest_sha256"),
        "review_manifest_sha256": manifest.get("manifest_sha256"),
        "imported_row_count": inserted_count,
        "rebound_existing_row_count": rebound_count,
        "reviewed_sample_count": metrics["reviewed_sample_count"],
        "metrics": metrics,
        "source_sample_changed": False,
        "contains_narratives": False,
    }
