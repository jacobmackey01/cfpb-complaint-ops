import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSummary, reviewSummary, routeCase } from './api';
import { demoCases } from './demo';

describe('write failure integrity', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('never fabricates a successful write for a public-snapshot case', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const publicCase = {
      ...demoCases.cases[0],
      id: 'public-case-1',
      complaintId: 'PUBLIC-1',
      sourceKind: 'cfpb_public_snapshot' as const,
    };

    await expect(createSummary(publicCase, 'reviewer-1')).rejects.toThrow('offline');
    await expect(
      reviewSummary('public-summary-1', {
        reviewerId: 'reviewer-1',
        decision: 'approve',
      }),
    ).rejects.toThrow('offline');
    await expect(
      routeCase(publicCase, {
        reviewerId: 'reviewer-1',
        decision: 'override',
        approvedRoute: publicCase.product,
        isDemo: false,
      }),
    ).rejects.toThrow('offline');
  });

  it('labels explicit demo fallbacks as simulated and non-persistent', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const demoCase = demoCases.cases[0];
    const draft = await createSummary(demoCase, 'demo-reviewer');
    const route = await routeCase(demoCase, {
      reviewerId: 'demo-reviewer',
      decision: 'override',
      approvedRoute: demoCase.product,
      isDemo: true,
    });

    expect(draft.source).toMatchObject({ isDemo: true, isVerifiedPublicData: false });
    expect(route.simulated).toBe(true);
  });
});
