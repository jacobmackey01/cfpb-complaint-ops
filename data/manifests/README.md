# Snapshot manifests

A successful extraction writes a sanitised manifest that links the canonical
request, downloaded pages, canonical rowset, QA report and code revision with
SHA-256 values. The manifest contains no complaint rows, narratives, prompts or
credentials.

Before committing a generated manifest, review it for local paths and unsafe
metadata. `snapshot_manifest.example.json` contains nulls intentionally and is
not evidence of a completed run.

