from __future__ import annotations

from cfpb_triage.repository import ComplaintRepository


def test_system_metrics_publish_rates_and_denominators(tmp_path) -> None:
    repository = ComplaintRepository(
        database_path=tmp_path / "missing.duckdb", demo_mode=True
    )
    repository.log_event(
        event_type="summary_generation",
        success=True,
        latency_ms=100,
        cost_usd=0.001,
    )
    repository.log_event(
        event_type="summary_refusal",
        success=False,
        latency_ms=200,
        cost_usd=0,
    )
    metrics = repository.system_metrics()
    assert metrics["request_count"] == 2
    assert metrics["failure_count"] == 1
    assert metrics["refusal_count"] == 1
    assert metrics["failure_rate"] == 0.5
    assert metrics["refusal_rate"] == 0.5
    assert metrics["rate_denominator"] == 2
    assert metrics["latency_observation_count"] == 2
    assert metrics["p50_latency_ms"] is not None
    assert metrics["p95_latency_ms"] is not None
