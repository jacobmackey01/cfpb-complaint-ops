from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np

from cfpb_triage.paths import ANOMALIES_PATH, DUCKDB_PATH
from cfpb_triage.schemas import AnomalyRecord

PUBLICATION_LAG_DAYS = 15
CURRENT_WINDOW_DAYS = 7
BASELINE_WINDOWS = 8
MINIMUM_CURRENT_COUNT = 5
ROBUST_Z_THRESHOLD = 3.0


def anomaly_cutoff(
    as_of: date, publication_lag_days: int = PUBLICATION_LAG_DAYS
) -> date:
    """Exclude the known recent-publication-lag interval from detection."""

    return as_of - timedelta(days=publication_lag_days)


def detect_volume_anomalies(
    rows: Iterable[tuple[date, str, int]],
    *,
    dimension: Literal["product", "issue"],
    as_of: date,
    publication_lag_days: int = PUBLICATION_LAG_DAYS,
) -> list[AnomalyRecord]:
    cutoff = anomaly_cutoff(as_of, publication_lag_days)
    current_start = cutoff - timedelta(days=CURRENT_WINDOW_DAYS - 1)
    earliest = current_start - timedelta(days=BASELINE_WINDOWS * CURRENT_WINDOW_DAYS)
    by_label_date: dict[str, Counter[date]] = defaultdict(Counter)
    for row_date, label, count in rows:
        if earliest <= row_date <= cutoff:
            by_label_date[str(label)][row_date] += int(count)

    anomalies: list[AnomalyRecord] = []
    for label, daily in by_label_date.items():
        current_count = sum(
            daily[current_start + timedelta(days=offset)]
            for offset in range(CURRENT_WINDOW_DAYS)
        )
        baseline: list[int] = []
        for window_index in range(BASELINE_WINDOWS):
            end = current_start - timedelta(days=1 + window_index * CURRENT_WINDOW_DAYS)
            start = end - timedelta(days=CURRENT_WINDOW_DAYS - 1)
            baseline.append(
                sum(
                    daily[start + timedelta(days=offset)]
                    for offset in range(CURRENT_WINDOW_DAYS)
                )
            )
        median = float(np.median(baseline))
        mad = float(np.median(np.abs(np.asarray(baseline, dtype=float) - median)))
        # Count data can have zero MAD. Poisson-like scale is a conservative floor.
        scale = max(1.4826 * mad, math.sqrt(median + 1.0), 1.0)
        robust_z = (current_count - median) / scale
        if current_count < MINIMUM_CURRENT_COUNT or robust_z < ROBUST_Z_THRESHOLD:
            continue
        severity: Literal["high", "medium", "low"]
        if robust_z >= 6:
            severity = "high"
        elif robust_z >= 4:
            severity = "medium"
        else:
            severity = "low"
        anomalies.append(
            AnomalyRecord(
                dimension=dimension,
                label=label,
                window_start=current_start,
                window_end=cutoff,
                current_count=current_count,
                baseline_median=median,
                robust_z=float(robust_z),
                severity=severity,
            )
        )
    return sorted(
        anomalies, key=lambda row: (row.robust_z, row.current_count), reverse=True
    )


def generate_anomaly_report(
    *,
    database_path: Path = DUCKDB_PATH,
    output_path: Path = ANOMALIES_PATH,
    as_of: date | None = None,
) -> dict[str, object]:
    as_of = as_of or datetime.now(timezone.utc).date()
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        product_rows = connection.execute(
            "SELECT date, label, count FROM daily_product_volume"
        ).fetchall()
        issue_rows = connection.execute(
            "SELECT date, label, count FROM daily_issue_volume"
        ).fetchall()
    finally:
        connection.close()
    anomalies = [
        *detect_volume_anomalies(product_rows, dimension="product", as_of=as_of),
        *detect_volume_anomalies(issue_rows, dimension="issue", as_of=as_of),
    ]
    report: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "metric_basis": "weekly_stratified_monthly_capped_snapshot_sample",
        "publication_lag_days": PUBLICATION_LAG_DAYS,
        "cutoff_date": anomaly_cutoff(as_of).isoformat(),
        "method": {
            "current_window_days": CURRENT_WINDOW_DAYS,
            "baseline_windows": BASELINE_WINDOWS,
            "baseline_window_days": CURRENT_WINDOW_DAYS,
            "scale": "max(1.4826*MAD, sqrt(median+1), 1)",
            "robust_z_threshold": ROBUST_Z_THRESHOLD,
            "minimum_current_count": MINIMUM_CURRENT_COUNT,
            "dimensions_evaluated_separately": ["product", "issue"],
        },
        "items": [item.model_dump(mode="json") for item in anomalies],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    return report
