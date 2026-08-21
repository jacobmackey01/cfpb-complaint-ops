import {
  createSummary as createUnsafeSummary,
  normalizeSummary,
  normalizeSummaryReview as normalizeUnsafeSummaryReview,
  resolveApiBase,
} from './apiUnsafe';
import type {
  CaseRecord,
  CaseStatus,
  RouteDecision,
  SummaryDraft,
  SummaryReview,
} from './types';

export {
  getAnomalies,
  getCases,
  getModelMetrics,
  getOverview,
  normalizeAnomalies,
  normalizeCase,
  normalizeCases,
  normalizeModelMetrics,
  normalizeOverview,
  normalizeSource,
  normalizeSummary,
  resolveApiBase,
} from './apiUnsafe';

const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE_URL);

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const firstString = (...values: unknown[]): string | null => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return null;
};

const isDemoSource = (sourceKind: string): boolean =>
  sourceKind === 'synthetic_offline_demo' ||
  sourceKind === 'synthetic_demo' ||
  sourceKind.startsWith('synthetic_');

const requestJson = async (
  path: string,
  init?: RequestInit,
): Promise<unknown> => {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(
      `API request failed (${response.status})${detail ? `: ${detail.slice(0, 180)}` : ''}`,
    );
  }
  return response.json();
};

export const normalizeSummaryReview = (
  raw: unknown,
  summaryId: string,
): SummaryReview & { simulated: boolean } => ({
  ...normalizeUnsafeSummaryReview(raw, summaryId),
  simulated: false,
});

export const createSummary = async (
  item: CaseRecord,
  requestedBy: string,
): Promise<SummaryDraft> => {
  if (isDemoSource(item.sourceKind)) {
    return createUnsafeSummary(item, requestedBy);
  }
  const raw = await requestJson('/summaries', {
    method: 'POST',
    body: JSON.stringify({
      complaint_id: item.complaintId,
      requested_by: requestedBy,
    }),
  });
  return normalizeSummary(raw, item.id);
};

export const reviewSummary = async (
  summaryId: string,
  input: { reviewerId: string; decision: 'approve' | 'reject'; notes?: string; isDemo?: boolean },
): Promise<SummaryReview & { simulated: boolean }> => {
  try {
    const raw = await requestJson(
      `/summaries/${encodeURIComponent(summaryId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          summary_id: summaryId,
          reviewer_id: input.reviewerId,
          decision: input.decision,
          evidence_checked: true,
          notes: input.notes,
        }),
      },
    );
    return normalizeSummaryReview(raw, summaryId);
  } catch (error) {
    if (!input.isDemo) throw error;
    return {
      id: summaryId,
      status: input.decision === 'approve' ? 'approved' : 'rejected',
      reviewer: input.reviewerId,
      evidenceChecked: true,
      reviewedAt: new Date().toISOString(),
      simulated: true,
    };
  }
};

const normalizeStatus = (raw: unknown): CaseStatus => {
  const value = firstString(raw)?.toLowerCase().replaceAll(' ', '_');
  if (value === 'in_review' || value === 'routed' || value === 'closed') {
    return value;
  }
  return 'new';
};

const normalizeRouteDecision = (
  raw: unknown,
  caseId: string,
  route: string,
  reviewer: string,
): RouteDecision & { simulated: boolean } => {
  const response = isRecord(raw) ? raw : {};
  const nested = isRecord(response.route)
    ? response.route
    : isRecord(response.item)
      ? response.item
      : response;
  return {
    caseId:
      firstString(
        nested.case_id,
        nested.complaint_id,
        response.case_id,
      ) || caseId,
    route:
      firstString(
        nested.approved_route,
        nested.route,
        nested.assigned_product,
      ) || route,
    status: normalizeStatus(nested.route_status ?? nested.status ?? 'routed'),
    reviewer:
      firstString(
        nested.reviewer_id,
        nested.reviewer,
        response.reviewer,
      ) || reviewer,
    reviewedAt:
      firstString(nested.reviewed_at, response.reviewed_at) ||
      new Date().toISOString(),
    simulated: false,
  };
};

export const routeCase = async (
  item: CaseRecord,
  input: {
    reviewerId: string;
    decision: 'approve' | 'override' | 'reject';
    approvedRoute?: string;
    notes?: string;
    isDemo?: boolean;
  },
): Promise<RouteDecision & { simulated: boolean }> => {
  const approvedRoute =
    input.approvedRoute || item.predictedRoute || item.product;
  const path = `/cases/${encodeURIComponent(item.id)}/route`;
  const body = JSON.stringify({
    reviewer_id: input.reviewerId,
    decision: input.decision,
    approved_route: input.decision === 'reject' ? undefined : approvedRoute,
    notes: input.notes,
  });

  try {
    const raw = await requestJson(path, { method: 'PATCH', body });
    return normalizeRouteDecision(
      raw,
      item.id,
      approvedRoute,
      input.reviewerId,
    );
  } catch (patchError) {
    try {
      const raw = await requestJson(path, { method: 'POST', body });
      return normalizeRouteDecision(
        raw,
        item.id,
        approvedRoute,
        input.reviewerId,
      );
    } catch (postError) {
      if (!input.isDemo) throw postError;
      if (
        patchError instanceof DOMException &&
        patchError.name === 'AbortError'
      ) {
        throw patchError;
      }
      return {
        caseId: item.id,
        route: approvedRoute,
        status: input.decision === 'reject' ? 'in_review' : 'routed',
        reviewer: input.reviewerId,
        reviewedAt: new Date().toISOString(),
        simulated: true,
      };
    }
  }
};
