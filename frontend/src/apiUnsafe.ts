import { demoAnomalies, demoCases, demoModelMetrics, demoOverview } from './demo';
import type {
  AnomalyReport,
  CalibrationBin,
  CasePriority,
  CaseQueue,
  CaseRecord,
  CaseStatus,
  CategoryVolume,
  DriftPoint,
  FalseRoutePattern,
  ModelMetrics,
  OperationsOverview,
  RouteDecision,
  SourceKind,
  SourceMeta,
  SummaryDraft,
  SummaryReview,
  TimePoint,
  TrendAnomaly,
} from './types';

export const resolveApiBase = (rawValue: string | undefined): string => {
  const value = rawValue?.trim().replace(/\/+$/, '') || '';
  if (!value) return '/api/v1';
  if (value.endsWith('/api/v1')) return value;
  if (value.endsWith('/api')) return `${value}/v1`;
  return `${value}/api/v1`;
};

const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE_URL);

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asRecord = (value: unknown): JsonRecord => (isRecord(value) ? value : {});

const firstString = (...values: unknown[]): string | null => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return null;
};

const firstNumber = (...values: unknown[]): number | null => {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
};

const firstBoolean = (...values: unknown[]): boolean | null => {
  for (const value of values) {
    if (typeof value === 'boolean') return value;
    if (value === 1 || value === '1' || value === 'true' || value === 'Yes') return true;
    if (value === 0 || value === '0' || value === 'false' || value === 'No') return false;
  }
  return null;
};

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const stringArray = (value: unknown): string[] =>
  asArray(value)
    .map((item) => firstString(item))
    .filter((item): item is string => item !== null);

const clampRate = (value: number | null): number | null => {
  if (value === null) return null;
  const rate = value > 1 && value <= 100 ? value / 100 : value;
  return Math.min(1, Math.max(0, rate));
};

const demoKind = (kind: string) =>
  kind === 'synthetic_offline_demo' || kind === 'synthetic_demo' || kind.startsWith('synthetic_');

export const normalizeSource = (raw: unknown, fallbackKind?: unknown): SourceMeta => {
  const record = asRecord(raw);
  const sourceKind = (firstString(
    record.source_kind,
    record.sourceKind,
    fallbackKind,
  ) || 'unknown') as SourceKind;
  const isDemo = demoKind(sourceKind);
  const isVerifiedPublicData = sourceKind.startsWith('cfpb_') && !isDemo;

  return {
    sourceKind,
    snapshotId: firstString(record.snapshot_id, record.snapshotId, record.snapshot_hash),
    generatedAt: firstString(record.as_of, record.generated_at, record.generatedAt, record.snapshot_date),
    isDemo,
    isVerifiedPublicData,
  };
};

const normalizePriority = (raw: unknown, manualAttention: boolean): CasePriority => {
  const value = firstString(raw)?.toLowerCase();
  if (value === 'urgent' || value === 'high' || value === 'standard' || value === 'low') return value;
  return manualAttention ? 'high' : 'standard';
};

const normalizeStatus = (raw: unknown): CaseStatus => {
  const value = firstString(raw)?.toLowerCase().replaceAll(' ', '_');
  if (value === 'in_review' || value === 'routed' || value === 'closed') return value;
  return 'new';
};

