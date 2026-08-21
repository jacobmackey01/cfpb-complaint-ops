from __future__ import annotations

import pytest
from cfpb_triage.cli import main
from cfpb_triage.monitoring import SummaryEvaluationStore, SummaryFactualityReview
from cfpb_triage.schemas import UsageRecord
from cfpb_triage.services.summary import (
    SummaryUnavailableError,
    estimated_cost_usd,
)


def test_unknown_model_is_never_charged_at_luna_price() -> None:
    usage = UsageRecord(input_tokens=100, output_tokens=50)
    with pytest.raises(SummaryUnavailableError):
        estimated_cost_usd(usage, model="different-model")


def test_empty_factuality_sample_exposes_frozen_review_contract() -> None:
    metrics = SummaryEvaluationStore(demo_mode=True).metrics()
    assert metrics["reviewed_sample_count"] == 0
    assert metrics["status"] == "unavailable_until_frozen_sample_reviewed"
    assert metrics["rubric_version"] == "summary-factuality-v1"
    assert metrics["sample_selection"]["seed"] == 42
    assert metrics["sample_selection"]["strata"] == ["month", "product"]


def test_bootstrap_demo_is_read_only_and_explicit(capsys) -> None:
    assert main(["bootstrap-demo"]) == 0
    output = capsys.readouterr().out
    assert '"source_kind": "synthetic_offline_demo"' in output
    assert '"writes_performed": false' in output


def test_factuality_metrics_preserve_public_live_source_kind() -> None:
    store = SummaryEvaluationStore(
        demo_mode=True,
        source_kind="cfpb_public",
    )
    store.record(
        "live-summary-1",
        SummaryFactualityReview(
            reviewer_id="reviewer-1",
            factuality_score=5,
            all_claims_supported=True,
            quotes_exact=True,
        ),
    )
    assert store.metrics()["measurement_basis"] == "manual_reviews_of_cfpb_public"
