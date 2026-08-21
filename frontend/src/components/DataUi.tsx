import { AlertTriangle, CheckCircle2, Database, FlaskConical } from 'lucide-react';
import type { PropsWithChildren, ReactNode } from 'react';
import { formatDateTime } from '../format';
import type { SourceMeta } from '../types';

interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}

export const PageHeader = ({ eyebrow, title, description, actions }: PageHeaderProps) => (
  <header className="page-header">
    <div>
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="page-description">{description}</p>
    </div>
    {actions ? <div className="page-actions">{actions}</div> : null}
  </header>
);

export const SourceNotice = ({ source }: { source: SourceMeta }) => {
  if (source.isDemo) {
    return (
      <section className="source-notice source-demo" aria-label="Synthetic demo data notice">
        <FlaskConical aria-hidden="true" size={20} />
        <div>
          <strong>Offline synthetic demonstration</strong>
          <p>
            The API is unavailable or returned demo data. Every value on this view is illustrative—not
            a live CFPB observation, production result, or reviewed performance claim. Review actions
            in this demo are session-only and are not persisted.
          </p>
          <code>source_kind={source.sourceKind}</code>
        </div>
      </section>
    );
  }

  if (source.isVerifiedPublicData) {
    return (
      <section className="source-notice source-public" aria-label="CFPB snapshot source">
        <Database aria-hidden="true" size={20} />
        <div>
          <strong>CFPB public-data snapshot</strong>
          <p>
            Frozen public snapshot{source.generatedAt ? ` as of ${formatDateTime(source.generatedAt)}` : ''};
            this is not a live operational feed.
          </p>
          <code>source_kind={source.sourceKind}</code>
        </div>
      </section>
    );
  }

  return (
    <section className="source-notice source-unknown" aria-label="Unverified data provenance warning">
      <AlertTriangle aria-hidden="true" size={20} />
      <div>
        <strong>Source provenance is unverified</strong>
        <p>
          The API did not provide a recognised CFPB snapshot source. Treat these values as unverified;
          they are not labelled as live or public CFPB results.
        </p>
        <code>source_kind={source.sourceKind}</code>
      </div>
    </section>
  );
};

interface MetricCardProps {
  label: string;
  value: string;
  note: string;
  tone?: 'default' | 'attention' | 'positive';
}

export const MetricCard = ({ label, value, note, tone = 'default' }: MetricCardProps) => (
  <article className={`metric-card metric-${tone}`}>
    <p>{label}</p>
    <strong>{value}</strong>
    <small>{note}</small>
  </article>
);

export const Panel = ({ children, className = '' }: PropsWithChildren<{ className?: string }>) => (
  <section className={`panel ${className}`.trim()}>{children}</section>
);

export const PanelHeader = ({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) => (
  <header className="panel-header">
    <div>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
    </div>
    {action ? <div>{action}</div> : null}
  </header>
);

export const LoadingState = ({ label = 'Loading data' }: { label?: string }) => (
  <div className="loading-state" role="status">
    <span className="spinner" aria-hidden="true" />
    <span>{label}…</span>
  </div>
);

export const ErrorState = ({ message }: { message: string }) => (
  <div className="error-state" role="alert">
    <AlertTriangle aria-hidden="true" size={20} />
    <span>{message}</span>
  </div>
);

export const EmptyState = ({ title, message }: { title: string; message: string }) => (
  <div className="empty-state">
    <CheckCircle2 aria-hidden="true" size={24} />
    <strong>{title}</strong>
    <p>{message}</p>
  </div>
);

export const Pill = ({
  children,
  tone = 'neutral',
}: PropsWithChildren<{ tone?: 'neutral' | 'danger' | 'warning' | 'success' | 'info' }>) => (
  <span className={`pill pill-${tone}`}>{children}</span>
);
