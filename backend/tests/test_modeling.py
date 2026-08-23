from __future__ import annotations

from datetime import date, timedelta

import joblib
import numpy as np
from cfpb_triage.modeling.anomalies import anomaly_cutoff, detect_volume_anomalies
from cfpb_triage.modeling.router import (
    TrainingRow,
    chronological_complete_month_split,
    evaluate_router,
    score_texts,
    train_router,
)


def _rows() -> list[TrainingRow]:
    rows: list[TrainingRow] = []
    complaint = 0
    for month in range(1, 8):
        for index in range(12):
            complaint += 1
            rows.append(
                TrainingRow(
                    complaint_id=str(complaint),
                    received=date(2026, month, (index % 20) + 1),
                    text=f"credit card merchant charge billing dispute statement month{month} token{index}",
                    label="Credit card",
                )
            )
            complaint += 1
            rows.append(
                TrainingRow(
                    complaint_id=str(complaint),
                    received=date(2026, month, (index % 20) + 1),
                    text=f"mortgage escrow servicer home payment principal month{month} token{index}",
                    label="Mortgage",
                )
            )
    for index in range(4):
        complaint += 1
        rows.append(
            TrainingRow(
                complaint_id=str(complaint),
                received=date(2026, 7, index + 1),
                text=f"collector calling about debt not owed token{index}",
                label="Debt collection",
            )
        )
    # Current partial month must never enter a complete-month split.
    rows.append(
        TrainingRow(
            complaint_id="current",
            received=date(2026, 8, 2),
            text="credit card current partial month",
            label="Credit card",
        )
    )
    return rows


def test_complete_month_split_has_no_threshold_or_test_leakage() -> None:
    split = chronological_complete_month_split(_rows(), as_of=date(2026, 8, 21))
    assert split.train_months == ("2026-01", "2026-02", "2026-03", "2026-04")
    assert split.calibration_month == "2026-05"
    assert split.threshold_month == "2026-06"
    assert split.test_month == "2026-07"
    assert all(
        row.complaint_id != "current"
        for group in (split.train, split.calibration, split.threshold, split.test)
        for row in group
    )


def test_router_calibrates_abstains_and_reports_unseen_labels(tmp_path) -> None:
    model_path = tmp_path / "router.joblib"
    metrics_path = tmp_path / "metrics.json"
    report = train_router(
        _rows(),
        as_of=date(2026, 8, 21),
        model_path=model_path,
        metrics_path=metrics_path,
        snapshot_sha256="a" * 64,
    )
    assert report["split"]["calibration_month"] == "2026-05"
    assert report["split"]["threshold_month"] == "2026-06"
    assert report["split"]["test_month"] == "2026-07"
    assert report["threshold_selection"]["selection_rule"]
    assert 0 < report["temperature"]
    assert 0 <= report["threshold"] <= 1
    for name in ("macro_f1", "ece", "brier", "coverage", "selective_accuracy"):
        assert name in report["metrics"]
    assert report["unseen_labels"]["labels"] == ["Debt collection"]
    assert report["unseen_labels"]["row_count"] == 4
    assert isinstance(report["false_routes"], list)
    assert report["drift"]
    assert report["integrity"]["test_month_used_for_threshold_selection"] is False

    artifact = joblib.load(model_path)
    scores = score_texts(
        artifact,
        ["merchant credit card charge on statement", "home mortgage escrow payment"],
    )
    assert scores[0]["predicted_product"] == "Credit card"
    assert scores[1]["predicted_product"] == "Mortgage"
    assert all(0 <= score["confidence"] <= 1 for score in scores)


def test_anomalies_are_separate_and_exclude_publication_lag() -> None:
    as_of = date(2026, 8, 21)
    cutoff = anomaly_cutoff(as_of)
    current_start = cutoff - timedelta(days=6)
    rows: list[tuple[date, str, int]] = []
    # Eight quiet baseline weeks.
    for week in range(1, 9):
        rows.append((current_start - timedelta(days=week * 7), "Billing dispute", 2))
    rows.append((current_start, "Billing dispute", 30))
    # A huge recent count falls inside the excluded 15-day publication-lag interval.
    rows.append((as_of, "Ignored recent signal", 1000))

    issues = detect_volume_anomalies(rows, dimension="issue", as_of=as_of)
    assert [item.label for item in issues] == ["Billing dispute"]
    assert issues[0].window_end == cutoff
    assert issues[0].dimension == "issue"
    products = detect_volume_anomalies(rows, dimension="product", as_of=as_of)
    assert products[0].dimension == "product"


def test_evaluation_metrics_fail_closed_below_support_gate() -> None:
    probabilities = np.asarray([[0.8, 0.2], [0.7, 0.3]])
    report = evaluate_router(
        probabilities,
        ["Credit card", "Mortgage"],
        np.asarray(["Credit card", "Mortgage"]),
        threshold=0.5,
        minimum_test_rows=3,
        minimum_class_support=2,
    )
    assert report["status"] == "unavailable_insufficient_test_support"
    assert report["metrics"]["macro_f1"] is None
    assert report["support_gate"]["passed"] is False


def test_duplicate_narratives_are_grouped_before_chronological_split() -> None:
    rows = [
        TrainingRow("early", date(2026, 1, 1), "same complaint text", "Credit card"),
        TrainingRow("late", date(2026, 2, 1), " SAME   complaint text ", "Credit card"),
    ]
    from cfpb_triage.modeling.router import deduplicate_training_rows

    unique, grouping = deduplicate_training_rows(rows)
    assert [row.complaint_id for row in unique] == ["early"]
    assert grouping["excluded_duplicate_rows"] == 1
