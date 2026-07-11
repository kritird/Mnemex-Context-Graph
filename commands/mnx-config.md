---
description: View or change your Mnemex graph's behavior config (decay half-life, tiers, freshness, boosts, budgets, death policy) with a guided explanation of each knob. No args = display current settings; pass a key and value to modify one safely.
argument-hint: "[<key> <value>] [--all]"
---

Use the **mnx-config** skill to view or tune the Mnemex graph's behavior configuration.

Options: $ARGUMENTS

Preflight first (`mnx_binding.py status` → resolve the graph root, or stop and point at
`/mnemex:mnx-init`); all config operations use that graph, not the working directory.

- **No key given** (or `--all`): run **display mode** — `mnx_config.py show <graph_root> [--all]` — and
  present the values grouped, showing each value (and its default if different), whether it's overridden,
  and a one-line meaning. Lead with: you really only need to set `half_life_days`; everything else has a
  sensible default.
- **A `<key> <value>` pair**: run **modify mode** — first explain what the knob does and the effect of the
  new value (warn if it's a decay/freshness knob whose change is staged and gradual), confirm, then
  `mnx_config.py set <graph_root> <key> <value>`. It validates the value, writes it (preserving comments),
  and auto-bumps `config_version`. Report `old → new` and the version bump; if `renorm_pending`, note that
  the next `mnx-promote` re-normalizes scores and `mnx-read` will warn until then. For a remote graph,
  persist with `mnx_binding.py persist`.

Never hand-edit `mnemex.config.md` YAML — always go through `mnx_config.py set`. Config lives only in the
graph repo, never in a project binding or user config.
