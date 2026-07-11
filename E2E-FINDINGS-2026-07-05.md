# Mnemex E2E Findings — 2026-07-05

Full agent-driven end-to-end test: acted as the agent, executing every `SKILL.md` step against the
real scripts and a **real private GitHub remote graph**, in an isolated sandbox `HOME` (so the user's
real `~/.claude/mnemex` was never touched). Bug-hunt mindset (find breakage, not green assertions).

- **Test graph:** https://github.com/kritird/mnemex-payments-knowledge (PRIVATE, owner `kritird`).
- **Domain:** payments (ISO 8583 / DE124, settlement, card rails, settlement finality).
- **Shape:** org index → `team-payments`{`settlement`, `rails`} + `team-risk`{`finality`}, ~15 live
  nodes + 1 dead, intra-team cross-cluster edges (`cross-links.md`), one cross-team `references`
  pointer, a wiki-mesh with a healed red-link, patterns+domain nodes, freshness horizons, a held
  contradiction. Final state doctor-clean (E0/W0/I3-orphans), staging integrity E0/W0/I0.
- **Baseline:** `pytest` = 387 passed (28s) before any E2E work.
- **Coverage:** all 7 skills (init, read, capture, promote, consolidate, doctor, status) + the reconcile
  sub-agent logic + all hooks (session-start, stop, pre-compact, pre-commit-gate) + full user journey.

Severity legend: **HIGH** = silent correctness / knowledge-loss · **MED** = breaks/traps a documented
flow · **LOW** = first-run / nag / polish.

---

## Findings index

| ID | Sev | One-line |
|----|-----|----------|
| F5 | HIGH | ✅ FIXED — `volatility` dropped in capture→promote → freshness axis inert; timeless nodes auto-killable |
| F9 | HIGH | `mnx_mesh.apply_links` is append-only, not a "mirror" → phantom mentions/edges |
| F8 | MED | ✅ FIXED — resolve now forwards a superseded name to its live successor → re-mesh repoints the edge |
| F10 | MED | ✅ FIXED — added `mnx_doctor regen-crosslinks`; promote Step 5.2 runs it before the check |
| F11 | MED | SessionStart resync silently `reset --hard`+`clean -fd` → uncommitted node writes vanish |
| F7 | MED | read's "maintenance overdue" nag fires forever when scoped to `graph_root` |
| F6 | MED | `mnx_node` truth-writes succeed with NO lock held (contradicts exit contract) |
| F1 | LOW | fresh graph: mnx-init never registers merge driver → inv-1 (W) on day one |
| F2 | LOW | fresh graph: mnx-init never stamps `config_version` JSON → inv-15 (W) on day one |
| F4 | LOW | `[[name]]` only resolves if it equals the minted slug/alias → permanent red-links |
| F3/F0 | LOW | `status.py` emits JSON+`STATUS` line (parse footgun); no CLI `--help` (known) |

---

## F5 — [HIGH] ✅ FIXED — Proposed `volatility` is silently dropped in the capture→promote handoff (freshness feature dead)

**Fix (2026-07-05):** `mnx_stage.list_atoms()` and `overlay()` now project `volatility` (plus
`mentions`, and `trigger` for `list_atoms`), so the promote reconcile agent can see and carry the
author's proposed freshness. `mnx_node.create/merge` already accepted `volatility` — the break was
purely the two stage projections. Regression tests: `test_list_atoms_exposes_volatility_trigger_mentions`,
`test_overlay_exposes_volatility` in `tests/test_stage.py`; verified end-to-end that a `timeless`
staged atom now promotes to a `timeless` node and `mnx_node.tombstone` refuses to auto-kill it.


**What:** The staged atom file correctly persists `volatility: timeless|volatile|<int>` (capture Phase 1
proposes it; data-model §7 documents it). But `mnx_stage.list_atoms()` and `mnx_stage.overlay()` BOTH
project a fixed field set that **omits `volatility`** (`list_atoms` also omits `trigger`/`mentions`/
`provenance`; `overlay` omits `volatility` + `mentions`). The `mnx-promote` skill Step 2 says: *"Carry
the atom's proposed volatility onto the node … surface it in the plan for the human to confirm or
override."* But promote reads the batch via `mnx_stage.py list` / `overlay` — **neither exposes
`volatility`** — so the reconcile agent cannot see or carry it. Every promoted node lands
`volatility: default`, regardless of the author's proposal.