export const normalizeCase = (raw: unknown, parentSource: SourceMeta): CaseRecord => {
  const record = asRecord(raw);
  const complaintId = firstString(record.complaint_id, record.complaintId, record.id) || 'unknown-case';
  const manualAttention =
    firstBoolean(
      record.requires_manual_attention,
      record.manual_attention,
      record.manualAttention,
    ) ?? false;
  const itemSource = normalizeSource(record, parentSource.sourceKind);

  return {
    id: firstString(record.id, record.case_id, record.complaint_id, record.complaintId) || complaintId,
    complaintId,
    dateReceived: firstString(record.date_received, record.dateReceived, record.submitted_at) || '',
    product: firstString(record.product) || 'Unspecified product',
    issue: firstString(record.issue) || 'Unspecified issue',
    subProduct: firstString(record.sub_product, record.subProduct),
    subIssue: firstString(record.sub_issue, record.subIssue),
    company: firstString(record.company) || 'Company not supplied',
    state: firstString(record.state),
    narrative: firstString(record.narrative, record.consumer_complaint_narrative),
    companyResponse: firstString(record.company_response, record.companyResponse, record.response),
    timelyResponse: firstBoolean(record.timely, record.timely_response, record.timelyResponse),
    submissionChannel: firstString(record.submitted_via, record.submission_channel, record.submissionChannel),
    predictedRoute: firstString(
      record.predicted_route,
      record.assigned_product,
      record.predicted_issue,
      record.predicted_product,
    ),
    predictedProduct: firstString(record.predicted_product, record.predictedProduct),
    predictedIssue: firstString(record.predicted_issue, record.predictedIssue),
    confidence: clampRate(firstNumber(record.confidence, record.prediction_confidence)),
    abstained: firstBoolean(record.abstained, record.is_abstained) ?? false,
    manualAttention,
    attentionReasons: stringArray(record.attention_reasons ?? record.attentionReasons),
    priority: normalizePriority(record.priority, manualAttention),
    status: normalizeStatus(record.route_status ?? record.status),
    ageDays: firstNumber(record.age_days, record.ageDays),
    sourceKind: itemSource.sourceKind,
  };
};

export const normalizeCases = (raw: unknown): CaseQueue => {
  const record = asRecord(raw);
  const source = normalizeSource(record);
  const candidates = record.items ?? record.cases ?? record.data;
  const cases = asArray(candidates).map((item) => normalizeCase(item, source));
  return {
    cases,
    total: firstNumber(record.total, record.total_count, record.count) ?? cases.length,
    source,
  };
};

const normalizeTimePoint = (raw: unknown): TimePoint | null => {
  const record = asRecord(raw);
  const period = firstString(record.period, record.date, record.week, record.month);
  const count = firstNumber(record.count, record.volume);
  if (!period || count === null) return null;
  return {
    period,
    count,
    timelyRate: clampRate(firstNumber(record.timely_rate, record.timelyRate)),
  };
};

const normalizeCategory = (raw: unknown): CategoryVolume | null => {
  const record = asRecord(raw);
  const label = firstString(record.label, record.product, record.category);
  const count = firstNumber(record.count, record.volume);
  if (!label || count === null) return null;
  return { label, count, share: clampRate(firstNumber(record.share, record.rate)) };
};

export const normalizeOverview = (raw: unknown): OperationsOverview => {
  const record = asRecord(raw);
  const source = normalizeSource(record);
  return {
    totalComplaints: firstNumber(record.total_complaints, record.totalComplaints, record.total) ?? 0,
    newComplaints: firstNumber(record.new_complaints, record.newComplaints, record.new_count) ?? 0,
    manualAttention:
      firstNumber(record.manual_attention_count, record.manualAttention, record.manual_review_count) ?? 0,
    timelyRate: clampRate(
      firstNumber(record.timely_response_rate, record.timely_rate, record.timelyRate),
    ),
    abstentionRate: clampRate(
      firstNumber(
        record.abstention_rate,
        record.abstentionRate,
        firstNumber(record.total_complaints) && firstNumber(record.abstained_count) !== null
          ? (firstNumber(record.abstained_count) as number) / (firstNumber(record.total_complaints) as number)
          : null,
      ),
    ),
    medianAgeDays: firstNumber(record.median_age_days, record.medianAgeDays),
    volumeChange: firstNumber(record.volume_change, record.volumeChange),
    periodLabel: firstString(record.period_label, record.periodLabel, record.as_of) || 'Current snapshot',
    series: asArray(record.series)
      .map(normalizeTimePoint)
      .filter((item): item is TimePoint => item !== null),
    products: asArray(record.products ?? record.product_volumes)
      .map(normalizeCategory)
      .filter((item): item is CategoryVolume => item !== null),
    source,
  };
};

