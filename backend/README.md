# CFPB complaint operations backend

This package implements the reproducible data, modeling, and API layers for the
complaint-operations demonstration. It downloads public CFPB complaint records,
checks the snapshot, materializes DuckDB views, trains an abstaining product router,
detects product and issue volume signals, and serves reviewer-controlled workflows
through FastAPI.

The raw snapshot, narratives, DuckDB file, trained model, and generated metrics are
local artifacts. They are ignored by Git and are not packaged into the repository.

## Reproduce the pipeline

From the repository root:

```powershell
python -m pip install -e ".[backend,dev]"
cfpb-triage build-all --as-of 2026-08-21 --max-records 100000
cfpb-triage serve --port 8000
```

Individual stages are available as `snapshot`, `qa`, `warehouse`, `train`, and
`anomalies`. `bootstrap-demo` validates the clearly labeled synthetic offline demo
without downloading data or writing artifacts.

## Human review boundary

Routing probabilities and summaries are advisory. A route changes state only after
an identified reviewer sends an approve, override, or reject action. Generated
summaries remain pending until a separate review action; even an approved summary
cannot make a final complaint decision. Exact narrative quotes and their character
indices are validated before a draft is returned.

## Statistical boundary

CFPB complaints are not a representative statistical sample. Company complaint
counts are not comparative company-performance measures without appropriate
market-share denominators. The monthly-capped snapshot supports model development
and product/issue composition signals; exact API window totals are stored separately
for volume reporting so capped rows are never presented as population volume.

