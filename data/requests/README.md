# Snapshot requests

Commit only sanitised request JSON. A request records the source endpoint,
explicit `as_of` date, maximum record count, ordering, fields and client
version. It never contains credentials or response rows.

The privacy-safe release [`snapshot_request.json`](snapshot_request.json) records
the verified local run's canonical request plan and SHA-256 without complaint
rows. The example file is a contract illustration only.