**Where:** `scripts/mnx_stage.py` → `list_atoms()` and `overlay()` field projections.

**Verified:** staged 5 atoms `timeless` + 1 `volatile`; all 6 became `volatility: default` nodes in the
graph. Confirmed the atom *files* held the right value and `overlay` output lacked the key.

**User impact (correctness, not cosmetic):**
- A definition/invariant the author marked `timeless` is NOT exempt from staleness NOR from
  auto-tombstone (consolidate's death gate + `mnx_node.tombstone` exempt only `volatility==timeless`).
  So a node declared eternal can be flagged stale and later **auto-killed** → silent knowledge loss.
  (Directly linked to the working timeless-exemption — see "What worked": the safety net exists but F5
  bypasses it by never setting `timeless`.)
- A fast-rotting fact marked `volatile` gets the full default horizon → the agent trusts stale data.

**Fix direction:** include `volatility` (and `mentions`, `trigger` for `list_atoms`) in the
`list_atoms`/`overlay` projections; have promote pass it into `mnx_node.create/merge`. (The mesh
survives the omission only because it re-parses `[[links]]` from the body, not from `mentions`.)

---

## F9 — [HIGH] `mnx_mesh.apply_links` is append-only: removed body links leave phantom mentions+edges  ✅ FIXED 2026-07-05

**What:** Data-model + Link-Reconciliation §8 call front-matter `edges:` (and `mentions:`) a GENERATED
MIRROR of the body's resolved `[[wiki-links]]`. It is actually append-only. After editing a node body
from `[[de124-legacy-map]]` to `[[de124-legacy-map-v2]]` and re-running `mnx_mesh plan` + `apply`:

```
BODY links:  ledger-routing, de124-legacy-map-v2            (2)
mentions:    ledger-routing, de124-legacy-map, de124-legacy-map-v2   (3 — stale kept)
edges:       ledger-routing, de124-legacy-map, de124-legacy-map-v2   (3 — stale kept)
```

`plan_links` correctly parsed only the 2 current links, but `apply_links` **set-UNIONs** the plan into
the existing front-matter and never prunes entries whose `[[link]]` was removed.

**Where:** `scripts/mnx_mesh.py` → `apply_links`.

**User impact:**
- A phantom edge to a still-**live** node is SILENT: doctor inv-21 only checks `mentions ⊆ edges` (both
  carry the stale entry); nothing checks `edges/mentions ⊆ current-body-resolved-links`.
- Structural-strength in-degree is inflated by ghost edges → wrong tiering / death decisions;
  death-severing chases links the author removed.
- SUPERSEDE (F8) can never be completed by editing bodies — the dead edge persists → permanent
  doctor E inv-2.
- Any ordinary edit that drops/renames a link leaks a phantom edge forever.

**Fix direction:** `apply_links` must RE-DERIVE `mentions`/`edges` from the current body's resolved links
(set-REPLACE, not set-union), or explicitly prune links absent from the note body; add a doctor
invariant `edges ⊆ current body-resolved-links`.

**Fixed 2026-07-05:** `plan_links` now emits `sources:` (the batch note ids whose full body it parsed).
`apply_links` RE-DERIVES the mirror from scratch for those sources (set-REPLACE → removed/renamed
links are pruned, and a note that dropped all links is emptied), while a backlink-only older note
(absent from `sources`) is still APPENDed so L2 back-fill never wipes its body-backed edges. Added
doctor **inv-22 (W)**: every `mentions[]` entry must trace to a current body `[[wiki-link]]`; a
phantom is flagged. Tests: `tests/test_mesh.py::test_apply_prunes_removed_link_no_phantom`,
`::test_apply_clears_mirror_when_all_links_removed`,
`::test_apply_backlink_only_source_preserves_existing_mirror`,
`tests/test_doctor.py::test_phantom_mention_flags_inv22`.

---

## F8 — [MED] SUPERSEDE gives no auto-repoint; naive re-mesh drops the edge to a red-link

**What:** `mnx_node.supersede` sets `old.status=dead` + `superseded-by=<new>`, and (per contract)
"referrer repoint stays with the caller." promote Step 5: *"repoint every referrer to the successor"*
via mnx_mesh/mnx_resolve. But `mnx_phonebook.resolve("de124-legacy-map")` (the superseded id) returns
`resolved: null` (only fuzzy candidates incl. the v2). Edges are a generated mirror of body `[[links]]`;
the referrer body still says `[[de124-legacy-map]]`. So:
- doctor correctly flags **E inv-2** (live edge → tombstoned node) — GOOD backstop.
- re-running mesh does NOT repoint to v2 — the old name no longer resolves → it becomes a **red-link**,
  silently DROPPING the connection instead of forwarding it.
- the only real fix is a human/agent rewrite of every referrer body `[[old]]`→`[[new-slug]]`, which no
  tool assists (resolve won't forward `superseded-by`), and F9 then blocks even that.

**Where:** `scripts/mnx_phonebook.py` `resolve` (no superseded-by forwarding); `scripts/mnx_mesh.py`
(emits red-link instead of a supersede-repoint); interacts with F9.

**User impact:** SUPERSEDE (a documented first-class disposition) leaves the graph in a doctor-error
state that self-heals into edge LOSS if the agent trusts the mesh.

**Fix direction:** make resolve/mesh forward a dead node's `superseded-by` to the successor (auto-repoint
body link + edge), or have mesh emit a "supersede-repoint" action instead of a red-link when the missing
target has a `superseded-by` successor.

**✅ FIXED:** `mnx_phonebook._supersede_map` scans dead nodes with `superseded-by`, collapses supersede
chains (v1→v2→v3) to the final LIVE successor, and keys on the old id + the dead node's own aliases.
`resolve` consults it after the active-exact passes fail: a superseded name now returns the successor with
`match: "superseded-by"` + `forwarded_from: <old>` (instead of null). `mnx_mesh.plan_links` tags that link
`origin: "supersede-repoint"` so the skill can optionally rewrite the body `[[old]]→[[new]]` — the EDGE is
already forwarded, so a naive re-mesh now repoints instead of dropping to a red-link, and doctor E inv-2
self-heals. A chain that dead-ends at a still-dead terminal stays a red-link (inv-2 backstop preserved).
Tests: `test_resolve_forwards_superseded_id_to_successor` / `_alias` / `_follows_supersede_chain…` /
`_still_red_link_when_successor_dead` (test_phonebook.py); `test_supersede_repoints_edge_not_dropped_end_to_end`
(test_mesh.py).

---

## F10 — [MED] Promote's doctor-check gate can block on cross-links, but no step/CLI updates cross-links — ✅ FIXED 2026-07-08

**Status:** FIXED via Option A. Added `regen_crosslinks(scope)` to `scripts/mnx_doctor.py` — the targeted
cross-links-only writer, factored out of `fix` so both reuse the SAME `_boundary_rows` derivation the
check gates on (they can never disagree) — and exposed it as `mnx_doctor.py regen-crosslinks <graph_root>`.
Promote Step 5.2 now calls it before the Step 5.3 check (skill updated to name the real command instead of
the phantom "delta-update cross-links.md"). Verified: boundary-edge repro goes `check E=1 (inv-4)` →
`regen-crosslinks` → `check E=0`, node truth byte-identical, output identical to full `fix`; full suite 398
passed. (Chose A over B — a second writer in `mesh.apply` — to avoid a rival derivation drifting from the
check.)

**What:** promote Step 5.2 says *"delta-update cross-links.md"*; Step 5.3 gates on `mnx_doctor.py check`
E==0. But:
- `mnx_mesh.apply_links` writes the boundary EDGE into node front-matter but does NOT touch
  `cross-links.md`.
- `mnx_index.regenerate_index` does NOT touch `cross-links.md`.
- There is NO standalone "delta-update / regenerate cross-links" CLI. The ONLY writer is
  `mnx_doctor.fix` (full regen) or the `mnx-regen` merge driver.

So a faithful promote that creates ANY cross-cluster link (very common) and then runs the Step-5.3
doctor CHECK sees `E inv-4: boundary edge missing from <team>/cross-links.md` and is BLOCKED, with no
documented command to satisfy the "delta-update cross-links.md" the skill named.

**Where:** `skills/mnx-promote/SKILL.md` Step 5.2/5.3; `scripts/mnx_mesh.py`; `scripts/mnx_doctor.py`
(`fix` is the only cross-links writer besides `mnx_regen`).

**Verified:** 6 nodes with 4 rails→settlement boundary edges → `doctor check` E=4; only `mnx_doctor fix`
cleared it. (Cross-**team** `references` are correctly NOT integrity-checked — validated, no error.)

**Fix direction:** either promote Step 5 must run `mnx_doctor fix` (or a real cross-links delta-updater)
BEFORE the check, and the skill must say so; or `mesh.apply` must maintain `cross-links.md` as it writes
boundary edges.

---

## F11 — [MED] SessionStart resync silently `reset --hard` + `clean -fd`s the clone

**What:** `mnx_binding.sync()` for a git-remote does `git fetch` → `git reset --hard origin/<branch>` →
`git clean -fd` (see `scripts/mnx_binding.py` `sync`, ~line 33) with NO dirty-tree check, NO stash, NO
warning. SessionStart calls this every session and reports only "Graph resynced to origin/main."

**Verified (painfully):** created `de124-legacy-map` + `de124-legacy-map-v2` (a SUPERSEDE) in the clone
but hadn't committed/pushed them; running the SessionStart hook mid-session **silently deleted BOTH node
files** (untracked → `clean -fd`) and reverted the supersede edits (`reset --hard`). The remote never
received them; zero signal that work was discarded.

By design the clone is ephemeral (truth = remote; staging lives outside the clone), BUT:
- A promote that writes nodes via `mnx_node` then crashes/aborts/errs BEFORE persist loses those node
  files at the next session start. Only still-staged atoms save it (and only if not yet cleared) — the
  reconcile + mesh work is silently thrown away and must be redone.
- A standalone `mnx-doctor --fix` (or any manual node edit) not persisted is silently gone next session.
  The doctor skill DOES warn to persist "so a remote graph's repair is pushed rather than discarded at
  the next session resync" — proof the authors know the hazard — but `sync()` itself provides no guard.

**Where:** `scripts/mnx_binding.py` `sync()`.

**User impact:** silent data loss of in-clone work with a reassuring "resynced" message.

**Fix direction:** `sync()` should detect a dirty/untracked tree and (a) warn loudly listing what will be
discarded, and/or (b) stash or refuse when uncommitted node truth is present.

---

## F7 — [MED] Read's "maintenance overdue" nag fires forever when scoped to graph_root

**What:** `mnx-read` SKILL step 1: *"Run `mnx_compact.py overdue`"* — no scope arg given, and the skill
uses `graph_root` as THE location everywhere else. But `overdue(graph_root)` computes
`team_of(graph_root, graph_root)` = None → falls back to `Path(graph_root).name` = the clone-slug dir
name (e.g. `mnemex-payments-knowledge-16a26e93`), then looks for that key in `.mnemex/last_compaction`
whose keys are real team names (`team-payments`). Never matches → `never_compacted:true, due:true` ALWAYS.

**Verified:** with a fresh `team-payments=<now>` last_compaction stamp,
```
overdue <graph_root>              -> due:true,  never_compacted:true, team:"<clone-slug>"   (SPURIOUS)
overdue <graph_root>/team-payments -> due:false                                             (correct)
```

**Where:** `skills/mnx-read/SKILL.md` step 1 (under-specified scope); `scripts/mnx_compact.py` `overdue`
(silently accepts a graph-root arg, keys by dir name). The CORRECT pattern already exists in
`scripts/mnx_hooks.py` `_session_nags` (iterates `team-*` dirs, calls `overdue(team_dir, …)` per team).

**User impact:** the user sees "Knowledge maintenance is N days overdue — run /mnemex:mnx-promote" on
EVERY read, seconds after a clean promote. Cry-wolf → users learn to ignore the nag (and miss a real
overdue).

**Fix direction:** read must call `overdue` per-team (iterate teams, or pass the routed team dir); and
`overdue()` should refuse/iterate a graph-root arg instead of silently keying by the clone-dir name.

---

## F6 — [MED] Truth-writes (`mnx_node`) are NOT lock-guarded, contradicting the exit contract

**What:** `docs/script-contracts.md` "Exit/IO contract": *"all mutating scripts are no-ops without the
team lock (they verify the lock handle)."* Verified: `mnx_node.py merge --id iso8583-mti` wrote node
truth with the team lock demonstrably FREE (`mnx_lock status` → `held:false`) and returned
`action:merged`. `mnx_node`'s own docstring says "the writer does not take the lock itself" (relies on
caller discipline) and it also never verifies one is held. So the blanket contract claim is false for
the single most important mutator.

