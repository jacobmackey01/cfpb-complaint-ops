# Public artifact contract

This directory can hold versioned outputs that are both reproducibility evidence
and safe to publish. Examples include:

- aggregate data-quality counts and missingness rates;
- sufficiently supported product/issue/time aggregates;
- chronological split metadata and aggregate evaluation metrics;
- reliability-bin and aggregate confusion tables;
- model configuration and hashes; and
- a model binary only after a specific text-disclosure review.

The aggregate [summary factuality review metrics](summary_factuality_review_metrics.json)
record the completed private human review of the frozen sample. They contain no
narratives, generated summaries, complaint IDs or reviewer worksheet fields.

Each promoted artifact should include or accompany:

- schema version and creation timestamp;
- full Git commit SHA;
- snapshot ID and parent/request/row hashes;
- artifact SHA-256;
- relevant filters, split boundaries and record counts;
- metric numerators and denominators;
- configuration/model/price-table versions; and
- privacy reviewer/status.

Do not publish:

- complaint rows or narratives;
- complaint-level predictions or review decisions;
- prompts, completions or manual factuality sheets with excerpts;
- rare aggregates that make a complaint identifiable; or
- a vectoriser, vocabulary or model retaining narrative fragments unless it has
  passed an explicit disclosure review.

An empty directory means no artifact has yet been promoted. It must not be
replaced with invented performance figures or placeholder production evidence.

