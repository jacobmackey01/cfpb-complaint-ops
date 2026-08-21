from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field

from cfpb_triage.config import Settings, settings
from cfpb_triage.monitoring import SummaryEvaluationStore, SummaryFactualityReview
from cfpb_triage.repository import (
    CaseNotFoundError,
    ComplaintRepository,
    ReviewNotFoundError,
)
from cfpb_triage.schemas import (
    AnomaliesResponse,
    CasesResponse,
    HealthResponse,
    LineageResponse,
    OverviewMetrics,
    RouteDecisionRequest,
    RouteDecisionResponse,
    SourceKind,
    StrictModel,
    SummaryRequest,
    SummaryResponse,
    SummaryReviewRequest,
    SummaryReviewResponse,
    TrendsResponse,
)
from cfpb_triage.services.summary import (
    SummaryGroundingError,
    SummaryRefusedError,
    SummaryUnavailableError,
    build_summary_draft,
)


class CanonicalSummaryRequest(StrictModel):
    complaint_id: str = Field(min_length=1, max_length=100)
    requested_by: str = Field(min_length=2, max_length=100)


class CanonicalSummaryReviewRequest(StrictModel):
    reviewer_id: str = Field(min_length=2, max_length=100)
    decision: Literal["approve", "reject"]
    notes: str | None = Field(default=None, max_length=1000)


