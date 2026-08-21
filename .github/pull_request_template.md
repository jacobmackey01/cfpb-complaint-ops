## Decision and scope

Describe the user decision this change supports and the behaviour changed.

## Verification

- [ ] Backend lint, format and tests pass.
- [ ] Frontend lint, tests and build pass.
- [ ] Repository privacy guard passes.
- [ ] Docker/serving path was checked when runtime configuration changed.
- [ ] New metrics include definitions, numerators, denominators and lineage.
- [ ] Public performance claims trace to a frozen, hashed evaluation artifact.

Commands/results:

```text
Add concise commands and pass/fail results; do not paste complaint data.
```

## Privacy and data publication

- [ ] No `.env.local`, secret or populated environment file is tracked.
- [ ] No raw/row-level complaint data, narrative-bearing database, prompt,
      completion, manual review row or complaint-level prediction is included.
- [ ] Any aggregate/model artifact was reviewed for rare cells and retained
      narrative fragments.
- [ ] Consent-withdrawal and publication-lag behaviour remains correct.

## Human control and failure behaviour

- [ ] Model routes and LLM drafts remain proposals pending human review.
- [ ] Abstention/refusal/failure states fail safely and are measurable.
- [ ] Public-demo approvals remain visibly session-only unless this change also
      provides authenticated durable storage and audit evidence.

## Deployment

State whether deployment is required, the exact commit SHA and any rollback or
configuration change. Leave live URLs blank until they have been verified.

