# Deployment runbook

This runbook covers a local full-stack deployment, publication of the source
repository and a read-only public interface demonstration. It does not turn the
portfolio demo into a production case-management system.

## 1. Release evidence

Before any public release:

1. Confirm the working tree contains no secret, raw complaint snapshot,
   narrative-bearing database, prompt/completion log or complaint-level review
   file.
2. Run the repository privacy guard and all tests from a clean environment.
3. Build or select a sanitised demo artifact. Record its snapshot ID, parent
   hash and artifact hash. Do not deploy local raw data.
4. Confirm the UI displays the CFPB representativeness limitation, the snapshot
   timestamp and the publication-lag warning.
5. Confirm all AI drafts remain pending human review and every low-confidence
   route abstains.
6. Record the full commit SHA that will be deployed. Push that exact SHA before
   creating the deployment.

Verification commands:

```bash
python .github/scripts/check_repository_privacy.py
python .github/scripts/check_deployment_configuration.py
python -m pip install -e ./backend pytest ruff
python -m ruff check backend
python -m ruff format --check backend
python -m pytest backend/tests

cd frontend
pnpm install --frozen-lockfile
pnpm run lint
pnpm test
pnpm run build
cd ..

git status --short
git rev-parse HEAD
```

Review Git's actual publication set, not only the filesystem:

```bash
git ls-files
```

The list must not include `.env.local`, `data/raw/`, `data/local/`,
`data/working/`, row-level CSV/JSONL/Parquet, DuckDB files or private artifacts.

## 2. Build a bounded local snapshot

Copy configuration and keep the populated file untracked:

```bash
cp .env.example .env.local
```

Install the package and inspect the installed CLI contract:

```bash
python -m pip install -e ./backend
cfpb-triage --help
```

For a real local snapshot, substitute the declared UTC date:

```bash
cfpb-triage snapshot --as-of YYYY-MM-DD --max-records 100000
cfpb-triage qa PATH_RETURNED_BY_SNAPSHOT --as-of YYYY-MM-DD
cfpb-triage train
cfpb-triage anomalies
```

The combined path is:

```bash
cfpb-triage build-all --as-of YYYY-MM-DD --max-records 100000
```

`build-all` must stop on a hard QA failure. Review the generated request,
manifest, QA report, chronological split and artifact hashes. Only sanitised
metadata and privacy-reviewed aggregates/evaluation/model artifacts can be
committed.

For deterministic offline UI/API verification without CFPB network access:

```bash
cfpb-triage bootstrap-demo
```

The bootstrap command must use the repository's non-narrative demonstration
fixture and must not be presented as real evaluation evidence.

## 3. Run the full stack locally

```bash
cp .env.example .env.local
docker compose build
docker compose run --rm backend cfpb-triage bootstrap-demo
docker compose up -d
docker compose ps
```

Verify:

```bash
curl --fail http://localhost:8080/api/health
curl --fail --head http://localhost:8080/
```

Then manually verify the case queue, operations dashboard and model-monitoring
page at `http://localhost:8080`. Exercise an abstention, an API failure, a
summary-disabled/refusal state and an ephemeral human review action. Check that
the browser console contains no errors and no narrative or secret is returned
by a public asset request.

Stop services without deleting local evidence:

```bash
docker compose down
```

Do not add `--volumes` unless local container data have been backed up or are
intentionally disposable.

## 4. Publish the GitHub repository

Publishing is an external write. Confirm the intended owner and repository name
before running the command. With an authenticated GitHub CLI:

```bash
gh auth status
git branch --show-current
git rev-parse HEAD
gh repo create <owner>/<repository> --public --source=. --remote=origin --push
```

If the repository already exists, add its verified remote and push the intended
branch instead of creating another repository. After pushing:

```bash
git ls-remote --heads origin main
gh run list --limit 5
```

The remote `main` SHA must match the recorded local SHA, and the CI workflow
must pass. Repository existence or a local commit is not evidence that the push
succeeded.