const normalizeAnomaly = (raw: unknown, index: number): TrendAnomaly | null => {
  const record = asRecord(raw);
  const product = firstString(record.product, record.label) || 'All products';
  const issue = firstString(record.issue) || (firstString(record.dimension) === 'issue' ? product : 'All issues');
  const observed = firstNumber(record.observed, record.current_count, record.count);
  if (observed === null) return null;
  const zScore = firstNumber(record.z_score, record.zScore, record.robust_z);
  const rawSeverity = firstString(record.severity)?.toLowerCase();
  const severity = rawSeverity === 'high' || rawSeverity === 'medium' ? rawSeverity : 'watch';
  return {
    id: firstString(record.id) || `anomaly-${index}`,
    period:
      firstString(record.period, record.window_end, record.date, record.cutoff_date) || 'Current window',
    product,
    issue,
    observed,
    expected: firstNumber(record.expected, record.baseline_median, record.baseline),
    zScore,
    direction: (zScore ?? 0) < 0 ? 'down' : 'up',
    severity,
    explanation:
      firstString(record.explanation) ||
      'The current volume crossed the configured rolling-baseline threshold. Review the underlying cases before acting.',
  };
};

export const normalizeAnomalies = (raw: unknown): AnomalyReport => {
  const record = asRecord(raw);
  return {
    anomalies: asArray(record.items ?? record.anomalies ?? record.data)
      .map(normalizeAnomaly)
      .filter((item): item is TrendAnomaly => item !== null),
    source: normalizeSource(record),
  };
};

const normalizeFalseRoute = (raw: unknown): FalseRoutePattern | null => {
  const record = asRecord(raw);
  const actual = firstString(record.actual, record.actual_label, record.true_label);
  const predicted = firstString(record.predicted, record.predicted_label);
  const count = firstNumber(record.count, record.n);
  if (!actual || !predicted || count === null) return null;
  return { actual, predicted, count, share: clampRate(firstNumber(record.share, record.rate)) };
};

const normalizeCalibration = (raw: unknown): CalibrationBin | null => {
  const record = asRecord(raw);
  const meanConfidence = clampRate(
    firstNumber(record.mean_confidence, record.meanConfidence, record.confidence),
  );
  const accuracy = clampRate(firstNumber(record.accuracy, record.observed_accuracy));
  if (meanConfidence === null || accuracy === null) return null;
  return {
    lower: clampRate(firstNumber(record.lower, record.bin_lower)) ?? 0,
    upper: clampRate(firstNumber(record.upper, record.bin_upper)) ?? 1,
    meanConfidence,
    accuracy,
    count: firstNumber(record.count, record.n) ?? 0,
  };
};

const normalizeDrift = (raw: unknown): DriftPoint | null => {
  const record = asRecord(raw);
  const period = firstString(record.period, record.month, record.date);
  if (!period) return null;
  const rawStatus = firstString(record.status)?.toLowerCase();
  const status =
    rawStatus === 'stable' || rawStatus === 'watch' || rawStatus === 'alert'
      ? rawStatus
      : 'unknown';
  return {
    period,
    product: firstString(record.product, record.label) || 'All products',
    macroF1: clampRate(firstNumber(record.macro_f1, record.macroF1)),
    abstentionRate: clampRate(firstNumber(record.abstention_rate, record.abstentionRate)),
    driftScore: firstNumber(record.drift_score, record.psi, record.js_divergence),
    status,
  };
};

