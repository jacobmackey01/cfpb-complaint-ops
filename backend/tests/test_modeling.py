from __future__ import annotations

from datetime import date, timedelta

import joblib
from cfpb_triage.modeling.anomalies import anomaly_cutoff, detect_volume_anomalies
from cfpb_triage.modeling.router import (
    TrainingRow,
    chronological_complete_month_split,
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
                    text=f"credit card merchant charge billing dispute statement token{index}",
                    label="Credit card",
                )
            )
            complaint += 1
            rows.append(
                TrainingRow(
                    complaint_id=str(complaint),
                    received=date(2026, month, (index % 20) + 1),
                    text=f"mortgage escrow servicer home payment principal token{index}",
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
