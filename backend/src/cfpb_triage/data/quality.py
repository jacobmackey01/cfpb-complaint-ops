from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from cfpb_triage.paths import QUALITY_PATH, SNAPSHOT_PATH
from cfpb_triage.schemas import QualityCheckResult, QualityReport

PROFILE_COLUMNS = (
    "complaint_id",
    "date_received",
    "product",
    "issue",
    "company",
    "state",
    "submitted_via",
    "timely",
    "narrative",
    "has_narrative",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(
    name: str,
    passed: bool,
    severity: str,
    observed: float | str | None,
    threshold: float | str | None,
    detail: str,
) -> QualityCheckResult:
    return QualityCheckResult(
        name=name,
        passed=passed,
        severity=severity,  # type: ignore[arg-type]
        observed=observed,
        threshold=threshold,
        detail=detail,
    )


def run_quality_checks(
    snapshot_path: Path = SNAPSHOT_PATH,
    *,
    output_path: Path | None = QUALITY_PATH,
    manifest_path: Path | None = None,
    as_of: date | None = None,
) -> QualityReport:
    as_of = as_of or datetime.now(timezone.utc).date()
    nulls: Counter[str] = Counter()
    distinct: dict[str, set[str]] = {column: set() for column in PROFILE_COLUMNS}
    ids: Counter[str] = Counter()
    required_columns = {"complaint_id", "date_received", "product", "issue"}
    row_count = 0
    invalid_json = 0
    invalid_dates = 0
    future_dates = 0
    missing_required_columns = 0
    missing_ids = 0
    missing_labels = 0
    narrative_mismatch = 0
    sent_before_received = 0

    with snapshot_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                invalid_json += 1
                continue
            if not isinstance(row, dict):
                invalid_json += 1
                continue
            row_count += 1
            if not required_columns.issubset(row):
                missing_required_columns += 1
            for column in PROFILE_COLUMNS:
                value = row.get(column)
                if value is None or value == "":
                    nulls[column] += 1
                elif len(distinct[column]) < 50_000:
                    distinct[column].add(str(value))
            complaint_id = str(row.get("complaint_id") or "").strip()
            if complaint_id:
                ids[complaint_id] += 1
            else:
                missing_ids += 1
            received: date | None = None
            try:
                received = date.fromisoformat(str(row.get("date_received")))
                if received > as_of:
                    future_dates += 1
            except (TypeError, ValueError):
                invalid_dates += 1
            sent_raw = row.get("date_sent_to_company")
            if received is not None and sent_raw:
                try:
                    if date.fromisoformat(str(sent_raw)) < received:
                        sent_before_received += 1
                except (TypeError, ValueError):
                    sent_before_received += 1
            if not row.get("product") or not row.get("issue"):
                missing_labels += 1
            narrative = row.get("narrative")
            has_text = isinstance(narrative, str) and bool(narrative.strip())
            if bool(row.get("has_narrative")) != has_text:
                narrative_mismatch += 1

    duplicate_rows = sum(count - 1 for count in ids.values() if count > 1)
    denominator = max(row_count, 1)
    snapshot_hash = file_sha256(snapshot_path)
    checks = [
        _check(
            "parseable_json_lines",
            invalid_json == 0,
            "critical",
            invalid_json,
            0,
            "Every non-empty line must be a valid JSON object.",
        ),
        _check(
            "row_count_within_snapshot_contract",
            1 <= row_count <= 100_000,
            "critical",
            row_count,
            "1..100000",
            "The reproducible snapshot is intentionally capped at 100,000 rows.",
        ),
        _check(
            "required_columns_present",
            missing_required_columns == 0,
            "critical",
            missing_required_columns,
            0,
            "Every row must carry the required extraction schema.",
        ),
        _check(
            "complaint_id_present",
            missing_ids == 0,
            "critical",
            missing_ids,
            0,
            "Complaint ID is required for the canonical row grain.",
        ),
        _check(
            "complaint_id_unique",
            duplicate_rows == 0,
            "critical",
            duplicate_rows,
            0,
            "Complaint ID is the intended row grain and must be unique.",
        ),
        _check(
            "date_received_valid",
            invalid_dates == 0,
            "high",
            invalid_dates,
            0,
            "Chronological validation requires parseable received dates.",
        ),
        _check(
            "date_received_not_future",
            future_dates == 0,
            "high",
            future_dates,
            0,
            f"Dates later than the declared as-of date {as_of} are invalid.",
        ),
        _check(
            "date_sent_not_before_received",
            sent_before_received == 0,
            "high",
            sent_before_received,
            0,
            "Date sent to company cannot precede date received.",
        ),
        _check(
            "routing_labels_present",
            missing_labels / denominator <= 0.001,
            "high",
            round(missing_labels / denominator, 6),
            "<=0.001",
            "Product and issue labels are required for supervised routing evaluation.",
        ),
        _check(
            "narrative_flag_consistent",
            narrative_mismatch / denominator <= 0.001,
            "medium",
            round(narrative_mismatch / denominator, 6),
            "<=0.001",
            "has_narrative should agree with the normalized narrative field.",
        ),
    ]

    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        expected_hash = str(manifest.get("snapshot_sha256") or "")
        checks.append(
            _check(
                "manifest_snapshot_sha256_matches",
                expected_hash == snapshot_hash,
                "critical",
                expected_hash or "missing",
                snapshot_hash,
                "The QA input must match the rowset hash recorded by its manifest.",
            )
        )
        source_meta = [
            window.get("source_meta", {})
            for window in manifest.get("windows", [])
            if isinstance(window, dict)
        ]
        has_data_issue = any(
            isinstance(meta, dict) and meta.get("has_data_issue") is True
            for meta in source_meta
        )
        is_stale = any(
            isinstance(meta, dict) and meta.get("is_data_stale") is True
            for meta in source_meta
        )
        checks.extend(
            [
                _check(
                    "source_reports_no_data_issue",
                    bool(source_meta) and not has_data_issue,
                    "high",
                    int(has_data_issue),
                    0,
                    "The CFPB source metadata must not report a data issue.",
                ),
                _check(
                    "source_reports_fresh",
                    bool(source_meta) and not is_stale,
                    "high",
                    int(is_stale),
                    0,
                    "The CFPB source metadata must not report stale data.",
                ),
            ]
        )

    profile = {
        column: {
            "null_count": nulls[column],
            "null_rate": round(nulls[column] / denominator, 6),
            "distinct_count_observed": len(distinct[column]),
            "distinct_count_capped": len(distinct[column]) >= 50_000,
        }
        for column in PROFILE_COLUMNS
    }
    report = QualityReport(
        generated_at=datetime.now(timezone.utc),
        snapshot_sha256=snapshot_hash,
        row_count=row_count,
        passed=all(
            check.passed for check in checks if check.severity in {"critical", "high"}
        ),
        checks=checks,
        column_profile=profile,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    return report