**Where:** `scripts/mnx_node.py` (no lock verification); `docs/script-contracts.md` (blanket claim).

**User impact:** concurrent promotes / a stray caller / a skill that forgets `mnx_lock.acquire` can write
nodes + race index regen with no guard. The PreToolUse commit-gate only blocks the eventual git commit on
invariant errors — it does not serialize node writes.

**Fix direction:** either enforce a lock-handle check in `mnx_node` truth-write entrypoints, or correct
the contract to state truth-writers are unguarded-by-design (caller must lock).

---

## F1 — [LOW] Fresh graph fails doctor inv-1 (W): merge driver not registered

**What:** After a faithful mnx-init (scaffold + sync), `mnx_doctor check` reports
`inv 1 (W) "mnx-regen merge driver not registered"`. The `mnx-init` SKILL never runs
`mnx_regen.py install`. The merge driver is per-clone git config, so EVERY fresh clone/session starts
dirty until a `doctor --fix` or promote installs it.

**Where:** `skills/mnx-init/SKILL.md` (missing an install step); `scripts/mnx_regen.py install`.

**Open question:** does session-start `sync` re-install the driver each session? (worth verifying — the
per-clone config is lost on each fresh clone.)

**Fix direction:** mnx-init should run `mnx_regen.py install <graph_root>` during scaffold (and possibly
session-start after a fresh clone).

