// OpenCode adapter (multi-agent plan v2, Phase 4 / commit 4a).
//
// Thin translator only: normalizes OpenCode's plugin event shape into the host-neutral
// event dict `mnx_hooks.core_*()` expects (see scripts/mnx_hooks.py), then execs the same
// Python engine Claude Code's hooks/hooks.json shells out to. No side-effect logic lives here.
//
// Mapping (session-lifecycle events only, per plan scope):
//   session.created   -> session-start   (consent primer + graph sync)
//   session.idle      -> stop            (usage-stamp flush + capture nudge bookkeeping)
//   session.compacted -> pre-compact     (re-arms the Stop nudge for the lost window)
//   dispose()         -> session-end     (safety-net flush; best-effort synthetic session id,
//                                          since OpenCode's dispose() carries no event payload)
//
// `session.compacted` (stable, post-hoc) is used instead of the experimental
// `experimental.session.compacting` pre-hook: core_pre_compact() is side-effect-only and never
// injects context into the compaction itself, so before-vs-after timing does not matter for us,
// and the stable event is a safer bet across OpenCode versions (§12 item 2 — re-verify the event
// API at integration time; https://opencode.ai/docs/plugins/ as of 2026-07).
//
// Delivery gap (documented in LIMITATIONS.md #3): mnx_hooks.py's HookOutcome (context/block/
// notice text -- e.g. the session-start consent primer) has no rendering surface here; OpenCode's
// `event` hook is fire-and-forget with no return channel back into the model's context. Only the
// underlying SIDE EFFECTS run (graph sync, usage-stamp flush, marker bookkeeping, doctor checks
// via the pre-compact re-arm); the advisory/consent prompts themselves reach the model via
// AGENTS.md instructions instead, same as any Assisted-tier host. Do not add a `console.log` of
// the hook's stdout here as a workaround -- it would print to OpenCode's own process output, not
// the model's context, and would look like working delivery while doing nothing.
// Scope boundary: this path is correct for this file's location in THIS repo checkout
// (integrations/opencode/mnemex.ts -> ../../scripts/mnx_hooks.py). When Phase 5's installer
// copies/emits this file into a consumer project's `.opencode/plugin/mnemex.ts`, that copy needs
// an installed-package-relative (or absolute, baked in at install time) path instead — rewriting
// HOOKS_SCRIPT for the target layout is Phase 5's job (commit 5b), not done here.
import type { Plugin } from "@opencode-ai/plugin"

const HOOKS_SCRIPT = new URL("../../scripts/mnx_hooks.py", import.meta.url).pathname

async function runHook(
  cwd: string,
  subcommand: string,
  event: Record<string, unknown>,
): Promise<void> {
  try {
    const proc = Bun.spawn(["python3", HOOKS_SCRIPT, subcommand], {
      cwd,
      stdin: "pipe",
      stdout: "ignore",
      stderr: "ignore",
    })
    proc.stdin.write(JSON.stringify(event))
    proc.stdin.end()
    await proc.exited
  } catch {
    // advisory hooks must never break a session — same fail-open contract as the Claude adapter
  }
}

export const MnemexPlugin: Plugin = async ({ directory }) => {
  let lastSessionID = ""

  return {
    event: async ({ event }) => {
      switch (event.type) {
        case "session.created": {
          const sid = (event.properties as any)?.info?.id ?? ""
          lastSessionID = sid
          await runHook(directory, "session-start", { session_id: sid })
          break
        }
        case "session.idle": {
          const sid = (event.properties as any)?.sessionID ?? lastSessionID
          lastSessionID = sid
          await runHook(directory, "stop", { session_id: sid })
          break
        }
        case "session.compacted": {
          const sid = (event.properties as any)?.sessionID ?? lastSessionID
          await runHook(directory, "pre-compact", { session_id: sid })
          break
        }
      }
    },
    dispose: async () => {
      if (lastSessionID) await runHook(directory, "session-end", { session_id: lastSessionID })
    },
  }
}
