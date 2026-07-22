"""mnx_lock.py — team lock + crash recovery.

See docs/architecture.md §9-10 and docs/script-contracts.md.

One mutating operation per team at a time (mnx-promote apply, incl. its folded consolidate). A crash leaves a
readable plan and (possibly) a dirty tree that recover() can roll back via `git checkout`
to the last good commit (F10). Reads need no lock (registry appends are commutative).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import mnx_common


class Busy(Exception):
    """Raised when the team lock is already held."""


# --- stale-lock reclaim (F4) -------------------------------------------------
# A lock file persists on disk after the process that wrote it exits — that is deliberate:
# the skill runs promote `begin` and `apply` as SEPARATE short-lived processes, so the lock
# has to outlive the process that took it. The flip side is that a crash/disconnect between
# begin and apply leaves the lock stranded with no owner and nothing to clear it (recover()
# only reclaims a lock that has a stranded *plan* beside it; the begin→apply window has none),
# wedging every later acquire with Busy forever.
#
# The safe staleness signal is AGE, not pid-liveness: because the legitimate begin→apply flow
# routinely leaves a dead pid on disk mid-transaction, a pid-liveness probe would false-positive
# and steal a lock that a human is still holding to review a plan. Locks live under the
# gitignored .mnemex/locks/, so they are always local to this machine and age is unambiguous.
# The TTL is generous enough to never bite a real review, yet bounds an abandoned-lock wedge to
# at most the TTL instead of forever.
STALE_LOCK_TTL_SECONDS = 3600  # 1h; override with MNEMEX_LOCK_TTL_SECONDS


def _lock_ttl_seconds() -> int:
    raw = os.environ.get("MNEMEX_LOCK_TTL_SECONDS")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return STALE_LOCK_TTL_SECONDS


def _lock_age_seconds(path: Path, meta: dict) -> Optional[float]:
    """Age of the lock in seconds, from its recorded `acquired` timestamp; falls back to the
    file mtime for a corrupt/undated lock so even a malformed one still ages out."""
    acquired = meta.get("acquired")
    if acquired:
        try:
            dt = mnx_common.parse_ts(acquired)
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            pass
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _reclaim_if_stale(path: Path) -> Optional[dict]:
    """If the lock at `path` is older than the reclaim TTL (abandoned), delete it and return
    reclaim metadata; otherwise return None (a live lock the caller must treat as Busy)."""
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    age = _lock_age_seconds(path, meta if isinstance(meta, dict) else {})
    ttl = _lock_ttl_seconds()
    if age is None or age <= ttl:
        return None
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    prior = {k: meta.get(k) for k in ("team", "cluster", "pid", "acquired")
             if isinstance(meta, dict) and k in meta}
    return {"path": str(path), "age_seconds": round(age, 1), "ttl_seconds": ttl, "prior": prior}


def _team_name(team: str) -> str:
    root = mnx_common.find_graph_root(team)
    if root is None:
        return Path(team).name
    return mnx_common.team_of(root, team) or Path(team).name


def _lock_path(team: str) -> Path:
    root = mnx_common.require_graph_root(team)
    return mnx_common.state_dir(root) / "locks" / f"{_team_name(team)}.lock"


# --- multiple-granularity locking (W4) --------------------------------------
# The team lock above is coarse: one mutating op per team, even for disjoint clusters. W4 adds
# per-CLUSTER exclusive locks so N authors can promote different clusters concurrently, with a
# team-EXCLUSIVE lock retained only for the rare window that severs cross-cluster edges / rewrites
# cross-links. Compatibility rule, enforced under a per-team guard (atomic check-and-set):
#   * a cluster lock conflicts with the team-exclusive lock and with the SAME cluster's lock;
#   * the team-exclusive lock (legacy `acquire`) conflicts with ANY cluster lock in the team.
# So cluster-scoped writers run in parallel; a cross-cluster writer waits for a quiet team.

def _locks_dir(team: str) -> Path:
    root = mnx_common.require_graph_root(team)
    return mnx_common.state_dir(root) / "locks"


def _guard_path(team: str) -> Path:
    return _locks_dir(team) / f"{_team_name(team)}.guard"


def _cluster_marker(cluster: str) -> Path:
    root = mnx_common.require_graph_root(cluster)
    key = mnx_common.cluster_key(root, cluster)
    team = mnx_common.team_of(root, cluster) or _team_name(cluster)
    return _locks_dir(cluster) / f"{team}__{key}.cluster.lock"


def _cluster_markers(team: str) -> list[Path]:
    return sorted(_locks_dir(team).glob(f"{_team_name(team)}__*.cluster.lock"))


def _acquire_guard(team: str, spin: float = 2.0):
    """Short-lived guard so a check-and-set of lock state is atomic within a team."""
    import time
    gp = _guard_path(team)
    gp.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + spin
    while True:
        try:
            fd = os.open(str(gp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return gp
        except FileExistsError:
            if time.time() > deadline:
                raise Busy(f"lock guard contended: {gp}")
            time.sleep(0.02)


def _release_guard(gp: Path) -> None:
    try:
        os.unlink(gp)
    except FileNotFoundError:
        pass


def acquire_cluster(cluster: str) -> dict[str, Any]:
    """Acquire an exclusive lock on ONE cluster. Raises Busy if the team is exclusively locked or
    this cluster is already locked. Lets disjoint clusters be written concurrently."""
    gp = _acquire_guard(cluster)          # helpers take any path within the graph, not the team name
    try:
        reclaimed = []
        lp = _lock_path(cluster)
        if lp.exists():
            r = _reclaim_if_stale(lp)
            if r is None:
                raise Busy(f"team exclusively locked: {_team_name(cluster)}")
            reclaimed.append({"lock": "team", **r})
        marker = _cluster_marker(cluster)
        if marker.exists():
            r = _reclaim_if_stale(marker)
            if r is None:
                raise Busy(f"cluster lock already held: {marker}")
            reclaimed.append({"lock": "cluster", **r})
        marker.write_text(json.dumps({"cluster": str(cluster), "pid": os.getpid(),
                                      "acquired": mnx_common.now_utc()}), encoding="utf-8")
        handle = {"path": str(marker), "scope": "cluster", "cluster": str(cluster)}
        if reclaimed:
            handle["reclaimed"] = reclaimed
        return handle
    finally:
        _release_guard(gp)


def release_cluster(handle: Any) -> None:
    path = handle["path"] if isinstance(handle, dict) else str(handle)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def held_cluster(cluster: str) -> bool:
    return _cluster_marker(cluster).exists()


def plan_path(team: str) -> str:
    """Path to the team's pass plan: <graph>/.mnemex/plans/<team>.plan.json."""
    root = mnx_common.require_graph_root(team)
    return str(mnx_common.state_dir(root) / "plans" / f"{_team_name(team)}.plan.json")