def create_app(
    *,
    repository: ComplaintRepository | None = None,
    app_settings: Settings = settings,
) -> FastAPI:
    repo = repository or ComplaintRepository(
        demo_mode=app_settings.demo_mode,
        allow_demo_fallback=app_settings.allow_demo_fallback,
        live_read_mode=app_settings.live_read_mode,
    )
    evaluation_store = SummaryEvaluationStore(
        database_path=repo.database_path,
        demo_mode=getattr(
            repo, "session_only", repo.source_kind.value.startswith("synthetic")
        ),
        source_kind=(
            repo.source_kind.value
            if hasattr(repo.source_kind, "value")
            else str(repo.source_kind)
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description=(
            "Human-in-the-loop complaint operations API. Model outputs are advisory; "
            "explicit reviewer actions are required for route and summary state changes."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )
    prefix = app_settings.api_prefix

    def health_payload() -> HealthResponse:
        model = repo.model_metrics()
        return HealthResponse(
            status="ok",
            source_kind=repo.source_kind,
            model_status=str(model.get("status", "unknown")),
            timestamp=datetime.now(timezone.utc),
        )

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    def root_health() -> HealthResponse:
        return health_payload()

    @application.get(f"{prefix}/health", response_model=HealthResponse, tags=["health"])
    def api_health() -> HealthResponse:
        return health_payload()

    @application.get(f"{prefix}/cases", response_model=CasesResponse, tags=["cases"])
    def list_cases(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 25,
        product: str | None = None,
        issue: str | None = None,
        manual_attention: bool | None = None,
        search: Annotated[str | None, Query(max_length=200)] = None,
    ) -> CasesResponse:
        return repo.list_cases(
            page=page,
            page_size=page_size,
            product=product,
            issue=issue,
            manual_attention=manual_attention,
            search=search,
        )

    @application.get(f"{prefix}/cases/{{complaint_id}}", tags=["cases"])
    def get_case(complaint_id: str):
        try:
            return repo.get_case(complaint_id)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Complaint not found") from exc

    def route_case(
        complaint_id: str, request: RouteDecisionRequest
    ) -> RouteDecisionResponse:
        try:
            return repo.record_route(complaint_id, request)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Complaint not found") from exc

    application.patch(
        f"{prefix}/cases/{{complaint_id}}/route",
        response_model=RouteDecisionResponse,
        tags=["human review"],
    )(route_case)
    application.post(
        f"{prefix}/cases/{{complaint_id}}/route",
        response_model=RouteDecisionResponse,
        tags=["human review"],
    )(route_case)

    def _generate_summary(*, complaint_id: str, requested_by: str) -> SummaryResponse:
        started = time.perf_counter()
        try:
            case = repo.get_case(complaint_id)
            if (
                case.source_kind == SourceKind.CFPB_PUBLIC
                and not app_settings.llm_summary_enabled
            ):
                raise SummaryUnavailableError(
                    "LLM summary generation is disabled; manual review is required"
                )
            if not case.narrative:
                raise SummaryUnavailableError("This case has no published narrative")
            draft = build_summary_draft(
                complaint_id=complaint_id,
                narrative=case.narrative,
                source_kind=case.source_kind,
            )
            repo.save_summary(draft, requested_by)
            repo.log_event(
                event_type="summary_generation",
                success=True,
                latency_ms=draft.latency_ms,
                cost_usd=draft.cost_usd,
                detail=draft.provider,
            )
            return SummaryResponse(draft=draft)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Complaint not found") from exc
        except SummaryRefusedError as exc:
            repo.log_event(
                event_type="summary_refusal",
                success=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                detail=str(exc)[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The summary provider refused this request; manual review is required.",
            ) from exc
        except SummaryGroundingError as exc:
            repo.log_event(
                event_type="summary_grounding_failure",
                success=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                detail=str(exc)[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Generated evidence did not pass exact quote validation; manual review is required.",
            ) from exc
        except SummaryUnavailableError as exc:
            repo.log_event(
                event_type="summary_failure",
                success=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                detail=str(exc)[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @application.post(
        f"{prefix}/summaries",
        response_model=SummaryResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["AI draft with human review"],
    )
    def create_summary(request: CanonicalSummaryRequest) -> SummaryResponse:
        return _generate_summary(
            complaint_id=request.complaint_id,
            requested_by=request.requested_by,
        )

    @application.post(
        f"{prefix}/cases/{{complaint_id}}/summary",
        response_model=SummaryResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["AI draft with human review"],
    )
    def create_case_summary(
        complaint_id: str, request: SummaryRequest
    ) -> SummaryResponse:
        return _generate_summary(
            complaint_id=complaint_id,
            requested_by=request.requested_by,
        )

    def _review_summary(
        summary_id: str,
        reviewer_id: str,
        decision: Literal["approve", "reject"],
        notes: str | None,
    ) -> SummaryReviewResponse:
        request = SummaryReviewRequest(
            summary_id=summary_id,
            reviewer_id=reviewer_id,
            decision=decision,
            notes=notes,
        )
        try:
            return repo.review_summary(summary_id, request)
        except ReviewNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Summary draft not found"
            ) from exc

    @application.post(
        f"{prefix}/summaries/{{summary_id}}/review",
        response_model=SummaryReviewResponse,
        tags=["human review"],
    )
    def review_summary(
        summary_id: str, request: CanonicalSummaryReviewRequest
    ) -> SummaryReviewResponse:
        return _review_summary(
            summary_id,
            request.reviewer_id,
            request.decision,
            request.notes,
        )

    @application.post(
        f"{prefix}/cases/{{complaint_id}}/summary-review",
        response_model=SummaryReviewResponse,
        tags=["human review"],
    )
    def review_case_summary(
        complaint_id: str, request: SummaryReviewRequest
    ) -> SummaryReviewResponse:
        response = _review_summary(
            request.summary_id,
            request.reviewer_id,
            request.decision,
            request.notes,
        )
        if response.complaint_id != complaint_id:
            raise HTTPException(
                status_code=409, detail="Summary does not belong to this complaint"
            )
        return response

    @application.post(
        f"{prefix}/summaries/{{summary_id}}/evaluation",
        status_code=status.HTTP_201_CREATED,
        tags=["model monitoring"],
    )
    def record_summary_evaluation(summary_id: str, request: SummaryFactualityReview):
        return evaluation_store.record(summary_id, request)

    @application.get(
        f"{prefix}/summaries/evaluation-metrics", tags=["model monitoring"]
    )
    def summary_evaluation_metrics():
        return evaluation_store.metrics()

    @application.get(
        f"{prefix}/metrics/overview",
        response_model=OverviewMetrics,
        tags=["operations metrics"],
    )
    def overview() -> OverviewMetrics:
        return repo.overview()

    @application.get(f"{prefix}/metrics/source-volume", tags=["operations metrics"])
    def source_volume():
        return repo.source_volume()

    @application.get(f"{prefix}/metrics/system", tags=["model monitoring"])
    def system_metrics():
        result = repo.system_metrics()
        result["summary_factuality"] = evaluation_store.metrics()
        return result

    @application.get(
        f"{prefix}/trends", response_model=TrendsResponse, tags=["operations metrics"]
    )
    def trends(
        response: Response,
        dimension: Literal["product", "issue"] = "product",
        days: Annotated[int, Query(ge=7, le=400)] = 90,
    ) -> TrendsResponse:
        response.headers["X-Metric-Basis"] = (
            "synthetic_offline_demo"
            if repo.source_kind.value.startswith("synthetic")
            else (
                "bounded_live_read"
                if app_settings.live_read_mode
                else "capped_snapshot_sample"
            )
        )
        return repo.trends(dimension=dimension, days=days)

    @application.get(
        f"{prefix}/trends/anomalies",
        response_model=AnomaliesResponse,
        tags=["operations metrics"],
    )
    def anomalies(
        response: Response,
        dimension: Literal["product", "issue", "all"] = "all",
    ) -> AnomaliesResponse:
        response.headers["X-Metric-Basis"] = (
            "synthetic_offline_demo"
            if repo.source_kind.value.startswith("synthetic")
            else (
                "bounded_live_read"
                if app_settings.live_read_mode
                else "capped_snapshot_sample_signal"
            )
        )
        return repo.anomalies(dimension=dimension)

    @application.get(f"{prefix}/model/metrics", tags=["model monitoring"])
    def model_metrics():
        return repo.model_metrics()

    @application.get(f"{prefix}/quality", tags=["data quality"])
    def quality():
        return repo.quality()

    @application.get(
        f"{prefix}/lineage", response_model=LineageResponse, tags=["data quality"]
    )
    def lineage() -> LineageResponse:
        return repo.lineage()

    return application


app = create_app()