## 5. Deploy the read-only Vercel demonstration

Import the same public GitHub repository into two separate Vercel projects.
Both projects must deploy the same verified Git commit SHA.

### Backend project

Set Root Directory to `.`. The root `vercel.json`, root `app.py` and
`requirements.txt` serve FastAPI. Configure these server-side variables in
Preview and Production as appropriate:

```text
PUBLIC_DEMO_MODE=false
CFPB_LIVE_READ_MODE=true
CFPB_ALLOW_DEMO_FALLBACK=false
LLM_MODEL=gpt-5.6-luna
LLM_SUMMARY_ENABLED=false
OPENAI_API_KEY=<unset>
ALLOWED_ORIGINS=https://<verified-frontend-origin>
```

This is a bounded live CFPB read, not a synthetic demo: each request may hold
at most 25 current API records in process memory. It does not load a local raw
snapshot, DuckDB database or trained model artifact, and it does not persist
records, routes or summaries. Responses use `source_kind=cfpb_public`; every
live-read case abstains and remains subject to human review. Verify `/health`
and `/api/v1/health`, then record the backend URL before configuring the
frontend.

The serverless API exposes the human-review contract, but review state is
in-memory/ephemeral and can reset between requests, instances or deployments.
It is not an audit store or a durable case-management system.

### Frontend project

Create a second project from the same repository with Root Directory
`frontend`. Vercel uses `frontend/vercel.json`, `pnpm-lock.yaml` and the pinned
package manager. Set the build-time variable to the verified backend HTTPS
origin:

```text
VITE_API_BASE_URL=https://<verified-backend-origin>
```

The client appends the canonical `/api/v1` path. Never put an OpenAI key or
another server secret in a `VITE_*` variable; Vite publishes those values to
the browser. Add the final frontend origin to the backend `ALLOWED_ORIGINS`,
then redeploy the backend configuration if necessary.

This topology is deliberately limited:

- it uses a bounded live CFPB read of at most 25 records per process;
- it does not claim that the bounded read is a representative sample or exact
  population volume;
- review actions are ephemeral and visibly reset;
- it does not persist human approval or overrides;
- it does not run the CFPB download/training pipeline during a request or
  frontend build; and
- it never exposes `OPENAI_API_KEY` or any server secret to `VITE_*` variables.

Use Vercel Git integration to create Preview deployments for the pushed branch.
Promote each project only after the cross-origin flow passes. Record both
project IDs, deployment IDs, URLs and commit SHAs; do not hard-code an
unverified URL in the README.

Public verification must include:

- both backend health routes return `source_kind=cfpb_public` and the
  not-trained bounded-live state;
- the queue contains no more than 25 current API records and every live case
  is marked abstained/manual-review;
- the root route and all interface pages load after a hard refresh;
- both deployed commit SHAs match the pushed release;
- frontend requests reach backend `/api/v1` routes without a CORS error;
- the bounded live-read label, CFPB representativeness limitation and
  publication-lag warning are visible;
- company counts are not presented as comparative performance;
- approval/override state is labelled session-only;
- public LLM generation is disabled and no key appears in browser assets;
- browser network/console inspection shows no exposed secret or narrative
  asset; and
- mobile and desktop layouts pass a visual smoke test.

## 6. Deploy a containerised API demonstration

Use this only when the public demonstration needs a live FastAPI contract.
Build the backend image from the verified SHA:

```bash
docker build -f docker/backend.Dockerfile -t <registry>/cfpb-triage-api:<git-sha> .
docker run --rm -p 8000:8000 --env-file .env.local \
  <registry>/cfpb-triage-api:<git-sha>
```

Deploy the immutable image to the chosen container platform with
`PUBLIC_DEMO_MODE=true`, HTTPS, restricted CORS, a read-only sanitised artifact
and no raw narrative snapshot. Store secrets in the platform's encrypted secret
manager. Verify `GET /health`, representative read endpoints, rate limiting,
timeouts and refusal behaviour from the public origin.

