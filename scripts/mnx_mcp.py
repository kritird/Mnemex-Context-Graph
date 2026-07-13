"""mnx_mcp.py — the OpenMnemex stdio MCP server (multi-agent plan v2 §5, Phase 1).

One stdio server, spawned by the host agent, dead with the session — no port, no daemon.
Every tool is a thin shim over an importable engine function (in-process, no subprocess
fan-out); no logic lives here beyond schema validation, the session guards, and the
path-confinement check. Commit 1a ships the scaffolding only: the server starts, lists
zero tools, and exits cleanly. Tools arrive in 1b (binding/health), 1c (read), 1d (capture).

Session-level contracts implemented here (§5.2):

  * **Error contract** — a tool result is either ``{"ok": true, ...payload}`` or
    ``{"ok": false, "error": {"code", "message", "action"}}`` where ``action`` is the
    human-actionable next step. Never a traceback. No tool mutates anything when it
    returns an internal error.
  * **Sync-once** — the first graph-touching tool call per server process runs
    ``mnx_binding.sync`` (blocking, same as the SessionStart hook); later calls skip it.
    ``offline`` / ``skipped-dirty`` / ``skipped-unpushed`` are available-but-DEGRADED,
    never errors (E2E finding F11): results carry ``degraded: true`` plus the sync detail,
    and ``skipped-unpushed`` points at ``promote_retry_push``.
  * **Mute** — consent on MCP hosts is implicit-by-invocation, but the per-session
    opt-out marker (mnx_hooks) is still honored: every tool checks it first and returns a
    structured ``muted`` refusal. The session id is ``$MNEMEX_SESSION_ID`` when the host
    pins one, else the shared ``"default"`` session (what ``mnx_hooks.py opt-out`` with
    no ``--session`` toggles).
  * **Confinement** — every path a tool reads or writes must resolve (symlinks followed)
    inside the graph root, the per-author mnemex home, or the ingest cache — never the
    caller's CWD/project. ``confine()`` is the one shared guard.

The ``mcp`` SDK is an OPTIONAL extra (``pip install openmnemex[mcp]``, Python 3.10+); this
module must stay importable without it (the packaging bridge imports every engine module,
and the engine keeps its 3.9 floor), so the SDK import is soft and only ``serve()``/
``create_server()`` require it. ``serve`` failures print to stderr — stdout belongs to the
JSON-RPC protocol.

CLI:
    serve   — run the stdio server (default; blocks until the host disconnects)
    info    — server identity + SDK availability as JSON (never starts the server)

Run: ``uvx openmnemex-mcp`` (packaged) or ``python3 scripts/mnx_mcp.py`` (checkout).
"""
from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import mnx_binding
import mnx_common
import mnx_hooks

# Soft SDK import: the engine (and the packaging bridge, which imports every mnx_* module)
# must work on 3.9 / without the [mcp] extra. Only building/running the server needs it.
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_IMPORT_ERROR: Optional[BaseException] = None
except Exception as _exc:  # ImportError, or SyntaxError on very old Pythons
    FastMCP = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = _exc

SERVER_NAME = "openmnemex"
_INSTRUCTIONS = (
    "OpenMnemex context-graph memory: a Markdown-in-git knowledge graph — no daemon, no "
    "database, no vector store. Tools are added phase by phase; read/capture/promote "
    "procedures arrive with them."
)


def engine_version() -> str:
    """The engine's own version, single-sourced with pyproject.toml.

    The plugin manifest next to the running engine wins (a checkout may coexist with an
    older pip install); a wheel install has no manifest and uses its package metadata.
    """
    manifest = mnx_common.plugin_root().parent / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("openmnemex")
    except Exception:
        return "0+unknown"


# --- error contract -----------------------------------------------------------

class ToolError(Exception):
    """A structured, host-renderable tool failure: code + message + actionable next step."""

    def __init__(self, code: str, message: str, action: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.action = action

    def to_result(self) -> dict[str, Any]:
        return err(self.code, str(self), self.action)


def ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **payload}


