import { getModelMetrics } from '../api';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Panel,
  PanelHeader,
  Pill,
  SourceNotice,
} from '../components/DataUi';
import {
  formatDecimal,
  formatInteger,
  formatMoney,
  formatPercent,
  sentenceCase,
} from '../format';
import { useAsyncResource } from '../hooks';

export const ModelPage = () => {
  const resource = useAsyncResource(getModelMetrics);
  if (resource.status === 'loading') return <LoadingState label="Loading model evaluation" />;
  if (resource.status === 'error') return <ErrorState message={resource.message} />;

  const model = resource.data;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Integrity and reliability"
        title="Model monitor"
        description="Chronological holdout quality, selective-routing behaviour, drift, and AI-summary controls in one reviewable record."
        actions={<Pill tone="neutral">{model.modelVersion}</Pill>}
      />
      <SourceNotice source={model.source} />

      <section className="model-context" aria-label="Model evaluation context">
        <div>
          <span>Model</span>
          <strong>{model.modelName}</strong>
        </div>
        <div>
          <span>Target</span>
          <strong>{model.target}</strong>
        </div>
        <div>
          <span>Validation</span>
          <strong>{model.validationWindow}</strong>
        </div>
        <div>
          <span>Evaluated rows</span>
          <strong>{formatInteger(model.evaluatedRows)}</strong>
        </div>
      </section>

      <section className="metric-grid model-metrics" aria-label="Routing quality metrics">
        <MetricCard label="Macro-F1" value={formatDecimal(model.macroF1)} note="Across labels in chronological holdout" />
        <MetricCard
          label="Calibration error (ECE)"
          value={formatDecimal(model.expectedCalibrationError)}
          note="Lower is better; confidence is not certainty"
        />
        <MetricCard
          label="Routing coverage"
          value={formatPercent(model.coverage)}
          note={`At ${formatPercent(model.abstentionThreshold, 0)} confidence threshold`}
        />
        <MetricCard
          label="Abstention rate"
          value={formatPercent(model.abstentionRate)}
          note="Cases held for a person instead of assigned"
          tone="attention"
        />
      </section>

      {model.source.isDemo ? (
        <p className="inline-warning prominent-warning">
          These performance values are synthetic UI fixtures. They are not results from the CFPB snapshot or a trained production model.
        </p>
      ) : null}

      <div className="model-grid">
        <Panel>
          <PanelHeader
            title="Calibration by confidence band"
            description="Observed accuracy should track mean confidence on the frozen holdout."
          />
          {model.calibration.length === 0 ? (
            <EmptyState title="No calibration bins" message="The API did not return calibration-bin evidence." />
          ) : (
            <div className="calibration-chart" role="img" aria-label="Confidence compared with observed accuracy">
              {model.calibration.map((bin) => (
                <div className="calibration-row" key={`${bin.lower}-${bin.upper}`}>
                  <span>{formatPercent(bin.lower, 0)}–{formatPercent(bin.upper, 0)}</span>
                  <div className="dual-bar">
                    <span className="confidence-bar" style={{ width: `${bin.meanConfidence * 100}%` }} />
                    <span className="accuracy-bar" style={{ width: `${bin.accuracy * 100}%` }} />
                  </div>
                  <span>{formatInteger(bin.count)}</span>
                </div>
              ))}
              <div className="chart-legend">
                <span><i className="legend-confidence" /> Mean confidence</span>
                <span><i className="legend-accuracy" /> Observed accuracy</span>
              </div>
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="False-routing patterns"
            description="Most common reviewed confusions; counts require the evaluation denominator above."
          />
          {model.falseRoutes.length === 0 ? (
            <EmptyState title="No confusion detail" message="No reviewed false-routing patterns were returned." />
          ) : (
            <ol className="false-route-list">
              {model.falseRoutes.map((pattern) => (
                <li key={`${pattern.actual}-${pattern.predicted}`}>
                  <div>
                    <small>Actual</small>
                    <strong>{pattern.actual}</strong>
                  </div>
                  <span aria-hidden="true">→</span>
                  <div>
                    <small>Suggested</small>
                    <strong>{pattern.predicted}</strong>
                  </div>
                  <Pill tone="warning">{formatInteger(pattern.count)}</Pill>
                </li>
              ))}
            </ol>
          )}
        </Panel>

        <Panel className="panel-wide">
          <PanelHeader
            title="Monthly and product drift"
            description="Performance and distribution checks should be segmented; an alert triggers investigation, not automatic retraining."
          />
          {model.drift.length === 0 ? (
            <EmptyState title="No drift series" message="The API did not return monthly or product-level drift checks." />
          ) : (
            <div className="table-shell compact-table-shell">
              <table className="monitor-table">
                <caption>Model drift checks by month and product</caption>
                <thead>
                  <tr>
                    <th scope="col">Period</th>
                    <th scope="col">Product</th>
                    <th scope="col">Macro-F1</th>
                    <th scope="col">Abstention</th>
                    <th scope="col">Drift score</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {model.drift.map((point) => (
                    <tr key={`${point.period}-${point.product}`}>
                      <td>{point.period}</td>
                      <td>{point.product}</td>
                      <td>{formatDecimal(point.macroF1)}</td>
                      <td>{formatPercent(point.abstentionRate)}</td>
                      <td>{formatDecimal(point.driftScore, 2)}</td>
                      <td>
                        <Pill
                          tone={
                            point.status === 'alert'
                              ? 'danger'
                              : point.status === 'watch'
                                ? 'warning'
                                : point.status === 'stable'
                                  ? 'success'
                                  : 'neutral'
                          }
                        >
                          {sentenceCase(point.status)}
                        </Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel className="panel-wide">
          <PanelHeader
            title="AI summary and system controls"
            description="Operational measurements remain separate from routing quality. Human review is the release gate."
          />
          <dl className="integrity-grid">
            <div>
              <dt>Summary factuality</dt>
              <dd>
                {model.summaryReviewedN === 0 || model.summaryFactuality === null
                  ? 'Not measured'
                  : formatPercent(model.summaryFactuality)}
              </dd>
              <small>Manually reviewed n={formatInteger(model.summaryReviewedN)}</small>
            </div>
            <div>
              <dt>API latency p50 / p95</dt>
              <dd>{formatInteger(model.latencyP50Ms)} ms / {formatInteger(model.latencyP95Ms)} ms</dd>
              <small>Measured request latency</small>
            </div>
            <div>
              <dt>Mean API cost</dt>
              <dd>{formatMoney(model.meanApiCostUsd)}</dd>
              <small>Per summary request</small>
            </div>
            <div>
              <dt>System failures</dt>
              <dd>{formatInteger(model.systemFailures)}</dd>
              <small>Explicit failed requests in the evaluation window</small>
            </div>
            <div>
              <dt>Refusal rate</dt>
              <dd>{formatPercent(model.refusalRate)}</dd>
              <small>Safe refusals and missing-narrative responses</small>
            </div>
          </dl>
          {model.summaryReviewedN === 0 ? (
            <p className="inline-warning">
              No summary factuality claim is shown because the reviewed sample size is zero.
            </p>
          ) : null}
        </Panel>
      </div>
    </div>
  );
};
