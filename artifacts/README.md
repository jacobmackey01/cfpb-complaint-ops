# Artifacts

`artifacts/public/` is the only repository location intended for promoted,
privacy-reviewed analytical artifacts. Runtime, temporary and private artifacts
are ignored.

An allowed filename or directory is not evidence that its contents are safe.
Review every proposed artifact against
[the lineage and data card](../docs/lineage-data-card.md) before adding it to
Git.

The application must not silently fall back to a stale artifact. Serving code
validates the artifact schema, snapshot relationship and SHA-256 lineage, then
returns an explicit unavailable/manual-review state on failure.

