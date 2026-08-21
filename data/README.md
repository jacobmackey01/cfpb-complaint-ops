# Data directory

This repository stores only reproducibility metadata and privacy-reviewed,
non-narrative artifacts. It does not distribute the CFPB complaint snapshot.

## Tracked

```text
data/requests/      Sanitised request specifications
data/manifests/     Sanitised manifests, hashes and QA summaries
```

The `.example.json` files document the contract; they are not evidence that a
snapshot has been downloaded or evaluated.

## Local-only

The pipeline creates ignored directories such as `data/raw/`, `data/working/`
and `data/local/`. They may contain consented narratives, row-level exports or
DuckDB files and must not be committed. Do not remove the relevant `.gitignore`
rules to make a deployment easier.

Run a bounded extraction with:

```bash
cfpb-triage snapshot --as-of YYYY-MM-DD --max-records 100000
```

See [the lineage and data card](../docs/lineage-data-card.md) for QA,
reproducibility, consent-withdrawal and publication rules.

