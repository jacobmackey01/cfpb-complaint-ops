# Snapshot manifests

A successful extraction writes a sanitised manifest that links the canonical
request, downloaded pages, canonical rowset, QA report and code revision with
SHA-256 values. The manifest contains no complaint rows, narratives, prompts or
credentials.

The privacy-safe release [`snapshot_manifest.json`](snapshot_manifest.json)
contains the verified rowset/request/QA hashes and aggregate window counts; the
row-level snapshot remains ignored. The example manifest contains nulls
intentionally and is not evidence of a completed run.
