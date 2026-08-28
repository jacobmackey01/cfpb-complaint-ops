# Metric and evaluation definitions

This document is the metric contract for the application. A displayed or
portfolio metric is valid only when its artifact records the snapshot ID,
chronological split, code/model version, denominator and calculation version.
Training-set results and hand-entered values are not release evidence.

## Global conventions

- `N` is always the number of eligible records after named exclusions; the raw
  snapshot count is reported separately.
- Dates are interpreted in the source field's documented grain and stored with
  an explicit timezone where a timestamp exists.
- Missing and `not applicable` values are separate from negative outcomes.
- Filtered UI metrics recompute both numerator and denominator.
- Cells below the artifact's declared minimum support are marked low support or
  suppressed; they are not silently merged into an `other` success result.
- Point estimates are accompanied by support. Release reports add bootstrap or
  binomial confidence intervals where the sampling assumptions are defensible.
- All `test` metrics use the frozen chronological test partition. Validation
  results used for threshold choice are labelled validation results.

## Operational metrics

### Complaint volume

For a period and filter:

```text
complaint_volume = count(distinct complaint_id)
```

The view must show the period, snapshot timestamp and publication-lag warning.
Volume measures records published in the CFPB database, not incidence in the
consumer population or product market.

### Narrative availability

```text
narrative_availability = complaints_with_non_empty_published_narrative
                         / complaints_in_scope
```

This is a consent/publication measure. It is not data quality evidence that
narrative-bearing complaints represent all complaints.

### Timely-response rate

```text
timely_response_rate = complaints_where_timely_response_is_yes
                       / complaints_where_timely_response_is_yes_or_no
```

The dashboard also reports the count excluded because the timeliness field is
missing or outside the recognised `Yes`/`No` domain. The value describes the
published CFPB field for the selected complaints. It is not a company ranking;
raw complaint records provide no market-share denominator.

### Manual-attention rate

```text
manual_attention_rate = cases_with_one_or_more_attention_reasons
                        / cases_loaded_into_the_queue
```

Reasons are reported separately: routing abstention, unavailable artifact,
model/service failure, summary refusal/failure, and any deterministic rule the
release explicitly defines. Overlapping reasons mean their percentages need
not sum to 100%.

## Routing evaluation

### Eligibility and target

The evaluation manifest names the target. The current trained artifact targets `product`; `issue` is used for filtering and separate trend/anomaly monitoring, not presented as a trained issue router. A future issue router must publish its own target-specific split, support, calibration and abstention evidence. The label mapping, minimum class support, exclusions and features are recorded. Only information available at the routing decision time is eligible. The current public label is used as a
supervised target, not as proof that the label is objectively correct.

Records are sorted chronologically with a deterministic complaint-ID tie-break.
The partitions are contiguous:

```text
training period < validation period < frozen test period
```

The validation partition selects hyperparameters, probability calibration and
the abstention threshold. The test partition remains unopened until those
choices and artifact hashes are frozen. The release gate is explicit: the
frozen test window covers the last three complete months, requires at least 50
narrative-eligible rows and at least two rows for every product represented in
that window. If the gate fails, routing performance is returned as
`unavailable_insufficient_test_support`; no macro-F1, accuracy, calibration or
coverage claim is published. Normalized duplicate narratives are grouped by
SHA-256 and the earliest row is retained so the same text cannot cross a split.

The current local release passes this gate with 112 test rows across May--July
2026 and support of at least two for each represented product. This is still a
snapshot-sample evaluation, not a representative population estimate.


### Macro-F1

For each target class `k`, precision and recall are calculated on every
eligible frozen-test record using the model's highest-probability label before
abstention:

```text
F1_k = 2 * precision_k * recall_k / (precision_k + recall_k)
macro_F1 = mean(F1_k for every evaluated class k)
```

A zero-denominator class receives the documented library behaviour and is
listed explicitly. Macro-F1 gives each evaluated class equal weight; weighted
or micro scores may be supplementary but cannot replace it.

### Calibration

The primary confidence is `max_k p(k | x)`. Calibration evidence includes a
reliability table/plot and:

```text
multiclass_Brier = (1 / N) * sum_i sum_k (p_ik - y_ik)^2
ECE = sum_b (n_b / N) * abs(accuracy_b - mean_confidence_b)
```

ECE bin edges and the number of bins are stored in the artifact. Because ECE
depends on binning, it is never reported without that configuration. The
uncalibrated and calibrated models are compared on validation data; the chosen
calibrator is then frozen.

