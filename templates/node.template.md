---
id: REPLACE-with-stable-slug          # [a-z0-9-]+, assigned at creation, NEVER changes
type: domain                          # domain | pattern
title: Human-readable title (may change freely)
summary: One line that lands in the index verbatim — the match + routing surface.
aliases: [other name, abbreviation, synonym]
domain: [sub-domain]                  # may be a LIST (a node can belong to >1 sub-index)
status: active                        # active | dead   (retired-why is a field: superseded-by, died)
confidence: high                      # high | medium | low
volatility: default                   # default | timeless | volatile | <int days> — freshness horizon (Freshness & Revalidation)
trigger: null                         # REQUIRED (non-null) for type: pattern; null for domain
mentions:                             # GENERATED from body [[wiki-links]] at promote (Link Reconciliation). Author links
  - { name: other-node-id, resolved_id: other-node-id, type: null }  #   inline in the BODY, not here.
  - { name: page-not-created-yet, resolved_id: null, type: null }    #   resolved_id null = a red-link
edges:                                # GENERATED MIRROR of resolved mentions (Link Reconciliation §8) — not hand-authored
  - { to: other-node-id, type: null }               # untyped by default; type is optional
references: []                        # SOFT cross-TEAM pointers only (no integrity guarantee)
provenance:
  artifact: name-of-build-artifact
  reviews: []                         # human review-point ids that fed this node
  session: 1970-01-01T00:00:00Z
created: 1970-01-01T00:00:00Z
updated: 1970-01-01T00:00:00Z         # meaning-change time (NOT usage)
verified: 1970-01-01T00:00:00Z       # last confirmed-still-true time (NOT usage, NOT meaning-change)
---

## Summary
One paragraph; read first on a body expansion.

## What
(domain nodes) The knowledge itself. Link to other pages inline by NAME with wiki-links —
e.g. "…settles against [[other-node-id]] before posting." Promote resolves them (Link Reconciliation).

## How / Notes
(pattern nodes) The prescriptive procedure / rule and its rationale.

## Provenance
Why this node exists; trace to the artifact and the specific human review points.
