# Snapshot requests

Commit only sanitised request JSON. A request records the source endpoint,
explicit `as_of` date, maximum record count, ordering, fields and client
version. It never contains credentials or response rows.

`snapshot_request.example.json` is a schema illustration, not a completed
request. The pipeline writes the authoritative request for each extraction.

