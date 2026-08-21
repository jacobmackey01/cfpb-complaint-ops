import { Search } from 'lucide-react';
import { useDeferredValue, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCases } from '../api';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SourceNotice,
} from '../components/DataUi';
import { formatDate, formatPercent, sentenceCase } from '../format';
import { useAsyncResource } from '../hooks';
import type { CasePriority, CaseRecord } from '../types';

const priorityTone = (priority: CasePriority) => {
  if (priority === 'urgent') return 'danger' as const;
  if (priority === 'high') return 'warning' as const;
  if (priority === 'low') return 'success' as const;
  return 'neutral' as const;
};

const searchable = (item: CaseRecord) =>
  [item.complaintId, item.company, item.product, item.issue, item.state]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

export const QueuePage = () => {
  const queue = useAsyncResource(getCases);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const [manualOnly, setManualOnly] = useState(true);
  const [status, setStatus] = useState('all');
  const [sort, setSort] = useState('priority');

  const filtered = useMemo(() => {
    if (queue.status !== 'ready') return [];
    const priorityRank: Record<CasePriority, number> = { urgent: 0, high: 1, standard: 2, low: 3 };
    return [...queue.data.cases]
      .filter((item) => !manualOnly || item.manualAttention)
      .filter((item) => status === 'all' || item.status === status)
      .filter((item) => !deferredSearch || searchable(item).includes(deferredSearch))
      .sort((left, right) => {
        if (sort === 'newest') return right.dateReceived.localeCompare(left.dateReceived);
        if (sort === 'confidence') return (left.confidence ?? -1) - (right.confidence ?? -1);
        return priorityRank[left.priority] - priorityRank[right.priority];
      });
  }, [deferredSearch, manualOnly, queue, sort, status]);

  if (queue.status === 'loading') return <LoadingState label="Loading case queue" />;
  if (queue.status === 'error') return <ErrorState message={queue.message} />;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Human review workspace"
        title="Case queue"
        description="Find low-confidence, rule-flagged, and operationally sensitive complaints. Routing remains a reviewer action."
        actions={<Pill tone="info">{filtered.length} shown</Pill>}
      />
      <SourceNotice source={queue.data.source} />

      <section className="queue-controls" aria-label="Queue filters">
        <label className="search-field">
          <span>Search complaints</span>
          <span className="input-with-icon">
            <Search aria-hidden="true" size={17} />
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="ID, product, issue, company, state"
              type="search"
              value={search}
            />
          </span>
        </label>
        <label>
          <span>Status</span>
          <select onChange={(event) => setStatus(event.target.value)} value={status}>
            <option value="all">All statuses</option>
            <option value="new">New</option>
            <option value="in_review">In review</option>
            <option value="routed">Routed</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label>
          <span>Sort</span>
          <select onChange={(event) => setSort(event.target.value)} value={sort}>
            <option value="priority">Attention priority</option>
            <option value="newest">Newest received</option>
            <option value="confidence">Lowest confidence</option>
          </select>
        </label>
        <label className="checkbox-control">
          <input
            checked={manualOnly}
            onChange={(event) => setManualOnly(event.target.checked)}
            type="checkbox"
          />
          <span>Manual attention only</span>
        </label>
      </section>

      {filtered.length === 0 ? (
        <EmptyState
          title="No cases match these filters"
          message="Change the search, status, or manual-attention filter to widen the queue."
        />
      ) : (
        <div className="table-shell">
          <table className="case-table">
            <caption>
              Complaint cases requiring operational review. Confidence is a model score, not a decision.
            </caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Product and issue</th>
                <th scope="col">Attention</th>
                <th scope="col">Model suggestion</th>
                <th scope="col">Response</th>
                <th scope="col">
                  <span className="sr-only">Open case</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link className="case-id-link" to={`/cases/${encodeURIComponent(item.id)}`}>
                      {item.complaintId}
                    </Link>
                    <span className="table-secondary">{formatDate(item.dateReceived)}</span>
                    <span className="table-secondary">{item.company}</span>
                  </td>
                  <td>
                    <strong>{item.product}</strong>
                    <span className="table-secondary">{item.issue}</span>
                  </td>
                  <td>
                    <Pill tone={priorityTone(item.priority)}>{item.priority}</Pill>
                    <span className="table-secondary">
                      {item.attentionReasons[0] || (item.manualAttention ? 'Review flag' : 'Standard queue')}
                    </span>
                  </td>
                  <td>
                    <strong>{item.abstained ? 'Abstained' : item.predictedRoute || 'No suggestion'}</strong>
                    <span className="table-secondary">
                      {item.confidence === null ? 'No score' : `${formatPercent(item.confidence)} confidence`}
                    </span>
                  </td>
                  <td>
                    <Pill
                      tone={
                        item.timelyResponse === false
                          ? 'danger'
                          : item.timelyResponse === true
                            ? 'success'
                            : 'neutral'
                      }
                    >
                      {item.timelyResponse === null
                        ? 'Pending'
                        : item.timelyResponse
                          ? 'Timely'
                          : 'Untimely'}
                    </Pill>
                    <span className="table-secondary">{sentenceCase(item.status)}</span>
                  </td>
                  <td>
                    <Link className="button button-small button-quiet" to={`/cases/${encodeURIComponent(item.id)}`}>
                      Review
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
