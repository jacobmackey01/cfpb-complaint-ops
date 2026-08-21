import { ArrowDownRight, ArrowUpRight, Clock3, TriangleAlert } from 'lucide-react';
import { getAnomalies, getOverview } from '../api';
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
import { formatDecimal, formatInteger, formatPercent } from '../format';
import { useAsyncResource } from '../hooks';
import type { CategoryVolume, TimePoint } from '../types';

const VolumeSeries = ({ points }: { points: TimePoint[] }) => {
  if (points.length === 0) {
    return (
      <EmptyState
        title="No trend series returned"
        message="The snapshot summary is available, but the API did not return a time series for this view."
      />
    );
  }
  const max = Math.max(1, ...points.map((point) => point.count));
  return (
    <div className="volume-chart" role="img" aria-label="Complaint volume by period">
      {points.map((point) => (
        <div className="volume-column" key={point.period}>
          <span className="volume-value">{formatInteger(point.count)}</span>
          <div className="volume-track">
            <span style={{ height: `${Math.max(5, (point.count / max) * 100)}%` }} />
          </div>
          <span className="volume-label">{point.period}</span>
        </div>
      ))}
    </div>
  );
};

const ProductBars = ({ products }: { products: CategoryVolume[] }) => {
  if (products.length === 0) {
    return (
      <EmptyState
        title="No product breakdown returned"
        message="No product-level volume was supplied by this API response."
      />
    );
  }
  const max = Math.max(1, ...products.map((product) => product.count));
  return (
    <ol className="rank-list">
      {products.map((product) => (
        <li key={product.label}>
          <div className="rank-label">
            <span>{product.label}</span>
            <strong>{formatInteger(product.count)}</strong>
          </div>
          <div className="horizontal-track" aria-hidden="true">
            <span style={{ width: `${(product.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ol>
  );
};

export const DashboardPage = () => {
  const overview = useAsyncResource(getOverview);
  const anomalyReport = useAsyncResource(getAnomalies);

  if (overview.status === 'loading') return <LoadingState label="Loading operations overview" />;
  if (overview.status === 'error') return <ErrorState message={overview.message} />;

  const metrics = overview.data;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations control room"
        title="Complaint operations"
        description="Prioritise human review, monitor response handling, and inspect emerging themes without treating model suggestions as decisions."
      />
      <SourceNotice source={metrics.source} />
      <p className="method-note">
        Recent trends are incomplete: eligible complaints are published after a qualifying company
        response or after 15 days, whichever comes first, and narrative processing may add further lag.
      </p>

      <section className="metric-grid" aria-label="Operations metrics">
        <MetricCard
          label="Complaints in view"
          value={formatInteger(metrics.totalComplaints)}
          note={metrics.periodLabel}
        />
        <MetricCard
          label="Manual attention"
          value={formatInteger(metrics.manualAttention)}
          note="Rules, abstentions, or reviewer flags"
          tone="attention"
        />
        <MetricCard
          label="Timely responses"
          value={formatPercent(metrics.timelyRate)}
          note="Among records with a response-timeliness outcome"
          tone="positive"
        />
        <MetricCard
          label="Routing abstention"
          value={formatPercent(metrics.abstentionRate)}
          note="Sent to human review instead of auto-routing"
        />
      </section>

      <div className="dashboard-grid">
        <Panel className="panel-wide">
          <PanelHeader
            title="Volume pulse"
            description="Counts over the periods returned by the API; no company comparison is implied."
            action={
              metrics.volumeChange === null ? null : (
                <Pill tone={metrics.volumeChange > 0 ? 'warning' : 'success'}>
                  {metrics.volumeChange > 0 ? (
                    <ArrowUpRight aria-hidden="true" size={14} />
                  ) : (
                    <ArrowDownRight aria-hidden="true" size={14} />
                  )}
                  {formatPercent(Math.abs(metrics.volumeChange))}
                </Pill>
              )
            }
          />
          <VolumeSeries points={metrics.series} />
        </Panel>

        <Panel>
          <PanelHeader
            title="Product mix"
            description="Raw CFPB volume is workload, not a market-share-adjusted performance ranking."
          />
          <ProductBars products={metrics.products} />
        </Panel>

        <Panel className="panel-wide">
          <PanelHeader
            title="Emerging-theme monitor"
            description="Rolling-baseline alerts are prompts to inspect cases—not findings or causal conclusions."
            action={
              anomalyReport.status === 'ready' ? (
                <code className="source-chip">{anomalyReport.data.source.sourceKind}</code>
              ) : null
            }
          />
          {anomalyReport.status === 'loading' ? (
            <LoadingState label="Checking anomaly feed" />
          ) : anomalyReport.status === 'error' ? (
            <ErrorState message={anomalyReport.message} />
          ) : anomalyReport.data.anomalies.length === 0 ? (
            <EmptyState
              title="No threshold crossings"
              message="No product or issue combination crossed the configured monitoring threshold."
            />
          ) : (
            <div className="anomaly-list">
              {anomalyReport.data.anomalies.map((anomaly) => (
                <article className="anomaly-row" key={anomaly.id}>
                  <div className={`severity-mark severity-${anomaly.severity}`} aria-hidden="true" />
                  <div className="anomaly-copy">
                    <div className="anomaly-title">
                      <strong>{anomaly.issue}</strong>
                      <Pill
                        tone={
                          anomaly.severity === 'high'
                            ? 'danger'
                            : anomaly.severity === 'medium'
                              ? 'warning'
                              : 'info'
                        }
                      >
                        {anomaly.severity}
                      </Pill>
                    </div>
                    <p>{anomaly.product}</p>
                    <small>{anomaly.explanation}</small>
                  </div>
                  <div className="anomaly-stat">
                    {anomaly.direction === 'up' ? (
                      <TriangleAlert aria-hidden="true" size={16} />
                    ) : (
                      <Clock3 aria-hidden="true" size={16} />
                    )}
                    <strong>{formatInteger(anomaly.observed)}</strong>
                    <span>
                      baseline {formatInteger(anomaly.expected)} · z {formatDecimal(anomaly.zScore, 1)}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
          {anomalyReport.status === 'ready' && anomalyReport.data.source.isDemo ? (
            <p className="inline-warning">
              This anomaly list is synthetic demonstration data; it is not evidence of an emerging CFPB theme.
            </p>
          ) : null}
        </Panel>
      </div>
    </div>
  );
};