def acquire(team: str) -> dict[str, Any]:
    """Acquire the team-EXCLUSIVE lock; return a handle. Raise Busy if the team lock is held OR any
    per-cluster lock in the team is held (W4 multiple-granularity rule). Used by a cross-cluster
    writer (promote's severing/cross-links window); cluster-scoped writers use acquire_cluster."""
    lp = _lock_path(team)
    lp.parent.mkdir(parents=True, exist_ok=True)
    gp = _acquire_guard(team)
    try:
        reclaimed = []
        if lp.exists():
            r = _reclaim_if_stale(lp)
            if r is None:
                raise Busy(f"team lock already held: {lp}")
            reclaimed.append({"lock": "team", **r})
        for c in _cluster_markers(team):
            r = _reclaim_if_stale(c)
            if r is None:
                raise Busy(f"team has cluster lock(s) held: {lp}")
            reclaimed.append({"lock": "cluster", **r})
        try:
            fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise Busy(f"team lock already held: {lp}")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"team": _team_name(team), "pid": os.getpid(),
                                 "acquired": mnx_common.now_utc()}))
        handle = {"path": str(lp), "team": _team_name(team), "scope": "team"}
        if reclaimed:
            handle["reclaimed"] = reclaimed
        return handle
    finally:
        _release_guard(gp)


def release(handle: Any) -> None:
    """Release a previously acquired lock handle."""
    path = handle["path"] if isinstance(handle, dict) else str(handle)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def held(team: str) -> bool:
    return _lock_path(team).exists()


def write_plan(team: str, plan: dict) -> None:
    """Persist a Phase-A maintenance plan (for crash recovery / replay)."""
    p = Path(plan_path(team))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, indent=2, default=str) + "\n", encoding="utf-8")


def read_plan(team: str) -> Optional[dict]:
    """Return the persisted plan, or None."""
    p = Path(plan_path(team))
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def remove_plan(team: str) -> None:
    try:
        os.unlink(plan_path(team))
    except FileNotFoundError:
        pass


def in_progress(team: str) -> bool:
    """True iff a pass plan is present (a pass is mid-flight)."""
    return Path(plan_path(team)).is_file()


def _git_dirty(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    r = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def recover(team: str) -> dict[str, Any]:
    """Inspect for a stranded pass + dirty tree.

    Returns {dirty, action: 'rollback'|'replay'|'none'}:
      - plan present + dirty tree  → 'rollback' (git checkout to last good commit, then replay)
      - plan present + clean tree  → 'replay'   (pass committed but plan not cleared)
      - no plan                    → 'none'
    """
    root = mnx_common.require_graph_root(team)
    dirty = _git_dirty(root)
    if not in_progress(team):
        return {"dirty": dirty, "action": "none"}
    return {"dirty": dirty, "action": "rollback" if dirty else "replay",
            "plan": plan_path(team)}


_USAGE = [
    'mnx_lock.py acquire <team> | release <team>                  — team-level consolidation lock',
    'mnx_lock.py acquire-cluster <cluster> | release-cluster <cluster>  — cluster-level lock',
    'mnx_lock.py status <team>                                    — lock + in-progress pass state',
    'mnx_lock.py recover <team>                                   — crash recovery for a stranded pass',
]


def _main(argv: list[str]) -> int:
    handled = mnx_common.cli_guard(argv, _USAGE)
    if handled is not None:
        return handled
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "acquire":
            try:
                return mnx_common.emit({"action": "acquired", **acquire(argv[2])})
            except Busy as b:
                return mnx_common.emit({"action": "busy", "detail": str(b)}, ok=False)
        if cmd == "release":
            release({"path": str(_lock_path(argv[2]))})
            return mnx_common.emit({"action": "released", "team": _team_name(argv[2])})
        if cmd == "acquire-cluster":
            try:
                return mnx_common.emit({"action": "acquired", **acquire_cluster(argv[2])})
            except Busy as b:
                return mnx_common.emit({"action": "busy", "detail": str(b)}, ok=False)
        if cmd == "release-cluster":
            release_cluster({"path": str(_cluster_marker(argv[2]))})
            return mnx_common.emit({"action": "released", "cluster": argv[2]})
        if cmd == "status":
            return mnx_common.emit({"team": _team_name(argv[2]), "held": held(argv[2]),
                                    "in_progress": in_progress(argv[2]),
                                    "cluster_locks": [p.name for p in _cluster_markers(argv[2])]})
        if cmd == "recover":
            return mnx_common.emit(recover(argv[2]))
        return mnx_common.emit({"error": f"unknown subcommand: {cmd}"}, ok=False)
    except Exception as exc:
        return mnx_common.emit({"error": str(exc)}, ok=False)


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
