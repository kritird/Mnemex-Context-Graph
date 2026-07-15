# Project instructions

## Keep the MCP and plugin surfaces in sync

This repo ships two parallel delivery paths for the same functionality: the **MCP server**
(`scripts/mnx_mcp.py`, tools consumed by any MCP client) and the **Claude plugin**
(`skills/*/SKILL.md`, driving the same underlying `scripts/mnx_*.py` engine by hand). Both
ultimately call the same shared engine functions, but a fix or enhancement made through one
surface does not automatically reach the other — a validation check added only at the MCP
tool layer, for example, leaves the CLI/skill path exposed to the exact same bug.

**Rule: whenever an MCP feature is fixed or enhanced, make the corresponding fix/enhancement
on the plugin (skill) side too, and vice versa. Keep both in lockstep — do not let one surface
silently get ahead of the other.**

Concretely:
- Prefer putting a fix in the **shared engine function** (`scripts/mnx_*.py`, below both
  `mnx_mcp.py` and the skills) rather than only in the MCP tool wrapper, whenever the fix is
  about correctness/validation — that way every caller benefits automatically.
- When a fix or new capability is necessarily surface-specific (e.g. an MCP tool's structured
  error payload, or a skill's prose instructions), still check whether the *other* surface
  needs an equivalent update, and make it in the same session/PR rather than deferring it.
- If parity is deliberately deferred (e.g. a capability is MCP-only for now, per a documented
  phased rollout), say so explicitly at the point of change — don't leave it to be discovered
  as a surprise later.
