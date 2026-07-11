# Build Plan — Corpus Ingestion + Gleanings

**Status:** proposed · **Owner:** Kriti · **Created:** 2026-07-11
**Scope:** two features that share one backbone —
1. **Corpus Ingestion (`mnx-ingest`)** — bootstrap/update a graph from an existing code or doc repo
   (local or remote), distilling durable atoms into the *existing* staging → promote → mesh pipeline.
   Spec: [`docs/corpus-ingestion.md`](docs/corpus-ingestion.md).
2. **Gleanings** — a bounded, source-agnostic "what did I miss?" recall pass that lifts extraction
   completeness for **both** episodic capture and ingest.

This is the authoritative, phased, commit-level plan. Read the ingestion spec plus
[`docs/staging-and-promotion.md`](docs/staging-and-promotion.md),
[`docs/link-reconciliation.md`](docs/link-reconciliation.md),
[`docs/multi-graph-and-team-routing.md`](docs/multi-graph-and-team-routing.md), and
[`docs/script-contracts.md`](docs/script-contracts.md) first — this plan assumes them.

---

## 0. The insight that shapes everything

**Ingest is a *source adapter*, not a new subsystem.** A live session is one producer of staged atoms; a
corpus is a second. Ingest adds only a *front-end* (walk → distill → wikify → stage) plus a scale-adapted
promote mode and a delta manifest. Everything downstream — reconcile, MERGE/SUPERSEDE, contradiction HITL,
the wiki mesh (Step 2b), consolidate, doctor, push — is **reused unchanged**. `mnx-promote` stays the only
writer to the graph.

**The two features port differently, and that split is deliberate** (mirrors the two-layer split the rest
of the system uses):

| Concern | Where it lives | Nature |
|---|---|---|
| **Deterministic mechanics** | new/extended `mnx_*.py` (stdlib + PyYAML) | walk, classify, chunk, hash, diff, manifest, ER blocking/clustering, bulk-budget — pure CLI subcommands, `STATUS=OK\|FAIL` + JSON |
| **LLM judgment** | skill prose + sub-agents | distill "is this a durable atom?", wikify (which `[[name]]`), the glean re-ask, disposition — cannot move into Python |

**Why GraphRAG machinery is ingest-only.** Its heavy parts (entity-resolution clustering, Leiden
communities, the two-pass catalog) solve *cold-input + scale + redundancy* — which episodic capture does
not have. The **one** transferable technique is *gleanings*, so we build it once as a shared recall pass and
leave the rest ingest-scoped. (Resolved-decisions in the spec.)

---

## 1. Design points every phase must honor

These are the load-bearing invariants; each acceptance check below traces to one.

- **DP1 — Single writer.** Ingest never writes the graph; it only stages. `mnx-promote` is the sole writer.
- **DP2 — Distill, never transcribe.** No file body copied wholesale into a node; zero atoms from a file is
  valid. The graph is distilled memory, not a corpus mirror / RAG index.
- **DP3 — Read-only source.** Clone a remote to a read-only cache or read a local path in place; never
  mutate the source corpus. Never read secrets (skip-list).
- **DP4 — Idempotent re-ingest.** manifest delta → content-hash idempotency → ER/reconcile dedup. A re-run
  never blindly re-creates; a deleted source file never auto-tombstones its nodes (surfaced for decision).
- **DP5 — One entity → one node.** ER collapses intra-batch duplicates *before* staging and merges into the
  existing page. Redundancy becomes provenance + aliases, never duplicate nodes.
- **DP6 — Exact resolves, fuzzy proposes.** A discovered link that is an exact catalog/phonebook match goes
  live deterministically; a fuzzy/semantic association is `⚠ suggested` (HITL), never auto-written. A wrong
  link is a false edge.
- **DP7 — No structure from global clustering.** Community detection may *propose* a folder map at gate #1
  only; path-based routing is the default; it never runs at read time. (overview.md goal 6.)
- **DP8 — Bulk isolation.** Ingest atoms are label-partitioned from hand-captured atoms; an import never
  entangles a user's episodic captures.
- **DP9 — Two gates, no per-atom review.** Gate #1 = scope + source-tree→cluster map (up front); gate #2 =
  bulk promote summary, stopping only on contradictions + new-cluster creation. Auto-accept plain CREATE/MERGE.
- **DP10 — Gleaning is bounded and cheap.** Max N passes, stop on a no-new-atoms pass; re-staging identical
  content stays an idempotent no-op; it never mutates the graph.
