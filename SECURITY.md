# Security and data disclosure

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature for this repository when
available. Do not open a public issue containing an exploit, credential,
complaint narrative, prompt/completion, local path or complaint-level record.

This repository is a portfolio demonstration, not an emergency or regulatory
reporting channel. Do not submit consumer complaints or personal information to
the application or repository.

## Supported state

Security fixes target the current `main` branch. Public demonstration builds
are read-only and session-only: an on-screen approval or override is not durable
unless the deployment explicitly adds authenticated identity and a durable
audit store.

## Data boundary

The application uses public CFPB complaint data locally, but raw snapshots and
narrative-bearing databases are intentionally excluded from Git and public
deployments. Published narrative consent can later be withdrawn. The handling,
refresh and deletion procedure is defined in
[the lineage and data card](docs/lineage-data-card.md).

The path-based CI guard is defence in depth. It does not make an artifact safe
merely because the filename is allowed. Review aggregate/model artifacts for
rare cells, complaint-level content and retained text fragments before
publication.

## Secret handling

- Store keys only in `.env.local` for local use or a deployment platform's
  encrypted server-side secret store.
- Never prefix a server secret with `VITE_`; Vite variables are shipped to the
  browser.
- Rotate a credential immediately if it enters Git history, a log, issue or
  pull request. Removing the visible line is not sufficient.
- Keep LLM summaries disabled when no protected server-side key is configured.

## Production boundary

The included Docker Compose and static Vercel configurations demonstrate the
application. A production complaints workflow additionally requires
authentication, role-based authorisation, a transactional append-only audit
store, encryption, retention and withdrawal controls, backups, recovery tests,
network policy and incident response.