### Abstention and coverage

For frozen threshold `t`, a case is accepted only when its maximum calibrated
probability is at least `t` and no hard failure/invalid-input rule applies.

```text
coverage(t) = accepted_predictions / all_eligible_test_cases
abstention_rate(t) = abstained_predictions / all_eligible_test_cases
accepted_route_accuracy(t) = correct_accepted_predictions
                             / accepted_predictions
selective_risk(t) = 1 - accepted_route_accuracy(t)
```

When no prediction is accepted, accepted-route accuracy is undefined, not
zero. A coverage-versus-selective-risk curve is retained. The release records
the validation-only selection rule for `t`; the threshold is not tuned to make
the test result look favourable.

The application's route remains a proposal even above `t`. `Accepted` in this
metric means accepted by the threshold, not approved by a person.

### False-routing patterns

False routes are reported as counts and rates with denominators, including:

- the most frequent actual-to-proposed confusion pairs;
- false-route rate by actual class and proposed class;
- results by month and, for issue routing, by parent product;
- confidence distribution for incorrect accepted predictions; and
- support/low-support status for every slice.

Narrative examples are not published in the artifact. A reviewer can inspect
them locally under the narrative data controls.

### Drift

Drift is a change in input or label distribution, not automatically a change in
quality. For each month and product, the monitor records support and a declared
distance against the frozen training reference, such as Jensen-Shannon
divergence for categorical distributions. If target labels have matured, the
same slice may also report macro-F1, accepted-route accuracy, coverage and ECE.

```text
JSD(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
where M = 0.5 * (P + Q)
```

The artifact stores smoothing, category grouping and alert thresholds.
Small-support slices are labelled unstable. A drift alert requires review; it
does not itself trigger retraining or model promotion.

## Trend and anomaly evidence

An anomaly row contains the product/issue series, interval, observed count,
prior-only baseline, expected range or score, detector configuration, minimum
support and snapshot ID. The detector must meet these evaluation controls:

- baseline data precede the scored interval;
- the publication-lag exclusion is recorded;
- missing periods are distinguished from true zero counts;
- the minimum-support rule prevents unstable percentage spikes; and
- alert counts and reviewer dispositions are retained by detector version.

Useful monitoring measures are alerts per scored series-period, percentage of
alerts reviewed, and reviewer-confirmed actionability. Actionability is a
human workflow label, not statistical proof that an alert is a true event.

## LLM summary evaluation

### Schema and quote validity

Every provider response must parse into the current Pydantic schema. Each
evidence excerpt must be a byte-for-byte or documented Unicode-normalised
substring of the supplied narrative.

```text
schema_valid_rate = schema_valid_responses / completed_provider_responses
quote_valid_rate = responses_where_every_quote_is_verified
                   / schema_valid_responses
```

Invalid schema or quote mismatch fails closed and is also counted in system
failures.

### Manual factuality

A frozen sample is selected before review and records its source population,
strata, random seed, sample count and exclusions. This implementation records a
summary-level 1--5 factuality score, an all-claims-supported boolean and an
exact-quote boolean for each reviewed draft. It does not claim to measure
atomic-claim counts, material omissions, reviewer disagreement or adjudication;
those require a future rubric extension. The reported quantities are:

```
mean_factuality_score = sum(reviewed 1--5 scores) / reviewed summaries
all_claims_supported_rate = summaries marked true / reviewed summaries
exact_quote_rate = summaries with exact quotes / reviewed summaries
```

An automated quote check supports the reviewer but does not substitute for the
manual sample. The result cannot be generalised beyond its documented
selection frame.

### Private review worksheet

The command `cfpb-triage export-summary-review` accepts only a sample whose
status is `frozen_unreviewed` and writes a bounded CSV containing IDs and
stratification fields (`complaint_id`, month and product) plus blank rubric
columns. It deliberately excludes complaint narratives, generated summaries and
free-text reviewer notes. The export is a worksheet, not review evidence: it
returns `reviewed_sample_count=0`, does not mutate the frozen sample, and refuses
to export a sample with another status. Reviewers inspect narratives and drafts
under approved private data controls; only completed review records may change
the monitoring metrics.

