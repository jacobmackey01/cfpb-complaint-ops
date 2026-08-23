import { ArrowLeft, CheckCircle2, Quote, Route, ShieldAlert, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { createSummary, getCases, normalizeSource, reviewSummary, routeCase } from '../api';
import { EmptyState, ErrorState, LoadingState, Panel, PanelHeader, Pill, SourceNotice } from '../components/DataUi';
import { formatDate, formatDateTime, formatMoney, formatPercent, sentenceCase } from '../format';
import { useAsyncResource } from '../hooks';
import type { CaseRecord, RouteDecision, SourceMeta, SummaryDraft } from '../types';

const CaseWorkspace = ({ item, parentSource }: { item: CaseRecord; parentSource: SourceMeta }) => {
  const source = normalizeSource({
    source_kind: item.sourceKind,
    as_of: parentSource.generatedAt,
    data_mode: parentSource.dataMode,
    persistence_mode: parentSource.persistenceMode,
  });
  const [requester, setRequester] = useState('');
  const [summary, setSummary] = useState<SummaryDraft | null>(null);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryReviewer, setSummaryReviewer] = useState('');
  const [summaryNotes, setSummaryNotes] = useState('');
  const [evidenceChecked, setEvidenceChecked] = useState(false);
  const [routeReviewer, setRouteReviewer] = useState('');
  const [routeChoice, setRouteChoice] = useState(item.predictedRoute || item.product);
  const [routeMode, setRouteMode] = useState<'approve' | 'override' | 'reject'>(item.abstained ? 'override' : 'approve');
  const [routeNotes, setRouteNotes] = useState('');
  const [routeConfirmed, setRouteConfirmed] = useState(false);
  const [routeBusy, setRouteBusy] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [routeResult, setRouteResult] = useState<RouteDecision | null>(null);

  const quoteChecks = (summary?.quotedEvidence ?? []).map((text) => ({ text, exact: Boolean(item.narrative?.includes(text)) }));
  const allQuotesExact = quoteChecks.length > 0 && quoteChecks.every((quote) => quote.exact);
  const canReviewSummary = Boolean(summaryReviewer.trim() && evidenceChecked && summary && summary.status === 'draft');

  const requestSummary = async () => {
    setSummaryBusy(true);
    setSummaryError(null);
    try {
      const draft = await createSummary(item, requester.trim());
      setSummary(draft);
      setEvidenceChecked(false);
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'Summary request failed.');
    } finally {
      setSummaryBusy(false);
    }
  };

  const submitSummaryReview = async (decision: 'approve' | 'reject') => {
    if (!summary) return;
    setSummaryBusy(true);
    setSummaryError(null);
    try {
      const review = await reviewSummary(summary.id, { reviewerId: summaryReviewer.trim(), decision, notes: summaryNotes.trim() || undefined, isDemo: summary.source.isDemo });
      setSummary((current) => current ? { ...current, status: review.status, reviewer: review.reviewer, evidenceChecked: review.evidenceChecked, reviewedAt: review.reviewedAt } : current);
      if (review.simulated) setSummaryError('Demo only: this review state is held in the browser and was not saved to an operational system.');
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'The summary review was not saved.');
    } finally {
      setSummaryBusy(false);
    }
  };

  const submitRoute = async () => {
    setRouteBusy(true);
    setRouteError(null);
    try {
      const result = await routeCase(item, { reviewerId: routeReviewer.trim(), decision: routeMode, approvedRoute: routeMode === 'approve' ? item.predictedRoute || routeChoice : routeChoice, notes: routeNotes.trim() || undefined, isDemo: source.isDemo });
      setRouteResult(result);
      if (result.simulated) setRouteError('Demo only: this routing choice is held in the browser and was not persisted.');
    } catch (error) {
      setRouteError(error instanceof Error ? error.message : 'The route was not saved.');
    } finally {
      setRouteBusy(false);
    }
  };

  return (
    <div className="page case-page">
      <Link className="back-link" to="/queue"><ArrowLeft aria-hidden="true" size={16} /> Back to queue</Link>
      <header className="case-header">
        <div>
          <p className="eyebrow">Case review</p>
          <h1>{item.complaintId}</h1>
          <p>{item.product} · received {formatDate(item.dateReceived)}</p>
          <code className="source-chip">source_kind={item.sourceKind}</code>
        </div>
        <div className="case-header-badges">
          <Pill tone={item.priority === 'urgent' ? 'danger' : item.priority === 'high' ? 'warning' : 'neutral'}>{item.priority} priority</Pill>
          <Pill tone={item.status === 'routed' ? 'success' : 'info'}>{sentenceCase(item.status)}</Pill>
        </div>
      </header>
      <SourceNotice source={source} />

      <div className="case-grid">
        <div className="case-main-column">
          <Panel>
            <PanelHeader title="Published complaint narrative" description="Use the supplied text as the only evidence source for summary review." />
            {item.narrative ? <blockquote className="narrative">{item.narrative}</blockquote> : <EmptyState title="No published narrative" message="A narrative may be absent because publication consent was not given or no text was available. Do not infer missing details." />}
          </Panel>

          <Panel>
            <PanelHeader title="AI-assisted summary" description="A structured draft for review. It cannot close, route, or otherwise decide this case." action={<Pill tone="warning">Human approval required</Pill>} />
            {!summary ? (
              <div className="summary-request">
                <label><span>Requested by</span><input value={requester} onChange={(event) => setRequester(event.target.value)} placeholder="Reviewer name or ID" /></label>
                <button className="button button-primary" type="button" disabled={!requester.trim() || summaryBusy} onClick={requestSummary}><Sparkles aria-hidden="true" size={16} />{summaryBusy ? 'Creating draft…' : 'Create evidence-grounded draft'}</button>
                <p className="form-help">The service may refuse when there is no narrative or evidence cannot be quoted safely.</p>
              </div>
            ) : (
              <div className="summary-draft">
                <SourceNotice source={summary.source} />
                <div className="summary-status-line"><Pill tone={summary.status === 'approved' ? 'success' : summary.status === 'rejected' ? 'danger' : 'warning'}>{summary.status}</Pill><span>{summary.provider || 'Provider not reported'}{summary.model ? ` · ${summary.model}` : ''}</span></div>
                {summary.refusalReason ? <p className="inline-warning"><ShieldAlert aria-hidden="true" size={16} /> Refused: {summary.refusalReason}</p> : null}
                <h3>Draft overview</h3><p className="summary-overview">{summary.overview}</p>
                {summary.keyPoints.length ? <><h3>Key points</h3><ul>{summary.keyPoints.map((point) => <li key={point}>{point}</li>)}</ul></> : null}
                <h3>Quoted evidence</h3>
                {quoteChecks.length ? <div className="quote-list">{quoteChecks.map((quote) => <blockquote key={quote.text} className={quote.exact ? 'quote-match' : 'quote-mismatch'}><Quote aria-hidden="true" size={16} /><span>{quote.text}</span><strong>{quote.exact ? 'Exact narrative match' : 'Not an exact match—do not approve'}</strong></blockquote>)}</div> : <p className="inline-warning">No evidence quote was returned. This draft cannot be approved.</p>}
                {summary.suggestedActions.length ? <><h3>Suggested human actions</h3><ul>{summary.suggestedActions.map((action) => <li key={action}>{action}</li>)}</ul></> : null}
                {summary.caveats.length ? <><h3>Caveats and missing information</h3><ul>{summary.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul></> : null}
                <dl className="summary-meta"><div><dt>Latency</dt><dd>{summary.latencyMs === null ? 'Not measured' : `${summary.latencyMs} ms`}</dd></div><div><dt>Estimated API cost</dt><dd>{formatMoney(summary.estimatedCostUsd)}</dd></div></dl>

                {summary.status === 'draft' ? <fieldset className="review-gate"><legend>Human evidence review</legend><label><span>Reviewer name or ID</span><input value={summaryReviewer} onChange={(event) => setSummaryReviewer(event.target.value)} /></label><label><span>Review notes (optional)</span><textarea rows={3} value={summaryNotes} onChange={(event) => setSummaryNotes(event.target.value)} /></label><label className="checkbox-control align-start"><input type="checkbox" checked={evidenceChecked} onChange={(event) => setEvidenceChecked(event.target.checked)} /><span>I compared every displayed quote with the supplied narrative and checked the draft for unsupported claims.</span></label><div className="button-row"><button className="button button-primary" type="button" disabled={!canReviewSummary || !allQuotesExact || summaryBusy} onClick={() => submitSummaryReview('approve')}><CheckCircle2 aria-hidden="true" size={16} /> Approve summary</button><button className="button button-danger" type="button" disabled={!canReviewSummary || summaryBusy} onClick={() => submitSummaryReview('reject')}>Reject draft</button></div><p className="form-help">Approving the text does not approve the model route. Routing has a separate control.</p></fieldset> : <p className="review-record">Reviewed by <strong>{summary.reviewer || 'Unreported reviewer'}</strong>{summary.reviewedAt ? ` at ${formatDateTime(summary.reviewedAt)}` : ''}. Evidence check: {summary.evidenceChecked ? 'recorded' : 'not recorded'}.</p>}
              </div>
            )}
            {summaryError ? <p className="inline-warning" role="alert">{summaryError}</p> : null}
          </Panel>
        </div>

        <aside className="case-side-column" aria-label="Case controls and metadata">
          <Panel>
            <PanelHeader title="Routing review" description="The model may recommend or abstain. Only the named reviewer submits a route." />
            <div className="prediction-card"><span>Model suggestion</span><strong>{item.abstained ? 'Abstain—manual route required' : item.predictedRoute || 'No suggestion returned'}</strong><small>{item.confidence === null ? 'Confidence not returned' : `${formatPercent(item.confidence)} confidence`}</small></div>
            <fieldset className="route-options"><legend>Reviewer decision</legend><label><input type="radio" name="route-mode" value="approve" checked={routeMode === 'approve'} disabled={!item.predictedRoute || item.abstained} onChange={() => setRouteMode('approve')} /><span>Approve model suggestion</span></label><label><input type="radio" name="route-mode" value="override" checked={routeMode === 'override'} onChange={() => setRouteMode('override')} /><span>Override with reviewed route</span></label><label><input type="radio" name="route-mode" value="reject" checked={routeMode === 'reject'} onChange={() => setRouteMode('reject')} /><span>Reject and keep in manual review</span></label></fieldset>
            {routeMode !== 'reject' ? <label><span>{routeMode === 'approve' ? 'Suggested route' : 'Reviewed route'}</span><input value={routeMode === 'approve' ? item.predictedRoute || '' : routeChoice} readOnly={routeMode === 'approve'} onChange={(event) => setRouteChoice(event.target.value)} /></label> : null}
            <label><span>Reviewer name or ID</span><input value={routeReviewer} onChange={(event) => setRouteReviewer(event.target.value)} /></label>
            <label><span>Routing note (optional)</span><textarea rows={3} value={routeNotes} onChange={(event) => setRouteNotes(event.target.value)} /></label>
            <label className="checkbox-control align-start"><input type="checkbox" checked={routeConfirmed} onChange={(event) => setRouteConfirmed(event.target.checked)} /><span>I reviewed the narrative, published labels, model confidence, and attention flags. This is my decision—not an automated action.</span></label>
            <button className="button button-primary button-full" type="button" disabled={routeBusy || !routeReviewer.trim() || !routeConfirmed || (routeMode === 'override' && !routeChoice.trim())} onClick={submitRoute}><Route aria-hidden="true" size={16} />{routeBusy ? 'Submitting…' : routeMode === 'reject' ? 'Keep in manual review' : 'Submit reviewed route'}</button>
            {routeResult ? <p className="success-message" role="status">Decision recorded: <strong>{routeResult.route}</strong> · {sentenceCase(routeResult.status)} · reviewer {routeResult.reviewer}.</p> : null}
            {routeError ? <p className="inline-warning" role="alert">{routeError}</p> : null}
          </Panel>

          <Panel><PanelHeader title="Case facts" /><dl className="case-facts"><div><dt>Published product</dt><dd>{item.product}</dd></div><div><dt>Published issue</dt><dd>{item.issue}</dd></div><div><dt>Company</dt><dd>{item.company}</dd></div><div><dt>State</dt><dd>{item.state || 'Not supplied'}</dd></div><div><dt>Submission channel</dt><dd>{item.submissionChannel || 'Not supplied'}</dd></div><div><dt>Company response</dt><dd>{item.companyResponse || 'Pending or not supplied'}</dd></div><div><dt>Response timely</dt><dd>{item.timelyResponse === null ? 'Pending or unknown' : item.timelyResponse ? 'Yes' : 'No'}</dd></div></dl></Panel>
          <Panel><PanelHeader title="Attention reasons" />{item.attentionReasons.length ? <ul className="attention-list">{item.attentionReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>No manual-attention reasons were supplied.</p>}</Panel>
        </aside>
      </div>
    </div>
  );
};

export const CasePage = () => {
  const { caseId = '' } = useParams();
  const queue = useAsyncResource(getCases);
  if (queue.status === 'loading') return <LoadingState label="Loading case" />;
  if (queue.status === 'error') return <ErrorState message={queue.message} />;
  const item = queue.data.cases.find((candidate) => candidate.id === caseId || candidate.complaintId === caseId);
  if (!item) return <div className="page"><EmptyState title="Case not found" message="This case is not present in the current queue snapshot." /><Link className="button button-quiet" to="/queue">Return to case queue</Link></div>;
  return <CaseWorkspace item={item} parentSource={queue.data.source} />;
};
