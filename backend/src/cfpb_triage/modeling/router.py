from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, f1_score

from cfpb_triage.paths import DUCKDB_PATH, MODEL_METRICS_PATH, MODEL_PATH

RANDOM_SEED = 42
TARGET_SELECTIVE_ACCURACY = 0.80
MINIMUM_COVERAGE = 0.50
ROUTER_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class TrainingRow:
    complaint_id: str
    received: date
    text: str
    label: str

    @property
    def month(self) -> str:
        return self.received.strftime("%Y-%m")


@dataclass(frozen=True)
class ChronologicalSplit:
    train_months: tuple[str, ...]
    calibration_month: str
    threshold_month: str
    test_month: str
    train: tuple[TrainingRow, ...]
    calibration: tuple[TrainingRow, ...]
    threshold: tuple[TrainingRow, ...]
    test: tuple[TrainingRow, ...]


def _complete_month_boundary(as_of: date) -> date:
    return as_of.replace(day=1)


def chronological_complete_month_split(
    rows: Iterable[TrainingRow], *, as_of: date
) -> ChronologicalSplit:
    boundary = _complete_month_boundary(as_of)
    eligible = [row for row in rows if row.received < boundary]
    months = sorted({row.month for row in eligible})
    if len(months) < 4:
        raise ValueError(
            "routing requires at least four complete months: train, calibration, "
            "threshold selection, and test"
        )
    train_months = tuple(months[:-3])
    calibration_month, threshold_month, test_month = months[-3:]
    grouped: dict[str, list[TrainingRow]] = defaultdict(list)
    for row in eligible:
        grouped[row.month].append(row)
    train = tuple(row for month in train_months for row in grouped[month])
    return ChronologicalSplit(
        train_months=train_months,
        calibration_month=calibration_month,
        threshold_month=threshold_month,
        test_month=test_month,
        train=train,
        calibration=tuple(grouped[calibration_month]),
        threshold=tuple(grouped[threshold_month]),
        test=tuple(grouped[test_month]),
    )


def _decision_logits(classifier: SGDClassifier, features: Any) -> np.ndarray:
    scores = np.asarray(classifier.decision_function(features), dtype=float)
    if scores.ndim == 1:
        return np.column_stack((-scores / 2.0, scores / 2.0))
    return scores


def _softmax(logits: np.ndarray, temperature: float) -> np.ndarray:
    scaled = logits / max(float(temperature), 1e-6)
    scaled -= scaled.max(axis=1, keepdims=True)
    exponentiated = np.exp(scaled)
    return exponentiated / exponentiated.sum(axis=1, keepdims=True)