The companion `cfpb-triage build-summary-manifest` command creates a private
ID-only manifest from the generated Luna pack. It stores each complaint ID,
summary ID, model name and draft SHA-256, but never narrative text. The
`cfpb-triage import-summary-review` command requires that manifest as well as
the exact worksheet columns; every row's complaint ID, summary ID and
month/product stratum must match the frozen sample and generated-draft
manifest. It validates all rows before writing `SummaryEvaluationStore`
records, rejects narrative or extra columns, and leaves the frozen sample
status unchanged. Imported rows with
`included_in_review_sample=false` remain stored for audit but are excluded from
the reported factuality denominator. The review table records the private
manifest hash and draft lineage; the manifest and worksheet remain local.

### Latest private review evidence

On 2026-08-23, the frozen, deterministic sample was reviewed under private local
controls and imported without changing the source sample. The evidence is:

- reviewed sample count: 50 of 50;
- mean factuality score: 4.86 on the 1--5 rubric;
- all-claims-supported rate: 0.90; and
- exact-quote rate: 1.0.

The sample manifest SHA-256 is
`c9e13f5d11a98a3e63e75f423a8fca512bca59d93f67b300d988ce27ed2c4a4c`, with parent
snapshot SHA-256 `d393f6a83dc9c5248bf969ff6470c498b84397a46dfc93f7a229360d00db0864`.
The private generated-draft manifest SHA-256 is
`958a5580594f3740729190806fd71160ea82e3e4bab849f6a36a18989eafd3b1`, and all
50 imported rows are bound to it. These measurements describe the documented frozen selection frame only; they do
not generalise to all CFPB complaints. The public Vercel demonstration does not
persist this private review store, so it correctly reports no runtime factuality
sample.



### Public evidence visual

The README figure at docs/assets/summary_factuality_review.svg is generated directly from
the public aggregate artifact
artifacts/public/summary_factuality_review_metrics.json. From the repository root,
regenerate it with:

    python scripts/generate_summary_factuality_visual.py

The generator validates score counts, lineage-bound review support, the weighted mean,
rates and review mode before writing deterministic SVG bytes. The figure contains
aggregate evidence only; narratives, generated drafts and row-level review data remain
private.

### Latency

For all summary attempts, measure server-side monotonic elapsed time and report
count, p50 and p95 for:

- total request latency;
- provider latency; and
- validation/post-processing latency.

Timeouts are included in attempt and failure counts and reported separately;
they are not dropped from the latency narrative merely because no normal
response was returned.

### API cost

Record provider-reported input and output token counts per completed request.
The monitoring estimate is:

```text
estimated_cost_usd = input_tokens / 1_000_000 * input_rate
                   + output_tokens / 1_000_000 * output_rate
```

The repository default price table is versioned **2026-08-21** and configures
`gpt-5.6-luna` at **$0.20 per million input tokens** and **$1.20 per million
output tokens**. These are configuration assumptions for reproducible cost
estimation, not measured spend and not a promise of future pricing. A release
must verify current provider pricing, retain the model identifier and dated
rates used, and label missing/estimated usage explicitly.

### Failures and refusals

Operational outcomes are mutually exclusive at the top level:

- `success_pending_human_review`;
- `disabled`;
- `provider_refusal`;
- `timeout`;
- `provider_error`;
- `schema_validation_error`;
- `quote_validation_error`; or
- `input_rejected`.

```text
system_failure_rate = (timeouts + provider_errors + schema_errors
                       + quote_errors) / all_summary_attempts
provider_refusal_rate = provider_refusals / provider_calls
input_rejection_rate = input_rejections / all_summary_attempts
```

The evaluation suite also contains expected-refusal cases. Its pass rate is the
percentage for which the system fails safely with the expected category and no
unsupported draft. This safety-test result is separate from the observed
operational refusal rate.

## Artifact requirements

Each promoted evaluation JSON contains at least:

- artifact schema version and creation timestamp;
- Git commit SHA and model/configuration hash;
- snapshot ID plus request, row and parent artifact hashes;
- target, features and chronological split boundaries/counts;
- label mapping and support by class/month/product;
- calibration and abstention configuration;
- every metric numerator, denominator and undefined state;
- summary rubric/sample/price-table versions where applicable; and
- test command and pass/fail status.

The monitoring API must reject an artifact whose schema, snapshot relationship
or hash does not validate.

## Interpretation limitation

CFPB complaints are not a representative statistical sample. None of these
metrics estimates consumer-population prevalence, and raw company counts do not
measure comparative company performance without a suitable exposure or
market-share denominator. The source limitation remains visible in every
volume or trend presentation.

