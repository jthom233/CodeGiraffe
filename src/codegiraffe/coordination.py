"""Multi-agent coordination for concurrent AI-assisted development."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows platforms
    msvcrt = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


COORDINATION_DIR = ".codegiraffe"
COORDINATION_FILE = "agents.json"
# Claims expire after this many seconds (default 30 minutes)
DEFAULT_TTL = 1800

# Inter-process file lock tuning: retry cadence and overall bound.
LOCK_RETRY_INTERVAL = 0.05  # 50 ms
LOCK_TIMEOUT = 5.0  # ~5 s total wait before giving up


class LockTimeoutError(RuntimeError):
    """Raised when the coordination store lock cannot be acquired in time."""


# One threading.Lock per store path, shared by every CoordinationStore instance
# in this process (the MCP server and dashboard thread each construct their own
# instance but point at the same on-disk store). msvcrt/fcntl locks are
# per-process, so they alone wouldn't serialize two threads in one process.
_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}


def _get_thread_lock(store_path: Path) -> threading.Lock:
    key = str(store_path)
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


def _acquire_file_lock(fd: int, deadline: float) -> None:
    """Acquire an exclusive, non-blocking OS file lock on ``fd``, retrying
    until ``deadline`` (a ``time.monotonic()`` timestamp)."""
    if msvcrt is not None:
        # msvcrt.locking requires the locked region to exist in the file.
        try:
            size = os.fstat(fd).st_size
        except OSError:
            size = 0
        if size < 1:
            os.write(fd, b"\0")
            os.fsync(fd)
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Timed out waiting for coordination file lock after "
                        f"{LOCK_TIMEOUT}s."
                    ) from None
                time.sleep(LOCK_RETRY_INTERVAL)
    elif fcntl is not None:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Timed out waiting for coordination file lock after "
                        f"{LOCK_TIMEOUT}s."
                    ) from None
                time.sleep(LOCK_RETRY_INTERVAL)
    # else: neither primitive is available on this platform; fall back to
    # relying solely on the in-process threading.Lock.


def _release_file_lock(fd: int) -> None:
    if msvcrt is not None:
        with contextlib.suppress(OSError):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def _locked_store(store_path: Path):
    """Serialize access to ``store_path`` across threads in this process and
    across separate processes via a sibling ``.lock`` file.

    Raises ``LockTimeoutError`` if the lock cannot be acquired within
    ``LOCK_TIMEOUT`` seconds.
    """
    store_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store_path.with_name(store_path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT

    thread_lock = _get_thread_lock(store_path)
    if not thread_lock.acquire(timeout=LOCK_TIMEOUT):
        raise LockTimeoutError(
            f"Timed out waiting for in-process coordination lock on "
            f"{store_path} after {LOCK_TIMEOUT}s."
        )
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_file_lock(fd, deadline)
            try:
                yield
            finally:
                _release_file_lock(fd)
        finally:
            os.close(fd)
    finally:
        thread_lock.release()


@dataclass
class AgentClaim:
    """A claim by an agent on a node or region of the graph."""
    agent_id: str
    node_ids: list[str]
    task: str
    status: str  # "active", "done", "blocked"
    claimed_at: float = field(default_factory=time.time)
    ttl: int = DEFAULT_TTL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.claimed_at > self.ttl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentClaim:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CoordinationStore:
    """File-based coordination store for multi-agent status tracking."""

    def _store_path(self, project_path: str) -> Path:
        return Path(project_path).resolve() / COORDINATION_DIR / COORDINATION_FILE

    def _lock(self, project_path: str):
        """Context manager serializing load-modify-save sequences for
        ``project_path``'s store, across threads and processes."""
        return _locked_store(self._store_path(project_path))

    def _load_claims(self, project_path: str) -> list[AgentClaim]:
        """Load all claims, filtering out expired ones."""
        path = self._store_path(project_path)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            claims = [AgentClaim.from_dict(c) for c in raw]
            # Filter expired claims
            return [c for c in claims if not c.is_expired]
        except (json.JSONDecodeError, TypeError, KeyError):
            return []

    def _save_claims(self, project_path: str, claims: list[AgentClaim]) -> None:
        """Save claims to disk atomically.

        Writes to a tempfile in the same directory, then atomically renames
        it over the target with ``os.replace()`` (same pattern as
        ``JSONStorage.save``), so a crash mid-write leaves the previous file
        intact instead of a truncated/partial one.
        """
        path = self._store_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        active = [c for c in claims if not c.is_expired]
        content = json.dumps([c.to_dict() for c in active], indent=2) + "\n"

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise

    def claim(
        self,
        project_path: str,
        agent_id: str,
        node_ids: list[str],
        task: str,
        ttl: int = DEFAULT_TTL,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Claim nodes for an agent. Returns claim info or conflict details."""
        with self._lock(project_path):
            claims = self._load_claims(project_path)

            # Check for conflicts (another active agent claiming the same nodes)
            conflicts = []
            for existing in claims:
                if existing.agent_id == agent_id:
                    continue
                if existing.status == "done":
                    continue
                overlap = set(existing.node_ids) & set(node_ids)
                if overlap:
                    conflicts.append({
                        "agent_id": existing.agent_id,
                        "overlapping_nodes": sorted(overlap),
                        "task": existing.task,
                        "status": existing.status,
                    })

            if conflicts:
                return {
                    "success": False,
                    "reason": "conflict",
                    "conflicts": conflicts,
                }

            # Remove previous claims by this agent
            claims = [c for c in claims if c.agent_id != agent_id]

            # Add new claim
            new_claim = AgentClaim(
                agent_id=agent_id,
                node_ids=node_ids,
                task=task,
                status="active",
                ttl=ttl,
                metadata=metadata or {},
            )
            claims.append(new_claim)
            self._save_claims(project_path, claims)

            return {
                "success": True,
                "claim": new_claim.to_dict(),
            }

    def update_status(
        self,
        project_path: str,
        agent_id: str,
        status: str,
        task: str | None = None,
    ) -> dict[str, Any]:
        """Update an agent's status."""
        with self._lock(project_path):
            claims = self._load_claims(project_path)

            for claim in claims:
                if claim.agent_id == agent_id:
                    claim.status = status
                    if task is not None:
                        claim.task = task
                    # Refresh the TTL on update
                    claim.claimed_at = time.time()
                    self._save_claims(project_path, claims)
                    return {"success": True, "claim": claim.to_dict()}

            return {"success": False, "reason": f"No active claim found for agent '{agent_id}'."}

    def release(self, project_path: str, agent_id: str) -> dict[str, Any]:
        """Release an agent's claim."""
        with self._lock(project_path):
            claims = self._load_claims(project_path)
            before = len(claims)
            claims = [c for c in claims if c.agent_id != agent_id]
            self._save_claims(project_path, claims)

            removed = before - len(claims)
            return {"success": True, "released": removed}

    def list_agents(self, project_path: str) -> list[dict[str, Any]]:
        """List all active agents and their claims."""
        claims = self._load_claims(project_path)
        return [c.to_dict() for c in claims]
