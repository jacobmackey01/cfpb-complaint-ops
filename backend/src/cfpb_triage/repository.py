from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import duckdb
import httpx

from cfpb_triage.config import settings
from cfpb_triage.data.snapshot import _hit_source, normalize_source
from cfpb_triage.data.warehouse import initialize_review_tables
from cfpb_triage.modeling.anomalies import (
    PUBLICATION_LAG_DAYS,
    anomaly_cutoff,
    detect_volume_anomalies,
)
from cfpb_triage.paths import (
    DUCKDB_PATH,
    MANIFEST_PATH,
    MODEL_METRICS_PATH,
    QUALITY_PATH,
)
from cfpb_triage.schemas import (
    CFPB_LIMITATION,
    LIVE_READ_NOTICE,
    NARRATIVE_NOTICE,
    AnomaliesResponse,
    CaseRecord,
    CasesResponse,
    LineageResponse,
    OverviewMetrics,
    RouteDecisionRequest,
    RouteDecisionResponse,
    SourceKind,
    SummaryDraft,
    SummaryReviewRequest,
    SummaryReviewResponse,
    TrendPoint,
    TrendsResponse,
)
from cfpb_triage.services.demo import DEMO_NOTICE, synthetic_cases
from cfpb_triage.services.summary import MODEL_PRICING

LIVE_READ_LIMIT = 25


class CaseNotFoundError(LookupError):
    pass


class ReviewNotFoundError(LookupError):
    pass


