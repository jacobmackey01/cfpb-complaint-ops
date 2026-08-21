import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );

describe('complaint operations UI', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
  });

  afterEach(() => vi.unstubAllGlobals());

  it('labels dashboard fixture metrics as synthetic rather than live', async () => {
    renderAt('/');
    expect(
      await screen.findByRole('heading', { name: 'Complaint operations' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Offline synthetic demonstration')).toBeInTheDocument();
    expect(screen.getByText(/not a live CFPB observation/i)).toBeInTheDocument();
  });

  it('shows the manual-attention queue with a model-abstention label', async () => {
    renderAt('/queue');
    expect(
      await screen.findByRole('heading', { name: 'Case queue' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'DEMO-1001' })).toBeInTheDocument();
    expect(screen.getAllByText('Abstained').length).toBeGreaterThan(0);
  });

  it('requires explicit evidence review and keeps summary approval separate from routing', async () => {
    const user = userEvent.setup();
    renderAt('/cases/demo-1001');
    const summaryHeading = await screen.findByRole('heading', {
      name: 'AI-assisted summary',
    });
    const summaryPanel = summaryHeading.closest('section');
    expect(summaryPanel).not.toBeNull();
    const summaryControls = within(summaryPanel as HTMLElement);

    await user.type(summaryControls.getByLabelText('Requested by'), 'analyst-1');
    await user.click(
      summaryControls.getByRole('button', {
        name: /create evidence-grounded draft/i,
      }),
    );
    const approve = await summaryControls.findByRole('button', {
      name: /approve summary/i,
    });
    expect(approve).toBeDisabled();
    expect(
      summaryControls.getByText(
        /Approving the text does not approve the model route/i,
      ),
    ).toBeInTheDocument();
    await user.type(
      summaryControls.getByLabelText('Reviewer name or ID'),
      'reviewer-2',
    );
    await user.click(
      summaryControls.getByLabelText(/I compared every displayed quote/i),
    );
    expect(approve).toBeEnabled();
    await user.click(approve);
    expect(await summaryControls.findByText(/Reviewed by/i)).toBeInTheDocument();

    const routeHeading = screen.getByRole('heading', { name: 'Routing review' });
    const routePanel = routeHeading.closest('section');
    expect(routePanel).not.toBeNull();
    const routeControls = within(routePanel as HTMLElement);
    await user.type(
      routeControls.getByLabelText('Reviewer name or ID'),
      'reviewer-2',
    );
    await user.click(
      routeControls.getByLabelText(/This is my decision—not an automated action/i),
    );
    await user.click(
      routeControls.getByRole('button', { name: /submit reviewed route/i }),
    );
    expect(await routeControls.findByText(/Decision recorded/i)).toBeInTheDocument();
    expect(routeControls.getByText(/not persisted/i)).toBeInTheDocument();
  });

  it('does not invent a reviewed summary-factuality score', async () => {
    renderAt('/model');
    expect(
      await screen.findByRole('heading', { name: 'Model monitor' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /No summary factuality claim is shown because the reviewed sample size is zero/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/synthetic UI fixtures/i)).toBeInTheDocument();
  });

  it('redirects unknown routes to the operations page', async () => {
    renderAt('/not-a-route');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Complaint operations' }),
      ).toBeInTheDocument(),
    );
  });
});