export const normalizeModelMetrics = (raw: unknown): ModelMetrics => {
  const record = asRecord(raw);
  const metrics = asRecord(record.metrics);
  const split = asRecord(record.split);
  const source = normalizeSource(record);
  const summaryFactuality = clampRate(
    firstNumber(
      record.summary_factuality,
      record.summaryFactuality,
      metrics.summary_factuality,
    ),
  );
  const summaryReviewedN =
    firstNumber(record.summary_reviewed_n, record.summaryReviewedN, metrics.summary_reviewed_n) ?? 0;

  return {
    modelName: firstString(record.model_name, record.modelName) || 'Complaint routing classifier',
    modelVersion: firstString(record.model_version, record.modelVersion) || 'unknown',
    target: firstString(record.target, metrics.target) || 'Published complaint label',
    validationWindow:
      firstString(
        record.validation_window,
        record.validationWindow,
        split.validation_window,
        split.test_window,
      ) || 'Chronological holdout',
    macroF1: clampRate(firstNumber(metrics.macro_f1, record.macro_f1, record.macroF1)),
    accuracy: clampRate(
      firstNumber(metrics.accuracy, metrics.selective_accuracy, record.accuracy),
    ),
    expectedCalibrationError: clampRate(
      firstNumber(metrics.ece, metrics.expected_calibration_error, record.ece),
    ),
    coverage: clampRate(firstNumber(metrics.coverage, record.coverage)),
    abstentionRate: clampRate(
      firstNumber(metrics.abstention_rate, record.abstention_rate),
    ),
    abstentionThreshold: clampRate(
      firstNumber(record.threshold, metrics.threshold, record.abstention_threshold),
    ),
    evaluatedRows:
      firstNumber(metrics.evaluated_rows, metrics.n, record.evaluated_rows, split.test_rows) ?? 0,
    falseRoutes: asArray(record.false_routes ?? metrics.false_routes)
      .map(normalizeFalseRoute)
      .filter((item): item is FalseRoutePattern => item !== null),
    calibration: asArray(record.calibration ?? metrics.calibration)
      .map(normalizeCalibration)
      .filter((item): item is CalibrationBin => item !== null),
    drift: asArray(record.drift ?? metrics.drift)
      .map(normalizeDrift)
      .filter((item): item is DriftPoint => item !== null),
    // A factuality score is shown only with a non-zero reviewed denominator.
    summaryFactuality: summaryReviewedN > 0 ? summaryFactuality : null,
    summaryReviewedN,
    latencyP50Ms: firstNumber(record.latency_p50_ms, metrics.latency_p50_ms),
    latencyP95Ms: firstNumber(record.latency_p95_ms, metrics.latency_p95_ms),
    meanApiCostUsd: firstNumber(record.mean_api_cost_usd, metrics.mean_api_cost_usd),
    systemFailures: firstNumber(record.system_failures, metrics.system_failures) ?? 0,
    refusalRate: clampRate(firstNumber(record.refusal_rate, metrics.refusal_rate)),
    source,
  };
};

const evidenceStrings = (value: unknown): string[] =>
  asArray(value)
    .map((item) => (isRecord(item) ? firstString(item.text, item.quote) : firstString(item)))
    .filter((item): item is string => item !== null);

const normalizeSummaryStatus = (raw: unknown): SummaryDraft['status'] => {
  const value = firstString(raw)?.toLowerCase();
  if (value === 'approved' || value === 'approve') return 'approved';
  if (value === 'rejected' || value === 'reject') return 'rejected';
  return 'draft';
};