- **DP11 — Everything reused stays reused.** No fork of `mnx_node` / `mnx_mesh` / `mnx_index` / `mnx_doctor`
  / consolidate; extend, don't duplicate.

---

## 2. New & changed surfaces (the full inventory of updates)

| Surface | Change | Feature |
|---|---|---|
| `scripts/mnx_ingest.py` | **new** — walk/clone-to-cache · classify · chunk · hash · delta diff · manifest r/w · `probe` | Ingest |
| `scripts/mnx_glean.py` | **new** — deterministic coverage helper: given staged ledger + candidate units, return the not-yet-covered set + pass bookkeeping | Gleanings |
| `scripts/mnx_stage.py` | **extend** — ingest-batch *label*; bulk budget profile (large cap, drained continuously); label-partitioned `list`/`overlay`/`clear` | Ingest |
| `scripts/mnx_simindex.py` | **extend** — expose LSH **candidate-pair generation** (ER blocker), not only point queries | Ingest |
| `scripts/mnx_er.py` | **new** — ER stage: block (via simindex/phonebook) → score → cluster → dispose; pure proposer | Ingest |
| `skills/mnx-ingest/SKILL.md` + `commands/mnx-ingest.md` | **new** — orchestrator (preflight → probe → scope gate → two-pass extract/wikify+glean → bulk drain → manifest → report) | Ingest |
| `skills/mnx-promote/SKILL.md` | **extend** — `--bulk` mode (forked reconcile, summarized plan, incremental consolidate) | Ingest |
| `skills/mnx-capture/SKILL.md` | **extend** — add the bounded glean loop to Phase 1 (delta-aware) | Gleanings |
| `docs/corpus-ingestion.md` | **update** — done (spec) | Ingest |
| `docs/script-contracts.md` | **extend** — contracts for `mnx_ingest`, `mnx_er`, `mnx_glean`, `mnx_stage` bulk, `mnx_simindex` pairs | both |
| `docs/data-model-and-schemas.md` | **extend** — corpus-provenance schema; ingest manifest under `.mnemex/ingest/`; staged-atom `ingest_batch` label | Ingest |
| `docs/staging-and-promotion.md` | **extend** — bulk budget profile; the `--bulk` promote variant | Ingest |
| `README.md` / `FEATURES.md` | **update** — new verb + the "bootstrap from an existing repo" story; gleaning note | both |
| `LIMITATIONS.md` | **update** — cost ceiling, code-extraction noise bounds, deletion-not-death | Ingest |

All scripts follow the shipped convention: hand-rolled `argv` parsing, module-level functions returning
plain dicts, output via `mnx_common.emit(payload)` → JSON line + `STATUS=OK|FAIL`, stdlib + PyYAML only.

---

## 2.5 Concrete interfaces, schemas & config

### 2.5.1 `mnx_glean.py`

```
# guardrail mode (episodic) — pure bookkeeping, no unit set
python3 scripts/mnx_glean.py step --before <n> --after <n> --pass <k> [--max <n=2>]
  → { "pass": k, "added": after-before, "stop": bool, "reason": "no-progress|cap|continue" }

# checklist mode (ingest) — coverage over an enumerated unit set
python3 scripts/mnx_glean.py coverage --units units.json --staged ledger.json --pass <k> [--max <n=2>]
  → { "total": m, "covered": c, "uncovered": ["unit-id", …], "stop": bool, "reason": … }
```
Functions: `step(before,after,pass_no,max_passes)->dict`, `coverage(units,staged,pass_no,max_passes)->dict`.
A unit is *covered* when ≥1 staged atom carries its `anchor` in provenance. Judgment ("what did I miss")
never enters this script.

### 2.5.2 `mnx_ingest.py`

```
python3 scripts/mnx_ingest.py acquire --source <path|url> [--cache <dir>]
  → { "kind":"local|remote", "root":"<abs>", "commit":"<sha|null>", "cached": bool }
python3 scripts/mnx_ingest.py probe --root <dir> [--include g1;g2] [--exclude g] [--max-bytes 1048576]
  → { "units":[{"id","path","kind","anchor","hash","bytes"}…],
      "counts":{"doc":n,"interface":n,"code-doc":n,"config":n,"skip":n},
      "est_atoms": n, "bytes_total": n, "skipped_secrets": n }
python3 scripts/mnx_ingest.py delta --root <dir> --manifest <graph>/.mnemex/ingest/<slug>.json
  → { "added":[unit…], "changed":[unit…], "unchanged": n, "orphans":[{"path","node_ids":[…]}] }
python3 scripts/mnx_ingest.py manifest-write --graph <root> --source-slug <s> --json  (stdin: files map)
  → { "path":"<graph>/.mnemex/ingest/<slug>.json", "files": n }
```
- **`source-slug`** reuses `mnx_binding.graph_slug`-style hashing over the source URL / abs path (same
  helper family, so it matches the staging slug scheme).
