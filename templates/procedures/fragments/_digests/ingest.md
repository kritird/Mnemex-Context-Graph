Procedure: `ingest_acquire` the repo (read-only) → `ingest_probe` for the extraction
units + a source-tree→cluster map (gate #1: confirm scope) → distil durable atoms with
`capture_add(ingest_batch=...)`, never transcribe (zero atoms from a file is fine) →
`glean_coverage` until complete/cap → `er_resolve` to dedupe and MERGE into existing pages
(one entity → one node) → drain with `promote_begin`/`promote_apply` in bulk. Two gates
only (scope, bulk summary); deleted-file orphans surface for the human, never auto-tombstoned.