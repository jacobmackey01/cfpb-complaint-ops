# Requirements, user stories and acceptance criteria

## Product objective

Give a complaints-operations manager one evidence-backed workspace for routing
new complaints, finding cases that need attention, detecting emerging themes
and monitoring operations and model behaviour. The product assists human
judgement; it never makes or records an unreviewed final decision.

## Primary user

The primary user is an operations manager responsible for queue health,
routing quality and escalation. A data/model steward is a secondary user who
owns snapshot, evaluation and release evidence. The public portfolio visitor
is a demonstration viewer, not an authenticated operator.

## User stories

### US-1 — Triage a case

As an operations manager, I want to see a proposed product or issue route with
confidence and evidence so that I can approve, override or send the case for
manual review.

Acceptance criteria:

1. Each queue row shows complaint ID, submission date, current product/issue,
   proposed route, calibrated confidence, attention reasons and model version.
2. Confidence below the frozen threshold displays `abstain` and cannot be
   presented as an automatic route.
3. Approve and override are explicit human actions, distinct from the model
   proposal in the UI and API payload.
4. An override requires the chosen label; a durable deployment also records
   reviewer identity, timestamp, reason and the original proposal.
5. Public-demo actions are visibly labelled ephemeral and do not claim durable
   auditability.

### US-2 — Prioritise manual attention

As an operations manager, I want one explainable attention state so that I can
focus on low-confidence, anomalous, failed or otherwise unresolved cases.

Acceptance criteria:

1. Attention reasons are enumerated, not collapsed into an unexplained score.
2. At minimum, abstention, model/service failure and summary refusal/failure can
   place a case in manual review.
3. Filtering by attention reason produces a stable count and is keyboard
   operable.
4. Missing data is shown as missing; it is not silently interpreted as a
   negative outcome.

### US-3 — Inspect an evidence-grounded draft

As an operations manager, I want a short narrative draft with source excerpts
so that I can verify it before accepting any of its wording.

Acceptance criteria:

1. The service accepts only a supplied narrative and approved structured case
   fields; it does not retrieve unsupported external facts.
2. Every response validates against the documented Pydantic schema.
3. Every evidence excerpt occurs verbatim in the supplied narrative; otherwise
   the response fails closed.
4. The initial approval status is `pending_human_review`.
5. The UI never labels a generated draft as approved until an explicit human
   action occurs.
6. Provider-disabled, timeout, refusal, invalid-schema and quote-mismatch states
   are visible and measurable.

### US-4 — Monitor operations

As an operations manager, I want volumes and response-timeliness trends so that
I can detect workload changes and follow up operationally.

Acceptance criteria:

1. Every metric shows its time range, denominator, snapshot timestamp and
   filters.
2. Timely-response rate follows the definition in
   [metrics-and-evaluation.md](metrics-and-evaluation.md); missing eligibility
   is reported separately.
3. Recent potentially incomplete periods display a publication-lag warning.
4. The dashboard displays the CFPB non-representativeness limitation.
5. Raw company totals are not labelled as comparative company performance and
   no company ranking is shown without an external exposure denominator.

### US-5 — Investigate emerging themes

As an operations manager, I want anomaly flags by product and issue with the
underlying counts so that I can distinguish a meaningful signal from a noisy
alert.

Acceptance criteria:

1. A flag shows product/issue, period, observed count, prior-only baseline,
   deviation, detector version and minimum-support status.
2. Users can inspect the underlying time series and filters that produced it.
3. The detector excludes or labels publication-lag-sensitive periods.
4. The interface describes the result as an anomaly for investigation, not a
   causal finding or forecast.

### US-6 — Monitor the router

As a model steward, I want frozen routing, calibration, coverage and drift
evidence so that I can decide whether the model remains safe to propose routes.

Acceptance criteria:

1. The page reports chronological split boundaries and record counts from the
   evaluation manifest.
2. Macro-F1, accepted-route accuracy, coverage, abstention, calibration and
   false-routing patterns use documented denominators.
3. Results are broken down by month and product when support is sufficient;
   low-support cells are suppressed or marked unstable.
4. The abstention threshold is selected on validation data and frozen before
   the test set is evaluated.
5. Drift is shown separately from performance; a distribution change alone is
   not called an accuracy decline.
6. Missing, stale or hash-mismatched artifacts produce an unavailable state,
   not placeholder metrics.

### US-7 — Monitor the summary system

As a model steward, I want manually reviewed factuality, latency, token cost,
failure and refusal measures so that I can bound the risk and operating cost of
the LLM feature.

Acceptance criteria:

1. Factuality is reported only from a documented manual sample and includes the
   sample count, selection method, rubric version and reviewer status.
2. Latency reports p50 and p95 with a request denominator and timeout handling.
3. Cost uses recorded input/output tokens and a dated price table; estimates
   are identified as estimates.
4. Failures and refusals have separate categories and denominators.
5. No summary metric is inferred from routing performance.

### US-8 — Reproduce a data release

As a data steward, I want a bounded snapshot request, QA report and hashes so
that I can trace every displayed value to a declared CFPB extraction.

Acceptance criteria:

1. The extraction requires `as_of` and `max_records <= 100000`.
2. A successful run writes a request record and manifest containing source,
   query, timestamps, field list, record count, date range, hashes, QA outcome
   and code revision.
3. A failed required QA check prevents downstream promotion.
4. Every aggregate, model and evaluation artifact references the snapshot ID
   and its parent hash.
5. Raw narratives and narrative-bearing DuckDB files remain outside Git and
   have a documented deletion/withdrawal procedure.

## Cross-cutting acceptance gates

### Data integrity

- The public snapshot contains no more than 100,000 complaints.
- Duplicate complaint IDs, schema drift, invalid dates and required-field
  missingness are measured and handled by an explicit rule.
- Snapshot and promoted artifact hashes are checked before service startup.
- Aggregate queries reconcile to the canonical DuckDB fact count for the same
  filters.

### Model integrity

- All split logic is chronological and persisted.
- Calibration and threshold selection use validation data only.
- The frozen test set is not reused for iterative feature or threshold choice.
- Results carry uncertainty/support context and never substitute training
  performance for held-out performance.

### Human control

- Model proposals and LLM drafts start unapproved.
- Abstention and all service failures route to human attention.
- A public demonstration cannot imply persistent approval state.
- A durable deployment records immutable proposal and human-decision events.

### Accessibility and interface quality

- Core queue, dashboard and monitoring paths are usable by keyboard.
- Status is not communicated by colour alone.
- Tables have accessible names, controls have labels and charts have textual
  summaries.
- Loading, empty, error, unavailable and stale states are distinct.
- Layouts remain usable at narrow mobile and desktop widths.

### Engineering and release

- Backend and frontend automated tests, linting, builds and the repository
  privacy guard pass in GitHub Actions.
- Docker Compose builds the API, frontend and gateway from a clean checkout.
- `GET /health` succeeds without an LLM key.
- The deployment runbook records the exact commit SHA, artifact hashes and
  verified public endpoint; no URL is claimed before that check passes.

## Explicit non-goals

- Automated complaint disposition, customer contact or regulatory advice.
- Company performance rankings from raw CFPB complaint totals.
- Population prevalence estimates from the complaint database.
- Treating anomaly flags as causes or forecasts.
- Publishing withdrawn or local narrative data.
- Claiming the Vercel interface demonstration is a production case-management
  system.