- **Classification** (deterministic, config-overridable): by extension + path.
  `doc` = `.md .rst .adoc .txt` under docs/wikis; `interface` = `.proto`, `.graphql`, `*.openapi.*`,
  exported symbols in `.py .ts .go .java`; `code-doc` = docstrings/module headers/`README*`;
  `config` = `.env.example`, `*.tf`, flag/schema files with comments; `skip` = the skip-list below.
- **Skip-list (never read):** `**/node_modules/** dist/ build/ vendor/ .git/ *.lock *.min.* *.map`
  binaries, and a **secret guard** — any file matching `.env`, `*.pem`, `*_rsa`, `credentials*`, `*.key`
  is counted in `skipped_secrets` and its bytes are **never** opened.

**Ingest manifest** — `<graph-root>/.mnemex/ingest/<source-slug>.json` (committed with the graph, like
`.mnemex/highwater/`):
```json
{ "source_repo": "github.com/acme/payments-service",
  "last_commit": "9f3c1a…", "ingested_at": "2026-07-11T…Z",
  "files": { "settlement/reconcile.md": { "hash": "sha1…", "nodes": ["settle-cutoff","recon-order"] } } }
```

**Corpus provenance** — carried on each ingest-staged atom (new fields threaded through `mnx_stage add`):
```yaml
provenance:
  source_repo: github.com/acme/payments-service
  commit_sha: 9f3c1a…
  source_path: settlement/reconcile.md
  anchor: "## Cut-off handling"        # heading | Lx-Ly | sym:Name — also the glean coverage key
  ingest_batch: ing-2026-07-11-a1b2
  kind: doc | interface | code-doc | config
```

### 2.5.3 `mnx_stage.py` extensions

- `add` accepts the corpus-provenance fields above **plus** a top-level label: `--ingest-batch <id>`
  (sets `bulk: true` on the atom). Flags mirror the existing `_arg` style; `--json` stdin already carries
  arbitrary provenance.
- **Bulk budget profile** — when an atom carries `ingest_batch`, budget checks use the bulk caps and the
  per-session soft/hard nag is **suppressed** for labeled atoms (DP8):
  `status` → `{ "budget": {...}, "by_label": { "<ingest-batch>": n, "_session": n } }`.
- Label-scoped ops: `list --ingest-batch <id>`, `overlay --ingest-batch <id>`, `clear --ingest-batch <id>`
  (drains only that batch — never the session atoms).

### 2.5.4 `mnx_simindex.py` extension (the ER blocker)

`pairs` today is **cross-cluster only** and reads on-disk nodes. Extend it to serve as the ER blocker:
```
python3 scripts/mnx_simindex.py pairs --scope <graph> [--with staged.json] [--intra] [--threshold 0.5]
  → { "candidate_pairs":[{"a","b","similarity","a_cluster","b_cluster"}…] }
```
`--with` injects staged atoms (`{id, summary, aliases}`, cluster=null) into the MinHash index so blocking
covers **staged↔graph** and **staged↔staged** pairs; `--intra` drops the same-cluster skip so intra-batch
duplicates surface (needed for DP5). The existing cross-cluster S2 behavior is the default (no flags).

### 2.5.5 `mnx_er.py` (new — pure proposer, writes nothing)

```
python3 scripts/mnx_er.py resolve --graph <root> --atoms staged.json [--team t]
        [--match 0.85] [--possible 0.60]
  → { "clusters":[ { "canonical":"iso8583-field124",
                     "members":["stg-d3d3…","stg-9af1…"], "aliases":["field 124","DE124"],
                     "disposition":"CREATE|MERGE|COLLAPSE", "target_id":"<graph-id|null>",
                     "confidence":0.93 } … ],
      "possible":[ {"a","b","score"} … ],      # the HITL band → ⚠ suggested at gate #2
      "counts":{"create":n,"merge":n,"collapse":n,"possible":n} }
```
- **Blocking:** `mnx_simindex.pairs --with atoms --intra` (2.5.4).
- **Score (per blocked pair):** weighted sum, defaults — alias/name token-Jaccard `0.4` · summary MinHash
  sim `0.3` · shared `domain` `0.2` · shared resolved link `0.1`. `≥ match` → same entity; `[possible,
  match)` → HITL band; `< possible` → distinct.
