import { describe, expect, it } from 'vitest';
import {
  normalizeCases,
  normalizeModelMetrics,
  normalizeSource,
  normalizeSummary,
  normalizeSummaryReview,
  resolveApiBase,
} from './api';

describe('API integrity normalizers', () => {
  it('appends the canonical API path to a bare backend origin', () => {
    expect(resolveApiBase('https://api.example.test')).toBe(
      'https://api.example.test/api/v1',
    );
    expect(resolveApiBase('https://api.example.test/api')).toBe(
      'https://api.example.test/api/v1',
    );
    expect(resolveApiBase('https://api.example.test/api/v1/')).toBe(
      'https://api.example.test/api/v1',
    );
    expect(resolveApiBase(undefined)).toBe('/api/v1');
  });

  it('never treats a synthetic backend response as verified public data', () => {
    expect(normalizeSource({ source_kind: 'synthetic_offline_demo' })).toMatchObject({
      isDemo: true,
      isVerifiedPublicData: false,
    });
    expect(normalizeSource({ source_kind: 'synthetic_demo' })).toMatchObject({
      isDemo: true,
      isVerifiedPublicData: false,
    });
  });

  it('keeps missing provenance unverified instead of implying live data', () => {
    expect(normalizeSource({})).toMatchObject({
      sourceKind: 'unknown',
      isDemo: false,
      isVerifiedPublicData: false,
    });
  });

  it('preserves case-level source_kind', () => {
    const queue = normalizeCases({
      source_kind: 'synthetic_offline_demo',
      items: [
        {
          complaint_id: '1',
          product: 'Mortgage',
          issue: 'Payment',
          source_kind: 'synthetic_offline_demo',
        },
      ],
    });
    expect(queue.cases[0].sourceKind).toBe('synthetic_offline_demo');
    expect(queue.source.isDemo).toBe(true);
  });

  it('normalizes both overview and summary response fields', () => {
    const overview = normalizeSummary(
      {
        source_kind: 'cfpb_public_snapshot',
        summary: {
          summary_id: 's1',
          overview: 'Overview text',
          evidence_quotes: [{ text: 'Exact quote' }],
        },
      },
      'c1',
    );
    const summary = normalizeSummary(
      { draft: { summary_id: 's2', summary: 'Summary text' } },
      'c2',
    );
    expect(overview.overview).toBe('Overview text');
    expect(overview.quotedEvidence).toEqual(['Exact quote']);
    expect(summary.overview).toBe('Summary text');
  });

  it('normalizes a minimal review response without replacing the draft', () => {
    expect(
      normalizeSummaryReview(
        { summary_id: 's1', status: 'approved', reviewer_id: 'reviewer-1' },
        's1',
      ),
    ).toMatchObject({
      id: 's1',
      status: 'approved',
      reviewer: 'reviewer-1',
      simulated: false,
    });
  });

  it('does not show factuality without a reviewed denominator', () => {
    const metrics = normalizeModelMetrics({
      source_kind: 'synthetic_offline_demo',
      summary_factuality: 0.99,
      summary_reviewed_n: 0,
    });
    expect(metrics.summaryFactuality).toBeNull();
    expect(metrics.summaryReviewedN).toBe(0);
  });
});
