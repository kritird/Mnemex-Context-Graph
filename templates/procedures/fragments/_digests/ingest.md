Procedure: `ingest_acquire` the repo (read-only) → `ingest_probe` for the extraction
units + a source-tree→cluster map (gate #1: confirm scope) → distil durable atoms with
`capture_add(ingest_batch=...)`, never transcribe (zero atoms from a file is fine) →
`glean_coverage` until complete/cap → `er_resolve` to dedupe and MERGE into existing pages
(one entity → one node) → drain with `promote_begin`/`promote_apply` in bulk. For every
NEW cluster created, write its one-line description into the cluster `index.md` header
(`> …` line) — read routing decides on that line, and regeneration preserves it; never
leave the scaffold placeholder. Two gates
only (scope, bulk summary); deleted-file orphans surface for the human, never auto-tombstoned.