- **Cluster:** union-find over `≥ match` pairs. Pick `canonical` = the longest existing graph-id in the
  cluster, else the highest-confidence staged summary's slug; **union** all aliases.
- **Dispose:** cluster with a graph member → `MERGE` (target = that id); all-staged cluster → `CREATE`;
  multiple staged with no graph member → `COLLAPSE` to one CREATE. The LLM judge (skill) is invoked
  **only** on the `possible` band — never on match/distinct.

### 2.5.6 Config keys added

Graph `mnemex.config.md` (behavior owned by the graph):
```yaml
# --- Ingestion ---
ingest_bulk_soft_atoms: 500
ingest_bulk_hard_atoms: 5000
ingest_max_atoms_per_run: 2000     # cost ceiling; excess resumes next run
er_match_threshold: 0.85
er_possible_threshold: 0.60
code_extract: gated                # gated | deep | off  (per-subtree overridable in the gate-#1 map)
```
User `~/.claude/mnemex/config.md` and ingest config (glean is shared):
```yaml
max_glean_passes: 2
```

---

## 3. Phases (commit-level; each leaves `main` green)

### Feature B first — Gleanings (shared, small, unblocks ingest Pass 1)

Build the shared recall pass before ingest so ingest's Pass-1 GLEAN step consumes a tested primitive.

**Phase G0 — Gleaning primitive**

`mnx_glean` runs in **two modes**, matching the asymmetry between the two sources (episodic keeps capture
cheap; ingest can afford a real coverage map):

| Mode | Consumer | Input | Output |
|---|---|---|---|
| **guardrail** (light) | episodic capture | `{staged_count_before, staged_count_after, pass_no}` | `stop` when a pass added nothing new **or** `pass_no ≥ max_glean_passes` |
| **checklist** (rich) | ingest | `{candidate_units, staged_ledger, pass_no}` | the enumerated units that produced **zero atoms** + the same `stop` signal |

- **G0a — `mnx_glean.py`.** Pure/deterministic, no LLM, no graph. Both modes above. Config
  `max_glean_passes` (default **2**) in user config (episodic) / ingest config (corpus). The *judgment*
  ("what did I miss") always stays in the skill/LLM — `mnx_glean` only bounds and bookkeeps the loop.
- **G0b — Contract + unit tests.** `docs/script-contracts.md` entry; `tests/test_glean.py`: guardrail
  stops on no-progress and at the cap; checklist flags zero-atom units; idempotent re-run.
  Acceptance: `mnx_glean.py step --before 5 --after 5 --pass 1` → `{"stop":true,"reason":"no-progress"}`;
  `--before 5 --after 7 --pass 2 --max 2` → `{"stop":true,"reason":"cap"}`.

