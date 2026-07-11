---
description: Bootstrap or update a Mnemex knowledge graph from an EXISTING code or documentation repository (a local folder or a git remote) — no live session needed. Walks the source, distills durable atoms (never transcribes), discovers a deduped entity catalog, wikifies links, and stages a labeled bulk batch that /mnemex:mnx-promote --bulk then merges. Two gates only (scope up front, bulk summary at the end); idempotent on re-run. Never writes the graph (staging only) and never mutates the source.
argument-hint: "<local-path|git-url> [--into <graph>] [--dry-run] [--resume <ingest-batch>]"
---

Use the **mnx-ingest** skill to bootstrap/update the graph from an existing repo.

Source + options: $ARGUMENTS

Run the orchestrator: **Preflight** (`mnx_binding.py status` or `--into` → resolve + echo the target
graph; sync if the clone is absent). **SOURCE** (`mnx_ingest.py acquire` — local in place, remote → shallow
clone to a read-only cache; never mutate the source). **PROBE + DELTA** (`mnx_ingest.py probe` for scope;
on re-ingest `mnx_ingest.py delta` against `.mnemex/ingest/<slug>.json` → extract only added/changed;
hold orphan candidates). **Gate #1** — STOP for the human with the scope counts + the source-tree→cluster
map (`--dry-run` stops here). **Pass 1** — per subtree, distil kind-aware atoms (code value-gate: public /
documented / config-only), run the bounded **glean** loop (`mnx_glean.py coverage`) over the unit
checklist, then entity-resolve (`mnx_er.py resolve`) → a deduped canonical entity set (CREATE/MERGE/COLLAPSE
+ a `possible` HITL band). **Pass 2** — wikify each atom against that catalog ∪ the phonebook (exact →
live `[[link]]`, fuzzy → `⚠ suggested`, unmatched → red-link) and **stage under the bulk label**
(`mnx_stage.py add --ingest-batch <id>` with source-anchored provenance). **DRAIN** by handing off to
`/mnemex:mnx-promote --bulk` (gate #2 = the bulk summary; it writes the manifest on persist). **Report**
created/merged/superseded/dropped-dup/held + orphan candidates.

Ingest **never writes the graph** (staging only; promote is the sole writer), **never mutates the source**,
**never reads secrets**, distills instead of transcribing (zero atoms from a file is valid), and is
idempotent on re-run (a deleted source file is an orphan candidate, never auto-death). Two gates only — no
per-atom review.