Do not rely on an ephemeral container filesystem for approvals. If human review
must persist, the release changes scope to a durable operational deployment and
requires authenticated users, role-based authorisation, a transactional audit
store, migrations, backups, recovery tests, retention and withdrawal handling.

## 7. LLM enablement gate

Live summary generation is optional and disabled by default. Before enabling:

1. set `OPENAI_API_KEY` only in the server-side secret store;
2. verify the configured model and the dated price table;
3. run schema, exact-quote, refusal, timeout and provider-error tests;
4. freeze a manual factuality sample and rubric;
5. confirm prompts/completions are not written to general logs;
6. confirm the UI requires human approval and can operate when the provider is
   unavailable; and
7. configure cost/latency/failure alerts with explicit denominators.

The default cost table is dated 2026-08-21. It is an estimation input and must
be refreshed when provider pricing or the selected model changes.

## 8. Monitoring and rollback

Monitor API health/error categories, request latency, summary provider latency
and cost, routing coverage/abstention, accepted-route accuracy once labels are
available, monthly/product drift, anomaly alert volume and reviewer overrides.
Never log narrative bodies to achieve observability.

Rollback when health or acceptance gates fail:

1. disable LLM summaries independently if the fault is provider-specific;
2. route all predictions to manual review if model/artifact validation fails;
3. redeploy the previous immutable image or Vercel deployment;
4. verify health, UI and artifact hashes after rollback; and
5. preserve request IDs and categorical failure evidence for the incident
   review, without preserving narrative content in general logs.

For local Compose rollback, check out the recorded prior commit, rebuild and
re-run verification. Do not overwrite the current snapshot or model artifact;
use versioned paths and parent hashes.

## 9. Release record

Capture these values for each public release:

```text
Git repository:
https://github.com/jacobmackey01/cfpb-complaint-ops
Git commit SHA:
316ce2e9ba142dfa01153db1ba9eb6580a33db7e
CI run URL/status:
https://github.com/jacobmackey01/cfpb-complaint-ops/actions/runs/32543386111 (all checks passed)
Snapshot or demo artifact ID:
CFPB snapshot manifest `a7f68aeecaa6be66496fd6db8aecf0ad46dc9a4037656f33ec2ced28d6c9d57e`
Request/row/artifact SHA-256:
Snapshot `d393f6a83dc9c5248bf969ff6470c498b84397a46dfc93f7a229360d00db0864`
Model/evaluation version:
Product router evaluation on the 10,000-row snapshot; live demo router state is `not_trained` and abstains.
Price-table version:
`gpt-5.6-luna` pricing table in `cfpb_triage.services.summary`
Preview deployment ID/URL:
Production deployment ID/URL:
API `8DcMqCkhjJJEHZvSnCCUqUDBkmkQ` / https://cfpb-complaint-ops-api.vercel.app; web `9SM3BuqLLxqskwTQ5tZPb4qiDqCu` / https://cfpb-complaint-ops-web.vercel.app
Deployment verification timestamp (UTC):
2026-08-22T01:28Z
Verifier:
Automated HTTPS checks plus authenticated Vercel deployment status
Known limitations:
Snapshot is 10,000 rows rather than the 100,000 maximum; live reads are bounded to 25 records, complaint data are not representative, and company counts are not comparative performance. The private frozen summary review is complete (`n=50`; mean factuality 4.86, all-claims-supported rate 0.90, exact-quote rate 1.0) for sample manifest `c9e13f5d11a98a3e63e75f423a8fca512bca59d93f67b300d988ce27ed2c4a4c`. The public Vercel live-read demo intentionally does not persist private worksheets or narratives, so its runtime summary metrics remain unavailable (`n=0`).
Rollback target:
```

Leave fields empty until verified. A saved build, preview or local health check
is not evidence that production is live.