---

## F2 — [LOW] Fresh graph fails doctor inv-15 (W): config_version drift on a brand-new graph

**What:** mnx-init SKILL says scaffold `.mnemex/` + write config, but never stamps `.mnemex/config_version`
as the JSON the code expects: `{config_version, lam_domain, lam_pattern, stamped_at}`. The data-model doc
describes it as "version + λ", ambiguous enough that a hand-scaffold writes `config_version=1` (plain
text). `mnx_config.read_stamp` does `json.loads` → fails → returns None → `changed_since_last_compaction`
returns True → inv-15 "re-normalization pending" on a NEW graph.

**Where:** `skills/mnx-init/SKILL.md`; `scripts/mnx_config.py` `read_stamp`/`stamp`;
`docs/data-model-and-schemas.md` §8 (ambiguous description).

**User impact:** a fresh graph immediately nags "maintenance/re-normalization pending"; confusing on
day one. (Together with F1: two W findings on first run.)

**Fix direction:** mnx-init should call `mnx_config.py stamp <graph_root>` during scaffold; clarify the
data-model §8 description as a JSON stamp.

---

## F4 — [LOW] Wiki-link `[[name]]` silently becomes a permanent red-link unless it equals the minted slug/alias

**What:** Capture guidance: *"Link freely BY NAME, even to a page that doesn't exist yet; promote resolves
each `[[name]]`."* But `mnx_phonebook.resolve` matches exact id → alias → summary token-overlap. The node
id is `slugify(title)`: `slugify("ISO 8583 Field 124 — stablecoin routing")` = `iso-8583-field-124-…`. So
an author who writes body link `[[iso8583-field124]]` and titles the node "ISO 8583 Field 124" gets a
red-link that NEVER heals (target slug differs, and the name isn't an alias). The reconcile agent must add
the referenced name as an alias, or the author must predict the eventual slug when choosing the link text.

**Where:** `scripts/mnx_common.py` `slugify`; `scripts/mnx_phonebook.py` `resolve`; capture/promote skill
"link freely by name" promise.

**User impact:** the mesh looks connected but many intended edges stay latent/red.

**Fix direction:** either resolve on a slugified form of the `[[name]]` too, or have reconcile
auto-register the referenced name as an alias of the created node, or document that wiki-links must be
slug-shaped.

---

## F3 / F0 — [LOW] status.py parse footgun; no CLI `--help`

- **F3:** `mnx_status.py status | json.tool` → "Extra data: line 2". The status skill says "read the
  single JSON object", but the script appends a `STATUS=OK` line. A skill that json-parses stdout naively
  breaks; must read the first line only. (`binding.py` deliberately omits the STATUS line; `status.py`
  includes it — inconsistent across the read-only surfaces.)
- **F0:** `mnx_stage.py --help`, `mnx_node.py`, etc. → `{"error":"unknown subcommand"}` STATUS=FAIL. No
  discoverable usage string. Already known (memory: `mnemex-test-findings`). Low impact (skills call them,
  not humans).

---

## What worked well (regression baseline — keep these passing)

- **mnx-init:** resolve → probe-remote → binding → sync (cloned) → status (clone_present, ahead=0),
  end-to-end against the real remote.
- **capture:** idempotent re-stage (same content hash, no dup), `[[wiki-link]]` → `mentions` hoist,
  budget/urgent, curate (`--drop`).
- **promote:** create via `mnx_node` + mesh (10 live links + 1 correct red-link) + doctor + persist
  (commit + push) + `clear-merged`; nodes verified live on GitHub.
- **red-link BACKFILL healing:** creating the target page auto-wrote the backlink onto the older node
  (mention `null → id`, edge added), red-links catalog → 0.
- **held-queue (contradiction HITL):** hold quarantines to a `held/` dir, excluded from `list`/`overlay`;
  `clear-merged` preserves held; status surfaces it.
- **freshness:** once `volatility` is on the node, `timeless → stale_after "—"`, `volatile → short
  horizon`, patterns get +30% horizon. (Only F5 breaks the plumbing.)
- **tombstone/death:** `tombstone` refuses a `timeless` node (inv-9d by construction), succeeds on
  `default`, `resurrect` works.
- **read durability (git-remote):** stamp `spilled` outside the clone → `flush` replays → commit + push →
  registry on GitHub; pending back to 0.
- **hooks:** pre-commit-gate (deny on E with clear reason, allow clean, ignore the author's project repo);
  session-start (sync + consent primer + per-team overdue nag); stop (flush + capture nudge, once/session);
  pre-compact (re-arm Stop nudge + flush, silent by design).
- **doctor:** detects injected corruption (bad edge → E), `--fix` regenerates derived (index, cross-links,
  phonebook, org) — cross-links healed after being flagged.
- **status skill:** 2 teams / 3 clusters / node + tier counts, org routing head, health, held-queue.
- **org→team→cluster routing** and **cross-team `references`** correctly excluded from integrity checks.

---

## Suggested fix priority

1. **F5, F9** — correctness/silent-loss; fix first. Both small: add `volatility`/`mentions` to the stage
   projections (F5); make `apply_links` re-derive from the body (F9).
2. **F8, F10, F11** — each breaks or traps a documented flow (supersede, cross-cluster promote, resync).
   (F8 ✅ fixed; F10 ✅ fixed; F11 remains.)
3. **F7, F1, F2** — nag/first-run polish that erodes trust in the (otherwise good) advisory signals.
4. **F6, F4, F3/F0** — contract/robustness hardening.

## Reproduction notes

Each finding above lists the exact script/skill location. The E2E was driven with:
`HOME=<sandbox> CLAUDE_PLUGIN_ROOT=<repo> GH_TOKEN=<token> python3 <repo>/scripts/mnx_*.py …`, cwd inside
a project dir carrying `.mnemex.md` (graph_remote → the GitHub repo). The graph itself is browsable at
https://github.com/kritird/mnemex-payments-knowledge for concrete before/after state.
