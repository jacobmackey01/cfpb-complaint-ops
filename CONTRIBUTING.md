# Contributing

Contributions are welcome when they preserve the project's human-review and
data-publication boundaries.

## Before changing code

Read:

- [requirements and acceptance criteria](docs/requirements.md);
- [metric definitions](docs/metrics-and-evaluation.md);
- [lineage and data card](docs/lineage-data-card.md); and
- [deployment runbook](docs/deployment-runbook.md).

Model proposals and LLM drafts must remain separate from human decisions. A
new feature must fail safely when its model, artifact or external provider is
unavailable.

## Never commit complaint rows or secrets

Do not add:

- `.env.local` or another populated environment file;
- CFPB API pages or row-level CSV, JSONL or Parquet snapshots;
- DuckDB/database files containing complaint records or narratives;
- complaint narratives, prompts, completions or manual review sheets;
- complaint-level predictions or approval events; or
- text-model/vocabulary artifacts until a specific disclosure review confirms
  that they cannot expose narrative fragments.

Published narratives are consented and processed by the CFPB, but consent can
later be withdrawn. Keep narrative-bearing work under the ignored local data
paths. Use synthetic, non-narrative fixtures in tests.

Before opening a pull request, inspect Git's actual publication set:

```bash
python .github/scripts/check_repository_privacy.py
git status --short
git ls-files
```

The privacy guard detects common unsafe paths. It cannot determine whether an
otherwise allowed artifact is safe; the contributor and reviewer must inspect
the content.

## Development checks

Backend:

```bash
python -m pip install -e ./backend pytest ruff
python -m ruff check backend
python -m ruff format --check backend
python -m pytest backend/tests
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm run lint
pnpm test
pnpm run build
```

Full-stack container build:

```bash
cp .env.example .env.local
docker compose config
docker compose build
```

Do not use a live OpenAI key in automated tests. Test success, refusal,
timeout, invalid schema and quote mismatch through deterministic adapters.

## Evidence requirements

A change to data, metrics or modelling should include:

- the affected snapshot/artifact schema version;
- a test that covers the calculation or failure boundary;
- numerators and denominators for new metrics;
- chronological split and threshold-selection effects, when relevant;
- lineage/hash changes; and
- documentation of any changed interpretation or limitation.

Do not add a performance number to public prose unless it is traceable to a
frozen, hashed evaluation artifact in the same release.

## Pull requests

Keep the scope reviewable. Describe the user decision affected, tests run,
privacy/data impact, human-control impact and deployment implications. Do not
paste narratives, secrets or production logs into a pull request, issue or CI
output.