def err(code: str, message: str, action: Optional[str] = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if action:
        error["action"] = action
    return {"ok": False, "error": error}


# --- confinement (§5.2 security) ------------------------------------------------

class ConfinementError(ToolError):
    def __init__(self, path: str):
        super().__init__("confined",
                         f"Path resolves outside the graph root / mnemex home: {path}",
                         "use paths inside the bound graph or the mnemex home")


def confine(path: str | Path, roots: list[str | Path]) -> Path:
    """Resolve ``path`` (symlinks followed) and require it inside one of ``roots``.

    Returns the resolved Path or raises ConfinementError — the server never touches the
    caller's CWD/project, only the graph, the per-author home, and the ingest cache.
    """
    resolved = Path(path).expanduser().resolve()
    for root in roots:
        root_resolved = Path(root).expanduser().resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    raise ConfinementError(str(path))


def allowed_roots(binding: Optional["mnx_binding.Binding"]) -> list[Path]:
    """The confinement whitelist: graph root + mnemex home + ingest cache (env-relocatable)."""
    roots = [mnx_common.mnemex_home()]
    ingest_cache = os.environ.get("MNEMEX_INGEST_CACHE")
    if ingest_cache:
        roots.append(Path(ingest_cache).expanduser())
    if binding is not None:
        roots.append(Path(binding.graph_root()))
    return roots


# --- mute (§5.2 consent) ---------------------------------------------------------

def session_id() -> str:
    """The mute-marker key: host-pinned $MNEMEX_SESSION_ID, else the shared default session."""
    return os.environ.get("MNEMEX_SESSION_ID") or "default"


def is_muted() -> bool:
    return mnx_hooks.core_is_muted(session_id())


_MUTED_RESULT = dict(code="muted",
                     message="Mnemex is muted for this session (the user opted out).",
                     action="stop calling mnemex tools; the user can opt back in with "
                            "mnx_hooks.py opt-in")


# --- sync-once (§5.2 session sync) ------------------------------------------------

# Sync actions that leave the graph usable but stale/local-only. NEVER errors (F11);
# unknown/new actions must also never be mapped to the error branch — that exact bug
# lived in the Claude hook adapter until the 2026-07-12 fix cycle.
_DEGRADED_HINTS = {
    "offline": None,
    "skipped-dirty": "persist or discard the local work, then resync",
    "skipped-unpushed": "run promote_retry_push",
}

_session_state: dict[str, Any] = {"synced": False, "sync": None}


def reset_session_state() -> None:
    """Forget the once-per-process sync (tests; a real server process never needs it)."""
    _session_state["synced"] = False
    _session_state["sync"] = None


def _resolve_binding() -> "mnx_binding.Binding":
    try:
        binding = mnx_binding.resolve()
    except Exception as exc:  # malformed binding file — report, don't traceback
        raise ToolError("binding-error", str(exc),
                        "fix or remove the malformed binding file") from exc
    if binding is None:
        raise ToolError("unresolved", "No Mnemex graph configured for this project or user.",
                        "run init_graph")
    return binding


def ensure_synced() -> dict[str, Any]:
    """Resolve the binding and sync the graph clone, once per server process.

    Returns ``{binding, sync}`` where ``sync`` carries ``degraded``/``offline_degraded``
    flags for tools to surface. A hard sync failure (missing local folder, clone failed
    with no local copy) raises ToolError and does NOT cache, so the next call retries.
    """
    binding = _resolve_binding()
    if _session_state["synced"]:
        return {"binding": binding, "sync": _session_state["sync"]}
    result = mnx_binding.sync(binding)
    action = result.get("action")
    if action == "error":
        raise ToolError("sync-failed", result.get("message", "Graph sync failed."),
                        "check the graph path/remote or run init_graph")
    sync_info: dict[str, Any] = {"action": action, "message": result.get("message"),
                                 "degraded": action in _DEGRADED_HINTS,
                                 "offline_degraded": action == "offline"}
    if _DEGRADED_HINTS.get(action):
        sync_info["next_step"] = _DEGRADED_HINTS[action]
    _session_state["synced"] = True
    _session_state["sync"] = sync_info
    return {"binding": binding, "sync": sync_info}


# --- the tool guard ---------------------------------------------------------------

def tool_guard(sync_first: bool = True) -> Callable:
    """Wrap an engine-calling tool body in the session contracts, in order:
    mute check → (optional) sync-once → run → shape the result; exceptions become the
    structured error result, never a traceback. The wrapped body returns a plain payload
    dict; graph-touching bodies receive ``binding=`` and ``sync=`` keyword arguments.
    """
    def deco(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                if is_muted():
                    return err(**_MUTED_RESULT)
                if sync_first:
                    session = ensure_synced()
                    kwargs.setdefault("binding", session["binding"])
                    kwargs.setdefault("sync", session["sync"])
                    payload = fn(*args, **kwargs)
                    if session["sync"].get("degraded"):
                        payload.setdefault("degraded", True)
                        payload.setdefault("sync", session["sync"])
                    return ok(payload)
                return ok(fn(*args, **kwargs))
            except ToolError as te:
                return te.to_result()
            except Exception as exc:  # never a traceback over the wire
                return err("internal", f"{type(exc).__name__}: {exc}",
                           "report this; the graph was not modified by this call")
        return wrapper
    return deco


# --- the server --------------------------------------------------------------------

def _sdk_missing_message() -> str:
    if sys.version_info < (3, 10):
        return (f"The OpenMnemex MCP server needs Python 3.10+ (running "
                f"{sys.version_info.major}.{sys.version_info.minor}); the engine itself "
                f"keeps working on 3.9 — only the MCP surface is gated.")
    return ("The 'mcp' SDK is not installed. Install the optional extra: "
            "pip install 'openmnemex[mcp]'  (or run via: uvx openmnemex-mcp). "
            f"Import error: {_MCP_IMPORT_ERROR}")


def sdk_available() -> bool:
    return FastMCP is not None and sys.version_info >= (3, 10)


def create_server() -> "FastMCP":
    """Build the FastMCP stdio server. Commit 1a registers no tools/prompts/resources yet."""
    if not sdk_available():
        raise RuntimeError(_sdk_missing_message())
    server = FastMCP(name=SERVER_NAME, instructions=_INSTRUCTIONS)
    # FastMCP doesn't expose a version parameter; the low-level server does, and without
    # this the host would see the SDK's version instead of ours in initialize.serverInfo.
    server._mcp_server.version = engine_version()
    return server


def info() -> dict[str, Any]:
    """Server identity + environment readiness, without starting anything."""
    return {"name": SERVER_NAME, "version": engine_version(),
            "sdk_available": sdk_available(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            **({} if sdk_available() else {"sdk_error": _sdk_missing_message()})}


def serve() -> int:
    """Run the stdio server (blocks). Pre-flight failures go to stderr — stdout is JSON-RPC."""
    try:
        server = create_server()
    except RuntimeError as exc:
        print(f"openmnemex-mcp: {exc}", file=sys.stderr)
        return 1
    server.run(transport="stdio")
    return 0


# --- cli -----------------------------------------------------------------------------

_USAGE = [
    "mnx_mcp.py serve  — run the stdio MCP server (default; blocks until the host disconnects)",
    "mnx_mcp.py info   — server identity + SDK availability as JSON (never starts the server)",
]


def _main(argv: list[str]) -> int:
    handled = mnx_common.cli_guard(argv, _USAGE)
    if handled is not None:
        return handled
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "info":
        return mnx_common.emit(info())
    if cmd == "serve":
        return serve()
    return mnx_common.emit({"error": f"unknown subcommand: {cmd}", "usage": _USAGE}, ok=False)


def main() -> int:
    """Console entry point (pyproject [project.scripts] openmnemex-mcp)."""
    return _main(sys.argv)


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