**Phase G1 — Wire gleaning into episodic capture (LIGHTWEIGHT — decided)**
- **G1a — Capture SKILL glean loop (guardrail mode).** Extend
  [`skills/mnx-capture/SKILL.md`](skills/mnx-capture/SKILL.md) Phase 1: after Pass 0 (today's extraction),
  run **one** bounded "what durable fact — *especially a review-point pattern* — did I not stage yet?"
  re-scan of the transcript, guided by the Phase-0b delta ledger; stop on no-progress or the cap. **No
  self-enumerated coverage checklist for episodic** (that stays ingest-only) — this keeps capture
  cheap/fast (design goal) while recovering the under-captured "how". New candidates still pass the
  `now/later/not-needed` scoring gate; re-staging identical content stays an idempotent no-op (DP10).
- **G1b — Verify no regression.** Capture stays cheap/local/no-lock/graph-read-free; the existing
  agent-driven capture e2e must not increase graph writes (still zero) and must not double-stage; added
  latency is one bounded pass, not a per-topic walk.

Acceptance (B): `test_glean.py` green; an agent-driven capture scenario stages ≥ the atoms it did before
(with a measurable lift in *pattern* atoms), no duplicates, within the pass cap; capture stays graph-read-free.

---

### Feature A — Corpus Ingestion

**Phase A0 — Walk, classify, probe (no staging, no LLM)**
- **A0a — `mnx_ingest.py` source acquisition.** Local path used in place; remote → shallow clone into a
  read-only cache dir (reuse `mnx_binding` auth/probe patterns). Never touches the graph or the source
  working tree. (DP3)
- **A0b — Enumerate + classify.** Walk with include/exclude globs, per-file size cap, skip-list
  (lockfiles/vendored/generated/binaries/secrets). Classify each file `doc | interface | code-doc | config
  | skip` per spec §2. Emit a candidate-unit list (path, kind, anchor, hash). (DP2, DP3)
- **A0c — Chunk.** Split large files along structure — headings (md/rst) / exported symbols (code) — into
  units that stay a complete idea. Never truncate.
- **A0d — `probe` subcommand.** Return scope estimate: file counts by kind, unit count, est. atoms/cost,
  what is skipped. Powers gate #1 and `--dry-run`.
- **A0e — Contract + tests.** `docs/script-contracts.md`; `tests/test_ingest_walk.py` over the §7 fixture
  corpus: classification correctness, skip-list, glob honor, chunk boundaries, `probe` counts, secret file
  never read. Acceptance: `mnx_ingest.py probe --root tests/fixtures/corpus_sample` →
  `counts.doc==2 ∧ counts.interface==2 ∧ skipped_secrets==1` and no unit anchored in `.env`.

**Phase A1 — Ingest manifest & delta**
- **A1a — Manifest r/w.** `<graph-root>/.mnemex/ingest/<source-slug>.json` — `source_path@commit →
  {hash, node_ids}` (spec §3). Committed with the graph (mirrors `.mnemex/highwater/`).
- **A1b — Delta diff.** On re-ingest, diff walked hashes vs manifest → extract only added/changed files;
  surface deleted files' node_ids as **orphan candidates** (never auto-tombstone). (DP4)
- **A1c — Tests.** `tests/test_ingest_manifest.py`: first run records all; second run over unchanged tree →
  empty delta; a changed file → only that unit; a deleted file → orphan-candidate list.

**Phase A2 — Entity resolution stage**
- **A2a — Extend `mnx_simindex.pairs` into the ER blocker.** Add `--with <staged.json>` (inject staged
  atoms into the index) and `--intra` (drop the same-cluster skip), per 2.5.4. The default no-flag behavior
  (cross-cluster S2 worklist) is unchanged — verify the existing simindex test still passes. (DP5)
- **A2b — `mnx_er.py` proposer** per 2.5.5: block (A2a) → score (2.5.5 weights) → union-find cluster →
  dispose CREATE/MERGE/COLLAPSE + `possible` band. Pure; writes nothing. Runs per delta batch over
  `{new atoms ∪ existing graph pages}`. (DP5, DP6)
- **A2c — Tests.** `tests/test_er.py` over the fixture corpus (§7): `duplicate_note.md`'s fact collapses
  into `settlement.md`'s node (one cluster, unioned aliases); two genuinely distinct settlement facts stay
  two clusters (**no false-merge** — the R3 bug-hunt case); a mid-score pair lands in `possible`, not
  auto-merged.
  Acceptance: `python3 scripts/mnx_er.py resolve --graph <fx> --atoms <fx-atoms.json>` yields
  `counts.collapse == 1`, `counts.create == expected`, and the distinct pair absent from any cluster.

**Phase A3 — Bulk staging**
- **A3a — `mnx_stage` bulk profile + label.** Add `--ingest-batch <id>` label; a bulk budget profile
  (large cap, meant to be drained continuously) that suppresses the per-session soft/hard nag for labeled
  atoms; `list`/`overlay`/`clear` filter by label so ingest and hand-captures stay partitioned. (DP8)
- **A3b — Tests.** `tests/test_stage_bulk.py`: labeled atoms don't trip the episodic hard cap; a hand-capture
  in the same graph stays visible and untouched; `clear --ingest-batch` drains only the batch.

**Phase A4 — The ingest skill (extract → wikify → stage), two-pass + glean**
- **A4a — `mnx-ingest` SKILL + command scaffolding.** Preflight (binding / `--into`), source probe, emit
  the **scope + source-tree→cluster map** for **gate #1**. `--dry-run` stops here. (DP9)
- **A4b — Pass 1 extraction + glean.** Per subtree: distil candidate atoms + entities (kind-aware §2,
  code value-gate), run the **glean** loop in **checklist mode** (Feature B — re-examine zero-atom units),
  assemble the in-batch entity catalog, run `mnx_er` → deduped entity set. Stamp corpus provenance (§3).
  (DP2, DP5, DP10)
- **A4c — Pass 2 wikify.** Rewrite atom bodies with `[[canonical-name]]` links against catalog ∪ phonebook;
  unmatched mentions → red-links; confident links live, fuzzy → `⚠ suggested`. Stage under the bulk label.
  (DP6)
- **A4d — Tests.** `tests/e2e/agent_ingest_scenario.py` (bug-hunt style): a fixture doc+code repo →
  inspect staged atoms for distillation quality, wikilink correctness, no transcription, secrets excluded,
  entity dedup. Assert **no graph write** happened during ingest (DP1).

**Phase A5 — Bulk promote**
- **A5a — `mnx-promote --bulk`.** Forked reconcile per cluster (contract already allows forking);
  summarized plan (per-cluster counts) surfacing only contradictions + new clusters (gate #2);
  incremental consolidate + checkpoint per drained batch over a frozen view. Reuses `mnx_node`, Step 2b
  mesh, doctor, persist unchanged. (DP9, DP11)
- **A5b — Manifest write on confirmed persist.** After push/commit, write `source_path@commit → node_ids`
  (A1). Only on confirmed persist (mirrors `clear_merged`). (DP4)
- **A5c — Tests.** `tests/e2e/agent_bulk_promote_scenario.py`: drain a staged ingest batch → assert nodes
  created, mesh links resolved (red-links healed within the run via backfill), doctor E==0, manifest
  written; re-run ingest → delta empty → promote no-ops. Concurrency: bulk promote honors the team lock.
  Acceptance (idempotency proof, the DP4 gate): after a full ingest+bulk-promote of the fixture corpus,
  a second `mnx-ingest` of the *unchanged* corpus reports `delta.added==0 ∧ delta.changed==0`, stages 0
  atoms, and `mnx_doctor check` stays `E==0` with the node count unchanged.

**Phase A6 — Documentation sweep (complete, gating — DoD blocker)**

> **Docs-with-code rule.** Each phase above updates the doc(s) its change touches **in the same commit**
> (a contract lands with its `script-contracts.md` entry; a schema lands with `data-model-and-schemas.md`).
> A6 is the **final completeness sweep + the user-facing narrative**, not the only doc work — but nothing
> ships as "done" until **every** row in the table below is checked and the cross-link/glossary/consistency
> checks pass. This is a hard gate (see Definition of Done).

**A6a — Update every affected document.** The full inventory — none may be skipped:

| Doc | Update | Landed in |
|---|---|---|
| `docs/corpus-ingestion.md` | the spec (done) + wire into the reading order | done / A6b |
| `docs/script-contracts.md` | `mnx_ingest`, `mnx_er`, `mnx_glean` full contracts; `mnx_stage` bulk/label; `mnx_simindex.pairs` `--with`/`--intra` | A0e, A1c, A2a, A2b, G0b |
| `docs/data-model-and-schemas.md` | corpus-provenance block; ingest manifest under `.mnemex/ingest/`; staged-atom `ingest_batch`/`bulk` fields | A1a, A3a |
| `docs/staging-and-promotion.md` | bulk budget profile; the `--bulk` promote variant; label partition | A3a, A5a |
| `docs/link-reconciliation.md` | the "agent authors, human adjudicates uncertain-only" clarification (§2 wording); ingest as a second author of `[[links]]`; in-batch catalog consumer | A4c |
| `docs/multi-graph-and-team-routing.md` | the source-tree→cluster map as the bulk analog of per-atom `domain:`; gate #1 | A4a |
| `docs/configuration.md` | new keys + defaults: `ingest_bulk_soft/hard_atoms`, `ingest_max_atoms_per_run`, `er_match/possible_threshold`, `code_extract`, `max_glean_passes` | A3a, A2b, G0a |
| `docs/invariants-and-failure-modes.md` | ingest invariants DP1–DP8 (single-writer, distill-not-transcribe, read-only source, idempotent re-ingest, one-entity-one-node, deletion≠death); orphan-candidate flow | A5b |
| `docs/freshness-and-revalidation.md` | corpus atoms get `verified=now` on write; re-verification by re-reading `source_path@commit` | A5a |
| `docs/maintenance-pass-algorithm.md` | incremental (per-batch, frozen-view) consolidate under `--bulk` | A5a |
| `docs/binding-and-graph-sync.md` | source acquisition (shallow clone → read-only cache); reuse of `probe-remote` categories for source reachability | A0a |
| `docs/skills-commands-hooks.md` | the new `mnx-ingest` skill + command; `mnx-promote --bulk`; capture's glean loop | A4a, A5a, G1a |
| `docs/user-journey.md` | the ingest walkthrough — trigger → gate #1 → extract → gate #2 → report → re-ingest (the two-gate touch-point model) | A6b |
| `docs/appendix-glossary-acronyms.md` | new terms: *ingest, corpus, gleaning, entity resolution (ER), wikification, ingest batch, source-tree→cluster map, orphan candidate, bulk promote* | A6b |
| `docs/overview.md` | one line: a corpus is a second knowledge source feeding the same pipeline (thesis unchanged) | A6b |
| `docs/architecture.md` | ingest as a source adapter in front of staging; no new subsystem | A6b |
| `docs/rationale-and-concepts.md` | why distilled-memory-not-mirror; why GraphRAG is ingest-only (the resolved decision) | A6b |
| `README.md` | "bootstrap the graph from an existing repo" story + the new verb + gleaning note | A6b |
| `FEATURES.md` | ingest + gleaning feature entries | A6b |
| `LIMITATIONS.md` | cost ceiling + resume; aggressive-code noise bounds & the value-gate; deletion≠death; two-gate (no unattended default) | A6c |

**A6b — Narrative + navigation.** Author the user-journey walkthrough; wire `corpus-ingestion.md` into the
`docs/` reading order (overview → … → staging → link-reconciliation → **corpus-ingestion**); add glossary
terms; land the README/FEATURES/overview/architecture/rationale one-to-few-line updates.

**A6c — LIMITATIONS + consistency checks.** Land the LIMITATIONS entries, then run a docs-consistency pass:
- **No dead cross-links** — every `[...](...)` doc link resolves (add `tests/test_doc_links.py` or a make
  target that greps + checks paths).
- **No stale pointers** — no doc still cites a removed/renamed script or the defunct
  `docs/resilient-mesh-roadmap.md`; every new script name appears in `script-contracts.md`.
- **Glossary completeness** — each new term used in a doc has an appendix entry.
- **Config parity** — every key in §2.5.6 appears in both `config/mnemex.config.md` and `docs/configuration.md`.

Acceptance (A6): the table is fully checked; `test_doc_links.py` green; a reader following the reading order
reaches ingest with every referenced term/contract/schema already defined.

---

## 4. Cross-cutting concerns (verified against current code)

- **Team lock & crash recovery.** `--bulk` promote takes the same `mnx_lock` and recovers a stranded
  `pass.plan.json` exactly as episodic promote; a crashed bulk run must not wedge the next pass, and a
  partially-drained batch must be resumable (`--resume <ingest-batch>`) from manifest + remaining staged.
- **Doctor gate.** Every bulk batch runs `mnx_doctor check` before persist and refuses on E-level findings;
  inv-4 cross-links regenerated when any cross-cluster link is created (same as episodic Step 5).
- **Freshness.** Corpus atoms get `verified = now` on write (they were just derived) via `mnx_node`; a
  doc-sourced atom is re-verifiable by re-reading its `source_path@commit` on a later ingest.
- **Multi-graph routing.** Ingest resolves the target graph via the same `mnx_binding` precedence (or
  explicit `--into`); the source-tree→cluster map is the bulk analog of per-atom `domain:`, still gated.
- **Offline/remote degradation.** A source clone failure fails fast at gate #1 with remediation (reuse
  `probe-remote` categories); a graph-push failure after commit uses the existing `--retry-push` recovery.
- **Cost containment.** LLM-judge escalation in ER is the main variable cost — capped to the `possible`
  band; a per-run atom/token ceiling with resume prevents a monorepo runaway.
- **Security.** File I/O confined to the source cache (read) and the graph root (write); a path outside
  either is refused; secrets never read (skip-list + a content guard).

---

## 5. Sequencing & dependencies

```
G0 ─► G1                         (gleaning primitive, then episodic wiring)
  └─► A0 ─► A1 ─► A2 ─► A3 ─► A4 ─► A5 ─► A6
                              ▲
                     A4 consumes G0 (Pass-1 glean)
```

- **G0/G1 first** — small, independently valuable, and A4 depends on the glean primitive.
- **A0→A2** are pure deterministic scripts (no LLM, fully unit-testable) — build and prove them before the
  judgment-heavy skill in A4.
- **A5 (`--bulk`)** is the riskiest change (touches the write path) — land it last behind the tested
  front-end, guarded by lock + doctor.

---

## 6. Risk register

| # | Risk | Likelihood / Impact | Mitigation |
|---|---|---|---|
| R1 | Aggressive code extraction floods the graph with low-value nodes | med / high | Symbol-not-line granularity + value-gate (public/doc'd/config-only); code-deep opt-in per subtree; bug-hunt e2e asserts noise bounds |
| R2 | `--bulk` promote corrupts a graph mid-merge | low / high | Team lock + pre-persist doctor + crash recovery reused; per-batch checkpoint; `--resume`; e2e on a real fixture graph |
| R3 | ER false-merge collapses two distinct entities into one node | med / high | Exact-resolves/fuzzy-proposes (DP6); `possible` band is HITL; `test_er.py` includes an explicit no-false-merge case |
| R4 | Wrong `[[link]]` creates false edges that inflate survival | med / med | Confident-only live links; fuzzy → `⚠ suggested`; red-links (cheap) absorb uncertainty |
| R5 | Re-ingest double-creates instead of updating | low / med | manifest delta → hash idempotency → ER/reconcile dedup (DP4); `test_ingest_manifest.py` |
| R6 | Cost runaway on a large monorepo | med / med | `probe` scope estimate at gate #1; per-run ceiling + resume; ER LLM-judge capped to the ambiguous band |
| R7 | Scope creep toward vectors / global index / RAG | med / high | Non-goal; DP2/DP7 normative; community detection is proposal-only |

---

## 7. Verification strategy (what "done" is proven by)

- **Unit (deterministic scripts):** `test_glean.py`, `test_ingest_walk.py`, `test_ingest_manifest.py`,
  `test_er.py`, `test_stage_bulk.py`, plus a `mnx_simindex` candidate-pair test. Reuse `tests/graphkit.py`
  fixtures; add the fixture corpus below, each file chosen to exercise one behavior:

  ```
  tests/fixtures/corpus_sample/
    docs/settlement.md      # 2 durable domain facts + 1 ADR-style pattern (trigger)  → 3 atoms
    docs/duplicate_note.md  # restates a settlement.md fact in other words            → ER COLLAPSE
    src/reconcile.py        # exported ReconcileBatch w/ docstring (→interface atom)
                            #   + a private _helper() with no doc (→ value-gate DROP)
    proto/settlement.proto  # 1 message (→ interface atom)
    CHANGELOG.md            # → classified skip (0 atoms)
    .env                    # planted secret → skipped_secrets, bytes never opened
  ```
  Expected `probe` counts: `doc=2, interface=2, code-doc≈1, skip≥1, skipped_secrets=1`; the private
  `_helper` never becomes an atom; ER collapses `duplicate_note` into the settlement fact.
- **Agent-driven e2e (bug-hunt fidelity, per the repo's testing philosophy):**
  `agent_ingest_scenario.py` (extraction/wikify/dedup quality; zero graph writes),
  `agent_bulk_promote_scenario.py` (drain → mesh heals → doctor clean → manifest written → re-run no-ops),
  and the existing `agent_promote_scenario.py` must stay green (no episodic regression from gleaning).
- **Invariant tracing:** every acceptance check names the DP it defends (DP1…DP11). CI asserts
  `mnx_doctor check` E==0 after every e2e promote.
- **Idempotency proof:** run ingest twice on an unchanged fixture → second run stages nothing, promotes
  nothing, manifest unchanged.
- **Isolation proof:** a hand-capture staged in the same graph before an ingest run survives untouched and
  is not swept by `clear --ingest-batch`.

## 8. Definition of done

- `/mnemex:mnx-ingest <local-or-remote>` bootstraps a new graph or updates an existing one, gated by scope
  (gate #1) and a bulk summary (gate #2), with no per-atom review.
- Re-ingest is idempotent; deletions surface as orphan candidates, never auto-death.
- Gleaning improves recall for both capture and ingest, bounded and duplicate-free.
- No vectors, no server, no global index introduced; the episodic path is behaviorally unchanged; every new
  surface has unit + agent-driven tests and CI runs them.
- **Documentation complete (hard gate):** every row of the A6a table is updated, the reading order includes
  `corpus-ingestion.md`, the glossary covers all new terms, config keys have parity across
  `config/mnemex.config.md` + `docs/configuration.md`, and `test_doc_links.py` passes with no dead
  cross-links or stale script/doc pointers. **The feature is not "done" until A6 is done.**

## 9. Open questions (resolve before the phase that needs them)

1. **Language coverage** for `interface`/`code-doc` classification — per-language extractors vs a
   language-agnostic heuristic (exported-symbol regex + docstring blocks). *(A0b.)*
2. **ER thresholds** — fixed defaults vs learned per-graph; the `possible` band is HITL regardless. *(A2b.)*
3. **`max_glean_passes` default** — 2 is the proposed start; confirm against a capture-recall measurement. *(G0a.)*
4. **Cross-team monorepo** — confirm the source-tree→cluster map schema carries a `team` column, not just a
   cluster. *(A4a.)*