class ComplaintRepository:
    def __init__(
        self,
        *,
        database_path: Path = DUCKDB_PATH,
        manifest_path: Path = MANIFEST_PATH,
        demo_mode: bool = False,
        allow_demo_fallback: bool = True,
        live_read_mode: bool = False,
        demo_as_of: date | None = None,
    ) -> None:
        self.database_path = database_path
        self.manifest_path = manifest_path
        self._live = bool(live_read_mode and not demo_mode)
        self._demo = bool(
            demo_mode
            or (allow_demo_fallback and not database_path.exists() and not self._live)
        )
        if not self._demo and not self._live and not database_path.exists():
            raise FileNotFoundError(f"DuckDB database does not exist: {database_path}")
        self._demo_cases = synthetic_cases(demo_as_of) if self._demo else []
        self._live_cases: list[CaseRecord] = []
        self._live_loaded = False
        self._live_error: str | None = None
        self._demo_routes: dict[str, RouteDecisionResponse] = {}
        self._demo_summaries: dict[str, SummaryDraft] = {}
        self._demo_summary_reviews: dict[str, SummaryReviewResponse] = {}
        self._demo_events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def _ensure_live_cases(self) -> None:
        if not self._live or self._live_loaded:
            return
        try:
            response = httpx.get(
                settings.cfpb_api_url,
                params={
                    "size": LIVE_READ_LIMIT,
                    "frm": 0,
                    "sort": "created_date_desc",
                    "no_aggs": "true",
                    "no_highlight": "true",
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; CFPBComplaintResearch/0.1; "
                        "+https://github.com/jacobmackey01)"
                    ),
                    "Referer": (
                        "https://www.consumerfinance.gov/data-research/consumer-complaints/"
                    ),
                },
                follow_redirects=True,
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json()
            hits = payload.get("hits", {}).get("hits", [])
            if not isinstance(hits, list):
                raise TypeError("CFPB API returned malformed hits")
            cases: list[CaseRecord] = []
            for hit in hits[:LIVE_READ_LIMIT]:
                if not isinstance(hit, dict):
                    continue
                row = normalize_source(_hit_source(hit))
                if not row.get("complaint_id") or not row.get("date_received"):
                    continue
                if not row.get("product") or not row.get("issue"):
                    continue
                cases.append(
                    CaseRecord(
                        complaint_id=str(row["complaint_id"]),
                        date_received=date.fromisoformat(str(row["date_received"])),
                        product=str(row["product"]),
                        issue=str(row["issue"]),
                        company=row.get("company"),
                        state=row.get("state"),
                        submitted_via=row.get("submitted_via"),
                        timely=row.get("timely"),
                        narrative=row.get("narrative"),
                        has_narrative=bool(row.get("has_narrative")),
                        predicted_product=None,
                        confidence=None,
                        abstained=True,
                        requires_manual_attention=True,
                        attention_reasons=["live_read_has_no_trained_router"],
                        source_kind=SourceKind.CFPB_PUBLIC,
                    )
                )
            self._live_cases = cases
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self._live_error = str(exc)[:300]
            self._live_cases = []
        finally:
            self._live_loaded = True

    def _memory_cases(self) -> list[CaseRecord]:
        self._ensure_live_cases()
        return self._demo_cases if self._demo else self._live_cases

    @property
    def session_only(self) -> bool:
        return self._demo or self._live

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SYNTHETIC_DEMO if self._demo else SourceKind.CFPB_PUBLIC

    @property
    def limitation(self) -> str:
        if self._demo:
            return DEMO_NOTICE
        if self._live:
            return f"{LIVE_READ_NOTICE} {CFPB_LIMITATION}"
        return CFPB_LIMITATION

    def _connect(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(str(self.database_path), read_only=read_only)
        if not read_only:
            initialize_review_tables(connection)
        return connection

    def _as_of(self) -> date:
        if self._demo or self._live:
            rows = self._memory_cases()
            return max(
                (row.date_received for row in rows),
                default=datetime.now(timezone.utc).date(),
            )
        connection = self._connect(read_only=True)
        try:
            value = connection.execute(
                "SELECT max(date_received) FROM complaints"
            ).fetchone()[0]
            return value or datetime.now(timezone.utc).date()
        finally:
            connection.close()

    @staticmethod
    def _demo_match(
        row: CaseRecord,
        *,
        product: str | None,
        issue: str | None,
        manual_attention: bool | None,
        search: str | None,
    ) -> bool:
        if product and row.product != product:
            return False
        if issue and row.issue != issue:
            return False
        if (
            manual_attention is not None
            and row.requires_manual_attention != manual_attention
        ):
            return False
        if search:
            needle = search.casefold()
            haystack = " ".join(
                filter(
                    None,
                    [
                        row.complaint_id,
                        row.product,
                        row.issue,
                        row.company,
                        row.narrative,
                    ],
                )
            ).casefold()
            if needle not in haystack:
                return False
        return True

    def list_cases(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        product: str | None = None,
        issue: str | None = None,
        manual_attention: bool | None = None,
        search: str | None = None,
    ) -> CasesResponse:
        if self._demo or self._live:
            with self._lock:
                items: list[CaseRecord] = []
                for original in self._memory_cases():
                    row = original.model_copy(deep=True)
                    review = self._demo_routes.get(row.complaint_id)
                    if review:
                        row.route_status = review.status
                        row.assigned_product = review.approved_route
                    if self._demo_match(
                        row,
                        product=product,
                        issue=issue,
                        manual_attention=manual_attention,
                        search=search,
                    ):
                        items.append(row)
                total = len(items)
                start = (page - 1) * page_size
                return CasesResponse(
                    items=items[start : start + page_size],
                    total=total,
                    page=page,
                    page_size=page_size,
                    source_kind=self.source_kind,
                    as_of=self._as_of(),
                    limitation=self.limitation,
                )

        conditions = ["1=1"]
        params: list[Any] = []
        if product:
            conditions.append("o.product = ?")
            params.append(product)
        if issue:
            conditions.append("o.issue = ?")
            params.append(issue)
        if manual_attention is not None:
            conditions.append("o.requires_manual_attention = ?")
            params.append(manual_attention)
        if search:
            conditions.append(
                "(o.complaint_id ILIKE ? OR o.product ILIKE ? OR o.issue ILIKE ? "
                "OR coalesce(o.company, '') ILIKE ? OR coalesce(o.narrative, '') ILIKE ?)"
            )
            pattern = f"%{search}%"
            params.extend([pattern] * 5)
        where = " AND ".join(conditions)
        connection = self._connect(read_only=True)
        try:
            total = int(
                connection.execute(
                    f"SELECT count(*) FROM operational_cases o WHERE {where}", params
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                WITH latest_route AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY complaint_id ORDER BY reviewed_at DESC
                    ) AS row_number
                    FROM route_reviews
                )
                SELECT
                    o.complaint_id, o.date_received, o.product, o.issue, o.company,
                    o.state, o.submitted_via, o.timely, o.narrative, o.has_narrative,
                    o.predicted_product, o.prediction_confidence,
                    o.prediction_abstained, o.requires_manual_attention,
                    o.attention_reasons,
                    CASE latest_route.decision
                        WHEN 'approve' THEN 'approved'
                        WHEN 'override' THEN 'overridden'
                        WHEN 'reject' THEN 'rejected'
                        ELSE 'unreviewed'
                    END AS route_status,
                    latest_route.approved_route
                FROM operational_cases o
                LEFT JOIN latest_route
                  ON latest_route.complaint_id = o.complaint_id
                 AND latest_route.row_number = 1
                WHERE {where}
                ORDER BY o.date_received DESC, o.complaint_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        finally:
            connection.close()
        items = [
            CaseRecord(
                complaint_id=row[0],
                date_received=row[1],
                product=row[2],
                issue=row[3],
                company=row[4],
                state=row[5],
                submitted_via=row[6],
                timely=row[7],
                narrative=row[8],
                has_narrative=row[9],
                predicted_product=row[10],
                confidence=row[11],
                abstained=row[12],
                requires_manual_attention=row[13],
                attention_reasons=list(row[14] or []),
                route_status=row[15],
                assigned_product=row[16],
                source_kind=self.source_kind,
            )
            for row in rows
        ]
        return CasesResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            source_kind=self.source_kind,
            as_of=self._as_of(),
            limitation=self.limitation,
        )

    def get_case(self, complaint_id: str) -> CaseRecord:
        if self._demo or self._live:
            with self._lock:
                for original in self._memory_cases():
                    if original.complaint_id == complaint_id:
                        row = original.model_copy(deep=True)
                        review = self._demo_routes.get(complaint_id)
                        if review:
                            row.route_status = review.status
                            row.assigned_product = review.approved_route
                        return row
            raise CaseNotFoundError(complaint_id)
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                """
                WITH latest_route AS (
                    SELECT *, row_number() OVER (ORDER BY reviewed_at DESC) AS rn
                    FROM route_reviews WHERE complaint_id = ?
                )
                SELECT
                    o.complaint_id, o.date_received, o.product, o.issue, o.company,
                    o.state, o.submitted_via, o.timely, o.narrative, o.has_narrative,
                    o.predicted_product, o.prediction_confidence,
                    o.prediction_abstained, o.requires_manual_attention,
                    o.attention_reasons,
                    CASE latest_route.decision
                        WHEN 'approve' THEN 'approved'
                        WHEN 'override' THEN 'overridden'
                        WHEN 'reject' THEN 'rejected'
                        ELSE 'unreviewed'
                    END,
                    latest_route.approved_route
                FROM operational_cases o
                LEFT JOIN latest_route ON latest_route.rn = 1
                WHERE o.complaint_id = ?
                """,
                [complaint_id, complaint_id],
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise CaseNotFoundError(complaint_id)
        return CaseRecord(
            complaint_id=row[0],
            date_received=row[1],
            product=row[2],
            issue=row[3],
            company=row[4],
            state=row[5],
            submitted_via=row[6],
            timely=row[7],
            narrative=row[8],
            has_narrative=row[9],
            predicted_product=row[10],
            confidence=row[11],
            abstained=row[12],
            requires_manual_attention=row[13],
            attention_reasons=list(row[14] or []),
            route_status=row[15],
            assigned_product=row[16],
            source_kind=self.source_kind,
        )

    def overview(self) -> OverviewMetrics:
        if self._demo or self._live:
            rows = self._memory_cases()
            total = len(rows)
            timely_denominator = sum(row.timely is not None for row in rows)
            timely_count = sum(row.timely is True for row in rows)
            return OverviewMetrics(
                source_kind=self.source_kind,
                as_of=self._as_of(),
                total_complaints=total,
                narrative_count=sum(row.has_narrative for row in rows),
                narrative_rate=sum(row.has_narrative for row in rows) / max(total, 1),
                timely_response_count=timely_count,
                timely_response_rate=timely_count / max(timely_denominator, 1),
                manual_attention_count=sum(
                    row.requires_manual_attention for row in rows
                ),
                abstained_count=sum(row.abstained for row in rows),
                model_status=(
                    "synthetic_offline_demo_scores" if self._demo else "not_trained"
                ),
                limitations=[self.limitation],
            )
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT
                    count(*),
                    count(*) FILTER (WHERE has_narrative),
                    count(*) FILTER (WHERE timely IS NOT NULL),
                    count(*) FILTER (WHERE timely IS TRUE),
                    count(*) FILTER (WHERE requires_manual_attention),
                    count(*) FILTER (WHERE prediction_abstained)
                FROM operational_cases
                """
            ).fetchone()
        finally:
            connection.close()
        total, narratives, timely_denominator, timely_count, attention, abstained = map(
            int, row
        )
        return OverviewMetrics(
            source_kind=self.source_kind,
            as_of=self._as_of(),
            total_complaints=total,
            narrative_count=narratives,
            narrative_rate=narratives / max(total, 1),
            timely_response_count=timely_count,
            timely_response_rate=timely_count / max(timely_denominator, 1),
            manual_attention_count=attention,
            abstained_count=abstained,
            model_status="trained" if MODEL_METRICS_PATH.exists() else "not_trained",
            limitations=[
                CFPB_LIMITATION,
                NARRATIVE_NOTICE,
                "Overview composition and response metrics use the capped snapshot sample; exact CFPB window volumes are exposed separately.",
            ],
        )

    def source_volume(self) -> dict[str, Any]:
        if self._live:
            self._ensure_live_cases()
            return {
                "source_kind": self.source_kind.value,
                "metric_basis": "bounded_live_read",
                "exact_population_volume": False,
                "items": [],
                "limitation": f"{LIVE_READ_NOTICE} Source-window totals are unavailable and are not substituted by the bounded records.",
            }
        if self._demo:
            return {
                "source_kind": self.source_kind.value,
                "metric_basis": "synthetic_offline_demo",
                "exact_population_volume": False,
                "items": [],
                "limitation": DEMO_NOTICE,
            }
        connection = self._connect(read_only=True)
        try:
            exists = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name='source_window_metrics'"
            ).fetchone()[0]
            if not exists:
                return {
                    "source_kind": self.source_kind.value,
                    "metric_basis": "unavailable",
                    "exact_population_volume": False,
                    "items": [],
                    "limitation": "Source-window totals have not been materialized; sample rows are not substituted.",
                }
            rows = connection.execute(
                """
                SELECT window_name, date_received_min, date_received_max_exclusive,
                       complete_month, source_total, source_total_relation,
                       selected_sample_rows
                FROM source_window_metrics ORDER BY date_received_min
                """
            ).fetchall()
        finally:
            connection.close()
        exact = all(row[5] == "eq" for row in rows)
        return {
            "source_kind": self.source_kind.value,
            "metric_basis": "cfpb_api_window_total",
            "exact_population_volume": exact,
            "items": [
                {
                    "window_name": row[0],
                    "date_received_min": row[1].isoformat(),
                    "date_received_max_exclusive": row[2].isoformat(),
                    "complete_month": row[3],
                    "source_total": row[4],
                    "source_total_relation": row[5],
                    "selected_sample_rows": row[6],
                }
                for row in rows
            ],
            "limitation": CFPB_LIMITATION,
        }

    def trends(
        self,
        *,
        dimension: Literal["product", "issue"],
        days: int,
    ) -> TrendsResponse:
        cutoff = self._as_of() - timedelta(days=days - 1)
        if self._demo or self._live:
            counts: dict[tuple[date, str], int] = {}
            for row in self._memory_cases():
                if row.date_received >= cutoff:
                    label = row.product if dimension == "product" else row.issue
                    counts[(row.date_received, label)] = (
                        counts.get((row.date_received, label), 0) + 1
                    )
            points = [
                TrendPoint(date=key[0], label=key[1], count=value)
                for key, value in sorted(counts.items())
            ]
        else:
            view = (
                "daily_product_volume"
                if dimension == "product"
                else "daily_issue_volume"
            )
            connection = self._connect(read_only=True)
            try:
                rows = connection.execute(
                    f"SELECT date, label, count FROM {view} WHERE date >= ? ORDER BY date, label",
                    [cutoff],
                ).fetchall()
            finally:
                connection.close()
            points = [
                TrendPoint(date=row[0], label=row[1], count=row[2]) for row in rows
            ]
        return TrendsResponse(
            metric_basis=(
                "bounded_live_read"
                if self._live
                else "daily_stratified_monthly_capped_snapshot_sample"
            ),
            limitation=self.limitation,
            dimension=dimension,
            series=points,
            source_kind=self.source_kind,
            as_of=self._as_of(),
        )

    def anomalies(
        self,
        *,
        dimension: Literal["product", "issue", "all"] = "all",
        as_of: date | None = None,
    ) -> AnomaliesResponse:
        as_of = as_of or self._as_of()
        if self._demo or self._live:
            return AnomaliesResponse(
                metric_basis=(
                    "bounded_live_read"
                    if self._live
                    else "daily_stratified_monthly_capped_snapshot_sample"
                ),
                limitation=self.limitation,
                items=[],
                publication_lag_days=PUBLICATION_LAG_DAYS,
                cutoff_date=anomaly_cutoff(as_of),
                source_kind=self.source_kind,
            )
        dimensions: list[Literal["product", "issue"]] = (
            ["product", "issue"] if dimension == "all" else [dimension]
        )
        connection = self._connect(read_only=True)
        try:
            items = []
            for selected in dimensions:
                view = (
                    "daily_product_volume"
                    if selected == "product"
                    else "daily_issue_volume"
                )
                rows = connection.execute(
                    f"SELECT date, label, count FROM {view}"
                ).fetchall()
                items.extend(
                    detect_volume_anomalies(rows, dimension=selected, as_of=as_of)
                )
        finally:
            connection.close()
        return AnomaliesResponse(
            metric_basis=(
                "bounded_live_read"
                if self._live
                else "daily_stratified_monthly_capped_snapshot_sample"
            ),
            limitation=self.limitation,
            items=items,
            publication_lag_days=PUBLICATION_LAG_DAYS,
            cutoff_date=anomaly_cutoff(as_of),
            source_kind=self.source_kind,
        )

    def record_route(
        self, complaint_id: str, request: RouteDecisionRequest
    ) -> RouteDecisionResponse:
        self.get_case(complaint_id)
        status = {
            "approve": "approved",
            "override": "overridden",
            "reject": "rejected",
        }[request.decision]
        response = RouteDecisionResponse(
            complaint_id=complaint_id,
            reviewer_id=request.reviewer_id,
            decision=request.decision,
            approved_route=request.approved_route,
            status=status,  # type: ignore[arg-type]
            reviewed_at=datetime.now(timezone.utc),
            ai_made_final_decision=False,
        )
        if self._demo or self._live:
            with self._lock:
                self._demo_routes[complaint_id] = response
            return response
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO route_reviews VALUES (?, ?, ?, ?, ?, ?)",
                [
                    complaint_id,
                    request.reviewer_id,
                    request.decision,
                    request.approved_route,
                    request.notes,
                    response.reviewed_at,
                ],
            )
        finally:
            connection.close()
        return response

    def save_summary(self, draft: SummaryDraft, requested_by: str) -> None:
        if self._demo or self._live:
            with self._lock:
                self._demo_summaries[draft.summary_id] = draft
            return
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO summary_drafts VALUES (?, ?, ?, ?, ?, ?)",
                [
                    draft.summary_id,
                    draft.complaint_id,
                    draft.model_dump_json(),
                    draft.status,
                    requested_by,
                    draft.created_at,
                ],
            )
        finally:
            connection.close()

    def review_summary(
        self, summary_id: str, request: SummaryReviewRequest
    ) -> SummaryReviewResponse:
        reviewed_at = datetime.now(timezone.utc)
        if self._demo or self._live:
            with self._lock:
                draft = self._demo_summaries.get(summary_id)
                if draft is None:
                    raise ReviewNotFoundError(summary_id)
                status = "approved" if request.decision == "approve" else "rejected"
                draft.status = status
                response = SummaryReviewResponse(
                    summary_id=summary_id,
                    complaint_id=draft.complaint_id,
                    reviewer_id=request.reviewer_id,
                    decision=request.decision,
                    status=status,
                    reviewed_at=reviewed_at,
                    final_decision_allowed=False,
                )
                self._demo_summary_reviews[summary_id] = response
                return response
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT complaint_id FROM summary_drafts WHERE summary_id = ?",
                [summary_id],
            ).fetchone()
            if row is None:
                raise ReviewNotFoundError(summary_id)
            status = "approved" if request.decision == "approve" else "rejected"
            connection.execute("BEGIN TRANSACTION")
            connection.execute(
                "UPDATE summary_drafts SET status = ? WHERE summary_id = ?",
                [status, summary_id],
            )
            connection.execute(
                "INSERT INTO summary_reviews VALUES (?, ?, ?, ?, ?, ?)",
                [
                    summary_id,
                    row[0],
                    request.reviewer_id,
                    request.decision,
                    request.notes,
                    reviewed_at,
                ],
            )
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except duckdb.TransactionException:
                pass
            raise
        finally:
            connection.close()
        return SummaryReviewResponse(
            summary_id=summary_id,
            complaint_id=row[0],
            reviewer_id=request.reviewer_id,
            decision=request.decision,
            status=status,
            reviewed_at=reviewed_at,
            final_decision_allowed=False,
        )

    def log_event(
        self,
        *,
        event_type: str,
        success: bool,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
        detail: str | None = None,
    ) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "success": success,
            "latency_ms": latency_ms,
            "cost_usd": cost_usd,
            "detail": detail,
            "occurred_at": datetime.now(timezone.utc),
        }
        if self._demo or self._live:
            with self._lock:
                self._demo_events.append(event)
            return
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO system_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                list(event.values()),
            )
        finally:
            connection.close()

    def system_metrics(self) -> dict[str, Any]:
        if self._demo or self._live:
            with self._lock:
                events = list(self._demo_events)
            latencies = sorted(
                int(item["latency_ms"])
                for item in events
                if item["latency_ms"] is not None
            )
            request_count = len(events)
            failure_count = sum(not item["success"] for item in events)
            refusal_count = sum(
                item["event_type"] == "summary_refusal" for item in events
            )
            return {
                "source_kind": self.source_kind.value,
                "request_count": request_count,
                "failure_count": failure_count,
                "refusal_count": refusal_count,
                "rate_denominator": request_count,
                "failure_rate": (
                    failure_count / request_count if request_count else None
                ),
                "refusal_rate": (
                    refusal_count / request_count if request_count else None
                ),
                "latency_observation_count": len(latencies),
                "total_cost_usd": sum(float(item["cost_usd"] or 0) for item in events),
                "p50_latency_ms": (
                    latencies[len(latencies) // 2] if latencies else None
                ),
                "p95_latency_ms": (
                    latencies[max(int(len(latencies) * 0.95) - 1, 0)]
                    if latencies
                    else None
                ),
                "price_table": dict(MODEL_PRICING),
            }
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT count(*), count(*) FILTER (WHERE success IS FALSE),
                       count(*) FILTER (WHERE event_type = 'summary_refusal'),
                       coalesce(sum(cost_usd), 0),
                       quantile_cont(latency_ms, 0.5) FILTER (WHERE latency_ms IS NOT NULL),
                       quantile_cont(latency_ms, 0.95) FILTER (WHERE latency_ms IS NOT NULL),
                       count(latency_ms)
                FROM system_events
                """
            ).fetchone()
        finally:
            connection.close()
        request_count = int(row[0])
        failure_count = int(row[1])
        refusal_count = int(row[2])
        return {
            "source_kind": self.source_kind.value,
            "request_count": request_count,
            "failure_count": failure_count,
            "refusal_count": refusal_count,
            "rate_denominator": request_count,
            "failure_rate": failure_count / request_count if request_count else None,
            "refusal_rate": refusal_count / request_count if request_count else None,
            "latency_observation_count": int(row[6]),
            "total_cost_usd": row[3],
            "p50_latency_ms": row[4],
            "p95_latency_ms": row[5],
            "price_table": dict(MODEL_PRICING),
        }

    def model_metrics(self) -> dict[str, Any]:
        if self._demo:
            return {
                "status": "synthetic_offline_demo",
                "source_kind": self.source_kind.value,
                "metrics": {},
                "false_routes": [],
                "unseen_labels": {"labels": [], "row_count": 0, "rate": 0},
                "drift": [],
                "integrity": {"final_decisions_by_ai": False},
            }
        if self._live:
            return {
                "status": "not_trained",
                "source_kind": self.source_kind.value,
                "metrics": {},
                "false_routes": [],
                "unseen_labels": {"labels": [], "row_count": 0, "rate": 0},
                "drift": [],
                "integrity": {"final_decisions_by_ai": False},
                "limitation": LIVE_READ_NOTICE,
            }
        if not MODEL_METRICS_PATH.exists():
            return {
                "status": "not_trained",
                "source_kind": self.source_kind.value,
                "metrics": {},
                "false_routes": [],
                "unseen_labels": {"labels": [], "row_count": 0, "rate": 0},
                "drift": [],
            }
        payload = json.loads(MODEL_METRICS_PATH.read_text("utf-8"))
        payload["source_kind"] = self.source_kind.value
        return payload

    def quality(self) -> dict[str, Any]:
        if self._demo:
            return {
                "status": "not_applicable_synthetic_offline_demo",
                "source_kind": self.source_kind.value,
                "limitation": DEMO_NOTICE,
            }
        if self._live:
            return {
                "status": "not_run",
                "source_kind": self.source_kind.value,
                "limitation": LIVE_READ_NOTICE,
            }
        if not QUALITY_PATH.exists():
            return {"status": "not_run", "source_kind": self.source_kind.value}
        payload = json.loads(QUALITY_PATH.read_text("utf-8"))
        payload["source_kind"] = self.source_kind.value
        return payload

    def lineage(self) -> LineageResponse:
        if self._demo:
            return LineageResponse(
                source="bundled synthetic offline demo",
                source_kind=self.source_kind,
                snapshot_manifest={"selection_method": "synthetic fixtures"},
                transformations=[],
                hashes={},
                metric_definitions={
                    "all_demo_metrics": "Synthetic fixture calculations only."
                },
                limitations=[DEMO_NOTICE],
            )
        if self._live:
            return LineageResponse(
                source=settings.cfpb_api_url,
                source_kind=self.source_kind,
                snapshot_manifest={
                    "selection_method": "bounded_live_read_in_memory",
                    "max_records": LIVE_READ_LIMIT,
                    "persisted": False,
                },
                transformations=[
                    {
                        "step": "live_read",
                        "definition": "One bounded CFPB API page normalized in UTC-date memory; no raw or DuckDB persistence.",
                    }
                ],
                hashes={},
                metric_definitions={
                    "router": "No trained model artifact is loaded; every live case abstains."
                },
                limitations=[self.limitation],
            )
        manifest = (
            json.loads(self.manifest_path.read_text("utf-8"))
            if self.manifest_path.exists()
            else {}
        )
        return LineageResponse(
            source=str(manifest.get("source", "CFPB Consumer Complaint Database API")),
            source_kind=self.source_kind,
            snapshot_manifest=manifest,
            transformations=[
                {
                    "step": "snapshot",
                    "definition": "Monthly-capped deterministic API selection with exclusive end dates.",
                },
                {
                    "step": "quality",
                    "definition": "Python grain, completeness, validity, temporal, and hash checks.",
                },
                {
                    "step": "warehouse",
                    "definition": "Typed DuckDB complaints table and SQL operational views.",
                },
                {
                    "step": "routing",
                    "definition": "Chronological product router with separate calibration, threshold, and test months.",
                },
            ],
            hashes={
                "snapshot_sha256": str(manifest.get("snapshot_sha256", "unavailable"))
            },
            metric_definitions={
                "timely_response_rate": "Snapshot complaints with timely=true divided by snapshot complaints with non-null timely status.",
                "routing_macro_f1": "Unweighted mean per-class F1 on the frozen complete test month before abstention.",
                "coverage": "Share of frozen test rows with calibrated maximum probability at or above the fixed threshold.",
                "selective_accuracy": "Accuracy among non-abstained frozen test rows.",
                "source_volume": "CFPB API-reported total for each non-overlapping date window; never replaced by capped sample rows.",
                "anomaly_robust_z": "Seven-day capped-snapshot signal compared with eight prior seven-day windows using median/MAD and a count-scale floor.",
            },
            limitations=[
                CFPB_LIMITATION,
                NARRATIVE_NOTICE,
                "Product/issue composition, response metrics, and anomalies are capped-snapshot sample signals; source-window totals are the volume source of truth.",
            ],
        )