export const normalizeSummary = (raw: unknown, caseId: string): SummaryDraft => {
  const response = asRecord(raw);
  const nested = isRecord(response.draft)
    ? response.draft
    : isRecord(response.summary)
      ? response.summary
      : response;
  const summaryText =
    firstString(nested.overview, nested.summary, response.overview) ||
    firstString(nested.headline, response.headline) ||
    'No summary text was returned.';
  const headline = firstString(nested.headline, response.headline);
  const overview = headline && headline !== summaryText ? `${headline}. ${summaryText}` : summaryText;
  const source = normalizeSource(nested, response.source_kind);

  return {
    id:
      firstString(nested.summary_id, nested.id, response.summary_id, response.id) ||
      `summary-${caseId}`,
    caseId: firstString(nested.complaint_id, nested.case_id, response.case_id) || caseId,
    overview,
    keyPoints: stringArray(nested.key_points ?? nested.keyPoints),
    quotedEvidence: evidenceStrings(
      nested.evidence_quotes ?? nested.quoted_evidence ?? nested.quotes,
    ),
    suggestedActions: stringArray(
      nested.recommended_human_actions ?? nested.suggested_actions ?? nested.suggestedActions,
    ),
    caveats: stringArray(nested.caveats ?? nested.missing_information),
    status: normalizeSummaryStatus(nested.status ?? response.status),
    provider: firstString(nested.provider, response.provider),
    model: firstString(nested.model, response.model),
    latencyMs: firstNumber(nested.latency_ms, response.latency_ms),
    estimatedCostUsd: firstNumber(nested.cost_usd, nested.estimated_cost_usd, response.cost_usd),
    refusalReason: firstString(nested.refusal_reason, response.refusal_reason),
    reviewer: firstString(nested.reviewer, nested.reviewer_id, response.reviewer),
    evidenceChecked: firstBoolean(nested.evidence_checked, response.evidence_checked) ?? false,
    reviewedAt: firstString(nested.reviewed_at, response.reviewed_at),
    source,
  };
};

export const normalizeSummaryReview = (raw: unknown, summaryId: string): SummaryReview => {
  const response = asRecord(raw);
  const nested = isRecord(response.review)
    ? response.review
    : isRecord(response.draft)
      ? response.draft
      : response;
  return {
    id: firstString(nested.summary_id, nested.id, response.summary_id) || summaryId,
    status: normalizeSummaryStatus(nested.status ?? nested.decision ?? response.status),
    reviewer: firstString(nested.reviewer, nested.reviewer_id, response.reviewer),
    evidenceChecked: firstBoolean(nested.evidence_checked, response.evidence_checked) ?? true,
    reviewedAt:
      firstString(nested.reviewed_at, response.reviewed_at) || new Date().toISOString(),
  };
};

interface RequestOptions extends RequestInit {
  signal?: AbortSignal;
}

const requestJson = async (path: string, options: RequestOptions = {}): Promise<unknown> => {
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    const message = await response.text().catch(() => '');
    throw new Error(`API ${response.status}${message ? `: ${message.slice(0, 180)}` : ''}`);
  }
  return response.json();
};

export const getCases = async (signal?: AbortSignal): Promise<CaseQueue> => {
  try {
    const raw = await requestJson('/cases?page=1&page_size=100', { signal });
    return normalizeCases(raw);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return demoCases;
  }
};

export const getOverview = async (signal?: AbortSignal): Promise<OperationsOverview> => {
  try {
    return normalizeOverview(await requestJson('/metrics/overview', { signal }));
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return demoOverview;
  }
};

export const getAnomalies = async (signal?: AbortSignal): Promise<AnomalyReport> => {
  try {
    return normalizeAnomalies(await requestJson('/trends/anomalies', { signal }));
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return demoAnomalies;
  }
};

export const getModelMetrics = async (signal?: AbortSignal): Promise<ModelMetrics> => {
  try {
    return normalizeModelMetrics(await requestJson('/model/metrics', { signal }));
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return demoModelMetrics;
  }
};

