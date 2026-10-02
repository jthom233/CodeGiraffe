"""Tests for multi-agent coordination (codegiraffe.coordination)."""
import concurrent.futures
import json
import time
import pytest
from pathlib import Path
from codegiraffe.coordination import AgentClaim, CoordinationStore, DEFAULT_TTL


@pytest.fixture
def store():
    return CoordinationStore()


def _claim_in_subprocess(args):
    """Top-level (picklable) helper used by the cross-process test below.

    Each subprocess constructs its own ``CoordinationStore`` -- this is what
    exercises the inter-process file lock rather than the in-process
    ``threading.Lock``, which is per-process and wouldn't be shared here.
    """
    project_path, agent_id, node_ids, task = args
    from codegiraffe.coordination import CoordinationStore as _Store

    return _Store().claim(project_path, agent_id, node_ids, task)


class TestAgentClaim:
    def test_create_claim(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["endpoint:/api/users"],
            task="Refactoring user endpoint",
            status="active",
        )
        assert claim.agent_id == "agent-1"
        assert not claim.is_expired

    def test_expired_claim(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["endpoint:/api/users"],
            task="Old task",
            status="active",
            claimed_at=time.time() - DEFAULT_TTL - 1,
        )
        assert claim.is_expired

    def test_round_trip(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["a", "b"],
            task="test",
            status="active",
            metadata={"key": "value"},
        )
        d = claim.to_dict()
        restored = AgentClaim.from_dict(d)
        assert restored.agent_id == claim.agent_id
        assert restored.node_ids == claim.node_ids
        assert restored.metadata == claim.metadata


class TestCoordinationStore:
    def test_claim_success(self, store, tmp_path):
        result = store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        assert result["success"] is True

    def test_claim_conflict(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        result = store.claim(str(tmp_path), "agent-2", ["node:a"], "Also working on A")
        assert result["success"] is False
        assert result["reason"] == "conflict"
        assert len(result["conflicts"]) == 1

    def test_claim_no_conflict_different_nodes(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        result = store.claim(str(tmp_path), "agent-2", ["node:b"], "Working on B")
        assert result["success"] is True

    def test_claim_replaces_previous(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "First task")
        store.claim(str(tmp_path), "agent-1", ["node:b"], "Second task")
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 1
        assert agents[0]["node_ids"] == ["node:b"]

    def test_update_status(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working")
        result = store.update_status(str(tmp_path), "agent-1", "done")
        assert result["success"] is True
        assert result["claim"]["status"] == "done"

    def test_update_nonexistent_agent(self, store, tmp_path):
        result = store.update_status(str(tmp_path), "ghost", "active")
        assert result["success"] is False

    def test_release(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working")
        result = store.release(str(tmp_path), "agent-1")
        assert result["success"] is True
        assert result["released"] == 1
        assert store.list_agents(str(tmp_path)) == []

    def test_list_agents(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Task 1")
        store.claim(str(tmp_path), "agent-2", ["node:b"], "Task 2")
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 2

    def test_expired_claims_filtered(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Old task", ttl=0)
        # Force expiration
        time.sleep(0.1)
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 0

    def test_done_agent_no_conflict(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Done task")
        store.update_status(str(tmp_path), "agent-1", "done")
        result = store.claim(str(tmp_path), "agent-2", ["node:a"], "New task")
        assert result["success"] is True

    def test_empty_store(self, store, tmp_path):
        agents = store.list_agents(str(tmp_path))
        assert agents == []


class TestConcurrency:
    """Covers the race documented in the coordination correctness fix:
    unsynchronized load -> check -> save let two agents both "win" a claim
    on the same node. These tests pin down that exactly one claim wins."""

    def test_concurrent_claims_single_winner(self, store, tmp_path):
        """8 threads race to claim the same node on one shared store
        instance. Exactly one must succeed; the rest get the conflict
        shape, and the store ends up holding exactly one claim."""
        n_threads = 8

        def do_claim(i):
            return store.claim(
                str(tmp_path), f"agent-{i}", ["node:shared"], f"task-{i}"
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
            results = list(pool.map(do_claim, range(n_threads)))

        successes = [r for r in results if r["success"]]
        conflicts = [r for r in results if not r["success"]]

        assert len(successes) == 1
        assert len(conflicts) == n_threads - 1
        for c in conflicts:
            assert c["reason"] == "conflict"
            assert "conflicts" in c

        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 1

    def test_cross_process_claims_single_winner(self, tmp_path):
        """Two separate OS processes race to claim the same node. Only
        the inter-process file lock (msvcrt/fcntl) can serialize this --
        a threading.Lock alone would not, since each process has its own."""
        n_procs = 4
        args_list = [
            (str(tmp_path), f"proc-agent-{i}", ["node:shared"], f"task-{i}")
            for i in range(n_procs)
        ]

        with concurrent.futures.ProcessPoolExecutor(max_workers=n_procs) as pool:
            results = list(pool.map(_claim_in_subprocess, args_list))

        successes = [r for r in results if r["success"]]
        assert len(successes) == 1

        store = CoordinationStore()
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 1


class TestCrashSafety:
    """`_save_claims` must write atomically (tempfile + os.replace): a
    failure partway through must never leave the store truncated or
    corrupted, matching the pattern in storage.py's JSONStorage.save."""

    def test_save_claims_atomic_on_replace_failure(self, store, tmp_path, monkeypatch):
        # Seed a known-good claim on disk.
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Initial task")
        path = store._store_path(str(tmp_path))
        original_content = path.read_text(encoding="utf-8")

        def boom(*_args, **_kwargs):
            raise OSError("simulated crash during os.replace")

        monkeypatch.setattr("codegiraffe.coordination.os.replace", boom)

        with pytest.raises(OSError):
            # Distinct node -- no conflict, so this reaches _save_claims.
            store.claim(str(tmp_path), "agent-2", ["node:b"], "Second task")

        # Original file must be untouched, not partially written/corrupted.
        assert path.read_text(encoding="utf-8") == original_content
        # The tempfile must have been cleaned up, not left behind.
        assert list(path.parent.glob("*.tmp")) == []

        monkeypatch.undo()

        # The lock must have been released despite the exception, so a
        # subsequent call is not left deadlocked.
        result = store.claim(str(tmp_path), "agent-3", ["node:c"], "Third task")
        assert result["success"] is True