def _known_indices(
    labels: Sequence[str], classes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    mapping = {str(label): index for index, label in enumerate(classes)}
    row_indices: list[int] = []
    class_indices: list[int] = []
    for row_index, label in enumerate(labels):
        if label in mapping:
            row_indices.append(row_index)
            class_indices.append(mapping[label])
    return np.asarray(row_indices, dtype=int), np.asarray(class_indices, dtype=int)


def fit_temperature(
    logits: np.ndarray, labels: Sequence[str], classes: np.ndarray
) -> tuple[float, dict[str, Any]]:
    rows, targets = _known_indices(labels, classes)
    if len(rows) == 0:
        raise ValueError("calibration month contains no labels seen during training")
    candidate_temperatures = np.geomspace(0.25, 4.0, 81)
    best_temperature = 1.0
    best_loss = float("inf")
    for candidate in candidate_temperatures:
        probabilities = _softmax(logits[rows], float(candidate))
        loss = float(
            -np.log(
                np.clip(probabilities[np.arange(len(targets)), targets], 1e-12, 1.0)
            ).mean()
        )
        if loss < best_loss:
            best_loss = loss
            best_temperature = float(candidate)
    return best_temperature, {
        "known_label_rows": len(rows),
        "unseen_label_rows": int(len(labels) - len(rows)),
        "negative_log_likelihood": best_loss,
    }


def choose_abstention_threshold(
    probabilities: np.ndarray,
    labels: Sequence[str],
    classes: np.ndarray,
    *,
    target_accuracy: float = TARGET_SELECTIVE_ACCURACY,
    minimum_coverage: float = MINIMUM_COVERAGE,
) -> tuple[float, dict[str, Any]]:
    predicted = classes[probabilities.argmax(axis=1)].astype(str)
    confidence = probabilities.max(axis=1)
    true = np.asarray(labels, dtype=str)
    candidates = sorted(
        set(np.linspace(0.20, 0.95, 76).tolist()) | set(confidence.tolist())
    )
    evaluations: list[dict[str, float]] = []
    for threshold in candidates:
        accepted = confidence >= threshold
        coverage = float(accepted.mean()) if len(accepted) else 0.0
        accuracy = (
            float(accuracy_score(true[accepted], predicted[accepted]))
            if accepted.any()
            else 0.0
        )
        evaluations.append(
            {"threshold": float(threshold), "coverage": coverage, "accuracy": accuracy}
        )
    feasible = [
        item
        for item in evaluations
        if item["coverage"] >= minimum_coverage and item["accuracy"] >= target_accuracy
    ]
    if feasible:
        selected = max(feasible, key=lambda item: (item["coverage"], item["accuracy"]))
        rule = "maximum coverage meeting selective-accuracy and coverage targets"
    else:
        selected = max(
            evaluations,
            key=lambda item: (item["accuracy"] * item["coverage"], item["coverage"]),
        )
        rule = "fallback maximum accuracy-times-coverage; target was not feasible"
    return selected["threshold"], {
        **selected,
        "target_selective_accuracy": target_accuracy,
        "minimum_coverage": minimum_coverage,
        "selection_rule": rule,
    }


def expected_calibration_error(
    probabilities: np.ndarray,
    labels: Sequence[str],
    classes: np.ndarray,
    bins: int = 10,
) -> float:
    predicted = classes[probabilities.argmax(axis=1)].astype(str)
    confidence = probabilities.max(axis=1)
    correct = predicted == np.asarray(labels, dtype=str)
    ece = 0.0
    edges = np.linspace(0, 1, bins + 1)
    for index in range(bins):
        if index == bins - 1:
            in_bin = (confidence >= edges[index]) & (confidence <= edges[index + 1])
        else:
            in_bin = (confidence >= edges[index]) & (confidence < edges[index + 1])
        if in_bin.any():
            ece += float(in_bin.mean()) * abs(
                float(correct[in_bin].mean()) - float(confidence[in_bin].mean())
            )
    return ece


def multiclass_brier(
    probabilities: np.ndarray, labels: Sequence[str], classes: np.ndarray
) -> float:
    mapping = {str(label): index for index, label in enumerate(classes)}
    targets = np.zeros_like(probabilities)
    unseen_true_label = np.zeros(len(labels), dtype=float)
    for index, label in enumerate(labels):
        if label in mapping:
            targets[index, mapping[label]] = 1.0
        else:
            # The model assigns zero probability to a true class absent from its
            # fitted class set, which contributes (0 - 1)^2 to the row score.
            unseen_true_label[index] = 1.0
    row_scores = np.square(probabilities - targets).sum(axis=1) + unseen_true_label
    return float(row_scores.mean())


def _false_routes(
    labels: Sequence[str], predictions: Sequence[str], limit: int = 20
) -> list[dict[str, Any]]:
    pairs = Counter(
        (truth, prediction)
        for truth, prediction in zip(labels, predictions, strict=True)
        if truth != prediction
    )
    return [
        {"actual": actual, "predicted": predicted, "count": count}
        for (actual, predicted), count in pairs.most_common(limit)
    ]


def evaluate_router(
    probabilities: np.ndarray,
    labels: Sequence[str],
    classes: np.ndarray,
    *,
    threshold: float,
) -> dict[str, Any]:
    predicted = classes[probabilities.argmax(axis=1)].astype(str)
    confidence = probabilities.max(axis=1)
    true = np.asarray(labels, dtype=str)
    accepted = confidence >= threshold
    unseen = sorted(set(true) - set(classes.astype(str)))
    metrics: dict[str, Any] = {
        "macro_f1": float(f1_score(true, predicted, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(true, predicted)),
        "ece": expected_calibration_error(probabilities, labels, classes),
        "brier": multiclass_brier(probabilities, labels, classes),
        "coverage": float(accepted.mean()),
        "abstention_rate": float(1.0 - accepted.mean()),
        "selective_accuracy": (
            float(accuracy_score(true[accepted], predicted[accepted]))
            if accepted.any()
            else None
        ),
        "selective_macro_f1": (
            float(
                f1_score(
                    true[accepted],
                    predicted[accepted],
                    average="macro",
                    zero_division=0,
                )
            )
            if accepted.any()
            else None
        ),
        "test_rows": len(true),
        "accepted_rows": int(accepted.sum()),
    }
    return {
        "metrics": metrics,
        "false_routes": _false_routes(true.tolist(), predicted.tolist()),
        "unseen_labels": {
            "labels": unseen,
            "row_count": int(sum(label in unseen for label in true)),
            "rate": float(sum(label in unseen for label in true) / max(len(true), 1)),
        },
    }


def _distribution_drift(
    rows: Sequence[TrainingRow],
    predictions: Sequence[str],
    *,
    training_rows: Sequence[TrainingRow],
) -> list[dict[str, Any]]:
    epsilon = 1e-6
    train_counts = Counter(row.label for row in training_rows)
    train_total = max(sum(train_counts.values()), 1)
    by_month: dict[str, list[tuple[TrainingRow, str]]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        by_month[row.month].append((row, prediction))
    output: list[dict[str, Any]] = []
    for month in sorted(by_month):
        pairs = by_month[month]
        actual = Counter(row.label for row, _ in pairs)
        predicted = Counter(value for _, value in pairs)
        products = sorted(set(train_counts) | set(actual) | set(predicted))
        month_size = len(pairs)
        components: list[dict[str, Any]] = []
        for product in products:
            baseline_share = train_counts[product] / train_total
            actual_share = actual[product] / month_size
            predicted_share = predicted[product] / month_size
            psi_component = (actual_share - baseline_share) * np.log(
                (actual_share + epsilon) / (baseline_share + epsilon)
            )
            components.append(
                {
                    "product": product,
                    "train_share": baseline_share,
                    "actual_share": actual_share,
                    "predicted_share": predicted_share,
                    "absolute_actual_share_shift": abs(actual_share - baseline_share),
                    "psi_component": float(psi_component),
                }
            )
        output.append(
            {
                "month": month,
                "sample_size": month_size,
                "actual_vs_train_psi": float(
                    sum(item["psi_component"] for item in components)
                ),
                "by_product": components,
            }
        )
    return output


def load_training_rows(database_path: Path = DUCKDB_PATH) -> list[TrainingRow]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        records = connection.execute(
            """
            SELECT complaint_id, date_received, narrative, product
            FROM complaints
            WHERE has_narrative IS TRUE
              AND narrative IS NOT NULL
              AND length(trim(narrative)) >= 20
              AND product IS NOT NULL
            ORDER BY date_received, complaint_id
            """
        ).fetchall()
        return [
            TrainingRow(str(cid), received, narrative, product)
            for cid, received, narrative, product in records
        ]
    finally:
        connection.close()


def train_router(
    rows: Sequence[TrainingRow],
    *,
    as_of: date,
    model_path: Path = MODEL_PATH,
    metrics_path: Path = MODEL_METRICS_PATH,
    snapshot_sha256: str = "unknown",
) -> dict[str, Any]:
    split = chronological_complete_month_split(rows, as_of=as_of)
    if len({row.label for row in split.train}) < 2:
        raise ValueError("training months must contain at least two product labels")
    min_df = 2 if len(split.train) >= 1_000 else 1
    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, 2),
        min_df=min_df,
        max_df=0.995,
        max_features=40_000,
        sublinear_tf=True,
        dtype=np.float32,
    )
    train_features = vectorizer.fit_transform([row.text for row in split.train])
    classifier = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=1e-5,
        max_iter=60,
        tol=1e-3,
        class_weight="balanced",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    classifier.fit(train_features, [row.label for row in split.train])
    classes = classifier.classes_

    calibration_features = vectorizer.transform([row.text for row in split.calibration])
    calibration_logits = _decision_logits(classifier, calibration_features)
    temperature, calibration_details = fit_temperature(
        calibration_logits, [row.label for row in split.calibration], classes
    )

    threshold_features = vectorizer.transform([row.text for row in split.threshold])
    threshold_probabilities = _softmax(
        _decision_logits(classifier, threshold_features), temperature
    )
    threshold, threshold_details = choose_abstention_threshold(
        threshold_probabilities, [row.label for row in split.threshold], classes
    )

    test_features = vectorizer.transform([row.text for row in split.test])
    test_probabilities = _softmax(
        _decision_logits(classifier, test_features), temperature
    )
    evaluation = evaluate_router(
        test_probabilities,
        [row.label for row in split.test],
        classes,
        threshold=threshold,
    )

    complete_rows = [
        row for row in rows if row.received < _complete_month_boundary(as_of)
    ]
    complete_probabilities = _softmax(
        _decision_logits(
            classifier, vectorizer.transform([row.text for row in complete_rows])
        ),
        temperature,
    )
    complete_predictions = classes[complete_probabilities.argmax(axis=1)].astype(str)
    drift = _distribution_drift(
        complete_rows, complete_predictions, training_rows=split.train
    )

    version_material = json.dumps(
        {
            "snapshot_sha256": snapshot_sha256,
            "schema": ROUTER_SCHEMA_VERSION,
            "classes": classes.astype(str).tolist(),
            "split": {
                "train": split.train_months,
                "calibration": split.calibration_month,
                "threshold": split.threshold_month,
                "test": split.test_month,
            },
        },
        sort_keys=True,
    ).encode("utf-8")
    model_version = (
        f"product-router-{hashlib.sha256(version_material).hexdigest()[:12]}"
    )
    generated_at = datetime.now(timezone.utc)
    split_payload = {
        "train_months": list(split.train_months),
        "calibration_month": split.calibration_month,
        "threshold_month": split.threshold_month,
        "test_month": split.test_month,
        "train_rows": len(split.train),
        "calibration_rows": len(split.calibration),
        "threshold_rows": len(split.threshold),
        "test_rows": len(split.test),
        "split_policy": "last three complete months reserved in order for calibration, threshold selection, and frozen test",
    }
    report = {
        "status": "trained",
        "schema_version": ROUTER_SCHEMA_VERSION,
        "model_version": model_version,
        "generated_at": generated_at.isoformat(),
        "target": "product",
        "metric_basis": "weekly_stratified_monthly_capped_snapshot_sample",
        "estimator": "word_tfidf_1_2gram_plus_sgd_log_loss",
        "snapshot_sha256": snapshot_sha256,
        "split": split_payload,
        "temperature": temperature,
        "calibration": calibration_details,
        "threshold": threshold,
        "threshold_selection": threshold_details,
        **evaluation,
        "drift": drift,
        "integrity": {
            "final_decisions_by_ai": False,
            "abstained_cases_require_human_review": True,
            "test_month_used_for_threshold_selection": False,
            "current_partial_month_excluded_from_training_and_evaluation": True,
        },
    }
    artifact = {
        "schema_version": ROUTER_SCHEMA_VERSION,
        "model_version": model_version,
        "trained_at": generated_at.isoformat(),
        "vectorizer": vectorizer,
        "classifier": classifier,
        "temperature": temperature,
        "threshold": threshold,
        "classes": classes,
        "split": split_payload,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    metrics_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    return report


def score_texts(artifact: dict[str, Any], texts: Sequence[str]) -> list[dict[str, Any]]:
    if not texts:
        return []
    vectorizer: TfidfVectorizer = artifact["vectorizer"]
    classifier: SGDClassifier = artifact["classifier"]
    classes = np.asarray(artifact["classes"])
    probabilities = _softmax(
        _decision_logits(classifier, vectorizer.transform(texts)),
        float(artifact["temperature"]),
    )
    indices = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    threshold = float(artifact["threshold"])
    return [
        {
            "predicted_product": str(classes[index]),
            "confidence": float(confidence[row_index]),
            "abstained": bool(confidence[row_index] < threshold),
        }
        for row_index, index in enumerate(indices)
    ]


def apply_router_to_warehouse(
    *,
    database_path: Path = DUCKDB_PATH,
    model_path: Path = MODEL_PATH,
    batch_size: int = 2_000,
) -> dict[str, int]:
    artifact = joblib.load(model_path)
    connection = duckdb.connect(str(database_path))
    scored_count = 0
    no_narrative_count = 0
    try:
        connection.execute("BEGIN TRANSACTION")
        rows = connection.execute(
            "SELECT complaint_id, narrative FROM complaints ORDER BY complaint_id"
        ).fetchall()
        updates: list[tuple[Any, ...]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            texts = [
                narrative for _, narrative in batch if narrative and narrative.strip()
            ]
            scores = iter(score_texts(artifact, texts))
            for complaint_id, narrative in batch:
                if narrative and narrative.strip():
                    score = next(scores)
                    updates.append(
                        (
                            score["predicted_product"],
                            score["confidence"],
                            score["abstained"],
                            complaint_id,
                        )
                    )
                    scored_count += 1
                else:
                    updates.append((None, None, True, complaint_id))
                    no_narrative_count += 1
            connection.executemany(
                """
                UPDATE complaints
                SET predicted_product = ?, prediction_confidence = ?, prediction_abstained = ?
                WHERE complaint_id = ?
                """,
                updates,
            )
            updates = []
        connection.execute("COMMIT")
        return {
            "scored_count": scored_count,
            "no_narrative_abstained_count": no_narrative_count,
        }
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
