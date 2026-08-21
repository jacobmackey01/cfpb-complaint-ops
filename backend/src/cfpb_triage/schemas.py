from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CFPB_LIMITATION = (
    "CFPB complaints are not a representative statistical sample. Raw company "
    "complaint counts must not be interpreted as comparative company performance "
    "without appropriate market-share denominators."
)
LIVE_READ_NOTICE = "Bounded live CFPB read: at most 25 current API records are held in process memory; no raw snapshot or DuckDB persistence is used. This is not a representative statistical sample, exact population volume, trained model, or production monitoring artifact."

NARRATIVE_NOTICE = (
    "Published narratives are included only with consumer consent and after the "
    "CFPB takes steps to remove personal information."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceKind(StrEnum):
    CFPB_PUBLIC = "cfpb_public"
    SYNTHETIC_DEMO = "synthetic_offline_demo"


class CaseRecord(StrictModel):
    complaint_id: str
    date_received: date
    product: str
    issue: str
    company: str | None = None
    state: str | None = None
    submitted_via: str | None = None
    timely: bool | None = None
    narrative: str | None = None
    has_narrative: bool = False
    predicted_product: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    abstained: bool = False
    requires_manual_attention: bool = False
    attention_reasons: list[str] = Field(default_factory=list)
    route_status: Literal["unreviewed", "approved", "overridden", "rejected"] = (
        "unreviewed"
    )
    assigned_product: str | None = None
    source_kind: SourceKind


class CasesResponse(StrictModel):
    items: list[CaseRecord]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    source_kind: SourceKind
    as_of: date
    limitation: str = CFPB_LIMITATION


class OverviewMetrics(StrictModel):
    source_kind: SourceKind
    as_of: date
    total_complaints: int = Field(ge=0)
    narrative_count: int = Field(ge=0)
    narrative_rate: float = Field(ge=0, le=1)
    timely_response_count: int = Field(ge=0)
    timely_response_rate: float = Field(ge=0, le=1)
    manual_attention_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    model_status: str
    limitations: list[str] = Field(
        default_factory=lambda: [CFPB_LIMITATION, NARRATIVE_NOTICE]
    )


class TrendPoint(StrictModel):
    date: date
    label: str
    count: int = Field(ge=0)


class TrendsResponse(StrictModel):
    metric_basis: str = "daily_stratified_monthly_capped_snapshot_sample"
    dimension: Literal["product", "issue"]
    series: list[TrendPoint]
    source_kind: SourceKind
    as_of: date


class AnomalyRecord(StrictModel):
    dimension: Literal["product", "issue"]
    label: str
    window_start: date
    window_end: date
    current_count: int = Field(ge=0)
    baseline_median: float = Field(ge=0)
    robust_z: float
    severity: Literal["high", "medium", "low"]


class AnomaliesResponse(StrictModel):
    metric_basis: str = "daily_stratified_monthly_capped_snapshot_sample"
    items: list[AnomalyRecord]
    publication_lag_days: int = 15
    cutoff_date: date
    source_kind: SourceKind


class UsageRecord(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class EvidenceQuote(StrictModel):
    text: str = Field(min_length=1, max_length=800)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_span(self) -> EvidenceQuote:
        if self.end <= self.start:
            raise ValueError("quote end must be greater than start")
        return self


class LLMSummaryPayload(StrictModel):
    """Schema passed directly to Responses structured-output parsing."""

    headline: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=1200)
    key_points: list[str] = Field(min_length=1, max_length=6)
    evidence_quotes: list[EvidenceQuote] = Field(min_length=1, max_length=4)
    missing_information: list[str] = Field(default_factory=list, max_length=6)
    risk_flags: list[str] = Field(default_factory=list, max_length=6)
    recommended_human_actions: list[str] = Field(default_factory=list, max_length=5)


class SummaryDraft(LLMSummaryPayload):
    summary_id: str
    complaint_id: str
    status: Literal["pending_review", "approved", "rejected", "refused"]
    reviewer_required: bool = True
    final_decision_allowed: bool = False
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    usage: UsageRecord = Field(default_factory=UsageRecord)
    source_kind: SourceKind
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SummaryResponse(StrictModel):
    draft: SummaryDraft


class SummaryRequest(StrictModel):
    complaint_id: str | None = None
    requested_by: str = Field(min_length=2, max_length=100)


class SummaryReviewRequest(StrictModel):
    summary_id: str
    reviewer_id: str = Field(min_length=2, max_length=100)
    decision: Literal["approve", "reject"]
    notes: str | None = Field(default=None, max_length=1000)


class SummaryReviewResponse(StrictModel):
    summary_id: str
    complaint_id: str
    reviewer_id: str
    decision: Literal["approve", "reject"]
    status: Literal["approved", "rejected"]
    reviewed_at: datetime
    final_decision_allowed: bool = False


class RouteDecisionRequest(StrictModel):
    reviewer_id: str = Field(min_length=2, max_length=100)
    decision: Literal["approve", "override", "reject"]
    approved_route: str | None = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def route_required(self) -> RouteDecisionRequest:
        if self.decision in {"approve", "override"} and not self.approved_route:
            raise ValueError("approved_route is required for approve or override")
        return self


class RouteDecisionResponse(StrictModel):
    complaint_id: str
    reviewer_id: str
    decision: Literal["approve", "override", "reject"]
    approved_route: str | None
    status: Literal["approved", "overridden", "rejected"]
    reviewed_at: datetime
    ai_made_final_decision: Literal[False] = False


class QualityCheckResult(StrictModel):
    name: str
    passed: bool
    severity: Literal["critical", "high", "medium", "low"]
    observed: int | float | str | None
    threshold: int | float | str | None
    detail: str


class QualityReport(StrictModel):
    generated_at: datetime
    snapshot_sha256: str
    row_count: int = Field(ge=0)
    passed: bool
    checks: list[QualityCheckResult]
    column_profile: dict[str, dict[str, Any]]


class LineageResponse(StrictModel):
    source: str
    source_kind: SourceKind
    snapshot_manifest: dict[str, Any]
    transformations: list[dict[str, str]]
    hashes: dict[str, str]
    metric_definitions: dict[str, str]
    limitations: list[str]


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    source_kind: SourceKind
    model_status: str
    timestamp: datetime