export const createSummary = async (
  item: CaseRecord,
  requestedBy: string,
): Promise<SummaryDraft> => {
  try {
    const raw = await requestJson('/summaries', {
      method: 'POST',
      body: JSON.stringify({
        complaint_id: item.complaintId,
        case_id: item.id,
        narrative: item.narrative,
        requested_by: requestedBy,
        source_kind: item.sourceKind,
      }),
    });
    return normalizeSummary(raw, item.id);
  } catch {
    const narrative = item.narrative || '';
    const quote = narrative.slice(0, 220).trim();
    return {
      id: `demo-summary-${item.id}`,
      caseId: item.id,
      overview: narrative
        ? 'Offline demo extraction only. A consumer describes the issue shown in the quoted source text.'
        : 'Summary refused because no published narrative was supplied.',
      keyPoints: narrative ? [`Published issue label: ${item.issue}`] : [],
      quotedEvidence: quote ? [quote] : [],
      suggestedActions: narrative ? ['A human reviewer should verify the quote and choose the route.'] : [],
      caveats: ['Synthetic offline fallback; this is not a reviewed or approved decision.'],
      status: 'draft',
      provider: 'offline-extractive-demo',
      model: null,
      latencyMs: 0,
      estimatedCostUsd: 0,
      refusalReason: narrative ? null : 'No narrative available',
      reviewer: null,
      evidenceChecked: false,
      reviewedAt: null,
      source: {
        sourceKind: 'synthetic_offline_demo',
        snapshotId: 'offline-demo-v1',
        generatedAt: new Date().toISOString(),
        isDemo: true,
        isVerifiedPublicData: false,
      },
    };
  }
};

export const reviewSummary = async (
  summaryId: string,
  input: { reviewerId: string; decision: 'approve' | 'reject'; notes?: string },
): Promise<SummaryReview> => {
  try {
    const raw = await requestJson(`/summaries/${encodeURIComponent(summaryId)}/review`, {
      method: 'POST',
      body: JSON.stringify({
        summary_id: summaryId,
        reviewer_id: input.reviewerId,
        decision: input.decision,
        evidence_checked: true,
        notes: input.notes,
      }),
    });
    return normalizeSummaryReview(raw, summaryId);
  } catch {
    return {
      id: summaryId,
      status: input.decision === 'approve' ? 'approved' : 'rejected',
      reviewer: input.reviewerId,
      evidenceChecked: true,
      reviewedAt: new Date().toISOString(),
    };
  }
};

const normalizeRouteDecision = (
  raw: unknown,
  caseId: string,
  route: string,
  reviewer: string,
): RouteDecision => {
  const response = asRecord(raw);
  const nested = isRecord(response.route) ? response.route : isRecord(response.item) ? response.item : response;
  return {
    caseId: firstString(nested.case_id, nested.complaint_id, response.case_id) || caseId,
    route: firstString(nested.approved_route, nested.route, nested.assigned_product) || route,
    status: normalizeStatus(nested.route_status ?? nested.status ?? 'routed'),
    reviewer: firstString(nested.reviewer_id, nested.reviewer, response.reviewer) || reviewer,
    reviewedAt: firstString(nested.reviewed_at, response.reviewed_at) || new Date().toISOString(),
  };
};

export const routeCase = async (
  item: CaseRecord,
  input: {
    reviewerId: string;
    decision: 'approve' | 'override' | 'reject';
    approvedRoute?: string;
    notes?: string;
  },
): Promise<RouteDecision> => {
  const approvedRoute = input.approvedRoute || item.predictedRoute || item.product;
  const path = `/cases/${encodeURIComponent(item.id)}/route`;
  const body = JSON.stringify({
    reviewer_id: input.reviewerId,
    decision: input.decision,
    approved_route: input.decision === 'reject' ? undefined : approvedRoute,
    notes: input.notes,
  });

  try {
    const raw = await requestJson(path, { method: 'PATCH', body });
    return normalizeRouteDecision(raw, item.id, approvedRoute, input.reviewerId);
  } catch (patchError) {
    try {
      const raw = await requestJson(path, { method: 'POST', body });
      return normalizeRouteDecision(raw, item.id, approvedRoute, input.reviewerId);
    } catch {
      if (patchError instanceof DOMException && patchError.name === 'AbortError') throw patchError;
      return {
        caseId: item.id,
        route: approvedRoute,
        status: input.decision === 'reject' ? 'in_review' : 'routed',
        reviewer: input.reviewerId,
        reviewedAt: new Date().toISOString(),
      };
    }
  }
};
